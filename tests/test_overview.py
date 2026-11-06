"""GET /overview — de cross-project stand van zaken (BETON-371).

Getest op gedrag via de TestClient (tellers, archivering, auth) plus één
structurele toets: het aantal query's mag niet met het aantal projecten
meegroeien (`set_trace_callback`, zelfde idioom als BETON-294).
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from betonning import db as db_module
from betonning.repo import overview as overview_repo
from betonning.repo import users as users_repo
from conftest import _create


@pytest.fixture
def other_key(conn: sqlite3.Connection) -> str:
    _, key = users_repo.create(conn, handle="claude", display_name="Claude", kind="agent")
    return key


@pytest.fixture
def other_auth(other_key: str) -> dict:
    return {"Authorization": f"Bearer {other_key}"}


def _by_key(rows: list[dict]) -> dict[str, dict]:
    return {r["key"]: r for r in rows}


def test_requires_auth(client: TestClient):
    assert client.get("/api/v1/overview").status_code == 401


def test_counts_open_in_progress_unassigned(client: TestClient, auth, project):
    _create(client, auth, project, title="open zonder assignee")
    _create(client, auth, project, title="aan mij", assignee="person")
    _create(client, auth, project, title="loopt", state="in-progress", assignee="person")
    _create(client, auth, project, title="klaar", state="done")

    row = _by_key(client.get("/api/v1/overview", headers=auth).json())["SOS"]
    assert row["name"] == "SOS"
    assert row["open"] == 3  # done telt niet mee
    assert row["in_progress"] == 1
    assert row["unassigned"] == 1


def test_cancelled_and_archived_items_fall_away(client: TestClient, auth, project):
    _create(client, auth, project, title="blijft")
    _create(client, auth, project, title="afgeblazen", state="cancelled")
    _create(client, auth, project, title="weg")
    client.delete("/api/v1/items/SOS-3", headers=auth)

    row = _by_key(client.get("/api/v1/overview", headers=auth).json())["SOS"]
    assert row["open"] == 1


def test_archived_project_is_not_listed(client: TestClient, auth, project):
    client.post("/api/v1/projects", json={"key": "OUD", "name": "Oud"}, headers=auth)
    _create(client, auth, "OUD", title="iets")
    assert "OUD" in _by_key(client.get("/api/v1/overview", headers=auth).json())

    client.delete("/api/v1/projects/OUD", headers=auth)
    rows = _by_key(client.get("/api/v1/overview", headers=auth).json())
    assert "OUD" not in rows and "SOS" in rows


def test_blocked_counts_only_the_blocked_side(client: TestClient, auth, project):
    """Richting: `blocked_by` ligt opgeslagen als een omgekeerde `blocks`, dus
    alleen het geblokkeerde item telt — de blokkeerder is gewoon werk."""
    _create(client, auth, project, title="blokkeerder")
    _create(client, auth, project, title="wacht")
    client.post(
        "/api/v1/items/SOS-2/relations",
        json={"type": "blocked_by", "target": "SOS-1"},
        headers=auth,
    )

    row = _by_key(client.get("/api/v1/overview", headers=auth).json())["SOS"]
    assert row["open"] == 2
    assert row["blocked"] == 1

    # Blokkeerder afgerond → het werk is vrij, ook al staat de relatie er nog:
    # op een echt bord wordt een blokkeerder vaker gesloten dan opgeruimd.
    client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=auth)
    row = _by_key(client.get("/api/v1/overview", headers=auth).json())["SOS"]
    assert row["blocked"] == 0


def test_open_questions_only_for_the_viewer(client: TestClient, auth, other_auth, project):
    """Gerichtheid = assignee/maker/@gementiond — dezelfde regel als
    `GET /questions?open=true`; de teller moet daar dus mee overeenkomen."""
    _create(client, auth, project, title="van person")
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Wat wordt het?", "kind": "question"},
        headers=other_auth,
    )
    _create(client, other_auth, project, title="van claude", assignee="person")
    client.post(
        "/api/v1/items/SOS-2/comments",
        json={"body_md": "En hier?", "kind": "question"},
        headers=other_auth,
    )

    mine = _by_key(client.get("/api/v1/overview", headers=auth).json())["SOS"]
    theirs = _by_key(client.get("/api/v1/overview", headers=other_auth).json())["SOS"]
    assert mine["open_questions"] == 2  # maker van SOS-1, assignee van SOS-2
    assert theirs["open_questions"] == 1  # alleen SOS-2, dat hij zelf aanmaakte

    # Zelfde regel, zelfde uitkomst als het bestaande vraag-endpoint.
    for headers, expected in ((auth, 2), (other_auth, 1)):
        listed = client.get("/api/v1/questions?open=true", headers=headers).json()
        assert len(listed) == expected


def test_unread_follows_foreign_comment_activity(
    client: TestClient, auth, other_auth, conn, project
):
    _create(client, auth, project, title="mijn ticket")
    assert _by_key(client.get("/api/v1/overview", headers=auth).json())["SOS"]["unread"] == 0

    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=other_auth)
    assert _by_key(client.get("/api/v1/overview", headers=auth).json())["SOS"]["unread"] == 1

    client.post("/api/v1/items/SOS-1/read", headers=auth)
    assert _by_key(client.get("/api/v1/overview", headers=auth).json())["SOS"]["unread"] == 0


def test_next_milestone_is_the_earliest_open_one(client: TestClient, auth, project):
    client.post(
        "/api/v1/projects/SOS/milestones",
        json={"name": "v2.0.0", "due_date": "2027-01-01"},
        headers=auth,
    )
    client.post(
        "/api/v1/projects/SOS/milestones",
        json={"name": "v1.5.0", "due_date": "2026-01-01"},
        headers=auth,
    )
    _create(client, auth, project, title="a", milestone="v1.5.0")
    _create(client, auth, project, title="b", milestone="v1.5.0", state="done")

    ms = _by_key(client.get("/api/v1/overview", headers=auth).json())["SOS"]["next_milestone"]
    assert ms["name"] == "v1.5.0"
    assert (ms["items_done"], ms["items_total"]) == (1, 2)


def test_completed_milestone_is_skipped(client: TestClient, auth, project):
    client.post(
        "/api/v1/projects/SOS/milestones",
        json={"name": "v1.0.0", "due_date": "2025-01-01"},
        headers=auth,
    )
    client.post(
        "/api/v1/projects/SOS/milestones",
        json={"name": "v1.1.0", "due_date": "2026-01-01"},
        headers=auth,
    )
    client.patch(
        "/api/v1/projects/SOS/milestones/v1.0.0", json={"status": "completed"}, headers=auth
    )

    ms = _by_key(client.get("/api/v1/overview", headers=auth).json())["SOS"]["next_milestone"]
    assert ms["name"] == "v1.1.0"


def test_last_activity_covers_items_and_comments(client: TestClient, auth, conn, project):
    """BETON-464: nieuwste item- of comment-tijd; leeg project = null."""
    client.post("/api/v1/projects", json={"key": "LEEG", "name": "Leeg"}, headers=auth)
    _create(client, auth, project, title="oud")
    conn.execute("UPDATE items SET updated_at = '2026-01-01T00:00:00.000Z'")
    conn.commit()
    rows = _by_key(client.get("/api/v1/overview", headers=auth).json())
    assert rows["SOS"]["last_activity_at"] == "2026-01-01T00:00:00.000Z"
    assert rows["LEEG"]["last_activity_at"] is None

    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=auth)
    rows = _by_key(client.get("/api/v1/overview", headers=auth).json())
    assert rows["SOS"]["last_activity_at"] > "2026-01-01T00:00:00.000Z"


def test_query_count_is_constant_in_projects(client: TestClient, auth, conn, db_path, project):
    """De structurele bewaking: het overzicht mag niet per project tellen.

    Meten op repo-niveau met een trace-callback (de query's van de
    request-connectie zijn via de TestClient niet te observeren) en de as die
    ertoe doet variëren: het aantal **projecten**, niet het aantal items.
    """
    viewer = conn.execute("SELECT id FROM users WHERE handle = 'person'").fetchone()["id"]

    def _count() -> int:
        traced = db_module.connect(db_path)
        statements: list[str] = []
        traced.set_trace_callback(statements.append)
        rows = overview_repo.project_overview(traced, viewer, "person")
        traced.close()
        return len(statements), len(rows)

    for n in range(2, 4):
        client.post(
            "/api/v1/projects", json={"key": f"P{n}", "name": f"P{n}"}, headers=auth
        )
        _create(client, auth, f"P{n}", title="iets")
    small, small_rows = _count()
    assert small_rows == 3

    for n in range(4, 8):
        client.post(
            "/api/v1/projects", json={"key": f"P{n}", "name": f"P{n}"}, headers=auth
        )
        _create(client, auth, f"P{n}", title="iets")
    big, big_rows = _count()
    assert big_rows == 7  # écht meer projecten geserialiseerd
    assert small == big
