"""MCP-verkeerstelling per JSON-RPC-methode en user (BETON-467)."""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from betonning import db as db_module
from betonning import mcp_stats
from betonning.repo import users as users_repo
from betonning.server import create_app


def test_method_of():
    assert mcp_stats.method_of(b'{"jsonrpc":"2.0","method":"tools/list","id":1}') == "tools/list"
    assert mcp_stats.method_of(b'[{"method":"b"},{"method":"a"}]') == "a,b"
    assert mcp_stats.method_of(b"geen json") == "?"


def test_flush_logs_counts_and_resets(caplog):
    now = [0.0]
    stats = mcp_stats.McpStats(interval=3600, clock=lambda: now[0])
    stats.record("POST", "tools/call", "claude")
    stats.record("POST", "tools/call", "claude")
    stats.record("GET", None, "codex")
    assert stats.snapshot()[("POST", "tools/call", "claude")] == 2
    with caplog.at_level(logging.INFO, logger="betonning.mcp_stats"):
        stats.flush()
    assert "total=3" in caplog.text
    assert "claude:POST:tools/call=2" in caplog.text
    assert stats.snapshot() == {}


def test_lazy_flush_after_interval(caplog):
    now = [0.0]
    stats = mcp_stats.McpStats(interval=10, clock=lambda: now[0])
    stats.record("POST", "ping", "a")
    now[0] = 11
    with caplog.at_level(logging.INFO, logger="betonning.mcp_stats"):
        stats.record("POST", "ping", "a")
    assert "total=2" in caplog.text


def test_mount_counts_and_does_not_log_body(tmp_path, caplog):
    db_path = str(tmp_path / "s.db")
    db_module.init_db(db_path).close()
    conn = db_module.connect(db_path)
    _, key = users_repo.create(conn, handle="claude", display_name="C", kind="agent")
    conn.close()
    app = create_app(db_path, enable_dispatcher=False, enable_mcp=True)
    secret = "GEHEIM-BODY-INHOUD"
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": secret, "version": "0"}}}
    with TestClient(app) as c:
        r = c.post(
            "/mcp/",
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            content=json.dumps(body),
        )
        assert r.status_code == 200  # de app kreeg de body intact
        assert app.state.mcp_stats.snapshot()[("POST", "initialize", "claude")] == 1
        with caplog.at_level(logging.INFO):
            app.state.mcp_stats.flush()
    assert secret not in caplog.text
