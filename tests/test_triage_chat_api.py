"""Chat-met-triage-endpoints (BETON-120): auth/scope/voorstel-flow via TestClient."""

from __future__ import annotations

from conftest import inject_llm

import json

import pytest

from betonning.repo import users as users_repo


class ScriptedLLM:
    """Geeft achtereenvolgens de vooraf-bepaalde replies (dicts → JSON) terug."""

    def __init__(self, replies: list) -> None:
        self._replies = list(replies)

    def complete(self, messages):
        reply = self._replies.pop(0)
        return reply if isinstance(reply, str) else json.dumps(reply)


class BoomLLM:
    """Simuleert een upstream-fout (bv. gateway-429) tijdens complete()."""

    def complete(self, messages):
        raise RuntimeError("upstream 429")


@pytest.fixture
def agent_auth(conn) -> dict:
    _, key = users_repo.create(
        conn, handle="smid", display_name="Smid", kind="agent", agent_type="hermes"
    )
    return {"Authorization": f"Bearer {key}"}


def _mk_item(client, auth, title: str) -> str:
    r = client.post(
        "/api/v1/projects/SOS/items", json={"title": title}, headers=auth
    )
    return r.json()["ref"]


# --- auth-grenzen -----------------------------------------------------------


def test_requires_auth(client, project):
    assert client.get("/api/v1/triage-chat").status_code == 401


def test_agent_forbidden(client, agent_auth, project):
    inject_llm(client, ScriptedLLM([{"kind": "reply", "text": "ok"}]))
    assert client.get("/api/v1/triage-chat", headers=agent_auth).status_code == 403
    r = client.post("/api/v1/triage-chat", json={"message": "hoi"}, headers=agent_auth)
    assert r.status_code == 403


def test_post_503_without_llm(client, auth, project):
    inject_llm(client, None)
    r = client.post("/api/v1/triage-chat", json={"message": "hoi"}, headers=auth)
    assert r.status_code == 503
    r2 = client.post(
        "/api/v1/projects/SOS/triage-chat", json={"message": "hoi"}, headers=auth
    )
    assert r2.status_code == 503


def test_post_502_on_llm_error(client, auth, project):
    inject_llm(client, BoomLLM())
    r = client.post("/api/v1/triage-chat", json={"message": "hoi"}, headers=auth)
    assert r.status_code == 502
    r2 = client.post(
        "/api/v1/projects/SOS/triage-chat", json={"message": "hoi"}, headers=auth
    )
    assert r2.status_code == 502


# --- reply-flow + scope -----------------------------------------------------


def test_global_reply_and_history(client, auth, project):
    inject_llm(client, ScriptedLLM([{"kind": "reply", "text": "Hallo!"}]))
    r = client.post("/api/v1/triage-chat", json={"message": "hoi"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["kind"] == "reply"

    got = client.get("/api/v1/triage-chat", headers=auth).json()
    bodies = [m["body_md"] for m in got["messages"]]
    assert "hoi" in bodies and "Hallo!" in bodies
    assert got["pending"] is None


def test_scopes_do_not_share_history(client, auth, project):
    inject_llm(client, ScriptedLLM(
        [{"kind": "reply", "text": "globaal-antwoord"},
         {"kind": "reply", "text": "project-antwoord"}]
    ))
    client.post("/api/v1/triage-chat", json={"message": "globale vraag"}, headers=auth)
    client.post(
        "/api/v1/projects/SOS/triage-chat", json={"message": "project vraag"}, headers=auth
    )

    global_bodies = [
        m["body_md"] for m in client.get("/api/v1/triage-chat", headers=auth).json()["messages"]
    ]
    project_bodies = [
        m["body_md"]
        for m in client.get("/api/v1/projects/SOS/triage-chat", headers=auth).json()["messages"]
    ]
    assert "globale vraag" in global_bodies and "project vraag" not in global_bodies
    assert "project vraag" in project_bodies and "globale vraag" not in project_bodies


def test_archive_starts_fresh_session(client, auth, project):
    inject_llm(client, ScriptedLLM([{"kind": "reply", "text": "ok"}]))
    client.post("/api/v1/triage-chat", json={"message": "oud bericht"}, headers=auth)
    fresh = client.post("/api/v1/triage-chat/archive", headers=auth).json()
    assert fresh["messages"] == []
    assert fresh["pending"] is None
    # de nieuwe GET toont ook de lege sessie
    assert client.get("/api/v1/triage-chat", headers=auth).json()["messages"] == []


# --- voorstel → confirm/cancel ----------------------------------------------


def _propose_archive(client, auth, refs):
    inject_llm(client, ScriptedLLM([{
        "kind": "proposal", "summary": f"archiveer {len(refs)}",
        "commands": [{"verb": "archive", "selector": {"refs": refs}}],
    }]))
    r = client.post(
        "/api/v1/projects/SOS/triage-chat", json={"message": "archiveer"}, headers=auth
    )
    return r.json()


def test_proposal_pending_then_confirm(client, auth, project):
    ref = _mk_item(client, auth, "Item")
    result = _propose_archive(client, auth, [ref])
    assert result["kind"] == "proposal"
    msg_id = result["message"]["id"]

    done = client.post(f"/api/v1/triage-chat/{msg_id}/confirm", headers=auth)
    assert done.status_code == 200
    assert done.json()["kind"] == "done"
    # item is gearchiveerd (uit het board)
    board = client.get("/api/v1/projects/SOS/items", headers=auth).json()
    assert all(i["ref"] != ref for i in board)


def test_confirm_twice_409(client, auth, project):
    ref = _mk_item(client, auth, "Item")
    msg_id = _propose_archive(client, auth, [ref])["message"]["id"]
    client.post(f"/api/v1/triage-chat/{msg_id}/confirm", headers=auth)
    again = client.post(f"/api/v1/triage-chat/{msg_id}/confirm", headers=auth)
    assert again.status_code == 409


def test_cancel_then_confirm_409(client, auth, project):
    ref = _mk_item(client, auth, "Item")
    msg_id = _propose_archive(client, auth, [ref])["message"]["id"]
    assert client.post(f"/api/v1/triage-chat/{msg_id}/cancel", headers=auth).status_code == 200
    again = client.post(f"/api/v1/triage-chat/{msg_id}/confirm", headers=auth)
    assert again.status_code == 409


def test_bulk_over_threshold_requires_typed_count(client, auth, project, monkeypatch):
    from betonning import triage_chat_engine
    monkeypatch.setattr(triage_chat_engine, "BULK_CONFIRM_THRESHOLD", 2)

    refs = [_mk_item(client, auth, f"Item {i}") for i in range(3)]
    result = _propose_archive(client, auth, refs)
    msg_id = result["message"]["id"]
    assert result["message"]["proposal"]["total_count"] == 3

    blocked = client.post(f"/api/v1/triage-chat/{msg_id}/confirm", headers=auth)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["error"] == "confirmation_required"
    assert blocked.json()["detail"]["total"] == 3

    ok = client.post(
        f"/api/v1/triage-chat/{msg_id}/confirm", json={"typed_count": 3}, headers=auth
    )
    assert ok.status_code == 200
    assert len(ok.json()["executed"]) == 3
