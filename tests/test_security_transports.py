"""Regressies voor intrekking en begrensde MCP-sessies (BETON-497/498)."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from betonning import db as dbm
from betonning.api import stream
from betonning.repo import users
from betonning.server import create_app


@pytest.mark.parametrize("operation", ["rotate", "disable"])
def test_sse_stops_after_revocation(
    client, auth, conn, project, monkeypatch, operation
):
    user, key = users.create(
        conn, handle="stream-agent", display_name="Stream", kind="agent"
    )
    fingerprint = users.get(conn, user["id"])["api_key_hash"]
    monkeypatch.setattr(stream, "POLL_INTERVAL", 0)

    class Request:
        async def is_disconnected(self):
            return False

    async def run():
        gen = stream._event_generator(
            Request(),
            client.app.state.db_path,
            0,
            from_latest=True,
            viewer_id=user["id"],
            key_fingerprint=fingerprint,
        )
        assert "heartbeat" in await anext(gen)
        if operation == "rotate":
            client.post("/api/v1/users/stream-agent/api-key/rotate", headers=auth)
        else:
            client.patch(
                "/api/v1/users/stream-agent", headers=auth, json={"active": False}
            )
        client.post("/api/v1/projects/SOS/items", headers=auth, json={"title": "Later"})
        with pytest.raises(StopAsyncIteration):
            await anext(gen)
        await gen.aclose()

    asyncio.run(run())


def test_mcp_owner_cleanup_and_limits(tmp_path):
    path = str(tmp_path / "mcp.db")
    dbm.init_db(path).close()
    conn = dbm.connect(path)
    _, a = users.create(conn, handle="a", display_name="A", kind="agent")
    _, b = users.create(conn, handle="b", display_name="B", kind="agent")
    conn.close()
    app = create_app(
        path,
        enable_mcp=True,
        enable_dispatcher=False,
        enable_triage=False,
        enable_wiki_compile=False,
    )
    manager = app.state.mcp.session_manager
    manager.max_sessions = 1
    headers = {
        "Authorization": f"Bearer {a}",
        "Accept": "application/json, text/event-stream",
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    with TestClient(app) as client:
        result = client.post("/mcp/", headers=headers, json=body)
        assert result.status_code == 200
        sid = result.headers["mcp-session-id"]
        assert (
            client.delete(
                "/mcp/",
                headers={
                    **headers,
                    "Authorization": f"Bearer {b}",
                    "mcp-session-id": sid,
                },
            ).status_code
            == 404
        )
        assert client.post("/mcp/", headers=headers, json=body).status_code == 503
        assert (
            client.delete(
                "/mcp/", headers={**headers, "mcp-session-id": sid}
            ).status_code
            == 200
        )
        assert len(manager._server_instances) == 0
        manager.session_idle_timeout = 0.05
        assert client.post("/mcp/", headers=headers, json=body).status_code == 200
        time.sleep(0.15)
        assert len(manager._server_instances) == 0


def test_sse_stops_after_browser_logout(client, auth, conn, monkeypatch):
    from betonning.security import hash_api_key

    monkeypatch.setattr(stream, "POLL_INTERVAL", 0)
    session = client.post("/api/v1/session", headers=auth).json()
    raw = client.cookies.get("bt_session")
    user = users.get_by_handle(conn, "person")

    class Request:
        async def is_disconnected(self):
            return False

    async def run():
        gen = stream._event_generator(
            Request(),
            client.app.state.db_path,
            0,
            from_latest=True,
            viewer_id=user["id"],
            key_fingerprint=user["api_key_hash"],
            browser_session_hash=hash_api_key(raw),
        )
        await anext(gen)
        assert (
            client.post(
                "/api/v1/logout", headers={"X-CSRF-Token": session["csrf_token"]}
            ).status_code
            == 200
        )
        with pytest.raises(StopAsyncIteration):
            await anext(gen)

    asyncio.run(run())


def test_sse_large_replay_requests_client_resync(client, auth, conn, monkeypatch):
    monkeypatch.setattr(stream, "MAX_REPLAY_EVENTS", 1)
    client.post("/api/v1/projects", headers=auth, json={"key": "SOS", "name": "SOS"})
    for i in range(2):
        client.post("/api/v1/projects/SOS/items", headers=auth, json={"title": str(i)})

    class Request:
        async def is_disconnected(self):
            return False

    async def run():
        gen = stream._event_generator(Request(), client.app.state.db_path, 0)
        assert "stream.resync" in await anext(gen)
        await gen.aclose()

    asyncio.run(run())
