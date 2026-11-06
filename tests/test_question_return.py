"""Teruggave na het antwoord op een vraag (BETON-285 + BETON-431)."""

from __future__ import annotations

import pytest
from conftest import _create
from test_question_assignment import _agent, _ask, _assignee

from betonning import triage as triage_mod
from betonning.repo import users as users_repo


@pytest.fixture
def project(project, client, auth):
    _create(client, auth, project)  # SOS-1
    return project


def _triage_question(client, auth, conn, *, body, options=None, assignee="lobke"):
    """Laat triage een vraag aan person plaatsen op SOS-1, dat bij `assignee` staat."""
    if users_repo.get_by_handle(conn, "triage") is None:
        users_repo.create(conn, handle="triage", display_name="Triage", kind="agent")
        conn.commit()
    triage_id = users_repo.get_by_handle(conn, "triage")["id"]
    client.patch("/api/v1/items/SOS-1", json={"assignee": assignee}, headers=auth)
    item = conn.execute("SELECT * FROM items WHERE seq = 1").fetchone()
    triage_mod.post_triage_comment(
        conn,
        item,
        body,
        triage_id,
        addressed_to=["person"],
        kind="question",
        options=options,
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM comments WHERE kind = 'question' ORDER BY id DESC"
    ).fetchone()["id"]


def _answer(client, auth, qid, **body):
    r = client.post(f"/api/v1/comments/{qid}/answer", json=body, headers=auth)
    assert r.status_code == 200, r.text


def test_triage_question_returns_to_prior_assignee_not_triage(
    client, auth, conn, project
):
    _agent(conn, "lobke")
    qid = _triage_question(client, auth, conn, body="Welke kant op?")
    assert _assignee(client, auth) == "person"
    _answer(client, auth, qid, text="links")
    assert _assignee(client, auth) == "lobke"


def test_agent_question_still_returns_to_asker(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    _agent(conn, "joop")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    q = _ask(client, lobke, "Rood of blauw, @person?")
    assert _assignee(client, auth) == "person"
    _answer(client, auth, q["id"], text="a")
    assert _assignee(client, auth) == "lobke"


def test_historical_triage_question_without_prior_keeps_old_behaviour(
    client, auth, conn, project
):
    """Zonder prior_assignee_id: de stale-uitzondering geldt, ticket blijft bij person."""
    _agent(conn, "lobke")
    body = triage_mod.format_stale_question(3, mention="person")
    qid = _triage_question(
        client, auth, conn, body=body, options=triage_mod.STALE_OPTIONS
    )
    conn.execute("UPDATE comments SET prior_assignee_id = NULL WHERE id = ?", (qid,))
    conn.commit()
    _answer(client, auth, qid, option_index=0)
    assert _assignee(client, auth) == "person"


def test_stale_release_choice_is_not_overwritten(client, auth, conn, project):
    body = triage_mod.format_stale_question(3, mention="person")
    qid = _triage_question(
        client,
        auth,
        conn,
        body=body,
        options=triage_mod.STALE_OPTIONS,
        assignee=users_repo.VIRTUAL_CODING,
    )
    assert _assignee(client, auth) == "person"
    # Optie 2 = vrijgeven aan de coding-queue; de teruggave laat dat staan.
    _answer(client, auth, qid, option_index=2)
    assert _assignee(client, auth) == users_repo.VIRTUAL_CODING


def test_stale_keep_going_returns_to_prior(client, auth, conn, project):
    body = triage_mod.format_stale_question(3, mention="person")
    qid = _triage_question(
        client,
        auth,
        conn,
        body=body,
        options=triage_mod.STALE_OPTIONS,
        assignee=users_repo.VIRTUAL_CODING,
    )
    _answer(client, auth, qid, option_index=0)
    assert _assignee(client, auth) == users_repo.VIRTUAL_CODING
