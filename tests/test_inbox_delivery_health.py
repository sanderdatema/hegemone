"""Onbereikbare agents als afgeleide inbox-entry (BETON-457)."""

from __future__ import annotations

import pytest

from betonning import db as db_module
from betonning.repo import inbox as inbox_repo
from betonning.repo import users as users_repo

from conftest import _create


@pytest.fixture
def event_id(client, auth, project, conn):
    _create(client, auth, project, title="aanleiding")
    return conn.execute("SELECT MAX(id) FROM events").fetchone()[0]


def _agent(conn, handle="smid", url="http://10.0.0.5:8644/webhooks/smid", **kw):
    users_repo.create(conn, handle=handle, display_name=handle.title(), kind="agent",
                      webhook_url=url, **kw)
    return conn.execute("SELECT id FROM users WHERE handle = ?", (handle,)).fetchone()[0]


def _deliver(conn, event_id, uid, status, channel="webhook", error=None):
    conn.execute(
        "INSERT INTO webhook_deliveries (event_id, user_id, channel, status, last_error) "
        "VALUES (?, ?, ?, ?, ?)",
        (event_id, uid, channel, status, error),
    )
    conn.commit()


def _entries(conn, handle="person"):
    user = users_repo.get_by_handle(conn, handle)
    return [e for e in inbox_repo.list_for_user(conn, user)["items"]
            if e["reason"] == "agent_unreachable"]


def test_three_failures_give_entry_and_one_delivered_clears_it(conn, event_id):
    uid = _agent(conn)
    for _ in range(3):
        _deliver(conn, event_id, uid, "failed", error="All connection attempts failed")
    [e] = _entries(conn)
    assert e["handle"] == "smid" and e["failed_count"] == 3
    assert e["last_error"] == "All connection attempts failed"
    assert e["event_id"] == 0 and e["ref"] is None and e["read"] is False
    assert e["last_delivered_at"] is None

    _deliver(conn, event_id, uid, "delivered")
    assert _entries(conn) == []


def test_below_threshold_no_entry(conn, event_id):
    uid = _agent(conn)
    _deliver(conn, event_id, uid, "failed")
    _deliver(conn, event_id, uid, "failed")
    assert _entries(conn) == []


def test_only_failures_after_last_delivered_count(conn, event_id):
    uid = _agent(conn)
    for _ in range(5):
        _deliver(conn, event_id, uid, "failed")
    _deliver(conn, event_id, uid, "delivered")
    _deliver(conn, event_id, uid, "failed")
    assert _entries(conn) == []


def test_pending_and_cancelled_are_not_outcomes(conn, event_id):
    uid = _agent(conn)
    for _ in range(2):
        _deliver(conn, event_id, uid, "failed")
    _deliver(conn, event_id, uid, "cancelled")
    _deliver(conn, event_id, uid, "pending")
    assert _entries(conn) == []


def test_telegram_channel_failures_do_not_count(conn, event_id):
    uid = _agent(conn)
    for _ in range(4):
        _deliver(conn, event_id, uid, "failed", channel="telegram")
    assert _entries(conn) == []


def test_agent_without_webhook_url_is_ignored(conn, event_id):
    users_repo.create(conn, handle="plain", display_name="Plain", kind="agent")
    uid = conn.execute("SELECT id FROM users WHERE handle='plain'").fetchone()[0]
    for _ in range(3):
        _deliver(conn, event_id, uid, "failed")
    assert _entries(conn) == []


def test_virtual_user_is_ignored(conn, event_id):
    uid = _agent(conn)
    conn.execute("UPDATE users SET is_virtual = 1 WHERE id = ?", (uid,))
    for _ in range(3):
        _deliver(conn, event_id, uid, "failed")
    assert _entries(conn) == []


def test_only_humans_get_the_entry(conn, event_id):
    uid = _agent(conn)
    for _ in range(3):
        _deliver(conn, event_id, uid, "failed")
    assert _entries(conn, "smid") == []
    assert len(_entries(conn, "person")) == 1


def test_counts_in_unread_count(conn, event_id):
    uid = _agent(conn)
    for _ in range(3):
        _deliver(conn, event_id, uid, "failed")
    user = users_repo.get_by_handle(conn, "person")
    assert inbox_repo.list_for_user(conn, user)["unread_count"] >= 1


def test_threshold_from_env(conn, event_id, monkeypatch):
    uid = _agent(conn)
    _deliver(conn, event_id, uid, "failed")
    monkeypatch.setenv("BETONNING_WEBHOOK_ALERT_AFTER", "1")
    assert len(_entries(conn)) == 1


def test_single_query_regardless_of_agent_count(db_path, conn, event_id):
    for h in ("a1", "a2", "a3", "a4"):
        uid = _agent(conn, h, url=f"http://10.0.0.5/{h}")
        for _ in range(3):
            _deliver(conn, event_id, uid, "failed")
    traced = db_module.connect(db_path)
    statements: list[str] = []
    traced.set_trace_callback(statements.append)
    user = users_repo.get_by_handle(traced, "person")
    entries = inbox_repo.delivery_health_entries(traced, user)
    traced.close()
    assert len(entries) == 4
    assert sum(1 for s in statements if "FROM webhook_deliveries" in s) == 1


def test_webhook_health_endpoint_is_human_only(client, auth, conn, event_id):
    uid = _agent(conn)
    for _ in range(3):
        _deliver(conn, event_id, uid, "failed")
    _, key = users_repo.create(conn, handle="bot", display_name="Bot", kind="agent")
    assert client.get("/api/v1/webhook-health", headers={"Authorization": f"Bearer {key}"}).status_code == 403
    assert client.get("/api/v1/webhook-health").status_code == 401
    rows = client.get("/api/v1/webhook-health", headers=auth).json()
    assert [(r["handle"], r["unreachable"], r["failed_count"]) for r in rows] == [("smid", True, 3)]
