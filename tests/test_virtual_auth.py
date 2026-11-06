"""Virtuele queues (`is_virtual=1`) authenticeren nooit (BETON-468)."""

from __future__ import annotations

import time

from starlette.testclient import TestClient

from betonning import admin
from betonning import db as db_module
from betonning import security
from betonning.repo import users as users_repo
from betonning.server import create_app

KEY = "bt_virtueel_lek"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"},
    },
}


def _leak_key(conn, handle="coding-agent"):
    """Zet een bekende, geldig gehashte key op de geseede virtuele user."""
    conn.execute(
        "UPDATE users SET api_key_hash = ? WHERE handle = ?",
        (security.hash_api_key(KEY), handle),
    )
    conn.commit()


def test_virtual_user_key_does_not_authenticate_rest(client, conn):
    _leak_key(conn)
    r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 401


def test_virtual_user_key_cannot_get_media_cookie(client, conn):
    _leak_key(conn)
    r = client.post("/api/v1/media-cookie", headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 401


def test_virtual_user_key_does_not_open_media_route(client, conn, auth):
    _leak_key(conn)
    png = b"\x89PNG\r\n\x1a\n fake"
    client.post(
        "/api/v1/users/person/avatar",
        files={"file": ("a.png", png, "image/png")},
        headers=auth,
    )
    r = client.get(
        "/api/v1/users/person/avatar", headers={"Authorization": f"Bearer {KEY}"}
    )
    assert r.status_code == 401


def test_media_cookie_of_virtual_user_is_refused(client, conn, auth):
    """Een cookie dat vóór de poort is uitgegeven werkt niet meer."""
    png = b"\x89PNG\r\n\x1a\n fake"
    client.post(
        "/api/v1/users/person/avatar",
        files={"file": ("a.png", png, "image/png")},
        headers=auth,
    )
    _leak_key(conn)
    row = users_repo.get_by_handle(conn, "coding-agent")
    from betonning import deps

    token = security.sign_media_token(
        int(time.time()) + 3600, row["id"], deps.media_key_fragment(row)
    )
    client.cookies.set(deps.MEDIA_COOKIE_NAME, token)
    assert client.get("/api/v1/users/person/avatar").status_code == 401


def test_virtual_user_key_does_not_pass_mcp_gate(tmp_path):
    db_path = str(tmp_path / "v.db")
    db_module.init_db(db_path).close()
    conn = db_module.connect(db_path)
    _leak_key(conn)
    conn.close()
    app = create_app(db_path, enable_dispatcher=False, enable_mcp=True)
    with TestClient(app) as c:
        r = c.post(
            "/mcp/",
            json=INITIALIZE,
            headers={**MCP_HEADERS, "Authorization": f"Bearer {KEY}"},
        )
        assert r.status_code == 401


def test_real_agent_still_authenticates(client, conn):
    _, key = users_repo.create(
        conn, handle="codex", display_name="Codex", kind="agent", agent_type="coding"
    )
    conn.commit()
    r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200


def test_rotate_virtual_user_is_422_and_leaves_hash(client, conn, auth):
    before = users_repo.get_by_handle(conn, "coding-agent")["api_key_hash"]
    r = client.post("/api/v1/users/coding-agent/api-key/rotate", headers=auth)
    assert r.status_code == 422
    assert users_repo.get_by_handle(conn, "coding-agent")["api_key_hash"] == before


def test_admin_rotate_key_refuses_virtual_user(tmp_path, capsys):
    db = str(tmp_path / "a.db")
    db_module.init_db(db).close()
    rc = admin.main(["rotate-key", "--db", db, "--handle", "coding-agent"])
    assert rc == 1
    assert "virtuele queue" in capsys.readouterr().out
    conn = db_module.connect(db)
    assert users_repo.get_by_handle(conn, "coding-agent")["api_key_hash"] == (
        "virtual:coding-agent"
    )
    conn.close()


def test_migration_044_replaces_leaked_virtual_hash(tmp_path):
    db = str(tmp_path / "m.db")
    # Schema tot en met 043 (latere ADD COLUMN-migraties lopen niet dubbel).
    conn = db_module.connect(db)
    applied = 0
    for v, sql in db_module._migration_files():
        if v >= 44:
            continue
        conn.executescript(sql)
        applied = v
    conn.execute(f"PRAGMA user_version = {applied}")
    conn.execute(
        "UPDATE users SET api_key_hash = printf('%064d', id) WHERE is_virtual = 1"
    )
    conn.commit()
    conn.close()
    conn = db_module.init_db(db)
    rows = conn.execute(
        "SELECT handle, api_key_hash FROM users WHERE is_virtual = 1"
    ).fetchall()
    assert rows
    assert all(r["api_key_hash"] == f"virtual:{r['handle']}" for r in rows)
    conn.close()
