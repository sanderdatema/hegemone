"""Webhooks: fanout-regels + gesigneerde bezorging met retries.

De bezorging wordt deterministisch getest via `deliver_pending` (dispatcher uit
in de client-fixture) tegen een lokale mock-receiver in een achtergrond-thread.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fastapi.testclient import TestClient



from betonning import db as db_module
from betonning import webhooks
from betonning.repo import access
from betonning.repo import events as events_repo
from betonning.repo import items as items_repo
from betonning.repo import users as users_repo
from betonning.server import create_app


@pytest.fixture(autouse=True)
def _no_trigger_delay(monkeypatch):
    """De meeste tests toetsen de bezorg-mechaniek, niet de trigger-delay; die
    zetten we hier standaard uit (0s) zodat deliveries direct verzendbaar zijn.
    De delay-specifieke tests zetten hem expliciet weer aan."""
    monkeypatch.setenv("BETONNING_TRIGGER_DELAY", "0")


# --- Mock-receiver --------------------------------------------------------


class _Receiver:
    def __init__(self, server: ThreadingHTTPServer):
        self._server = server
        self.received: list[dict] = []
        self.response_code = 200
        server.received = self.received  # type: ignore[attr-defined]
        server.get_code = lambda: self.response_code  # type: ignore[attr-defined]

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://127.0.0.1:{port}/hook"

    @property
    def base(self) -> str:
        host, port = self._server.server_address
        return f"http://127.0.0.1:{port}"


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server.received.append(  # type: ignore[attr-defined]
            {"headers": dict(self.headers), "body": body}
        )
        code = self.server.get_code()  # type: ignore[attr-defined]
        self.send_response(code)
        self.end_headers()

    def log_message(self, *args):  # stil houden
        pass


@pytest.fixture
def receiver(monkeypatch):
    # De mock-receiver draait op 127.0.0.1 en dat is sinds BETON-378 een
    # verboden webhook-doel; de dev-/test-escape zet die poort hier open.
    monkeypatch.setenv("BETONNING_WEBHOOK_ALLOW_LOOPBACK", "1")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _Receiver(server)
    finally:
        server.shutdown()
        server.server_close()


def _run_deliver(conn, **kwargs) -> int:
    async def go():
        async with httpx.AsyncClient(timeout=5) as client:
            return await webhooks.deliver_pending(conn, client, **kwargs)

    return asyncio.run(go())


def _deliveries_for(conn, handle):
    return conn.execute(
        "SELECT wd.* FROM webhook_deliveries wd JOIN users u ON u.id = wd.user_id "
        "WHERE u.handle = ? ORDER BY wd.id",
        (handle,),
    ).fetchall()


def _webhook_user(
    conn,
    handle,
    *,
    url="http://example.invalid/hook",
    secret="s3cret",
    subscribe_all=False,
):
    _, key = users_repo.create(
        conn,
        handle=handle,
        display_name=handle,
        kind="agent",
        webhook_url=url,
        webhook_secret=secret,
        subscribe_all=subscribe_all,
    )
    return key


@pytest.fixture
def project(project, client, auth):
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    return project


# --- Fanout-regels --------------------------------------------------------


def test_fanout_to_assignee(client, auth, conn, project):
    _webhook_user(conn, "hermes")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    assert len(_deliveries_for(conn, "hermes")) == 1


def test_fanout_to_mentioned(client, auth, conn, project):
    _webhook_user(conn, "hermes")
    client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "hoi @hermes"}, headers=auth
    )
    assert len(_deliveries_for(conn, "hermes")) == 1


def test_fanout_to_subscribe_all(client, auth, conn, project):
    _webhook_user(conn, "triage", subscribe_all=True)
    # Willekeurige mutatie zonder assignee/mention → triage krijgt hem toch.
    client.patch("/api/v1/items/SOS-1", json={"priority": "high"}, headers=auth)
    assert len(_deliveries_for(conn, "triage")) == 1


def test_fanout_excludes_actor(client, conn, project):
    key = _webhook_user(conn, "hermes")
    hermes_auth = {"Authorization": f"Bearer {key}"}
    # hermes wijst het item aan zichzelf toe → geen eigen webhook.
    client.patch(
        "/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=hermes_auth
    )
    assert _deliveries_for(conn, "hermes") == []


def test_fanout_skips_users_without_webhook(client, auth, conn, project):
    users_repo.create(conn, handle="claude", display_name="Claude", kind="agent")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "claude"}, headers=auth)
    assert _deliveries_for(conn, "claude") == []


def test_new_description_mention_notifies_once(client, auth, conn, project):
    _webhook_user(conn, "hermes")
    client.patch(
        "/api/v1/items/SOS-1",
        json={"description_md": "cc @hermes"},
        headers=auth,
    )
    assert len(_deliveries_for(conn, "hermes")) == 1
    # Een latere wijziging die @hermes ongemoeid laat mag hem niet opnieuw spammen.
    client.patch("/api/v1/items/SOS-1", json={"priority": "high"}, headers=auth)
    assert len(_deliveries_for(conn, "hermes")) == 1


def test_reediting_description_does_not_respam_mention(client, auth, conn, project):
    _webhook_user(conn, "hermes")
    client.patch(
        "/api/v1/items/SOS-1", json={"description_md": "hoi @hermes"}, headers=auth
    )
    assert len(_deliveries_for(conn, "hermes")) == 1
    # Zelfde mention, andere tekst → geen nieuwe delivery (mention niet nieuw).
    client.patch(
        "/api/v1/items/SOS-1",
        json={"description_md": "hoi @hermes, nog iets"},
        headers=auth,
    )
    assert len(_deliveries_for(conn, "hermes")) == 1


# --- Per-project agent-toegang (BETON-123) --------------------------------


def _project_id(conn, key="SOS"):
    return conn.execute("SELECT id FROM projects WHERE key = ?", (key,)).fetchone()[0]


def test_fanout_skips_none_access_agent(client, auth, conn, project):
    # smid (hermes) is op dit project uitgezet → geen delivery, ook niet bij mention.
    users_repo.create(
        conn,
        handle="smid",
        display_name="Smid",
        kind="agent",
        agent_type="hermes",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
    )
    access.set_type_access(conn, _project_id(conn), "hermes", "none")
    conn.commit()
    client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "hoi @smid"}, headers=auth
    )
    assert _deliveries_for(conn, "smid") == []


def test_fanout_allows_respond_access_agent(client, auth, conn, project):
    # 'respond' mag reageren → wordt wél getriggerd (alleen auto-assign is uit).
    users_repo.create(
        conn,
        handle="smid",
        display_name="Smid",
        kind="agent",
        agent_type="hermes",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
    )
    access.set_type_access(conn, _project_id(conn), "hermes", "respond")
    conn.commit()
    client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "hoi @smid"}, headers=auth
    )
    assert len(_deliveries_for(conn, "smid")) == 1


def test_fanout_none_is_per_project(client, auth, conn, project):
    # 'none' op SOS mag een ander project niet raken: daar krijgt smid gewoon delivery.
    users_repo.create(
        conn,
        handle="smid",
        display_name="Smid",
        kind="agent",
        agent_type="hermes",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
    )
    access.set_type_access(conn, _project_id(conn), "hermes", "none")
    conn.commit()
    client.post("/api/v1/projects", json={"key": "OTH", "name": "Other"}, headers=auth)
    client.post("/api/v1/projects/OTH/items", json={"title": "z"}, headers=auth)
    client.post(
        "/api/v1/items/OTH-1/comments", json={"body_md": "hoi @smid"}, headers=auth
    )
    assert len(_deliveries_for(conn, "smid")) == 1


def test_fanout_subscribe_all_respects_none_access(client, auth, conn, project):
    # BETON-390: subscribe_all=1 is een alles-opt-in, maar loopt door dezelfde
    # access-poort als assignee/mentions — 'none' op dit project houdt ook de
    # subscribe_all-ontvanger buiten schot.
    users_repo.create(
        conn,
        handle="smid",
        display_name="Smid",
        kind="agent",
        agent_type="hermes",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
        subscribe_all=True,
    )
    access.set_type_access(conn, _project_id(conn), "hermes", "none")
    conn.commit()
    # Willekeurige mutatie zonder assignee/mention op SOS-1 — smid leest alles
    # mee via subscribe_all, maar mag hier niet bij (none).
    client.patch("/api/v1/items/SOS-1", json={"workload": "heavy"}, headers=auth)
    assert _deliveries_for(conn, "smid") == []


def test_fanout_subscribe_all_allowed_with_respond_access(client, auth, conn, project):
    # Dezelfde agent met 'respond' op een ANDER project krijgt de delivery wél —
    # subscribe_all blijft legitiem voor meelezende agents op projecten waar ze
    # wél toegang hebben.
    users_repo.create(
        conn,
        handle="smid",
        display_name="Smid",
        kind="agent",
        agent_type="hermes",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
        subscribe_all=True,
    )
    access.set_type_access(conn, _project_id(conn), "hermes", "none")
    client.post("/api/v1/projects", json={"key": "OTH", "name": "Other"}, headers=auth)
    access.set_type_access(conn, _project_id(conn, key="OTH"), "hermes", "respond")
    conn.commit()
    client.post("/api/v1/projects/OTH/items", json={"title": "z"}, headers=auth)
    before = len(_deliveries_for(conn, "smid"))
    client.patch("/api/v1/items/OTH-1", json={"workload": "light"}, headers=auth)
    assert len(_deliveries_for(conn, "smid")) == before + 1


# --- Participant-fanout (BETON-110) ---------------------------------------


def test_comment_does_not_retrigger_prior_comment_author_without_fresh_mention(
    client, auth, conn, project
):
    # BETON-211: hermes wordt eenmalig gemention en reageert; een latere comment
    # zónder verse mention mag hem NIET opnieuw bereiken (was eerder participant,
    # maar dat telt niet meer mee voor comment-fanout) — anders wordt een agent
    # bij elke comment op de thread ingetrokken, ook als die niet voor hem is.
    _webhook_user(conn, "hermes")
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "kun je kijken @hermes?"},
        headers=auth,
    )
    assert len(_deliveries_for(conn, "hermes")) == 1
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "ja, zet maar op done"},
        headers=auth,
    )
    assert len(_deliveries_for(conn, "hermes")) == 1


def test_comment_does_not_retrigger_prior_description_mention_without_fresh_mention(
    client, auth, conn, project
):
    # BETON-211: hermes staat alleen in de omschrijving gemention (geen comment
    # ooit) — een comment zónder verse mention triggert hem niet meer.
    _webhook_user(conn, "hermes")
    client.patch(
        "/api/v1/items/SOS-1", json={"description_md": "cc @hermes"}, headers=auth
    )
    assert len(_deliveries_for(conn, "hermes")) == 1
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "iemand nog updates?"},
        headers=auth,
    )
    assert len(_deliveries_for(conn, "hermes")) == 1


def test_comment_still_reaches_assignee_without_mention(client, auth, conn, project):
    # BETON-211: de assignee blijft altijd bereikbaar op een comment, ook zonder
    # verse mention — dat komt van `fanout()` zelf (item.assignee_id), niet van
    # de (nu verwijderde) prior-participants-uitbreiding.
    _webhook_user(conn, "hermes")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    conn.execute("DELETE FROM webhook_deliveries")
    conn.commit()
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "geen mention hier"},
        headers=auth,
    )
    assert len(_deliveries_for(conn, "hermes")) == 1


def test_fanout_does_not_treat_unrelated_item_as_participant(
    client, auth, conn, project
):
    # Betrokkenheid is per item — een comment op een ánder item mag niemand
    # op dit item als participant tellen.
    _webhook_user(conn, "hermes")
    client.post("/api/v1/projects/SOS/items", json={"title": "y"}, headers=auth)
    client.post(
        "/api/v1/items/SOS-2/comments", json={"body_md": "hoi @hermes"}, headers=auth
    )
    assert len(_deliveries_for(conn, "hermes")) == 1
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "geen mention hier"},
        headers=auth,
    )
    # Nog steeds maar 1: SOS-1 heeft geen eigen participant-geschiedenis.
    assert len(_deliveries_for(conn, "hermes")) == 1


# --- Gerichte comments (BETON-216) -----------------------------------------
#
# Een comment mét @mentions is geadresseerd: alleen de gementionden krijgen
# hem. De assignee wordt dan niet meer auto-toegevoegd (het BRAND-150-scenario
# waarin Joop meepraatte op een vraag die aan Lobke gericht was). Een comment
# zónder mentions blijft ongericht: assignee zoals vanouds. subscribe_all is
# een expliciete alles-opt-in en blijft ook op gerichte comments gelden.


def test_directed_comment_skips_unmentioned_assignee(client, auth, conn, project):
    # Item toegewezen aan joop; comment richt zich expliciet tot lobke →
    # lobke krijgt hem, joop (assignee, niet geadresseerd) niet.
    _webhook_user(conn, "joop")
    _webhook_user(conn, "lobke")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    conn.execute("DELETE FROM webhook_deliveries")
    conn.commit()
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "@lobke waarom heb je dit aangemaakt?"},
        headers=auth,
    )
    assert len(_deliveries_for(conn, "lobke")) == 1
    assert _deliveries_for(conn, "joop") == []


def test_directed_comment_mentioning_assignee_reaches_him_once(
    client, auth, conn, project
):
    # De assignee die zélf gementiond wordt krijgt precies één delivery
    # (mention-route; geen dubbeling met de assignee-route).
    _webhook_user(conn, "joop")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    conn.execute("DELETE FROM webhook_deliveries")
    conn.commit()
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "@joop wat is de status?"},
        headers=auth,
    )
    assert len(_deliveries_for(conn, "joop")) == 1


def test_directed_comment_still_reaches_subscribe_all(client, auth, conn, project):
    # subscribe_all = expliciet "ik wil alles zien" — dat contract blijft ook
    # op gerichte comments overeind.
    _webhook_user(conn, "watcher", subscribe_all=True)
    _webhook_user(conn, "lobke")
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "@lobke kun je dit oppakken?"},
        headers=auth,
    )
    assert len(_deliveries_for(conn, "watcher")) == 1


def test_edited_comment_adding_mention_skips_assignee(client, auth, conn, project):
    # Een bewerking die een mention toevoegt maakt de comment gericht: alleen
    # de nieuw-gementionde krijgt een delivery, de assignee niet nogmaals.
    _webhook_user(conn, "joop")
    _webhook_user(conn, "lobke")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "even een notitie"},
        headers=auth,
    )
    comment_id = r.json()["id"]
    conn.execute("DELETE FROM webhook_deliveries")
    conn.commit()
    client.patch(
        f"/api/v1/items/SOS-1/comments/{comment_id}",
        json={"body_md": "even een notitie — @lobke kun jij dit checken?"},
        headers=auth,
    )
    assert len(_deliveries_for(conn, "lobke")) == 1
    assert _deliveries_for(conn, "joop") == []


def test_trigger_payload_carries_addressed_to(client, auth, conn, project, receiver):
    # De payload vertelt de ontvanger expliciet aan wie de comment gericht is
    # (addressed_to) — het vangnet voor routes waar een niet-geadresseerde wél
    # legitiem een notificatie krijgt (subscribe_all). lobke bestaat maar heeft
    # geen webhook, zodat de enige delivery die van de watcher is.
    _webhook_user(conn, "watcher", url=receiver.url, subscribe_all=True)
    users_repo.create(conn, handle="lobke", display_name="Lobke", kind="agent")
    conn.commit()
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "@lobke kun je dit oppakken?"},
        headers=auth,
    )
    assert _run_deliver(conn) == 1
    trigger = json.loads(receiver.received[0]["body"])["trigger"]
    assert trigger["addressed_to"] == ["lobke"]


def test_trigger_payload_addressed_to_none_for_non_comment_event(
    client, auth, conn, project, receiver
):
    # Bij niet-comment-events is er geen adressering: addressed_to is None.
    _webhook_user(conn, "joop", url=receiver.url)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    assert _run_deliver(conn) == 1
    trigger = json.loads(receiver.received[0]["body"])["trigger"]
    assert trigger["addressed_to"] is None


# --- Trigger-payload (BETON-110) -------------------------------------------


def test_trigger_payload_marks_fresh_mention(client, auth, conn, project, receiver):
    _webhook_user(conn, "hermes", url=receiver.url)
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "kun je dit oppakken @hermes?"},
        headers=auth,
    )
    assert _run_deliver(conn) == 1
    trigger = json.loads(receiver.received[0]["body"])["trigger"]
    assert trigger["type"] == "mention"
    assert trigger["mentioned_in"] == "comment"
    assert trigger["mentioned_by"] == "person"
    assert trigger["is_question"] is True


def test_trigger_payload_marks_prior_participant(client, auth, conn, project, receiver):
    # BETON-211: het "participant"-trigger-type bestaat nog uitsluitend via de
    # vrijgave-fanout (include_prior_participants=True) — een gewone comment
    # zonder verse mention retriggert een eerdere participant niet meer.
    _webhook_user(conn, "hermes", url=receiver.url)
    client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "hoi @hermes"}, headers=auth
    )
    assert _run_deliver(conn) == 1
    receiver.received.clear()
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    assert _run_deliver(conn) == 1
    trigger = json.loads(receiver.received[0]["body"])["trigger"]
    assert trigger["type"] == "participant"
    assert trigger["is_question"] is False


def test_trigger_payload_marks_assigned(client, auth, conn, project, receiver):
    _webhook_user(conn, "hermes", url=receiver.url)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    assert _run_deliver(conn) == 1
    trigger = json.loads(receiver.received[0]["body"])["trigger"]
    assert trigger["type"] == "assigned"


def test_trigger_payload_marks_subscribe_all(client, auth, conn, project, receiver):
    _webhook_user(conn, "triage", url=receiver.url, subscribe_all=True)
    client.patch("/api/v1/items/SOS-1", json={"priority": "high"}, headers=auth)
    assert _run_deliver(conn) == 1
    trigger = json.loads(receiver.received[0]["body"])["trigger"]
    assert trigger["type"] == "subscribe_all"


def test_blocking_state_limits_agent_to_comments(client, auth, conn, project, receiver):
    client.post(
        "/api/v1/projects/SOS/states",
        json={"name": "wachten", "group": "unstarted", "blocks_work": True},
        headers=auth,
    )
    client.patch("/api/v1/items/SOS-1", json={"state": "wachten"}, headers=auth)
    _webhook_user(conn, "hermes", url=receiver.url)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    assert _run_deliver(conn) == 1

    body = json.loads(receiver.received[0]["body"])
    assert body["agent_policy"] == {
        "state": "wachten",
        "work_allowed": False,
        "allowed_actions": ["comment"],
        "reason": "De huidige state blokkeert uitvoering; alleen comments zijn toegestaan.",
    }


def test_state_transition_signals_work_unblocked(client, auth, conn, project, receiver):
    _webhook_user(conn, "hermes", url=receiver.url, subscribe_all=True)

    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    assert _run_deliver(conn) == 1

    body = json.loads(receiver.received[0]["body"])
    assert body["agent_policy"]["work_allowed"] is True
    assert body["trigger"]["type"] == "subscribe_all"
    assert body["trigger"]["work_unblocked"] is True
    assert body["trigger"]["state_change"] == {
        "from": {"name": "backlog", "blocks_work": True},
        "to": {"name": "todo", "blocks_work": False},
    }


def test_unblocking_notifies_previously_mentioned_agent(client, auth, conn, receiver):
    _webhook_user(conn, "lobke", url=receiver.url)
    client.post(
        "/api/v1/projects", json={"key": "BRAND", "name": "Brand"}, headers=auth
    )
    client.post(
        "/api/v1/projects/BRAND/items",
        json={"title": "Onderzoek", "description_md": "@lobke wil je dit oppakken?"},
        headers=auth,
    )
    # De eerste webhook is in backlog: Lobke mag nog niet uitvoeren.
    assert _run_deliver(conn) == 1
    receiver.received.clear()

    client.patch("/api/v1/items/BRAND-1", json={"state": "todo"}, headers=auth)
    assert _run_deliver(conn) == 1

    body = json.loads(receiver.received[0]["body"])
    assert body["trigger"]["type"] == "mention"
    assert body["trigger"]["work_unblocked"] is True
    assert body["agent_policy"]["work_allowed"] is True


# --- Vrijgave notificeert alleen betrokken agents (BETON-201, was BETON-184) ---
#
# BETON-184 breidde de vrijgave-fanout uit naar álle agents met assign-toegang
# op het project, ook zonder eerdere betrokkenheid. In de praktijk (BRAND-160)
# leverde dat notificaties op voor agents die nergens bij betrokken waren.
# BETON-201 draait dat terug: vrijgave notificeert nog uitsluitend de maker,
# assignee, gementiondes en eerdere comment-auteurs — assign-toegang alleen
# bepaalt of een agent het item MAG oppakken, niet of hij een notificatie krijgt.


def test_unblocking_does_not_notify_uninvolved_assign_agent(
    client, auth, conn, project
):
    # smid heeft assign-toegang (default) en een webhook, maar raakte SOS-1 nooit
    # aan (niet gemaakt, niet toegewezen, niet gementiond, geen comment). Bij
    # vrijgave (backlog → todo) hoort hij dus GEEN delivery te krijgen.
    users_repo.create(
        conn,
        handle="smid",
        display_name="Smid",
        kind="agent",
        agent_type="hermes",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
    )
    conn.commit()
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    assert _deliveries_for(conn, "smid") == []


def test_unblocking_notifies_creator_without_mention(client, conn, project):
    # De maker van het item hoort altijd bij de vrijgave, ook zonder mention of
    # eigen comment. `project` maakt SOS-1 aan via `auth` (person) — geef person
    # hier een webhook om dat te kunnen verifiëren.
    users_repo.set_webhook(conn, "person", "http://example.invalid/hook", "s")
    conn.commit()
    key = _webhook_user(conn, "hermes")
    hermes_auth = {"Authorization": f"Bearer {key}"}
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=hermes_auth)
    assert len(_deliveries_for(conn, "person")) == 1


def test_unblocking_notifies_prior_commenter_without_mention(
    client, auth, conn, project
):
    # Iemand die eerder een comment plaatste (zonder mention) hoort bij vrijgave
    # ook zonder verse mention weer een delivery te krijgen.
    key = _webhook_user(conn, "hermes")
    hermes_auth = {"Authorization": f"Bearer {key}"}
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "kijk hier eens naar"},
        headers=hermes_auth,
    )
    conn.execute("DELETE FROM webhook_deliveries")
    conn.commit()
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    assert len(_deliveries_for(conn, "hermes")) == 1


def test_unblocking_still_skips_none_access_agents(client, auth, conn, project):
    # Zelfs een betrokken (gementiond) agent met effectief niveau 'none' blijft
    # buiten schot — dat blijft de harde per-agent opt-out (BETON-123).
    client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "hoi @nonny"}, headers=auth
    )
    users_repo.create(
        conn,
        handle="nonny",
        display_name="Nonny",
        kind="agent",
        agent_type="coding",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
    )
    conn.commit()
    pid = _project_id(conn)
    access.set_agent_access(
        conn,
        pid,
        conn.execute("SELECT id FROM users WHERE handle = 'nonny'").fetchone()[0],
        "none",
    )
    conn.commit()
    conn.execute("DELETE FROM webhook_deliveries")
    conn.commit()
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    assert _deliveries_for(conn, "nonny") == []


def test_unblocking_does_not_double_deliver_to_assignee(client, auth, conn, project):
    # smid is zowel assignee als assign-agent; hij mag maar één delivery krijgen
    # voor het vrijgave-event (de recipients-set dedupliceert). Alleen webhook-
    # kanaal (geen telegram), zodat het aantal ondubbelzinnig is.
    users_repo.create(
        conn,
        handle="smid",
        display_name="Smid",
        kind="agent",
        agent_type="hermes",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
    )
    client.patch("/api/v1/items/SOS-1", json={"assignee": "smid"}, headers=auth)
    # De assignee-toewijzing zelf gaf al een delivery; wis die om enkel het
    # vrijgave-event te tellen.
    conn.execute("DELETE FROM webhook_deliveries")
    conn.commit()
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    assert len(_deliveries_for(conn, "smid")) == 1


def test_normal_update_does_not_notify_uninvolved_assign_agent(
    client, auth, conn, project
):
    # Een gewone update (priority, geen vrijgave) mag géén assign-agents zonder
    # betrokkenheid triggeren — de doelgroep verandert alleen bij vrijgave.
    users_repo.create(
        conn,
        handle="smid",
        display_name="Smid",
        kind="agent",
        agent_type="hermes",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
    )
    conn.commit()
    client.patch("/api/v1/items/SOS-1", json={"priority": "high"}, headers=auth)
    assert _deliveries_for(conn, "smid") == []


# --- Admin zet webhook_url → fanout werkt (BETON-83/84, BETON-82) ---------


def test_admin_set_webhook_url_enables_fanout(client, auth, conn, project):
    # Root cause van BETON-83/84: vóór deze fix kon een admin geen webhook_url
    # op een agent zetten (alleen zelf-service via de eigen key), waardoor
    # Hermes-agents nooit getriggerd werden. Dit bewijst end-to-end dat een
    # PATCH door de mens nu een echte delivery-rij oplevert.
    r = client.post(
        "/api/v1/users",
        json={
            "handle": "smid",
            "display_name": "Smid",
            "kind": "agent",
            "agent_type": "hermes",
        },
        headers=auth,
    )
    assert r.status_code == 201
    r = client.patch(
        "/api/v1/users/smid",
        json={"webhook_url": "http://hermes.local/hook", "webhook_secret": "s3cret"},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["has_webhook"] is True

    client.patch("/api/v1/items/SOS-1", json={"assignee": "smid"}, headers=auth)

    deliveries = _deliveries_for(conn, "smid")
    assert len(deliveries) == 1
    assert deliveries[0]["channel"] == "webhook"
    assert deliveries[0]["status"] == "pending"


# --- Bezorging + signing --------------------------------------------------


def test_delivery_signed_and_verifiable(client, auth, conn, project, receiver):
    _webhook_user(conn, "hermes", url=receiver.url, secret="topsecret")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)

    assert _run_deliver(conn) == 1

    assert len(receiver.received) == 1
    got = receiver.received[0]
    expected = (
        "sha256=" + hmac.new(b"topsecret", got["body"], hashlib.sha256).hexdigest()
    )
    assert got["headers"]["X-Betonning-Signature"] == expected
    assert got["headers"]["X-Betonning-Event"] == "item.updated"

    delivery = _deliveries_for(conn, "hermes")[0]
    assert delivery["status"] == "delivered"
    assert delivery["attempts"] == 1


# --- Hermes Agent-compatibiliteit (BETON-104) ------------------------------


def test_sign_raw_matches_stdlib_hmac():
    body = b'{"hello":"world"}'
    expected = hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()
    assert webhooks.sign_raw("topsecret", body) == expected
    # Geen 'sha256='-prefix, in tegenstelling tot sign().
    assert not expected.startswith("sha256=")


def test_sign_v2_matches_stdlib_hmac_over_timestamp_dot_body():
    body = b'{"hello":"world"}'
    timestamp = "1720000000"
    expected = hmac.new(
        b"topsecret", f"{timestamp}.".encode("utf-8") + body, hashlib.sha256
    ).hexdigest()
    assert webhooks.sign_v2("topsecret", timestamp, body) == expected


def test_delivery_includes_hermes_compatible_headers(
    client, auth, conn, project, receiver
):
    # BETON-104: naast de bestaande X-Betonning-* headers moet elke delivery ook
    # de headers meesturen die Hermes Agent verwacht (Generic V1 + V2).
    _webhook_user(conn, "hermes", url=receiver.url, secret="topsecret")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)

    assert _run_deliver(conn) == 1
    assert len(receiver.received) == 1
    got = receiver.received[0]
    headers = got["headers"]
    body = got["body"]

    assert headers["Content-Type"] == "application/json"

    # Bestaande X-Betonning-* headers blijven werken (backward-compat).
    expected_betonning = (
        "sha256=" + hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()
    )
    assert headers["X-Betonning-Signature"] == expected_betonning
    assert headers["X-Betonning-Event"] == "item.updated"

    # Generic V1 (legacy): ruwe hex, geen prefix.
    expected_v1 = hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()
    assert headers["X-Webhook-Signature"] == expected_v1

    # Generic V2 (replay-veilig): hex over "<timestamp>.<body>".
    timestamp = headers["X-Webhook-Timestamp"]
    assert timestamp.isdigit()
    expected_v2 = hmac.new(
        b"topsecret", f"{timestamp}.".encode("utf-8") + body, hashlib.sha256
    ).hexdigest()
    assert headers["X-Webhook-Signature-V2"] == expected_v2


def test_mention_triggers_signed_webhook_delivery(
    client, auth, conn, project, receiver
):
    # BETON-15: een @mention van een agent (user met webhook_url = een 'Hermes'-
    # agent) levert end-to-end een gesigneerde webhook-POST bij die agent.
    _webhook_user(conn, "hermes", url=receiver.url, secret="agent-secret")
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "kun je kijken @hermes?"},
        headers=auth,
    )
    assert _run_deliver(conn) == 1
    assert len(receiver.received) == 1
    got = receiver.received[0]
    assert got["headers"]["X-Betonning-Event"] == "comment.created"
    expected = (
        "sha256=" + hmac.new(b"agent-secret", got["body"], hashlib.sha256).hexdigest()
    )
    assert got["headers"]["X-Betonning-Signature"] == expected


def test_webhook_payload_advertises_wiki_memory(client, auth, conn, project, receiver):
    # BETON-24/42/290: elke webhook-delivery draagt een SLANKE wegwijzer naar de
    # memory-provider mee (alleen context_url + hint), niet de volledige inhoud
    # en (sinds BETON-290) ook niet meer de paginalijst — die groeit onbegrensd
    # mee met de wiki en sloopt de truncatie-garantie net als de rest van de
    # brondata.
    client.post(
        "/api/v1/projects/SOS/wiki",
        json={"slug": "stijl", "title": "Stijl", "body_md": "wees beknopt"},
        headers=auth,
    )
    _webhook_user(conn, "hermes", url=receiver.url)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    assert _run_deliver(conn) == 1

    body = json.loads(receiver.received[0]["body"])
    assert "wiki" in body
    # De volledige body mag NIET in de delivery zitten; ook geen paginalijst meer.
    assert "memory" not in body["wiki"]
    assert "wees beknopt" not in json.dumps(body["wiki"])
    assert "pages" not in body["wiki"]
    assert body["wiki"]["context_url"].endswith("/projects/SOS/wiki/context")
    assert "memory-provider" in body["wiki"]["hint"]


# --- Payload-volgorde + afslanken onder de gateway-knip (BETON-290) ---------
#
# De Hermes-gateway rendert de webhook-prompt met
# `json.dumps(payload, indent=2)[:4000]` (een harde knip). Een test die alleen
# `"instructions" in payload` checkt (compacte JSON) blijft groen terwijl het
# veld de knip nooit haalt — dat was precies de bug. Deze tests repliceren de
# knip van de gateway exact: `json.dumps(body, indent=2)[:4000]`.

_GATEWAY_TRUNCATE_LIMIT = 4000
_INSTRUCTION_BLOCK_BUDGET = 2500


def _gateway_truncated(body: dict) -> str:
    """Repliceer de knip van de Hermes-gateway exact (BETON-290-bewijs)."""
    return json.dumps(body, indent=2)[:_GATEWAY_TRUNCATE_LIMIT]


def test_payload_survives_gateway_truncation_with_huge_description(
    client, auth, conn, project, receiver
):
    """Het echte prod-scenario: een item met een extreem lange omschrijving
    (50.000 tekens) mag de gateway-knip niet meer laten verdwijnen wat een agent
    nodig heeft om te reageren."""
    _webhook_user(conn, "joop", url=receiver.url)
    huge = "x" * 50_000
    client.patch("/api/v1/items/SOS-1", json={"description_md": huge}, headers=auth)
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "@joop wat vind jij hiervan?"},
        headers=auth,
    )
    assert _run_deliver(conn) == 1
    body = json.loads(receiver.received[-1]["body"])
    truncated = _gateway_truncated(body)

    assert '"expected_action"' in truncated
    assert '"instructions"' in truncated
    assert '"reply"' in truncated
    # De echte faalmodus: de agent kan de opdracht ook daadwerkelijk uitlezen uit
    # het geknipte fragment (niet alleen de sleutel, ook de waarde).
    assert body["expected_action"] in truncated
    assert "SOS-1" in truncated


def test_instruction_block_stays_within_budget(client, auth, conn, project, receiver):
    """Budgetbewaking: het opdrachtblok (t/m reply) blijft ruim onder de knip,
    zodat latere toevoegingen ons niet stilletjes weer over de rand duwen."""
    _webhook_user(conn, "joop", url=receiver.url)
    client.patch(
        "/api/v1/items/SOS-1", json={"description_md": "x" * 50_000}, headers=auth
    )
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "@joop wat vind jij hiervan?"},
        headers=auth,
    )
    assert _run_deliver(conn) == 1
    body = json.loads(receiver.received[-1]["body"])
    block = {
        "expected_action": body["expected_action"],
        "instructions": body["instructions"],
        "reply": body["reply"],
    }
    size = len(json.dumps(block, indent=2))
    assert size < _INSTRUCTION_BLOCK_BUDGET


def test_payload_has_no_source_content(client, auth, conn, project, receiver):
    """Bron-inhoud (BETON-290) zit niet meer in de delivery-payload: geen losse
    `context`, geen `item.description_md`, geen `wiki.pages` — die zijn
    onbegrensd en sloopten elke garantie op de gateway-knip."""
    _webhook_user(conn, "joop", url=receiver.url)
    client.patch(
        "/api/v1/items/SOS-1", json={"description_md": "x" * 50_000}, headers=auth
    )
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "@joop wat vind jij hiervan?"},
        headers=auth,
    )
    assert _run_deliver(conn) == 1
    body = json.loads(receiver.received[-1]["body"])

    assert "context" not in body
    assert "description_md" not in body["item"]
    assert "pages" not in body["wiki"]


def test_delivery_payload_key_order_puts_instructions_first(conn, project):
    """De sleutelvolgorde zelf: `expected_action`/`instructions`/`reply` staan
    vóór de brondata-armere velden (`event`/`item`/`wiki`) — dat is de enige
    échte garantie onder truncatie (`json.dumps` behoudt insertievolgorde)."""
    users_repo.create(
        conn,
        handle="joop",
        display_name="joop",
        kind="agent",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
    )
    conn.commit()
    from betonning.repo import events as events_repo

    item_id = conn.execute("SELECT id FROM items WHERE seq = 1").fetchone()["id"]
    event = events_repo.record(
        conn, type="item.updated", item_id=item_id, actor_id=None, payload={}
    )
    user = conn.execute("SELECT * FROM users WHERE handle = 'joop'").fetchone()
    payload = webhooks.build_delivery_payload(conn, event, user)
    keys = list(payload.keys())
    command_keys = [
        k for k in ("expected_action", "instructions", "reply") if k in keys
    ]
    tail_keys = [k for k in ("event", "item", "wiki") if k in keys]
    assert command_keys, "opdrachtdeel ontbreekt"
    assert max(keys.index(k) for k in command_keys) < min(
        keys.index(k) for k in tail_keys
    )


def test_push_and_pull_agree_on_expected_action(client, auth, conn, project, receiver):
    """BETON-296: de kern van de fix. Push (`_send_webhook` via
    `build_delivery_payload`) en pull (`GET /inbox?instructions=true` via
    `inbox.list_for_user`) moeten voor hetzelfde event/user hetzelfde
    `expected_action` opleveren — beide leunen nu op `build_agent_instructions`,
    één bron van waarheid i.p.v. twee parallelle implementaties."""
    key = _webhook_user(conn, "hermes", url=receiver.url)
    hermes_auth = {"Authorization": f"Bearer {key}"}

    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    assert _run_deliver(conn) == 1
    push_body = json.loads(receiver.received[-1]["body"])

    pull_data = client.get(
        "/api/v1/inbox", params={"instructions": "true"}, headers=hermes_auth
    ).json()
    pull_entry = next(e for e in pull_data["items"] if e["ref"] == "SOS-1")

    assert push_body["expected_action"] in ("pick_up", "acknowledge")
    assert pull_entry["instruction"]["expected_action"] == push_body["expected_action"]


def test_mention_without_webhook_url_does_not_trigger(client, auth, conn, project):
    # Een user zónder webhook_url (geen agent-endpoint) wordt niet getriggerd.
    users_repo.create(conn, handle="mensje", display_name="Mens", kind="human")
    client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "hoi @mensje"}, headers=auth
    )
    assert _deliveries_for(conn, "mensje") == []


def test_failing_receiver_retries_then_fails(client, auth, conn, project, receiver):
    receiver.response_code = 500
    _webhook_user(conn, "hermes", url=receiver.url)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)

    t0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)

    _run_deliver(conn, now=t0)
    d = _deliveries_for(conn, "hermes")[0]
    assert d["status"] == "pending"
    assert d["attempts"] == 1
    assert d["last_error"] == "HTTP 500"
    assert d["next_retry_at"] is not None

    # Nog niet verzendbaar op t0 zelf (next_retry_at ligt in de toekomst).
    _run_deliver(conn, now=t0)
    assert _deliveries_for(conn, "hermes")[0]["attempts"] == 1

    # Voorbij de backoff → tweede en derde poging; daarna 'failed'.
    _run_deliver(conn, now=t0 + timedelta(seconds=30))
    assert _deliveries_for(conn, "hermes")[0]["attempts"] == 2
    _run_deliver(conn, now=t0 + timedelta(seconds=60))
    d = _deliveries_for(conn, "hermes")[0]
    assert d["attempts"] == 3
    assert d["status"] == "failed"


def test_delivered_not_resent(client, auth, conn, project, receiver):
    _webhook_user(conn, "hermes", url=receiver.url)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    assert _run_deliver(conn) == 1
    # Tweede ronde vindt niets meer verzendbaars.
    assert _run_deliver(conn) == 0
    assert len(receiver.received) == 1


# --- Trigger-delay + annulering (BETON-18) --------------------------------


def test_trigger_delay_defers_delivery(
    client, auth, conn, project, receiver, monkeypatch
):
    monkeypatch.setenv("BETONNING_TRIGGER_DELAY", "5")
    _webhook_user(conn, "hermes", url=receiver.url)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)

    delivery = _deliveries_for(conn, "hermes")[0]
    assert delivery["not_before"] is not None
    nb = datetime.strptime(delivery["not_before"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )

    # Vlak vóór het venster: nog niets verzenden.
    assert _run_deliver(conn, now=nb - timedelta(seconds=1)) == 0
    assert receiver.received == []
    # Voorbij het venster: nu wel.
    assert _run_deliver(conn, now=nb + timedelta(seconds=1)) == 1
    assert len(receiver.received) == 1


def test_comment_deleted_within_delay_is_cancelled(
    client, auth, conn, project, receiver, monkeypatch
):
    monkeypatch.setenv("BETONNING_TRIGGER_DELAY", "5")
    _webhook_user(conn, "hermes", url=receiver.url)
    r = client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "cc @hermes"}, headers=auth
    )
    comment_id = r.json()["id"]
    delivery = _deliveries_for(conn, "hermes")[0]
    nb = datetime.strptime(delivery["not_before"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )

    # Comment wordt binnen het venster weer verwijderd.
    assert (
        client.delete(
            f"/api/v1/items/SOS-1/comments/{comment_id}", headers=auth
        ).status_code
        == 204
    )

    # Na het venster: delivery wordt geannuleerd, agent krijgt niets.
    assert _run_deliver(conn, now=nb + timedelta(seconds=1)) == 1
    assert receiver.received == []
    assert _deliveries_for(conn, "hermes")[0]["status"] == "cancelled"


def test_comment_still_present_after_delay_delivers(
    client, auth, conn, project, receiver, monkeypatch
):
    monkeypatch.setenv("BETONNING_TRIGGER_DELAY", "5")
    _webhook_user(conn, "hermes", url=receiver.url)
    client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "cc @hermes"}, headers=auth
    )
    delivery = _deliveries_for(conn, "hermes")[0]
    nb = datetime.strptime(delivery["not_before"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )
    assert _run_deliver(conn, now=nb + timedelta(seconds=1)) == 1
    assert len(receiver.received) == 1
    assert _deliveries_for(conn, "hermes")[0]["status"] == "delivered"


# --- Dispatcher-loop (end-to-end via lifespan) ----------------------------


# --- Telegram-kanaal ------------------------------------------------------


def _telegram_user(conn, handle, chat_id="123456"):
    users_repo.create(conn, handle=handle, display_name=handle, kind="human")
    users_repo.set_telegram(conn, handle, chat_id)


# BETON-313: Telegram is Persons telefoon, geen activiteitenstroom. Alleen de
# noodstop en een vraagmodule-vraag aan hem halen de lat; al het andere (gewone
# comments, mentions in afsluitberichten, toewijzingen, statuswissels) komt níet
# op Telegram. Zonder dat filter was het ~16 pings/dag (gemeten op een prod-kopie).


def test_plain_mention_creates_no_telegram_delivery(
    client, auth, conn, project, monkeypatch
):
    monkeypatch.setenv("BETONNING_TELEGRAM_TOKEN", "faketoken")
    _telegram_user(conn, "persont")
    client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "cc @persont"}, headers=auth
    )
    assert _deliveries_for(conn, "persont") == []


def test_assignment_creates_no_telegram_delivery(
    client, auth, conn, project, monkeypatch
):
    monkeypatch.setenv("BETONNING_TELEGRAM_TOKEN", "faketoken")
    _telegram_user(conn, "persont")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "persont"}, headers=auth)
    assert _deliveries_for(conn, "persont") == []


def test_question_creates_telegram_delivery(client, auth, conn, project, monkeypatch):
    monkeypatch.setenv("BETONNING_TELEGRAM_TOKEN", "faketoken")
    _telegram_user(conn, "persont")
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Welke kleur? @persont", "kind": "question"},
        headers=auth,
    )
    assert [d["channel"] for d in _deliveries_for(conn, "persont")] == ["telegram"]


def test_lock_creates_telegram_delivery(client, auth, conn, project, monkeypatch):
    monkeypatch.setenv("BETONNING_TELEGRAM_TOKEN", "faketoken")
    _telegram_user(conn, "persont")
    # De noodstop gaat gericht naar álle mensen, dus ook naar persont.
    client.post("/api/v1/items/SOS-1/lock", headers=auth)
    assert [d["channel"] for d in _deliveries_for(conn, "persont")] == ["telegram"]


def test_telegram_delivered_to_api(client, auth, conn, project, receiver, monkeypatch):
    monkeypatch.setenv("BETONNING_TELEGRAM_TOKEN", "faketoken")
    monkeypatch.setenv("BETONNING_TELEGRAM_API", receiver.base)
    monkeypatch.setenv("BETONNING_PUBLIC_URL", "http://box.local")
    _telegram_user(conn, "persont", chat_id="99887")
    # Een telegram-waardig event (BETON-313): een vraag gericht aan persont.
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Akkoord? @persont", "kind": "question"},
        headers=auth,
    )

    assert _run_deliver(conn) == 1
    assert len(receiver.received) == 1
    body = json.loads(receiver.received[0]["body"])
    assert body["chat_id"] == "99887"
    assert "SOS-1" in body["text"]
    assert "vraag" in body["text"].lower()
    # De notificatie bevat een deep-link naar het ticket.
    assert "http://box.local/#SOS-1" in body["text"]
    assert 'href="http://box.local/#SOS-1"' in body["text"]
    assert _deliveries_for(conn, "persont")[0]["status"] == "delivered"


def test_telegram_without_token_skips_fanout(client, auth, conn, project, monkeypatch):
    # BETON-43: zonder bot-token maken we telegram-deliveries niet aan; ze zouden
    # anders 3 retries afbranden en als 'failed' blijven staan (ruis).
    monkeypatch.delenv("BETONNING_TELEGRAM_TOKEN", raising=False)
    _telegram_user(conn, "persont")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "persont"}, headers=auth)

    # Geen delivery aangemaakt en dus ook niets te bezorgen/mislukken.
    assert _deliveries_for(conn, "persont") == []
    assert _run_deliver(conn) == 0
    failed = conn.execute(
        "SELECT COUNT(*) AS n FROM webhook_deliveries WHERE status = 'failed'"
    ).fetchone()["n"]
    assert failed == 0


def test_telegram_without_token_still_delivers_webhook(
    client, auth, conn, project, monkeypatch
):
    # Een user met zowel webhook_url als telegram_chat_id maar zonder token:
    # de webhook-delivery blijft, alleen het telegram-kanaal valt weg.
    monkeypatch.delenv("BETONNING_TELEGRAM_TOKEN", raising=False)
    _webhook_user(conn, "persont")
    users_repo.set_telegram(conn, "persont", "123456")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "persont"}, headers=auth)

    assert [d["channel"] for d in _deliveries_for(conn, "persont")] == ["webhook"]


def test_dispatcher_loop_delivers(db_path, receiver):
    """Met dispatcher aan bezorgt de achtergrondtaak vanzelf."""
    app = create_app(db_path, enable_dispatcher=True)
    with TestClient(app) as c:  # lifespan start de dispatcher-loop
        conn = db_module.connect(db_path)
        _, key = users_repo.create(
            conn, handle="person", display_name="Person", kind="human"
        )
        auth = {"Authorization": f"Bearer {key}"}
        _webhook_user(conn, "hermes", url=receiver.url, secret="s3cret")
        conn.close()

        c.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
        c.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
        c.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)

        deadline = time.time() + 5
        while time.time() < deadline and not receiver.received:
            time.sleep(0.1)

    assert len(receiver.received) == 1
    assert receiver.received[0]["headers"]["X-Betonning-Event"] == "item.updated"


# --- Inzicht + replay (BETON-52) ------------------------------------------


def test_list_deliveries_filters_by_status(client, auth, conn, project):
    _webhook_user(conn, "hermes")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    [delivery] = _deliveries_for(conn, "hermes")

    r = client.get("/api/v1/webhook-deliveries", headers=auth)
    assert r.status_code == 200
    assert any(d["id"] == delivery["id"] for d in r.json())

    r = client.get(
        "/api/v1/webhook-deliveries", params={"status": "failed"}, headers=auth
    )
    assert r.status_code == 200
    assert r.json() == []  # nog niets mislukt (pending)


def test_list_deliveries_finds_failed(client, auth, conn, project):
    _webhook_user(conn, "hermes")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    [delivery] = _deliveries_for(conn, "hermes")
    conn.execute(
        "UPDATE webhook_deliveries SET status = 'failed', attempts = 3, "
        "last_error = 'boom' WHERE id = ?",
        (delivery["id"],),
    )
    conn.commit()

    r = client.get(
        "/api/v1/webhook-deliveries", params={"status": "failed"}, headers=auth
    )
    assert r.status_code == 200
    ids = [d["id"] for d in r.json()]
    assert delivery["id"] in ids
    assert r.json()[0]["last_error"] == "boom"


def test_list_deliveries_enriches_target_and_event_type(client, auth, conn, project):
    # De lijst verrijkt elke delivery met de doel-user (handle) en het event-type,
    # zodat het UI-paneel (BETON-174) die zonder losse events-endpoint kan tonen.
    _webhook_user(conn, "hermes")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    [delivery] = _deliveries_for(conn, "hermes")

    r = client.get("/api/v1/webhook-deliveries", headers=auth)
    assert r.status_code == 200
    row = next(d for d in r.json() if d["id"] == delivery["id"])
    assert row["target_handle"] == "hermes"
    assert row["event_type"]  # niet-leeg (bv. 'item.updated')


def test_replay_resets_delivery(client, auth, conn, project):
    _webhook_user(conn, "hermes")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    [delivery] = _deliveries_for(conn, "hermes")
    conn.execute(
        "UPDATE webhook_deliveries SET status = 'failed', attempts = 3, "
        "last_error = 'boom', next_retry_at = '2099-01-01T00:00:00.000Z' WHERE id = ?",
        (delivery["id"],),
    )
    conn.commit()

    r = client.post(f"/api/v1/webhook-deliveries/{delivery['id']}/replay", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["attempts"] == 0
    assert body["last_error"] is None
    assert body["next_retry_at"] is None


def test_replay_unknown_delivery_404s(client, auth):
    r = client.post("/api/v1/webhook-deliveries/999999/replay", headers=auth)
    assert r.status_code == 404


def test_list_deliveries_403_for_agent(client, conn):
    # BETON-384: deliveries zijn troubleshooting-inzicht voor mensen, niet
    # gescopeerd naar "eigen" deliveries — een agent-key krijgt 403.
    agent_key = _webhook_user(conn, "hermes")
    r = client.get(
        "/api/v1/webhook-deliveries",
        headers={"Authorization": f"Bearer {agent_key}"},
    )
    assert r.status_code == 403


def test_replay_403_for_agent(client, auth, conn, project):
    agent_key = _webhook_user(conn, "hermes")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    [delivery] = _deliveries_for(conn, "hermes")

    r = client.post(
        f"/api/v1/webhook-deliveries/{delivery['id']}/replay",
        headers={"Authorization": f"Bearer {agent_key}"},
    )
    assert r.status_code == 403


# --- Zelf-dragende payload voor generieke agents (BETON-246) ----------------


def test_payload_mention_has_respond_instructions_and_context(
    client, auth, conn, project, receiver
):
    """Een @mention levert een zelf-dragende payload: NL-instructie, expected_action
    'respond', een reply-pad (incl. ophaalpad naar het ticket zelf)."""
    _webhook_user(conn, "joop", url=receiver.url)
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "@joop wat vind jij hiervan?"},
        headers=auth,
    )
    assert _run_deliver(conn) == 1
    body = json.loads(receiver.received[0]["body"])
    assert body["expected_action"] == "respond"
    assert "SOS-1" in body["instructions"]
    assert body["reply"]["url"].endswith("/api/v1/items/SOS-1/comments")
    assert body["reply"]["ref"] == "SOS-1"
    # BETON-290: geen bron-inhoud meer in de payload — de agent haalt het ticket
    # zelf op via het ophaalpad in de instructie/reply.
    assert "context" not in body
    assert body["reply"]["item_api_url"].endswith("/api/v1/items/SOS-1")
    assert "get_item" in body["instructions"]


def test_payload_assigned_has_pickup(client, auth, conn, project, receiver):
    """Toewijzing in een werkbare state → expected_action 'pick_up'."""
    # Eerst naar een werkbare state (een vers item staat in backlog, dat blokkeert
    # werk → dan zou 'acknowledge' terecht zijn); joop is dan nog niet betrokken.
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    _webhook_user(conn, "joop", url=receiver.url)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    assert _run_deliver(conn) == 1
    body = json.loads(receiver.received[0]["body"])
    assert body["expected_action"] == "pick_up"


def test_payload_subscribe_all_reader_gets_none(client, auth, conn, project, receiver):
    """Een subscribe_all-meelezer die niet geadresseerd is → expected_action 'none'."""
    _webhook_user(conn, "watcher", url=receiver.url, subscribe_all=True)
    users_repo.create(conn, handle="joop", display_name="joop", kind="agent")
    conn.commit()
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "@joop kun jij hiernaar kijken?"},
        headers=auth,
    )
    assert _run_deliver(conn) == 1
    body = json.loads(receiver.received[0]["body"])
    assert body["expected_action"] == "none"


# build_instructions is puur (dict-gebaseerd) — de expected_action-matrix los getest.


def _instr(trigger, policy, handle="joop"):
    item = {"ref": "SOS-1", "project": "SOS", "seq": 1}
    return webhooks.build_instructions({"handle": handle}, item, trigger, policy)


def test_build_instructions_respond_on_mention():
    r = _instr(
        {"type": "mention", "mentioned_by": "person", "addressed_to": ["joop"]},
        {"work_allowed": True, "state": "todo"},
    )
    assert r["expected_action"] == "respond"
    assert "reageren" in r["instructions"].lower()


@pytest.mark.parametrize("language", ["en", "nl"])
def test_instructions_use_human_readable_comment_references(monkeypatch, language):
    from betonning.outbound import outbound

    monkeypatch.setenv("HEGEMONE_LANGUAGE", language)
    result = _instr(
        {"type": "mention", "mentioned_by": "person", "addressed_to": ["worker"]},
        {"work_allowed": True, "state": "todo"},
        handle="worker",
    )
    assert result["expected_action"] == "respond"
    assert outbound("human_comment_references", language=language) in result["instructions"]
    assert result["reply"]["url"].endswith("/api/v1/items/SOS-1/comments")


def test_build_instructions_pickup_on_assigned_workable():
    r = _instr(
        {"type": "assigned", "mentioned_by": None, "addressed_to": None},
        {"work_allowed": True, "state": "todo"},
    )
    assert r["expected_action"] == "pick_up"


def test_build_instructions_acknowledge_when_work_blocked():
    r = _instr(
        {"type": "assigned", "mentioned_by": None, "addressed_to": None},
        {"work_allowed": False, "state": "review"},
    )
    assert r["expected_action"] == "acknowledge"


def test_build_instructions_comment_without_mention_on_own_item_is_respond():
    """BETON-299 (matrix-rij 3): een comment ZONDER mentions op een item waarvan
    de ontvanger assignee is, mag nooit 'pick_up' opleveren — dat is het gat
    tussen A2 (BETON-291, alleen item.updated) en A3 (BETON-292). `pick_up`
    hoort alleen bij een echte toewijzing/vrijgave, nooit bij een opmerking."""
    item = {"ref": "SOS-1", "project": "SOS", "seq": 1, "assignee": "joop"}
    trigger = {"type": "assigned", "mentioned_by": "person", "addressed_to": []}
    r = webhooks.build_instructions(
        {"handle": "joop"},
        item,
        trigger,
        {"work_allowed": True, "state": "todo"},
        event_type="comment.created",
    )
    assert r["expected_action"] == "respond"
    assert "reageren" in r["instructions"].lower()
    assert "opgepakt" not in r["instructions"].lower()


def test_build_instructions_comment_without_mention_blocked_state_is_acknowledge():
    """Dezelfde comment-zonder-mention-situatie, maar in een blokkerende state:
    acknowledge (mag reageren, niet uitvoeren), net als de item.updated-tak."""
    item = {"ref": "SOS-1", "project": "SOS", "seq": 1, "assignee": "joop"}
    trigger = {"type": "assigned", "mentioned_by": "person", "addressed_to": []}
    r = webhooks.build_instructions(
        {"handle": "joop"},
        item,
        trigger,
        {"work_allowed": False, "state": "review"},
        event_type="comment.created",
    )
    assert r["expected_action"] == "acknowledge"


def test_build_instructions_comment_with_mention_of_assignee_still_respond():
    """Regressie: een comment MET een mention van de assignee zelf blijft
    'respond' opleveren via de bestaande mention-tak (voorrang boven de
    nieuwe assigned+comment-tak, die overigens ook 'respond' zou geven)."""
    item = {"ref": "SOS-1", "project": "SOS", "seq": 1, "assignee": "joop"}
    trigger = {
        "type": "mention",
        "mentioned_by": "person",
        "addressed_to": ["joop"],
    }
    r = webhooks.build_instructions(
        {"handle": "joop"},
        item,
        trigger,
        {"work_allowed": True, "state": "todo"},
        event_type="comment.created",
    )
    assert r["expected_action"] == "respond"


def test_build_instructions_directed_comment_to_other_stays_none_not_pickup():
    """Regressie voor rij 2 (BRAND-150/A3): een gerichte comment aan iemand
    anders blijft 'none', ook met de nieuwe assigned+comment-tak (only_reading
    beslist vóór ttype/event_type worden bekeken)."""
    item = {"ref": "SOS-1", "project": "SOS", "seq": 1, "assignee": "joop"}
    trigger = {
        "type": "assigned",
        "mentioned_by": "person",
        "addressed_to": ["lobke"],
    }
    r = webhooks.build_instructions(
        {"handle": "joop"},
        item,
        trigger,
        {"work_allowed": True, "state": "todo"},
        event_type="comment.created",
    )
    assert r["expected_action"] == "none"


def test_comment_without_mention_on_own_item_delivers_respond_end_to_end(
    client, auth, conn, project, receiver
):
    """De volledige regressie via de echte PATCH/comment-flow (niet alleen de
    pure build_instructions-eenheid): een comment zonder mentions op een item
    waarvan de webhook-agent assignee is, levert 'respond' op, niet 'pick_up'."""
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    _webhook_user(conn, "joop", url=receiver.url)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    _run_deliver(conn)
    receiver.received.clear()

    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "geen mention hier"},
        headers=auth,
    )
    assert _run_deliver(conn) == 1
    body = json.loads(receiver.received[0]["body"])
    assert body["trigger"]["type"] == "assigned"
    assert body["expected_action"] == "respond"
    assert "opgepakt" not in body["instructions"].lower()


def test_build_instructions_none_for_unaddressed_reader():
    # Gerichte comment aan iemand anders, ontvanger is geen assignee → alleen meelezen.
    r = _instr(
        {"type": "participant", "mentioned_by": "person", "addressed_to": ["bob"]},
        {"work_allowed": True, "state": "todo"},
    )
    assert r["expected_action"] == "none"


def test_build_instructions_work_unblocked_non_assignee_not_pickup():
    """BETON-246 (advisor): de vrijgave-fanout notificeert óók niet-assignees
    (maker/participants). Die mogen NOOIT 'pick_up' + 'aan jou toegewezen' horen —
    dat zou het BRAND-150-ping-pong terugbrengen. Item is aan 'alice' toegewezen,
    ontvanger 'joop' was eerder betrokken → geen pick_up, geen ownership-claim."""
    item = {"ref": "SOS-1", "project": "SOS", "seq": 1, "assignee": "alice"}
    trigger = {
        "type": "participant",
        "mentioned_by": "person",
        "addressed_to": None,
        "work_unblocked": True,
    }
    r = webhooks.build_instructions(
        {"handle": "joop"}, item, trigger, {"work_allowed": True, "state": "todo"}
    )
    assert r["expected_action"] == "none"
    assert "toegewezen" not in r["instructions"].lower()


def test_build_instructions_work_unblocked_assignee_gets_pickup():
    """De échte assignee bij een vrijgave → wél 'pick_up'."""
    item = {"ref": "SOS-1", "project": "SOS", "seq": 1, "assignee": "joop"}
    trigger = {
        "type": "participant",
        "mentioned_by": "person",
        "addressed_to": None,
        "work_unblocked": True,
    }
    r = webhooks.build_instructions(
        {"handle": "joop"}, item, trigger, {"work_allowed": True, "state": "todo"}
    )
    assert r["expected_action"] == "pick_up"


def test_build_instructions_none_without_item_or_trigger():
    assert (
        webhooks.build_instructions(
            {"handle": "joop"}, None, {"type": "assigned"}, {"work_allowed": True}
        )
        is None
    )
    assert (
        webhooks.build_instructions(
            {"handle": "joop"},
            {"ref": "SOS-1", "project": "SOS", "seq": 1},
            None,
            {"work_allowed": True},
        )
        is None
    )


def test_build_instructions_answered_for_question_asker():
    """BETON-280: question.answered → expected_action 'answered', instructies
    verwijzen naar het inline-antwoord (BETON-265, geen los antwoord-comment)."""
    item = {"ref": "SOS-1", "project": "SOS", "seq": 1, "assignee": "joop"}
    trigger = {"type": "assigned", "mentioned_by": None, "addressed_to": None}
    r = webhooks.build_instructions(
        {"handle": "joop"},
        item,
        trigger,
        {"work_allowed": True, "state": "todo"},
        event_type="question.answered",
    )
    assert r["expected_action"] == "answered"
    assert "answer_text" in r["instructions"]


def test_build_instructions_answered_stays_none_for_subscribe_all_reader():
    """Een pure subscribe_all-meelezer hoort geen actie-opdracht te krijgen, ook
    niet bij question.answered — het bestaande 'none'-pad voor meelezers blijft
    voorrang houden."""
    item = {"ref": "SOS-1", "project": "SOS", "seq": 1, "assignee": "alice"}
    trigger = {"type": "subscribe_all", "mentioned_by": None, "addressed_to": None}
    r = webhooks.build_instructions(
        {"handle": "joop"},
        item,
        trigger,
        {"work_allowed": True, "state": "todo"},
        event_type="question.answered",
    )
    assert r["expected_action"] == "none"


def test_build_instructions_mention_unaffected_by_event_type():
    """Regressie: een gewoon mention-event zonder event_type (of met een ander
    event_type) blijft gewoon 'respond' opleveren."""
    r = webhooks.build_instructions(
        {"handle": "joop"},
        {"ref": "SOS-1", "project": "SOS", "seq": 1},
        {"type": "mention", "mentioned_by": "person", "addressed_to": ["joop"]},
        {"work_allowed": True, "state": "todo"},
        event_type="comment.created",
    )
    assert r["expected_action"] == "respond"


# --- BETON-291: expected_action afleiden uit het gewijzigde veld ------------
#
# `type == "assigned"` betekent "jij bent de assignee", NIET "je bent zojuist
# toegewezen" — dus mag een item.updated met alleen een labelwijziging niet
# blind 'pick_up' opleveren. `build_trigger` zet daarvoor `changed_fields`
# (en evt. `assignee_changed_to_me`/`to_state_grp`) op de trigger; deze tests
# oefenen `_field_based_action` (via `build_instructions`) rechtstreeks uit met
# handmatig samengestelde triggers, zoals de bestaande matrix-tests hierboven.


def _assigned_trigger(**overrides):
    trigger = {"type": "assigned", "mentioned_by": None, "addressed_to": None}
    trigger.update(overrides)
    return trigger


def test_build_instructions_label_change_on_assignee_is_none():
    """De regressietest voor de kern van BETON-282: een labelwijziging op een
    item waarvan de agent assignee is levert GEEN pick_up meer op."""
    r = _instr(
        _assigned_trigger(changed_fields=["labels"]),
        {"work_allowed": True, "state": "todo"},
    )
    assert r["expected_action"] == "none"


def test_build_instructions_plan_md_change_is_none():
    r = _instr(
        _assigned_trigger(changed_fields=["plan_md"]),
        {"work_allowed": True, "state": "todo"},
    )
    assert r["expected_action"] == "none"


def test_build_instructions_description_change_is_none():
    r = _instr(
        _assigned_trigger(changed_fields=["description_md"]),
        {"work_allowed": True, "state": "todo"},
    )
    assert r["expected_action"] == "none"


def test_build_instructions_state_change_within_workable_is_none():
    """todo → in-progress: geen van beide blokkeert werk, dus geen work_unblocked
    en geen completed/cancelled-groep → 'none', niet 'pick_up'."""
    r = _instr(
        _assigned_trigger(
            changed_fields=["state"], to_state_grp="started", work_unblocked=False
        ),
        {"work_allowed": True, "state": "in-progress"},
    )
    assert r["expected_action"] == "none"


def test_build_instructions_state_to_done_from_blocked_is_stand_down():
    """blocked (blocks_work=1) → done (blocks_work=0) zet `work_unblocked` op
    True (blocks_work-flip), maar dit is het item SLUITEN, geen vrijgave van
    werk. De grp-check (`to_state_grp == 'completed'`) moet vóór work_unblocked
    beslissen, anders levert dit ten onrechte 'pick_up' op.

    BETON-293 (matrixrij 9) scherpt de A2-uitkomst aan van `none` naar
    `stand_down`: de assignee wás hiermee bezig en moet nú stoppen."""
    r = _instr(
        _assigned_trigger(
            changed_fields=["state"], to_state_grp="completed", work_unblocked=True
        ),
        {"work_allowed": True, "state": "done"},
    )
    assert r["expected_action"] == "stand_down"


def test_build_instructions_state_to_cancelled_from_blocked_is_stand_down():
    r = _instr(
        _assigned_trigger(
            changed_fields=["state"], to_state_grp="cancelled", work_unblocked=True
        ),
        {"work_allowed": True, "state": "cancelled"},
    )
    assert r["expected_action"] == "stand_down"


def test_build_instructions_assignee_change_to_me_workable_is_pickup():
    r = _instr(
        _assigned_trigger(changed_fields=["assignee"], assignee_changed_to_me=True),
        {"work_allowed": True, "state": "todo"},
    )
    assert r["expected_action"] == "pick_up"


def test_build_instructions_assignee_change_to_me_blocking_state_is_acknowledge():
    r = _instr(
        _assigned_trigger(changed_fields=["assignee"], assignee_changed_to_me=True),
        {"work_allowed": False, "state": "blocked"},
    )
    assert r["expected_action"] == "acknowledge"


def test_build_instructions_state_change_release_still_pickup():
    """Regressietest: een écht werkende vrijgave (blocked → workable) via het
    gewijzigde-veld-pad blijft 'pick_up' opleveren — geen regressie op de
    bestaande work_unblocked-vrijgavelogica."""
    r = _instr(
        _assigned_trigger(
            changed_fields=["state"], to_state_grp="unstarted", work_unblocked=True
        ),
        {"work_allowed": True, "state": "todo"},
    )
    assert r["expected_action"] == "pick_up"


def test_build_instructions_combined_assignee_and_labels_prefers_pickup():
    """Meerdere velden tegelijk (assignee, labels): assignee weegt zwaarder."""
    r = _instr(
        _assigned_trigger(
            changed_fields=["assignee", "labels"], assignee_changed_to_me=True
        ),
        {"work_allowed": True, "state": "todo"},
    )
    assert r["expected_action"] == "pick_up"


def test_build_instructions_combined_labels_and_state_uses_state():
    """Meerdere velden tegelijk (labels, state) zonder assignee-wijziging: state
    weegt zwaarder dan labels (maar levert hier zelf 'none' op, geen vrijgave)."""
    r = _instr(
        _assigned_trigger(
            changed_fields=["labels", "state"],
            to_state_grp="started",
            work_unblocked=False,
        ),
        {"work_allowed": True, "state": "in-progress"},
    )
    assert r["expected_action"] == "none"


def test_build_instructions_participant_label_change_is_none():
    """Dezelfde generieke fallback (niet-assignee, bv. 'participant') had
    hetzelfde probleem — ook daar mag een labelwijziging geen 'respond' geven."""
    r = _instr(
        {
            "type": "participant",
            "mentioned_by": "person",
            "addressed_to": None,
            "changed_fields": ["labels"],
        },
        {"work_allowed": True, "state": "todo"},
    )
    assert r["expected_action"] == "none"


def test_field_based_action_none_without_changed_fields_falls_through():
    """Zonder `changed_fields` (geen item.updated-context) valt de aanroeper
    terug op het oude gedrag — geborgd door de bestaande matrix-tests hierboven
    (test_build_instructions_pickup_on_assigned_workable e.a.), hier expliciet
    getest op de helper zelf."""
    assert webhooks._field_based_action({"type": "assigned"}, True) is None


# --- End-to-end: de echte flow (PATCH labels) via build_trigger + fanout ----


def test_label_change_on_assignee_item_delivers_none_end_to_end(
    client, auth, conn, project, receiver
):
    """De volledige regressie voor BETON-282/291, via de echte PATCH-flow (niet
    alleen de pure build_instructions-eenheid): een labelwijziging op een item
    waarvan de webhook-agent assignee is, mag geen `pick_up` meer opleveren."""
    _webhook_user(conn, "joop", url=receiver.url)
    client.post("/api/v1/projects/SOS/labels", json={"name": "urgent"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    _run_deliver(conn)
    receiver.received.clear()

    client.patch("/api/v1/items/SOS-1", json={"labels": ["urgent"]}, headers=auth)
    assert _run_deliver(conn) == 1
    body = json.loads(receiver.received[0]["body"])
    assert body["trigger"]["type"] == "assigned"
    assert body["trigger"]["changed_fields"] == ["labels"]
    assert body["expected_action"] == "none"


# --- BETON-292: `do`/`do_not`/`read` als gestructureerde velden ------------
#
# Een scherpe opdracht met een leeslijst i.p.v. alleen `instructions`: `do`
# (wat verwacht wordt), `do_not` (de grenzen, expliciet) en `read` (welke
# bron, hoe, waarom). Grenzen zijn AFGELEID uit wat al berekend werd
# (`agent_policy`, `access.effective_level`, `trigger.addressed_to`).


def test_do_not_none_for_directed_comment_to_other_when_assignee():
    """Rij 2 — regressietest voor BRAND-150: een gerichte comment aan iemand
    anders levert 'none' op, óók als de ontvanger de assignee is (de assignee
    is geen uitzondering op 'aan iemand anders gericht'). `read` is dan leeg."""
    item = {"ref": "SOS-1", "project": "SOS", "seq": 1, "assignee": "joop"}
    trigger = {
        "type": "assigned",
        "mentioned_by": "person",
        "addressed_to": ["lobke"],
        "excerpt": "@lobke waarom heb je dit aangemaakt?",
    }
    r = webhooks.build_instructions(
        {"handle": "joop"},
        item,
        trigger,
        {"work_allowed": True, "state": "todo"},
        event_type="comment.created",
    )
    assert r["expected_action"] == "none"
    assert r["read"] == []
    assert any("iemand anders" in d for d in r["do_not"])


def test_read_includes_get_plan_when_has_plan(client, auth, conn, project, receiver):
    """Rij 5: een pick_up mét `has_plan: true` moet een `get_plan`-stap in de
    leeslijst hebben."""
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"plan_md": "# Plan"}, headers=auth)
    _webhook_user(conn, "joop", url=receiver.url)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    assert _run_deliver(conn) == 1
    body = json.loads(receiver.received[0]["body"])
    assert body["expected_action"] == "pick_up"
    assert any('get_plan("SOS-1")' in step["hoe"] for step in body["read"])


def test_read_omits_get_plan_when_no_plan(client, auth, conn, project, receiver):
    """Zelfde rij 5, maar zónder plan_md — geen `get_plan`-stap."""
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    _webhook_user(conn, "joop", url=receiver.url)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    assert _run_deliver(conn) == 1
    body = json.loads(receiver.received[0]["body"])
    assert body["expected_action"] == "pick_up"
    assert not any("get_plan" in step["hoe"] for step in body["read"])
    assert any('load_memory(project="SOS")' in step["hoe"] for step in body["read"])


def test_do_not_states_execution_forbidden_when_state_blocks():
    """Rij 6: een blokkerende state moet expliciet benoemen dat uitvoeren niet
    mag."""
    item = {"ref": "SOS-1", "project": "SOS", "seq": 1, "assignee": "joop"}
    trigger = {"type": "assigned", "mentioned_by": None, "addressed_to": None}
    r = webhooks.build_instructions(
        {"handle": "joop"},
        item,
        trigger,
        {"work_allowed": False, "state": "review"},
    )
    assert r["expected_action"] == "acknowledge"
    assert any("niet uit" in d.lower() or "verbiedt" in d.lower() for d in r["do_not"])


def test_do_not_states_pickup_forbidden_for_respond_access_level(
    client, auth, conn, project, receiver
):
    """`access.effective_level == 'respond'` betekent 'reageren mag, oppakken
    niet' — die grens moet expliciet in `do_not` staan, ook als de agent zelf
    assignee is."""
    users_repo.create(
        conn,
        handle="smid",
        display_name="Smid",
        kind="agent",
        agent_type="hermes",
        webhook_url=receiver.url,
        webhook_secret="s",
    )
    access.set_type_access(conn, _project_id(conn), "hermes", "respond")
    conn.commit()
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "smid"}, headers=auth)
    assert _run_deliver(conn) == 1
    body = json.loads(receiver.received[0]["body"])
    assert any("respond" in d and "oppakken" in d for d in body["do_not"])


def test_do_not_always_includes_universal_boundaries():
    """De universele grenzen staan in élk `do_not`, ongeacht `expected_action`."""
    item = {"ref": "SOS-1", "project": "SOS", "seq": 1, "assignee": "joop"}
    trigger = {"type": "mention", "mentioned_by": "person", "addressed_to": ["joop"]}
    r = webhooks.build_instructions(
        {"handle": "joop"}, item, trigger, {"work_allowed": True, "state": "todo"}
    )
    assert "Reageer niet als de thread al afgehandeld is." in r["do_not"]
    assert "Plaats geen comment die niets toevoegt." in r["do_not"]
    assert "Bevestig niet louter dat je het gezien hebt." in r["do_not"]


def test_read_empty_for_subscribe_all_none(client, auth, conn, project, receiver):
    """Rij 22: een pure subscribe_all-meelezer krijgt een lege leeslijst."""
    _webhook_user(conn, "watcher", url=receiver.url, subscribe_all=True)
    users_repo.create(conn, handle="joop", display_name="joop", kind="agent")
    conn.commit()
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "@joop kun jij hiernaar kijken?"},
        headers=auth,
    )
    assert _run_deliver(conn) == 1
    body = json.loads(receiver.received[0]["body"])
    assert body["expected_action"] == "none"
    assert body["read"] == []
    assert body["do_not"]


def test_read_includes_load_memory_for_mention_respond(
    client, auth, conn, project, receiver
):
    """Rij 1/15: een @mention-respond haalt zowel het ticket als
    `load_memory(project=...)` op."""
    _webhook_user(conn, "joop", url=receiver.url)
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "@joop wat vind jij hiervan?"},
        headers=auth,
    )
    assert _run_deliver(conn) == 1
    body = json.loads(receiver.received[0]["body"])
    assert body["expected_action"] == "respond"
    assert any('get_item("SOS-1")' in step["hoe"] for step in body["read"])
    assert any('load_memory(project="SOS")' in step["hoe"] for step in body["read"])


def test_do_do_not_read_positioned_after_instructions_in_payload(conn, project):
    """Sleutelvolgorde: `do`/`do_not`/`read` staan ná `instructions` maar vóór
    de brondata-armere staart (`event`/`item`/`wiki`)."""
    users_repo.create(
        conn,
        handle="joop",
        display_name="joop",
        kind="agent",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
    )
    conn.commit()
    from betonning.repo import events as events_repo

    item_id = conn.execute("SELECT id FROM items WHERE seq = 1").fetchone()["id"]
    event = events_repo.record(
        conn, type="comment.created", item_id=item_id, actor_id=None, payload={}
    )
    user = conn.execute("SELECT * FROM users WHERE handle = 'joop'").fetchone()
    payload = webhooks.build_delivery_payload(conn, event, user)
    keys = list(payload.keys())
    assert keys.index("instructions") < keys.index("do") < keys.index("reply")
    assert keys.index("instructions") < keys.index("do_not") < keys.index("reply")
    assert keys.index("instructions") < keys.index("read") < keys.index("reply")
    tail = [k for k in ("event", "item", "wiki") if k in keys]
    assert keys.index("reply") < min(keys.index(k) for k in tail)


# --- BETON-293: stand_down + notificatie aan de vórige assignee -------------
#
# De matrixrijen 7/9/17/19-21 uit BETON-288, plus de fanout-uitbreiding. Dit is
# de enige stap in de A-keten die notificaties TOEVOEGT, dus de grenzen (alleen
# de vorige assignee, alleen bij een echte wijziging, nooit de actor, nooit een
# `none`-agent) worden hier stuk voor stuk vastgelegd.


def _delivery_action(conn, handle):
    """De `expected_action` uit de payload die `handle` voor het laatste event
    zou krijgen — via `build_delivery_payload`, dus exact wat over de wire gaat."""
    rows = _deliveries_for(conn, handle)
    assert rows, f"geen delivery voor @{handle}"
    event = conn.execute(
        "SELECT * FROM events WHERE id = ?", (rows[-1]["event_id"],)
    ).fetchone()
    user = users_repo.get_by_handle(conn, handle)
    return webhooks.build_delivery_payload(conn, event, user)["expected_action"]


def test_assignee_handover_stands_down_previous_and_picks_up_new(
    client, auth, conn, project
):
    """De kern van BETON-293: bij A → B krijgt A `stand_down` en B `pick_up`.
    Vóór dit ticket kreeg A helemaal niets en kon hij doorwerken aan iets dat
    niet meer van hem was."""
    _webhook_user(conn, "lobke")
    _webhook_user(conn, "joop")
    # De default-state `backlog` blokkeert werk (blocks_work=1) → dat zou
    # `acknowledge` opleveren i.p.v. `pick_up`; dit gaat over de toewijzing.
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)

    assert len(_deliveries_for(conn, "lobke")) == 2  # toewijzing + weghalen
    assert _delivery_action(conn, "lobke") == "stand_down"
    assert _delivery_action(conn, "joop") == "pick_up"


def test_assignee_removed_to_nobody_stands_down_previous(client, auth, conn, project):
    _webhook_user(conn, "lobke")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": None}, headers=auth)

    assert len(_deliveries_for(conn, "lobke")) == 2
    assert _delivery_action(conn, "lobke") == "stand_down"


def test_assignee_noop_change_creates_no_extra_delivery(client, auth, conn, project):
    """Een no-op-PATCH schrijft geen event (verbeterplan A) en mag dus ook geen
    'de ticket is bij je weggehaald'-bericht opleveren."""
    _webhook_user(conn, "lobke")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    before = len(_deliveries_for(conn, "lobke"))
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    assert len(_deliveries_for(conn, "lobke")) == before


def test_previous_assignee_who_is_the_actor_gets_no_delivery(client, conn, project):
    """Geeft de agent het ticket zelf weg, dan weet hij het al — de actor-skip
    in `fanout` blijft onverkort gelden."""
    key = _webhook_user(conn, "lobke")
    _webhook_user(conn, "joop")
    lobke_auth = {"Authorization": f"Bearer {key}"}
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=lobke_auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=lobke_auth)

    assert _deliveries_for(conn, "lobke") == []
    assert len(_deliveries_for(conn, "joop")) == 1


def test_previous_assignee_with_access_none_gets_no_delivery(
    client, auth, conn, project
):
    """De `access`-poort (BETON-123) blijft gelden: een agent met effectief
    niveau `none` op dit project wordt nooit getriggerd, ook niet om te stoppen."""
    _webhook_user(conn, "lobke")
    _webhook_user(conn, "joop")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    client.put(
        "/api/v1/projects/SOS/access/agent/lobke", json={"level": "none"}, headers=auth
    )
    before = len(_deliveries_for(conn, "lobke"))
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    assert len(_deliveries_for(conn, "lobke")) == before


def test_previous_assignee_who_muted_gets_no_delivery(client, auth, conn, project):
    """De mute-filter (BETON-245) blijft een filter over de héle doelgroep."""
    _webhook_user(conn, "lobke")
    _webhook_user(conn, "joop")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    client.post("/api/v1/items/SOS-1/subscribers/lobke/mute", headers=auth)
    before = len(_deliveries_for(conn, "lobke"))
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    assert len(_deliveries_for(conn, "lobke")) == before


def test_state_to_done_stands_down_assignee(client, auth, conn, project):
    """Matrixrij 9, end-to-end (was `none` na A2)."""
    _webhook_user(conn, "lobke")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"state": "Done"}, headers=auth)
    assert _delivery_action(conn, "lobke") == "stand_down"


def test_archived_item_stands_down_assignee(client, auth, conn, project):
    """Matrixrij 17. NB: `item.deleted` (hard delete) kent geen fanout — dat
    event wordt met item_id=NULL weggeschreven — dus daar valt niets te testen."""
    _webhook_user(conn, "lobke")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    client.delete("/api/v1/items/SOS-1", headers=auth)
    assert _delivery_action(conn, "lobke") == "stand_down"


def test_blocked_by_relation_stands_down_assignee(client, auth, conn, project):
    """Matrixrij 19: er is een blokkade op jouw item gelegd → niet beginnen."""
    _webhook_user(conn, "lobke")
    client.post("/api/v1/projects/SOS/items", json={"title": "blokker"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocked_by", "target": "SOS-2"},
        headers=auth,
    )
    assert _delivery_action(conn, "lobke") == "stand_down"


def test_unblocking_relation_delete_picks_up_assignee(client, auth, conn, project):
    """Matrixrij 21: dezelfde relatie weer weg → de assignee mag door."""
    _webhook_user(conn, "lobke")
    client.post("/api/v1/projects/SOS/items", json={"title": "blokker"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocked_by", "target": "SOS-2"},
        headers=auth,
    )
    client.request(
        "DELETE",
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocked_by", "target": "SOS-2"},
        headers=auth,
    )
    assert _delivery_action(conn, "lobke") == "pick_up"


def test_blocks_relation_does_not_stand_down_the_blocker(client, auth, conn, project):
    """De tegenhanger van rij 19: als JOUW item iets ánders blokkeert, is er voor
    jou niets aan de hand — je werkt gewoon door. Richting is alles."""
    _webhook_user(conn, "lobke")
    client.post("/api/v1/projects/SOS/items", json={"title": "ander"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-2"},
        headers=auth,
    )
    assert _delivery_action(conn, "lobke") != "stand_down"


def test_duplicate_of_stands_down_only_the_duplicate(client, auth, conn, project):
    """Matrixrij 20 + de richting-valkuil: de assignee van het DUPLICAAT stopt,
    die van het canonieke item hoort niets. `repo/relations.py` slaat de bron
    (`item_id`) altijd op als het duplicaat — SOS-1 is hier het duplicaat."""
    _webhook_user(conn, "lobke")
    _webhook_user(conn, "joop")
    client.post("/api/v1/projects/SOS/items", json={"title": "canoniek"}, headers=auth)
    client.patch("/api/v1/items/SOS-2", json={"state": "todo"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    client.patch("/api/v1/items/SOS-2", json={"assignee": "joop"}, headers=auth)
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "duplicate_of", "target": "SOS-2"},
        headers=auth,
    )
    assert _delivery_action(conn, "lobke") == "stand_down"
    # joop (het canonieke item) krijgt van deze relatie geen enkel event: een
    # gericht relatietype spiegelt niet (BETON-138). Zijn laatste delivery is nog
    # steeds zijn eigen toewijzing.
    assert _delivery_action(conn, "joop") == "pick_up"


def test_duplicated_by_does_not_stand_down_the_canonical_item(
    client, auth, conn, project
):
    """Dezelfde relatie vanaf de andere kant gelegd (`duplicated_by` op het
    canonieke item): het canonieke item is juist NIET het duplicaat en mag dus
    geen stopsein krijgen."""
    _webhook_user(conn, "joop")
    client.post("/api/v1/projects/SOS/items", json={"title": "duplicaat"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "duplicated_by", "target": "SOS-2"},
        headers=auth,
    )
    assert _delivery_action(conn, "joop") != "stand_down"


def test_stand_down_payload_has_empty_read_and_hard_boundaries(client, auth, conn):
    """De vorm van een `stand_down`: lege leeslijst (niets ophalen, niets doen),
    en `do_not` draagt de kern."""
    r = webhooks.build_instructions(
        {"handle": "lobke"},
        {"ref": "SOS-1", "project": "SOS", "seq": 1, "assignee": "lobke"},
        _assigned_trigger(
            changed_fields=["assignee"],
            assignee_changed_to_me=False,
            assignee_changed_from_me=True,
        ),
        {"work_allowed": True, "state": "todo"},
    )
    assert r["expected_action"] == "stand_down"
    assert r["read"] == []
    assert "STOP" in r["instructions"]
    # Geen "reageren doe je via ..." — dat is precies wat NIET moet.
    assert "Reageren doe je via" not in r["instructions"]
    joined = " ".join(r["do_not"]).lower()
    assert "geen comment" in joined
    assert "af" in joined


def test_stand_down_survives_gateway_truncation_with_huge_description(
    client, auth, conn, project, receiver
):
    """De budget-/knipgarantie van BETON-290 blijft staan voor de nieuwe actie:
    juist een stopsein moet de knip van 4000 tekens overleven."""
    _webhook_user(conn, "lobke", url=receiver.url)
    _webhook_user(conn, "joop", url=receiver.url)
    client.patch(
        "/api/v1/items/SOS-1", json={"description_md": "x" * 50_000}, headers=auth
    )
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)

    rows = _deliveries_for(conn, "lobke")
    event = conn.execute(
        "SELECT * FROM events WHERE id = ?", (rows[-1]["event_id"],)
    ).fetchone()
    body = webhooks.build_delivery_payload(
        conn, event, users_repo.get_by_handle(conn, "lobke")
    )
    truncated = _gateway_truncated(body)
    assert "stand_down" in truncated
    assert '"instructions"' in truncated
    assert "SOS-1" in truncated


# --- record_and_fanout / _touch (BETON-321) --------------------------------


def test_record_and_fanout_creates_event_and_delivery(client, auth, conn, project):
    """`record_and_fanout` moet exact hetzelfde opleveren als een losse
    `events_repo.record` + `fanout`-aanroep: één event, één delivery, en de
    fanout-kwargs (hier `mentions`) gaan door naar `fanout`."""
    _webhook_user(conn, "hermes")
    item = items_repo.get_by_ref(conn, "SOS-1")

    event = webhooks.record_and_fanout(
        conn,
        type="item.updated",
        item_id=item["id"],
        actor_id=None,
        payload={"foo": "bar"},
        mentions=["hermes"],
    )

    assert event["type"] == "item.updated"
    stored = conn.execute("SELECT * FROM events WHERE id = ?", (event["id"],)).fetchone()
    assert stored is not None
    assert len(_deliveries_for(conn, "hermes")) == 1


def test_touch_marker_is_idempotent(conn, project):
    """`_touch` zet de marker eenmalig (WHERE ... AND col IS NULL); een tweede
    aanroep is een no-op — geen tweede write (rowcount 0), de eerst gezette
    timestamp blijft staan (BETON-321)."""
    item = items_repo.get_by_ref(conn, "SOS-1")
    assert item is not None

    before = conn.execute(
        "SELECT archived_at FROM items WHERE id = ?", (item["id"],)
    ).fetchone()["archived_at"]
    assert before is None

    events_repo._touch(conn, "items", "archived_at", item["id"])
    first = conn.execute(
        "SELECT archived_at FROM items WHERE id = ?", (item["id"],)
    ).fetchone()["archived_at"]
    assert first is not None

    changes_before = conn.total_changes
    events_repo._touch(conn, "items", "archived_at", item["id"])
    assert conn.total_changes == changes_before  # tweede aanroep is een no-op

    second = conn.execute(
        "SELECT archived_at FROM items WHERE id = ?", (item["id"],)
    ).fetchone()["archived_at"]
    assert first == second


# --- Webhook-host-poort (BETON-378) ---------------------------------------


def test_webhook_url_error_rejects_scheme_and_missing_host():
    assert webhooks.webhook_url_error("ftp://hermes.local/hook") is not None
    assert webhooks.webhook_url_error("file:///etc/passwd") is not None
    assert webhooks.webhook_url_error("niet-eens-een-url") is not None
    # Leegmaken/ontkoppelen mag altijd.
    assert webhooks.webhook_url_error(None) is None
    assert webhooks.webhook_url_error("") is None


def test_webhook_url_error_rejects_loopback_and_link_local():
    for url in (
        "http://127.0.0.1/hook",
        "http://127.0.0.53:8080/hook",
        "http://[::1]/hook",
        "http://localhost:8000/hook",
        "http://169.254.169.254/latest/meta-data/",  # cloud-metadata
    ):
        assert webhooks.webhook_url_error(url) is not None, url


def test_webhook_url_error_allows_normal_hosts_without_allowlist():
    # Zonder allowlist mag alles behalve loopback/link-local — de Hermes-gateway
    # staat op een privé-adres, dus RFC1918 blokkeren zou de fanout doodleggen.
    assert webhooks.webhook_url_error("https://hermes.example/hook") is None
    assert webhooks.webhook_url_error("http://10.23.45.67:8080/hook") is None


def test_webhook_allowlist_limits_hosts(monkeypatch):
    monkeypatch.setenv(
        "BETONNING_WEBHOOK_ALLOWED_HOSTS", "10.23.45.67, *.hermes.example"
    )
    assert webhooks.webhook_url_error("http://10.23.45.67:8080/hook") is None
    assert webhooks.webhook_url_error("https://gw.hermes.example/hook") is None
    assert webhooks.webhook_url_error("https://hermes.example/hook") is None  # wildcard-kern
    assert webhooks.webhook_url_error("https://evil.invalid/hook") is not None
    # Loopback blijft ook mét allowlist verboden zolang de escape uit staat.
    assert webhooks.webhook_url_error("http://127.0.0.1/hook") is not None


def test_loopback_escape_opens_the_gate(monkeypatch):
    monkeypatch.setenv("BETONNING_WEBHOOK_ALLOW_LOOPBACK", "1")
    assert webhooks.webhook_url_error("http://127.0.0.1:9000/hook") is None


def test_delivery_to_disallowed_host_is_not_sent(
    client, conn, auth, project, receiver, monkeypatch
):
    """Vuurmoment-poort: een niet-toegestane host levert géén HTTP-call op en de
    delivery gaat definitief op failed (geen retries)."""
    _webhook_user(conn, "lobke", url=receiver.url)
    conn.commit()

    client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "Iets", "assignee": "lobke"},
        headers=auth,
    )
    # De allowlist wordt ná het aanmaken versmald: de bestaande URL valt er nu buiten.
    monkeypatch.setenv("BETONNING_WEBHOOK_ALLOWED_HOSTS", "hermes.example")

    _run_deliver(conn)
    assert receiver.received == []
    rows = _deliveries_for(conn, "lobke")
    assert [r["status"] for r in rows] == ["failed"]
    assert "niet toegestaan" in rows[0]["last_error"]
    assert rows[0]["attempts"] == 1

    # Een tweede ronde probeert het niet opnieuw (terminaal).
    _run_deliver(conn)
    assert receiver.received == []


# BETON-420: een guardrail-reviewvraag is wél een vraagmodule-vraag, maar geen
# telefoon-waardig signaal — hij wacht prima in de UI-inbox en in
# `get_open_questions`. Gewone vragen gaan wél naar Telegram.
# BETON-422: een guardrail-VOORSTEL is geen vraag meer maar een concept op het
# ticket; de bijbehorende events halen de Telegram-lat per constructie niet.


@pytest.mark.parametrize(
    "event_type", ["item.guardrail_proposed", "item.guardrail_rejected"]
)
def test_guardrail_concept_events_are_not_telegram_worthy(conn, event_type):
    from betonning import webhooks as webhooks_mod

    event = {"type": event_type, "payload": "{}"}
    assert webhooks_mod.telegram_worthy(conn, event) is False


def test_guardrail_proposal_creates_no_telegram_delivery(
    client, auth, conn, project, monkeypatch
):
    """Het voorstel-endpoint zelf: geen comment, geen delivery, geen telefoon."""
    from betonning.repo import users as users_repo

    monkeypatch.setenv("BETONNING_TELEGRAM_TOKEN", "faketoken")
    _telegram_user(conn, "persont")
    _, key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent", agent_type="coding"
    )
    conn.commit()
    r = client.post(
        "/api/v1/items/SOS-1/guardrail/propose",
        json={"guardrail_md": "Houd prompts kort."},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    assert _deliveries_for(conn, "persont") == []


def test_guardrail_review_creates_no_telegram_delivery(
    client, auth, conn, project, monkeypatch
):
    from betonning import triage as triage_mod

    monkeypatch.setenv("BETONNING_TELEGRAM_TOKEN", "faketoken")
    _telegram_user(conn, "persont")
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={
            "body_md": triage_mod.format_guardrail_review_question(
                "Houd prompts kort.", "2020-01-01", mention="persont"
            ),
            "kind": "question",
            "options": triage_mod.GUARDRAIL_REVIEW_OPTIONS,
        },
        headers=auth,
    )
    assert _deliveries_for(conn, "persont") == []


def test_public_url_defaults_to_local_installation(monkeypatch):
    monkeypatch.delenv("HEGEMONE_PUBLIC_URL", raising=False)
    monkeypatch.delenv("BETONNING_PUBLIC_URL", raising=False)
    assert webhooks._public_url() == "http://localhost:8000"


def test_public_url_uses_installation_config_with_legacy_fallback(monkeypatch):
    monkeypatch.setenv("BETONNING_PUBLIC_URL", " https://legacy.example.org/ ")
    monkeypatch.delenv("HEGEMONE_PUBLIC_URL", raising=False)
    assert webhooks._public_url() == "https://legacy.example.org"
    monkeypatch.setenv("HEGEMONE_PUBLIC_URL", " https://tickets.example.org/ ")
    assert webhooks._public_url() == "https://tickets.example.org"
    monkeypatch.setenv("HEGEMONE_PUBLIC_URL", " ")
    assert webhooks._public_url() == "https://legacy.example.org"


@pytest.fixture(autouse=True)
def legacy_dutch_instructions(monkeypatch):
    """Bestaande NL-instructiecontracten blijven expliciet onder test."""
    monkeypatch.setenv('HEGEMONE_LANGUAGE', 'nl')
