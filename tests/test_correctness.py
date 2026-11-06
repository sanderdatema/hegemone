"""Fase A — correctheidsgaranties: transacties, diff-events, validaties.

Deze tests borgen het gedrag dat een halve mutatie nooit blijft staan, dat
events old→new bevatten (en no-ops overslaan), en dat ongeldige structuur
(parent-cyclus, cross-project parent, tegenstrijdige relatie, lege titel)
geweigerd wordt.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def project(project, client, auth):
    for _ in range(3):
        client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    return project


# --- Events: old→new + no-op-detectie -------------------------------------


def test_update_event_has_from_to(client, auth, project):
    client.patch("/api/v1/items/SOS-1", json={"priority": "high"}, headers=auth)
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert events[-1]["payload"]["priority"] == {"from": "none", "to": "high"}


def test_state_change_records_origin(client, auth, project):
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=auth)
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert events[-1]["payload"]["state"] == {"from": "todo", "to": "done"}


def test_noop_value_patch_writes_no_event(client, auth, project):
    # SOS-1 heeft al priority 'none'; opnieuw 'none' zetten wijzigt niets.
    client.patch("/api/v1/items/SOS-1", json={"priority": "none"}, headers=auth)
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert [e["type"] for e in events] == ["item.created"]


def test_noop_patch_does_not_bump_updated_at(client, auth, conn, project):
    before = client.get("/api/v1/items/SOS-1", headers=auth).json()["updated_at"]
    client.patch("/api/v1/items/SOS-1", json={"priority": "none"}, headers=auth)
    after = client.get("/api/v1/items/SOS-1", headers=auth).json()["updated_at"]
    assert after == before


# --- Validatie: parent -----------------------------------------------------


def test_parent_direct_cycle_400(client, auth, project):
    client.patch("/api/v1/items/SOS-2", json={"parent": "SOS-1"}, headers=auth)
    # SOS-1 als kind van SOS-2 zou een cyclus SOS-1→SOS-2→SOS-1 vormen.
    r = client.patch("/api/v1/items/SOS-1", json={"parent": "SOS-2"}, headers=auth)
    assert r.status_code == 400


def test_parent_self_cycle_400(client, auth, project):
    r = client.patch("/api/v1/items/SOS-1", json={"parent": "SOS-1"}, headers=auth)
    assert r.status_code == 400


def test_parent_cross_project_400(client, auth, project):
    client.post("/api/v1/projects", json={"key": "OTH", "name": "Other"}, headers=auth)
    client.post("/api/v1/projects/OTH/items", json={"title": "elders"}, headers=auth)
    r = client.patch("/api/v1/items/SOS-1", json={"parent": "OTH-1"}, headers=auth)
    assert r.status_code == 400


def test_create_with_cross_project_parent_400(client, auth, project):
    client.post("/api/v1/projects", json={"key": "OTH", "name": "Other"}, headers=auth)
    client.post("/api/v1/projects/OTH/items", json={"title": "elders"}, headers=auth)
    r = client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "kind", "parent": "OTH-1"},
        headers=auth,
    )
    assert r.status_code == 400


# --- Validatie: lege titel + tegenstrijdige relatie ------------------------


def test_patch_empty_title_422(client, auth, project):
    r = client.patch("/api/v1/items/SOS-1", json={"title": ""}, headers=auth)
    assert r.status_code == 422


def test_contradictory_blocks_409(client, auth, project):
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-2"},
        headers=auth,
    )
    # De omgekeerde richting (SOS-2 blokkeert SOS-1) is tegenstrijdig.
    r = client.post(
        "/api/v1/items/SOS-2/relations",
        json={"type": "blocks", "target": "SOS-1"},
        headers=auth,
    )
    assert r.status_code == 409


def test_contradictory_duplicate_409(client, auth, project):
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "duplicate_of", "target": "SOS-2"},
        headers=auth,
    )
    r = client.post(
        "/api/v1/items/SOS-2/relations",
        json={"type": "duplicate_of", "target": "SOS-1"},
        headers=auth,
    )
    assert r.status_code == 409


# --- Transactie: rollback bij fout halverwege ------------------------------


def test_patch_rolls_back_on_bad_label(client, auth, conn, project):
    # Titel-wijziging + onbekend label in één PATCH: het label faalt (400),
    # dus de titel mag ook niet zijn opgeslagen.
    r = client.patch(
        "/api/v1/items/SOS-1",
        json={"title": "nieuwe titel", "labels": ["bestaat-niet"]},
        headers=auth,
    )
    assert r.status_code == 400
    item = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert item["title"] == "x"  # ongewijzigd — rollback


def test_patch_rolls_back_leaves_no_event(client, auth, project):
    client.patch(
        "/api/v1/items/SOS-1",
        json={"priority": "high", "labels": ["bestaat-niet"]},
        headers=auth,
    )
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert [e["type"] for e in events] == ["item.created"]
