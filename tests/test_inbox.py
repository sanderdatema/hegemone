"""Inbox + My Issues (BETON-55): events die je raken en cross-project open items."""

from __future__ import annotations

import pytest

from betonning.repo import users as users_repo

from conftest import _create


@pytest.fixture
def claude_auth(conn):
    """Tweede user (agent) die comments/toewijzingen doet; geeft auth-headers."""
    _, key = users_repo.create(conn, handle="claude", display_name="Claude", kind="agent")
    return {"Authorization": f"Bearer {key}"}


# --- My Issues -----------------------------------------------------------


def test_my_issues_only_open_assigned(client, auth, claude_auth, project):
    # Twee projecten, één item toegewezen aan person in elk.
    client.post("/api/v1/projects", json={"key": "BRAND", "name": "Brand"}, headers=auth)
    _create(client, auth, "SOS", title="Aan mij", assignee="person")
    _create(client, auth, "BRAND", title="Ook aan mij", assignee="person")
    # Niet aan mij → niet in de lijst.
    _create(client, auth, "SOS", title="Aan claude", assignee="claude")
    # Aan mij maar afgerond → niet in de lijst.
    r = _create(client, auth, "SOS", title="Klaar", assignee="person")
    client.patch(f"/api/v1/items/{r.json()['ref']}", json={"state": "done"}, headers=auth)

    rows = client.get("/api/v1/me/issues", headers=auth).json()
    refs = {x["ref"] for x in rows}
    titles = {x["title"] for x in rows}
    assert titles == {"Aan mij", "Ook aan mij"}
    assert all(r.startswith(("SOS-", "BRAND-")) for r in refs)


def test_my_issues_requires_auth(client):
    assert client.get("/api/v1/me/issues").status_code == 401


# --- Inbox ---------------------------------------------------------------


def test_inbox_mention_in_comment(client, auth, claude_auth, project):
    r = _create(client, auth, project, title="Ticket")
    ref = r.json()["ref"]
    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "hoi @person kijk"}, headers=claude_auth)

    data = client.get("/api/v1/inbox", headers=auth).json()
    assert data["unread_count"] == 1
    entry = data["items"][0]
    assert entry["reason"] == "mention"
    assert entry["ref"] == ref
    assert entry["actor"] == "claude"
    assert entry["read"] is False


def test_inbox_assignment(client, auth, claude_auth, project):
    r = _create(client, claude_auth, project, title="Van claude")
    ref = r.json()["ref"]
    client.patch(f"/api/v1/items/{ref}", json={"assignee": "person", "handover_md": "Controleer dit ticket."}, headers=claude_auth)

    data = client.get("/api/v1/inbox", headers=auth).json()
    reasons = {e["reason"] for e in data["items"]}
    assert "assigned" in reasons


def test_inbox_comment_on_your_item(client, auth, claude_auth, project):
    r = _create(client, auth, project, title="Mijn item", assignee="person")
    ref = r.json()["ref"]
    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "geen mention"}, headers=claude_auth)

    data = client.get("/api/v1/inbox", headers=auth).json()
    assert any(e["reason"] == "comment" and e["ref"] == ref for e in data["items"])


def test_inbox_excludes_own_actions(client, auth, project):
    r = _create(client, auth, project, title="Mijn item", assignee="person")
    ref = r.json()["ref"]
    # Person reageert zelf → geen inbox-item voor person.
    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "@person self"}, headers=auth)
    data = client.get("/api/v1/inbox", headers=auth).json()
    assert data["unread_count"] == 0
    assert data["items"] == []


def test_inbox_seen_marks_read(client, auth, claude_auth, project):
    r = _create(client, auth, project, title="Ticket")
    ref = r.json()["ref"]
    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "@person een"}, headers=claude_auth)
    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "@person twee"}, headers=claude_auth)

    data = client.get("/api/v1/inbox", headers=auth).json()
    assert data["unread_count"] == 2
    top = data["items"][0]["event_id"]

    seen = client.post("/api/v1/inbox/seen", json={"event_id": top}, headers=auth)
    assert seen.status_code == 200
    assert seen.json()["last_seen_event_id"] == top

    after = client.get("/api/v1/inbox", headers=auth).json()
    assert after["unread_count"] == 0
    assert all(e["read"] for e in after["items"])


def test_inbox_seen_never_decreases(client, auth, claude_auth, project):
    r = _create(client, auth, project, title="Ticket")
    ref = r.json()["ref"]
    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "@person x"}, headers=claude_auth)
    top = client.get("/api/v1/inbox", headers=auth).json()["items"][0]["event_id"]
    client.post("/api/v1/inbox/seen", json={"event_id": top}, headers=auth)
    # Lagere marker mag niet terugzetten.
    r2 = client.post("/api/v1/inbox/seen", json={"event_id": 1}, headers=auth)
    assert r2.json()["last_seen_event_id"] == top


def test_inbox_requires_auth(client):
    assert client.get("/api/v1/inbox").status_code == 401


# --- Per-item read-state (BETON-286, bovenop BETON-294) -------------------


def test_item_read_marks_only_that_tickets_notifications(client, auth, claude_auth, project):
    """Kern van BETON-286: een ticket openen (`POST /items/{ref}/read`) markeert
    zijn eigen notificaties gelezen, maar laat andere tickets ongelezen — dat is
    precies wat de oude globale watermark niet kon (die zou alles ouder markeren)."""
    a = _create(client, auth, project, title="Ticket A").json()["ref"]
    b = _create(client, auth, project, title="Ticket B").json()["ref"]
    client.post(f"/api/v1/items/{a}/comments", json={"body_md": "@person a"}, headers=claude_auth)
    client.post(f"/api/v1/items/{b}/comments", json={"body_md": "@person b"}, headers=claude_auth)

    before = client.get("/api/v1/inbox", headers=auth).json()
    assert before["unread_count"] == 2

    client.post(f"/api/v1/items/{a}/read", headers=auth)

    after = client.get("/api/v1/inbox", headers=auth).json()
    assert after["unread_count"] == 1
    by_ref = {e["ref"]: e["read"] for e in after["items"]}
    assert by_ref[a] is True
    assert by_ref[b] is False


def test_item_read_does_not_affect_other_users(client, auth, claude_auth, project):
    """Read-state is per user; claude leest niks als person een item leest."""
    r = _create(client, auth, project, title="Ticket", assignee="claude")
    ref = r.json()["ref"]
    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "hoi"}, headers=auth)

    client.post(f"/api/v1/items/{ref}/read", headers=auth)  # person leest (geen notificaties)

    data = client.get("/api/v1/inbox", headers=claude_auth).json()
    assert data["unread_count"] == 1


def test_item_read_combines_with_global_watermark(client, auth, claude_auth, project):
    """Regressie: de globale watermark blijft gewoon werken náást de per-item-
    watermark (OR, niet vervangen)."""
    a = _create(client, auth, project, title="Ticket A").json()["ref"]
    b = _create(client, auth, project, title="Ticket B").json()["ref"]
    client.post(f"/api/v1/items/{a}/comments", json={"body_md": "@person a"}, headers=claude_auth)
    top_a = client.get("/api/v1/inbox", headers=auth).json()["items"][0]["event_id"]
    client.post("/api/v1/inbox/seen", json={"event_id": top_a}, headers=auth)

    client.post(f"/api/v1/items/{b}/comments", json={"body_md": "@person b"}, headers=claude_auth)

    data = client.get("/api/v1/inbox", headers=auth).json()
    by_ref = {e["ref"]: e["read"] for e in data["items"]}
    assert by_ref[a] is True  # via de globale watermark
    assert by_ref[b] is False


def test_inbox_list_does_not_query_per_item(client, auth, claude_auth, conn, project, db_path):
    """Bewaakt de bulkvorm van de per-item-watermarks in list_for_user — geen
    query per rij, spiegelt item_reads.unread_bulk/test_list_does_not_query_per_item."""
    from betonning import db as db_module
    from betonning.repo import inbox as inbox_repo
    from betonning.repo import users as users_repo

    for n in range(1, 4):
        r = _create(client, auth, project, title=f"t{n}")
        client.post(
            f"/api/v1/items/{r.json()['ref']}/comments",
            json={"body_md": "@person hoi"},
            headers=claude_auth,
        )

    traced = db_module.connect(db_path)
    traced.set_trace_callback(lambda s: statements.append(s))
    statements: list[str] = []
    user = users_repo.get_by_handle(traced, "person")
    inbox_repo.list_for_user(traced, user)
    traced.close()
    assert sum(1 for s in statements if "FROM item_reads" in s) == 1


# --- Opdrachtvelden op het pull-pad (BETON-296) ---------------------------


def test_inbox_instructions_omitted_by_default(client, auth, claude_auth, project):
    """Zonder `?instructions=true` blijft de inbox-respons ongewijzigd — geen
    `instruction`-sleutel, geen extra kosten voor de meeste consumenten (de UI)."""
    r = _create(client, auth, project, title="Ticket")
    ref = r.json()["ref"]
    client.post(
        f"/api/v1/items/{ref}/comments",
        json={"body_md": "hoi @person kijk"},
        headers=claude_auth,
    )
    data = client.get("/api/v1/inbox", headers=auth).json()
    assert "instruction" not in data["items"][0]


def test_inbox_instructions_included_when_requested(client, auth, claude_auth, project):
    """`?instructions=true` levert per entry hetzelfde opdrachtblok als een
    webhook-delivery (BETON-296: het pull-pad was niet zelf-dragend)."""
    r = _create(client, auth, project, title="Ticket")
    ref = r.json()["ref"]
    client.post(
        f"/api/v1/items/{ref}/comments",
        json={"body_md": "hoi @person kijk"},
        headers=claude_auth,
    )
    data = client.get(
        "/api/v1/inbox", params={"instructions": "true"}, headers=auth
    ).json()
    entry = data["items"][0]
    assert entry["instruction"]["expected_action"] == "respond"
    assert "do_not" in entry["instruction"]
    assert "reply" in entry["instruction"]
    # De bestaande gelezen/ongelezen-vlag blijft ongemoeid (geen sleutelbotsing
    # met het genest `instruction.read`-veld).
    assert entry["read"] is False


def test_inbox_instructions_bounded_by_limit_not_scan(client, auth, claude_auth, project, db_path):
    """BETON-296 performance-eis: `instructions=true` mag geen N+1 over de volle
    `_SCAN_LIMIT`-scan opleveren — alleen de teruggegeven (dus `limit`-begrensde)
    entries krijgen het opdrachtblok. We zetten veel meer relevante events neer
    dan `limit` en meten dat het aantal item-lookups schaalt met `limit`, niet
    met het totaal aantal relevante events."""
    from betonning import db as db_mod
    from betonning.repo import inbox as inbox_repo
    from betonning.repo import users as users_repo_mod

    N = 20
    for n in range(N):
        r = _create(client, auth, project, title=f"t{n}")
        client.post(
            f"/api/v1/items/{r.json()['ref']}/comments",
            json={"body_md": "@person hoi"},
            headers=claude_auth,
        )

    LIMIT = 3
    traced = db_mod.connect(db_path)
    statements: list[str] = []
    traced.set_trace_callback(lambda s: statements.append(s))
    user = users_repo_mod.get_by_handle(traced, "person")
    result = inbox_repo.list_for_user(
        traced, user, limit=LIMIT, include_instructions=True
    )
    traced.close()

    assert len(result["items"]) == LIMIT
    assert all(e["instruction"] is not None for e in result["items"])
    item_lookups = sum(
        1 for s in statements if "SELECT * FROM items WHERE id = ?" in s
    )
    # Bovengrens ruim boven wat `LIMIT` entries redelijkerwijs kosten (elke
    # entry roept `build_agent_instructions` aan, die zelf een paar keer het
    # item opvraagt), maar ver onder wat een N+1 over alle N=20 relevante
    # events zou kosten.
    assert item_lookups < N
    assert item_lookups <= LIMIT * 6


def test_coding_agent_sees_virtual_coding_queue(client, auth, conn, project):
    """BETON-207: een échte coding-agent ziet naast z'n eigen tickets ook de
    gedeelde `coding-agent`-queue in Mijn tickets — anders is de virtuele
    toewijzing onvindbaar. Een mens/andere-type-agent ziet die queue niet."""
    _, ckey = users_repo.create(
        conn, handle="codex", display_name="Codex", kind="agent", agent_type="coding"
    )
    _, hkey = users_repo.create(
        conn, handle="smid", display_name="Smid", kind="agent", agent_type="hermes"
    )
    conn.commit()
    coding_auth = {"Authorization": f"Bearer {ckey}"}
    hermes_auth = {"Authorization": f"Bearer {hkey}"}

    _create(client, auth, "SOS", title="Voor de queue", assignee="coding-agent")
    _create(client, auth, "SOS", title="Direct voor codex", assignee="codex")

    coding_titles = {x["title"] for x in client.get("/api/v1/me/issues", headers=coding_auth).json()}
    assert coding_titles == {"Voor de queue", "Direct voor codex"}
    # De mens en een Hermes-agent zien de coding-queue niet.
    assert "Voor de queue" not in {x["title"] for x in client.get("/api/v1/me/issues", headers=auth).json()}
    assert "Voor de queue" not in {x["title"] for x in client.get("/api/v1/me/issues", headers=hermes_auth).json()}
