"""Per-project automatic locks preserve manual safety controls."""

import pytest

from betonning.repo import users as users_repo


@pytest.fixture
def setup(client, auth, project, conn):
    _, key = users_repo.create(conn, handle="worker", display_name="Worker", kind="agent")
    conn.commit()
    agent = {"Authorization": f"Bearer {key}"}
    response = client.post(
        "/api/v1/projects/SOS/items", headers=auth,
        json={"title": "Example task", "state": "todo", "assignee": "worker"},
    )
    assert response.status_code == 201
    conn.execute("UPDATE items SET comment_limit = 1")
    conn.commit()
    return agent


def _set(client, auth, enabled):
    return client.put("/api/v1/projects/SOS/auto-lock", headers=auth, json={"enabled": enabled})


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("handover", [True, False])
def test_comment_threshold_respects_project_setting(client, auth, setup, enabled, handover):
    assert _set(client, auth, enabled).json()["auto_lock_enabled"] is enabled
    if handover:
        response = client.patch(
            "/api/v1/items/SOS-1", headers=setup,
            json={"assignee": "person", "handover_md": "Please verify the result."},
        )
        assert response.status_code == 200
    else:
        response = client.post(
            "/api/v1/items/SOS-1/comments", headers=setup, json={"body_md": "Work update."}
        )
        assert response.status_code == 201
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert (detail["locked_at"] is not None) is enabled
    assert len(detail["comments"]) == 1
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert any(event["type"] == "item.locked" for event in events) is enabled


def test_new_project_defaults_to_automatic_lock(client, auth, setup):
    assert client.get("/api/v1/projects", headers=auth).json()[0]["auto_lock_enabled"] is True
    client.post("/api/v1/items/SOS-1/comments", headers=setup, json={"body_md": "Update."})
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["locked_at"] is not None


@pytest.mark.parametrize("manual", [True, False])
def test_disabling_preserves_existing_locks(client, auth, setup, manual):
    if manual:
        assert client.post("/api/v1/items/SOS-1/lock", headers=auth).status_code == 200
    else:
        client.post("/api/v1/items/SOS-1/comments", headers=setup, json={"body_md": "Update."})
    assert _set(client, auth, False).status_code == 200
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["locked_at"] is not None
    assert client.post(
        "/api/v1/items/SOS-1/comments", headers=setup, json={"body_md": "Another update."}
    ).status_code == 409


def test_disabled_project_still_allows_manual_emergency_stop(client, auth, setup):
    assert _set(client, auth, False).status_code == 200
    assert client.post("/api/v1/items/SOS-1/lock", headers=auth).status_code == 200
    assert client.patch(
        "/api/v1/items/SOS-1", headers=setup,
        json={"assignee": "person", "handover_md": "Please verify the result."},
    ).status_code == 409


def test_agent_cannot_change_automatic_lock_policy(client, auth, setup):
    assert _set(client, setup, False).status_code == 403
    assert client.get("/api/v1/projects", headers=auth).json()[0]["auto_lock_enabled"] is True


def test_policy_is_project_scoped_and_archived_project_is_readonly(client, auth, setup):
    assert client.post(
        "/api/v1/projects", headers=auth, json={"key": "OTHER", "name": "Other project"}
    ).status_code == 201
    assert _set(client, auth, False).status_code == 200
    projects = {p["key"]: p for p in client.get("/api/v1/projects", headers=auth).json()}
    assert projects["OTHER"]["auto_lock_enabled"] is True
    assert client.delete("/api/v1/projects/SOS", headers=auth).status_code == 204
    assert _set(client, auth, True).status_code == 409


def test_upgrade_preserves_lock_default_and_archive_guard(tmp_path, monkeypatch):
    import sqlite3
    from betonning import db

    migrations = db._migration_files()
    with db.connect(tmp_path / "upgrade.db") as conn:
        with monkeypatch.context() as patch:
            patch.setattr(db, "_migration_files", lambda: [(v, sql) for v, sql in migrations if v < 57])
            db.migrate(conn)
        conn.execute("INSERT INTO projects (key, name, archived_at) VALUES ('DEMO', 'Demo', '2026-01-01')")
        db.migrate(conn)
        assert conn.execute("SELECT auto_lock_enabled FROM projects").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="archived_project_readonly"):
            conn.execute("UPDATE projects SET archived_at = NULL, auto_lock_enabled = 0")
        conn.execute("UPDATE projects SET archived_at = NULL")
        conn.execute("UPDATE projects SET auto_lock_enabled = 0")
        assert conn.execute("SELECT auto_lock_enabled FROM projects").fetchone()[0] == 0
