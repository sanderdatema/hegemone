"""Vroege weigering, rate-/streamlimieten en quota zonder productiebelasting."""

import asyncio
import pytest
from types import SimpleNamespace
from betonning.resource_limits import ResourceGuardMiddleware
from betonning.repo import users


def test_unauthenticated_body_is_not_consumed(client, db_path):
    async def inner(scope, receive, send):
        raise AssertionError("Geen anonieme parser aanroepen")

    async def receive():
        raise AssertionError("Geen anonieme body lezen")

    messages = []

    async def send(message):
        messages.append(message)

    owner = SimpleNamespace(
        state=SimpleNamespace(db_path=db_path, enable_api_limits=True)
    )
    middleware = ResourceGuardMiddleware(inner, owner)
    asyncio.run(
        middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/items/A-1/attachments",
                "headers": [],
            },
            receive,
            send,
        )
    )
    assert messages[0]["status"] == 401


@pytest.mark.parametrize(("kind", "burst"), [("agent", 10), ("human", 30)])
def test_upload_rate_limit_and_stream_concurrency(
    client, conn, db_path, monkeypatch, kind, burst
):
    _, key = users.create(conn, handle="quota-agent", display_name="Quota", kind=kind)
    from betonning import ratelimit

    clock = [0.0]
    monkeypatch.setattr(ratelimit, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    owner = SimpleNamespace(
        state=SimpleNamespace(db_path=db_path, enable_api_limits=True)
    )

    async def done(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = ResourceGuardMiddleware(done, owner)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/items/A-1/attachments",
        "headers": [(b"authorization", f"Bearer {key}".encode())],
    }

    async def run():
        statuses = []

        async def send(m):
            if m["type"] == "http.response.start":
                statuses.append(m["status"])
                if m["status"] == 429:
                    assert int(dict(m["headers"])[b"retry-after"]) > 0

        for _ in range(burst + 1):
            await middleware(scope, receive, send)
        assert statuses == [200] * burst + [429]
        # Het uurtempo blijft 30 per agent (mensen ×3).
        clock[0] += 120 / (3 if kind == "human" else 1)
        await middleware(scope, receive, send)
        assert statuses[-1] == 200
        await middleware(scope, receive, send)
        assert statuses[-1] == 429
        release = asyncio.Event()

        async def hold(scope, receive, send):
            await release.wait()

        guard = ResourceGuardMiddleware(hold, owner)
        scope["path"] = "/api/v1/events/stream"
        scope["method"] = "GET"
        tasks = [asyncio.create_task(guard(scope, receive, send)) for _ in range(8)]
        await asyncio.sleep(0.05)
        await guard(scope, receive, send)
        assert statuses[-1] == 429
        release.set()
        await asyncio.gather(*tasks)
        assert not guard.streams

    asyncio.run(run())


def test_upload_quota_rejects_before_disk_write(client, auth, project, monkeypatch):
    item = client.post(
        "/api/v1/projects/SOS/items", headers=auth, json={"title": "Quota"}
    ).json()
    monkeypatch.setenv("BETONNING_UPLOAD_USER_QUOTA", "1")
    result = client.post(
        f"/api/v1/items/{item['ref']}/attachments",
        headers=auth,
        files={"file": ("test.txt", b"hello", "text/plain")},
    )
    assert result.status_code == 413
    assert (
        client.get(f"/api/v1/items/{item['ref']}/attachments", headers=auth).json()
        == []
    )


def test_write_quota_is_durable_and_atomic(client, conn, monkeypatch):
    from betonning.repo import resource_usage

    user, _ = users.create(
        conn, handle="bytes-agent", display_name="Bytes", kind="agent"
    )
    row = users.get(conn, user["id"])
    monkeypatch.setenv("BETONNING_API_DAILY_BYTES", "10")
    monkeypatch.setenv("BETONNING_API_TOTAL_BYTES", "15")
    assert resource_usage.claim(conn, row, 6)
    assert not resource_usage.claim(conn, row, 5)
    assert resource_usage.claim(conn, row, 4)
    conn.execute(
        "UPDATE api_write_usage SET day='2000-01-01' WHERE user_id=?", (user["id"],)
    )
    assert resource_usage.claim(conn, row, 5)
    assert not resource_usage.claim(conn, row, 1)


def test_durable_quota_returns_429_before_handler(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from betonning import db as dbm
    from betonning.server import create_app

    path = str(tmp_path / "live.db")
    dbm.init_db(path).close()
    conn = dbm.connect(path)
    _, key = users.create(conn, handle="human", display_name="Human", kind="human")
    conn.close()
    monkeypatch.setenv("BETONNING_API_DAILY_BYTES", "1")
    app = create_app(
        path,
        enable_dispatcher=False,
        enable_mcp=False,
        enable_triage=False,
        enable_wiki_compile=False,
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {key}"},
            json={"key": "NO", "name": "No"},
        )
        assert response.status_code == 429
        assert (
            client.get(
                "/api/v1/projects", headers={"Authorization": f"Bearer {key}"}
            ).json()
            == []
        )


def test_metrics_and_human_recovery(client, auth, conn):
    agent, key = users.create(
        conn, handle="recover", display_name="Recover", kind="agent"
    )
    from betonning.repo import resource_usage

    resource_usage.claim(conn, users.get(conn, agent["id"]), 5)
    status = client.get("/api/v1/security-status", headers=auth)
    assert status.status_code == 200
    assert status.json()["write_usage"][0]["total_bytes"] == 5
    assert (
        client.get(
            "/api/v1/security-status", headers={"Authorization": f"Bearer {key}"}
        ).status_code
        == 403
    )
    assert (
        client.post("/api/v1/security-usage/recover/reset", headers=auth).status_code
        == 200
    )
    assert (
        client.get("/api/v1/security-status", headers=auth).json()["write_usage"] == []
    )
