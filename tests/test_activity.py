"""Events-log: elke item-mutatie schrijft een event; /activity leest ze terug."""

from __future__ import annotations

from conftest import _create


def test_create_writes_created_event(client, auth, project):
    _create(client, auth, project, title="Nieuw")
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert len(events) == 1
    assert events[0]["type"] == "item.created"
    assert events[0]["actor"] == "person"
    assert events[0]["payload"]["ref"] == "SOS-1"


def test_update_writes_updated_event(client, auth, project):
    _create(client, auth, project, title="x")
    client.patch("/api/v1/items/SOS-1", json={"priority": "high"}, headers=auth)
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    types = [e["type"] for e in events]
    assert types == ["item.created", "item.updated"]
    assert events[1]["payload"]["priority"] == {"from": "none", "to": "high"}


def test_noop_patch_writes_no_event(client, auth, project):
    _create(client, auth, project, title="x")
    client.patch("/api/v1/items/SOS-1", json={}, headers=auth)
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert [e["type"] for e in events] == ["item.created"]


def test_activity_requires_auth(client, project):
    assert client.get("/api/v1/items/SOS-1/activity").status_code == 401


def test_activity_unknown_item_404(client, auth, project):
    assert client.get("/api/v1/items/SOS-999/activity", headers=auth).status_code == 404
