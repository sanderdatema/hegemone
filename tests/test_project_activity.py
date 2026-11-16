"""Activiteitenfeed per project (BETON-372): GET /projects/{key}/activity.

Spiegelt tests/test_activity.py (item-scoped), maar dan over alle items van
één project heen — met filters (since/actor/type) en project-scoping."""

from __future__ import annotations

from conftest import _create

from betonning import db as db_module
from betonning.repo import events as events_repo
from betonning.repo import users as users_repo


def test_project_activity_lists_events_for_its_items(client, auth, project):
    _create(client, auth, project, title="Eerste")
    _create(client, auth, project, title="Tweede")
    events = client.get("/api/v1/projects/SOS/activity", headers=auth).json()
    assert [e["type"] for e in events] == ["item.created", "item.created"]
    # Nieuwste eerst.
    assert events[0]["ref"] == "SOS-2"
    assert events[1]["ref"] == "SOS-1"
    assert events[0]["actor"] == "person"


def test_project_activity_excludes_other_projects(client, auth, project):
    client.post("/api/v1/projects", json={"key": "BRAND", "name": "Brand"}, headers=auth)
    _create(client, auth, project, title="In SOS")
    _create(client, auth, "BRAND", title="In BRAND")

    sos_events = client.get("/api/v1/projects/SOS/activity", headers=auth).json()
    brand_events = client.get("/api/v1/projects/BRAND/activity", headers=auth).json()

    assert [e["ref"] for e in sos_events] == ["SOS-1"]
    assert [e["ref"] for e in brand_events] == ["BRAND-1"]


def test_project_activity_requires_auth(client, project):
    assert client.get("/api/v1/projects/SOS/activity").status_code == 401


def test_project_activity_unknown_project_404(client, auth, project):
    resp = client.get("/api/v1/projects/NOPE/activity", headers=auth)
    assert resp.status_code == 404


def test_project_activity_since_filters_older_events(client, auth, project):
    _create(client, auth, project, title="Eerste")
    first = client.get("/api/v1/projects/SOS/activity", headers=auth).json()
    first_id = first[0]["id"]
    _create(client, auth, project, title="Tweede")

    events = client.get(
        f"/api/v1/projects/SOS/activity?since={first_id}", headers=auth
    ).json()
    assert [e["ref"] for e in events] == ["SOS-2"]


def test_project_activity_filters_by_type(client, auth, project):
    _create(client, auth, project, title="x")
    client.patch("/api/v1/items/SOS-1", json={"priority": "high"}, headers=auth)

    events = client.get(
        "/api/v1/projects/SOS/activity?type=item.updated", headers=auth
    ).json()
    assert [e["type"] for e in events] == ["item.updated"]


def test_project_activity_filters_by_actor(client, auth, project, conn):
    _, other_key = users_repo.create(
        conn, handle="codex", display_name="Codex", kind="agent", agent_type="coding"
    )
    other_auth = {"Authorization": f"Bearer {other_key}"}
    _create(client, auth, project, title="Van person")
    _create(client, other_auth, project, title="Van codex")

    events = client.get(
        "/api/v1/projects/SOS/activity?actor=codex", headers=auth
    ).json()
    assert [e["ref"] for e in events] == ["SOS-2"]
    assert events[0]["actor"] == "codex"


def test_project_activity_unknown_actor_404(client, auth, project):
    resp = client.get("/api/v1/projects/SOS/activity?actor=nobody", headers=auth)
    assert resp.status_code == 404


def test_project_activity_respects_limit(client, auth, project):
    for i in range(3):
        _create(client, auth, project, title=f"Item {i}")
    events = client.get(
        "/api/v1/projects/SOS/activity?limit=2", headers=auth
    ).json()
    assert len(events) == 2
    assert events[0]["ref"] == "SOS-3"


def test_project_activity_includes_events_of_archived_items(client, auth, project):
    _create(client, auth, project, title="Archiveer mij")
    client.delete("/api/v1/items/SOS-1", headers=auth)

    events = client.get("/api/v1/projects/SOS/activity", headers=auth).json()
    types = [e["type"] for e in events]
    assert "item.created" in types
    assert "item.archived" in types
    assert all(e["ref"] == "SOS-1" for e in events)


def test_project_activity_includes_hard_deleted_item_via_payload_ref(
    client, auth, project
):
    _create(client, auth, project, title="Verwijder mij")
    client.delete("/api/v1/items/SOS-1?hard=true", headers=auth)

    events = client.get("/api/v1/projects/SOS/activity", headers=auth).json()
    deleted = [e for e in events if e["type"] == "item.deleted"]
    assert len(deleted) == 1
    assert deleted[0]["ref"] == "SOS-1"
    assert deleted[0]["title"] == "Verwijder mij"


def test_project_activity_does_not_scale_with_item_count(client, auth, project, db_path):
    """serialize_bulk gebruikt vaste query's, net als repo/items.py:_compact_rows —
    één actor-lookup + één item-lookup voor de hele lijst, niet één per event
    (BETON-372)."""

    def _add_items(n: int) -> None:
        for i in range(n):
            _create(client, auth, project, title=f"item {i}")

    def _query_count(expected_total: int) -> int:
        traced = db_module.connect(db_path)
        statements: list[str] = []
        traced.set_trace_callback(statements.append)
        project_id = traced.execute(
            "SELECT id FROM projects WHERE key = 'SOS'"
        ).fetchone()["id"]
        rows = events_repo.list_for_project(traced, project_id, "SOS", limit=500)
        assert len(rows) == expected_total  # écht zoveel events gebatcht
        result = events_repo.serialize_bulk(traced, rows)
        assert len(result) == expected_total
        traced.close()
        return sum(
            1 for s in statements if "FROM users" in s or "FROM items" in s
        )

    _add_items(2)
    small = _query_count(2)
    _add_items(9)  # totaal 11 items — het aantal query's mag niet meeschalen
    large = _query_count(11)
    assert small == large


def test_comment_preview_is_bounded_current_and_not_resurrected(client, auth, project, conn):
    item = _create(client, auth, project, title='Readable title').json()
    body = 'Visible text\n' * 60
    comment = client.post(f"/api/v1/items/{item['ref']}/comments", headers=auth, json={'body_md':body}).json()
    def feed():
        return client.get('/api/v1/projects/SOS/activity',headers=auth).json()
    event = next(e for e in feed() if e['type']=='comment.created')
    assert event['title'] == 'Readable title'
    assert event['comment_preview'].startswith('Visible text Visible text')
    assert len(event['comment_preview']) <= 241
    assert '\n' not in event['comment_preview']
    assert client.patch(f"/api/v1/items/{item['ref']}/comments/{comment['id']}",headers=auth,json={'body_md':'Updated content'}).status_code == 200
    assert next(e for e in feed() if e['type']=='comment.created')['comment_preview'] == 'Updated content'
    assert client.delete(f"/api/v1/items/{item['ref']}/comments/{comment['id']}",headers=auth).status_code == 204
    assert next(e for e in feed() if e['type']=='comment.created')['comment_preview'] is None


def test_comment_preview_requires_matching_event_item(client, auth, project, conn):
    first = _create(client, auth, project, title='First').json()
    second = _create(client, auth, project, title='Second').json()
    comment = client.post(f"/api/v1/items/{second['ref']}/comments",headers=auth,json={'body_md':'Other content'}).json()
    from betonning.repo import items
    item = items.get_by_ref(conn, first['ref'])
    events_repo.record(conn,type='comment.created',item_id=item['id'],actor_id=None,payload={'comment_id':comment['id']})
    conn.commit()
    feed = client.get('/api/v1/projects/SOS/activity',headers=auth).json()
    assert feed[0]['ref'] == first['ref']
    assert feed[0]['comment_preview'] is None
