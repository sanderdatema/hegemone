"""409-poort: een agent zet een ticket met een open vraag aan een mens niet weg (BETON-431)."""

from __future__ import annotations

import pytest
from conftest import _create
from test_question_assignment import _agent, _ask, _assignee

from betonning.repo import users as users_repo


@pytest.fixture
def project(project, client, auth):
    _create(client, auth, project)  # SOS-1
    return project


def test_agent_cannot_reassign_while_question_open(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    _ask(client, lobke, "Rood of blauw, @person?")
    r = client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=lobke)
    assert r.status_code == 409
    assert "open vraag" in r.json()["detail"]["message"]
    assert _assignee(client, auth) == "person"


def test_agent_cannot_clear_assignee_while_question_open(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    _ask(client, lobke, "Rood of blauw, @person?")
    r = client.patch("/api/v1/items/SOS-1", json={"assignee": ""}, headers=lobke)
    assert r.status_code == 409


def test_human_may_reassign_while_question_open(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    _ask(client, lobke, "Rood of blauw, @person?")
    r = client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    assert r.status_code == 200
    assert _assignee(client, auth) == "lobke"


def test_agent_may_reassign_after_question_answered(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    _agent(conn, "joop")
    q = _ask(client, lobke, "Rood of blauw, @person?")
    client.post(f"/api/v1/comments/{q['id']}/answer", json={"text": "a"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    r = client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=lobke)
    assert r.status_code == 200


def test_agent_may_edit_other_fields_while_question_open(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    _ask(client, lobke, "Rood of blauw, @person?")
    r = client.patch("/api/v1/items/SOS-1", json={"title": "nieuw"}, headers=lobke)
    assert r.status_code == 200


def test_no_gate_when_assignee_is_agent(client, auth, conn, project):
    """Stale-vraag aan een echte agent-assignee: ticket staat niet bij een mens."""
    lobke = _agent(conn, "lobke")
    _agent(conn, "joop")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    # Vraag zonder mention aan een agent-assignee is niet toegestaan via REST, dus
    # zet een open vraag direct in de db (zoals triage dat voor een agent doet).
    triage = users_repo.create(conn, handle="triage", display_name="T", kind="agent")[0]
    conn.execute(
        "INSERT INTO comments (item_id, author_id, body_md, kind) "
        "SELECT id, ?, 'Stale?', 'question' FROM items WHERE seq = 1",
        (triage["id"],),
    )
    conn.commit()
    r = client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=lobke)
    assert r.status_code == 200
