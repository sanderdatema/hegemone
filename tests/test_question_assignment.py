"""Open vraag aan een mens => ticket staat bij die mens (BETON-431)."""

from __future__ import annotations

import pytest
from conftest import _create

from betonning import triage as triage_mod
from betonning.repo import users as users_repo


@pytest.fixture
def project(project, client, auth):
    _create(client, auth, project)  # SOS-1, gemaakt door person
    return project


def _agent(conn, handle, *, webhook=True):
    _, key = users_repo.create(
        conn,
        handle=handle,
        display_name=handle,
        kind="agent",
        webhook_url="http://example.invalid/hook" if webhook else None,
        webhook_secret="s" if webhook else None,
    )
    conn.commit()
    return {"Authorization": f"Bearer {key}"}


def _human(conn, handle):
    _, key = users_repo.create(conn, handle=handle, display_name=handle, kind="human")
    conn.commit()
    return {"Authorization": f"Bearer {key}"}


def _ask(client, headers, body="Rood of blauw?", ref="SOS-1"):
    r = client.post(
        f"/api/v1/items/{ref}/comments",
        json={"body_md": body, "kind": "question"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _assignee(client, auth, ref="SOS-1"):
    return client.get(f"/api/v1/items/{ref}", headers=auth).json()["assignee"]


def _prior(conn, question_id):
    return conn.execute(
        "SELECT prior_assignee_id FROM comments WHERE id = ?", (question_id,)
    ).fetchone()["prior_assignee_id"]


def test_migration_adds_prior_assignee_column(conn):
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(comments)")]
    assert "prior_assignee_id" in cols


def test_agent_question_with_mention_assigns_to_mentioned_human(
    client, auth, conn, project
):
    lobke = _agent(conn, "lobke")
    _human(conn, "joop")
    _ask(client, lobke, "Rood of blauw, @joop?")
    assert _assignee(client, auth) == "joop"


def test_mention_with_capital_still_assigns_to_human(client, auth, conn, project):
    """Agents schrijven soms `@Person`; handles zijn lowercase (BRAND-421)."""
    lobke = _agent(conn, "lobke")
    _human(conn, "joop")
    _ask(client, lobke, "@Joop rood of blauw?")
    assert _assignee(client, auth) == "joop"


def test_prior_assignee_is_remembered(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    q = _ask(client, lobke, "Rood of blauw, @person?")
    assert _assignee(client, auth) == "person"
    lobke_id = users_repo.get_by_handle(conn, "lobke")["id"]
    assert _prior(conn, q["id"]) == lobke_id


def test_no_mention_falls_back_to_human_creator(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    joop = _human(conn, "joop")
    created = _create(client, joop, project, title="van joop").json()
    _ask(client, lobke, "Rood of blauw?", ref=created["ref"])
    assert _assignee(client, auth, created["ref"]) == "joop"


def test_no_mention_agent_creator_falls_back_to_first_human(
    client, auth, conn, project
):
    lobke = _agent(conn, "lobke")
    _human(conn, "joop")
    created = _create(client, lobke, project, title="van lobke").json()
    _ask(client, lobke, "Rood of blauw?", ref=created["ref"])
    assert _assignee(client, auth, created["ref"]) == "person"


def test_no_mention_keeps_existing_human_assignee(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    _human(conn, "joop")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    q = _ask(client, lobke, "Rood of blauw?")
    assert _assignee(client, auth) == "joop"
    assert _prior(conn, q["id"]) is None


def test_question_from_human_does_not_assign(client, auth, conn, project):
    _human(conn, "joop")
    _ask(client, auth, "Rood of blauw, @joop?")
    assert _assignee(client, auth) is None


def test_assignment_event_has_no_fanout_to_previous_assignee(
    client, auth, conn, project
):
    lobke = _agent(conn, "lobke")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    conn.execute("DELETE FROM webhook_deliveries")
    conn.commit()
    _ask(client, lobke, "Rood of blauw, @person?")
    assert _assignee(client, auth) == "person"
    # lobke is de vragensteller en vorige assignee: geen delivery, ook geen
    # stand_down voor het weggehaalde ticket.
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM webhook_deliveries wd JOIN users u "
        "ON u.id = wd.user_id WHERE u.handle = 'lobke'"
    ).fetchone()["n"]
    assert n == 0
    ev = conn.execute(
        "SELECT payload FROM events WHERE type = 'item.updated' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert '"to": "person"' in ev["payload"]


def test_triage_question_assigns_and_remembers_prior(client, auth, conn, project):
    users_repo.create(conn, handle="triage", display_name="Triage", kind="agent")
    conn.commit()
    triage_id = users_repo.get_by_handle(conn, "triage")["id"]
    coding = users_repo.get_by_handle(conn, users_repo.VIRTUAL_CODING)
    client.patch(
        "/api/v1/items/SOS-1", json={"assignee": users_repo.VIRTUAL_CODING}, headers=auth
    )
    item = conn.execute("SELECT * FROM items WHERE seq = 1").fetchone()
    triage_mod.post_triage_comment(
        conn,
        item,
        "Welke kant op?",
        triage_id,
        addressed_to=["person"],
        kind="question",
        options=["a", "b"],
    )
    conn.commit()
    assert _assignee(client, auth) == "person"
    qid = conn.execute(
        "SELECT id FROM comments WHERE kind = 'question' ORDER BY id DESC"
    ).fetchone()["id"]
    assert coding is not None
    assert _prior(conn, qid) == coding["id"]


def test_question_to_agent_addressee_does_not_assign(client, auth, conn, project):
    users_repo.create(conn, handle="triage", display_name="Triage", kind="agent")
    _agent(conn, "lobke")
    conn.commit()
    triage_id = users_repo.get_by_handle(conn, "triage")["id"]
    item = conn.execute("SELECT * FROM items WHERE seq = 1").fetchone()
    triage_mod.post_triage_comment(
        conn, item, "Stale?", triage_id, addressed_to=["lobke"], kind="question"
    )
    conn.commit()
    assert _assignee(client, auth) is None
