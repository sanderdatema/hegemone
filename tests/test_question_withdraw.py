"""Vragen intrekken + afsluiten met open vraag (BETON-454)."""

from __future__ import annotations

import json

import pytest
from conftest import _create
from test_question_assignment import _agent, _ask, _assignee

from betonning import admin
from betonning.repo import comments as comments_repo


@pytest.fixture
def project(project, client, auth):
    _create(client, auth, project)  # SOS-1
    return project


def _withdraw(client, headers, qid, reason="antwoord kwam in de chat"):
    return client.post(
        f"/api/v1/comments/{qid}/withdraw", json={"reason": reason}, headers=headers
    )


def _open_for_person(client, auth):
    return client.get("/api/v1/questions?open=true", headers=auth).json()


def test_migration_adds_withdrawn_columns(conn):
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(comments)")]
    assert {"withdrawn_at", "withdrawn_reason"} <= set(cols)


def test_asker_withdraws_question(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    q = _ask(client, lobke, "Rood of blauw, @person?")
    r = _withdraw(client, lobke, q["id"], "chat")
    assert r.status_code == 200
    body = r.json()
    assert body["withdrawn_reason"] == "chat"
    assert body["withdrawn_at"] is not None
    assert body["answered_at"] is None


def test_withdrawn_question_is_no_longer_open(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    q = _ask(client, lobke, "Rood of blauw, @person?")
    assert [x["id"] for x in _open_for_person(client, auth)] == [q["id"]]
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["has_open_question"]
    _withdraw(client, lobke, q["id"])
    assert _open_for_person(client, auth) == []
    assert not client.get("/api/v1/items/SOS-1", headers=auth).json()["has_open_question"]
    assert comments_repo.open_questions_for_item(conn, 1) == []
    # ... en blokkeert de reassign-poort niet meer
    r = client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=lobke)
    assert r.status_code == 200


def test_other_agent_may_withdraw_an_outdated_question(client, auth, conn, project):
    """BETON-481: een agent die merkt dat een vraag achterhaald is, mag hem
    sluiten, ook als een ander hem stelde. Anders bleef hij open staan."""
    lobke = _agent(conn, "lobke")
    joop = _agent(conn, "joop")
    q = _ask(client, lobke, "Rood of blauw, @person?")
    r = _withdraw(client, joop, q["id"], "al beantwoord in SOS-2")
    assert r.status_code == 200
    assert r.json()["withdrawn_reason"] == "al beantwoord in SOS-2"
    assert _open_for_person(client, auth) == []


def test_human_can_withdraw(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    q = _ask(client, lobke, "Rood of blauw, @person?")
    assert _withdraw(client, auth, q["id"]).status_code == 200


def test_withdraw_twice_and_answered_are_409(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    q1 = _ask(client, lobke, "Een, @person?")
    q2 = _ask(client, lobke, "Twee, @person?")
    assert _withdraw(client, lobke, q1["id"]).status_code == 200
    assert _withdraw(client, lobke, q1["id"]).status_code == 409
    client.post(f"/api/v1/comments/{q2['id']}/answer", json={"text": "a"}, headers=auth)
    assert _withdraw(client, lobke, q2["id"]).status_code == 409


def test_answering_withdrawn_question_is_409(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    q = _ask(client, lobke, "Een, @person?")
    _withdraw(client, lobke, q["id"])
    r = client.post(f"/api/v1/comments/{q['id']}/answer", json={"text": "a"}, headers=auth)
    assert r.status_code == 409


def test_reason_required_and_non_question_422(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    q = _ask(client, lobke, "Een, @person?")
    assert client.post(
        f"/api/v1/comments/{q['id']}/withdraw", json={}, headers=lobke
    ).status_code == 422
    c = client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=lobke
    ).json()
    assert _withdraw(client, lobke, c["id"]).status_code == 422


def test_last_withdrawal_returns_item_to_prior_assignee(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    q = _ask(client, lobke, "Rood of blauw, @person?")
    assert _assignee(client, auth) == "person"
    _withdraw(client, lobke, q["id"])
    assert _assignee(client, auth) == "lobke"


def test_withdraw_keeps_assignee_while_another_question_open(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    q1 = _ask(client, lobke, "Een, @person?")
    _ask(client, lobke, "Twee, @person?")
    _withdraw(client, lobke, q1["id"])
    assert _assignee(client, auth) == "person"


def test_withdraw_event_has_no_delivery(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    q = _ask(client, lobke, "Een, @person?")
    before = conn.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0]
    _withdraw(client, lobke, q["id"])
    ev = conn.execute(
        "SELECT payload FROM events WHERE type = 'question.withdrawn'"
    ).fetchall()
    assert [json.loads(e["payload"]) for e in ev] == [{"comment_id": q["id"]}]
    assert conn.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0] == before


# --- afsluiten met een open vraag ------------------------------------------


def test_agent_close_with_open_question_is_409(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    q = _ask(client, lobke, "Rood of blauw, @person?")
    for state in ("done", "cancelled"):
        r = client.patch("/api/v1/items/SOS-1", json={"state": state}, headers=lobke)
        assert r.status_code == 409, state
        assert r.json()["error_code"] == "open_question_close_forbidden"
        assert r.json()["error_params"]["id"] == str(q["id"])
        assert "Rood of blauw" in r.json()["error_params"]["question"]
        msg = r.json()["detail"]["message"]
        assert str(q["id"]) in msg and "Rood of blauw" in msg and "withdraw_question" in msg
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["state"] != "done"


def test_agent_close_after_withdraw_is_200(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    q = _ask(client, lobke, "Rood of blauw, @person?")
    _withdraw(client, lobke, q["id"])
    r = client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=lobke)
    assert r.status_code == 200


def test_agent_non_closing_state_change_allowed_with_open_question(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    _ask(client, lobke, "Rood of blauw, @person?")
    r = client.patch("/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=lobke)
    assert r.status_code != 409


def test_human_close_with_open_question_is_200(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    _ask(client, lobke, "Rood of blauw, @person?")
    r = client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=auth)
    assert r.status_code == 200


# --- backfill --------------------------------------------------------------


def test_withdraw_stale_questions_dry_run_and_real(client, auth, conn, db_path, project):
    lobke = _agent(conn, "lobke")
    _create(client, auth, project, title="tweede")  # SOS-2
    _ask(client, lobke, "Op afgesloten, @person?", ref="SOS-1")
    open_q = _ask(client, lobke, "Nog open, @person?", ref="SOS-2")
    client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=auth)

    found = admin.withdraw_stale_questions(db_path, dry_run=True)
    assert [f["ref"] for f in found] == ["SOS-1"]
    assert len(_open_for_person(client, auth)) == 2

    found = admin.withdraw_stale_questions(db_path)
    assert len(found) == 1
    assert [x["id"] for x in _open_for_person(client, auth)] == [open_q["id"]]
    row = conn.execute(
        "SELECT withdrawn_reason FROM comments WHERE id = ?", (found[0]["id"],)
    ).fetchone()
    assert row["withdrawn_reason"] == "ticket was al afgesloten"
    assert admin.withdraw_stale_questions(db_path) == []


def test_blank_reason_is_422(client, auth, conn, project):
    lobke = _agent(conn, "lobke")
    q = _ask(client, lobke, "Rood of blauw, @person?")
    assert _withdraw(client, lobke, q["id"], "   ").status_code == 422
    assert len(_open_for_person(client, auth)) == 1


def test_withdraw_rechecks_state_inside_transaction(client, auth, conn, project, monkeypatch):
    # Simuleert een antwoord dat tussen de eerste check en de schrijf-lock landt.
    lobke = _agent(conn, "lobke")
    q = _ask(client, lobke, "Rood of blauw, @person?")
    real_get = comments_repo.get
    calls = {"n": 0}

    def racing_get(c, cid):
        calls["n"] += 1
        row = real_get(c, cid)
        if calls["n"] == 1:
            return row
        c.execute("UPDATE comments SET answered_at = '2026-01-01T00:00:00.000Z' WHERE id = ?", (cid,))
        return real_get(c, cid)

    monkeypatch.setattr(comments_repo, "get", racing_get)
    assert _withdraw(client, lobke, q["id"]).status_code == 409
    monkeypatch.undo()
    assert real_get(conn, q["id"])["withdrawn_at"] is None
