"""Milestones: CRUD per project + koppelen aan items."""

from __future__ import annotations

import pytest


@pytest.fixture
def project(project, client, auth):
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    return project


def test_create_and_list_milestones(client, auth, project):
    r = client.post(
        "/api/v1/projects/SOS/milestones", json={"name": "v1.4.0"}, headers=auth
    )
    assert r.status_code == 201
    assert r.json()["status"] == "open"
    rows = client.get("/api/v1/projects/SOS/milestones", headers=auth).json()
    assert [m["name"] for m in rows] == ["v1.4.0"]


def test_duplicate_milestone_409(client, auth, project):
    client.post("/api/v1/projects/SOS/milestones", json={"name": "v1.4.0"}, headers=auth)
    r = client.post("/api/v1/projects/SOS/milestones", json={"name": "v1.4.0"}, headers=auth)
    assert r.status_code == 409


def test_complete_milestone(client, auth, project):
    client.post("/api/v1/projects/SOS/milestones", json={"name": "v1.4.0"}, headers=auth)
    r = client.patch(
        "/api/v1/projects/SOS/milestones/v1.4.0", json={"status": "completed"}, headers=auth
    )
    assert r.json()["status"] == "completed"


def test_delete_milestone(client, auth, project):
    client.post("/api/v1/projects/SOS/milestones", json={"name": "v1.4.0"}, headers=auth)
    assert (
        client.delete("/api/v1/projects/SOS/milestones/v1.4.0", headers=auth).status_code == 204
    )
    assert client.get("/api/v1/projects/SOS/milestones", headers=auth).json() == []


def test_delete_milestone_unlinks_items(client, auth, project):
    """BETON-336: verwijderen mag geen verweesde items.milestone_id achterlaten."""
    client.post("/api/v1/projects/SOS/milestones", json={"name": "v1.4.0"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"milestone": "v1.4.0"}, headers=auth)

    assert (
        client.delete("/api/v1/projects/SOS/milestones/v1.4.0", headers=auth).status_code == 204
    )

    r = client.get("/api/v1/items/SOS-1", headers=auth)
    assert r.status_code == 200
    assert r.json()["milestone"] is None


def test_patch_unknown_milestone_404(client, auth, project):
    r = client.patch(
        "/api/v1/projects/SOS/milestones/ghost", json={"status": "completed"}, headers=auth
    )
    assert r.status_code == 404


def test_assign_milestone_to_item(client, auth, project):
    client.post("/api/v1/projects/SOS/milestones", json={"name": "v1.4.0"}, headers=auth)
    r = client.patch("/api/v1/items/SOS-1", json={"milestone": "v1.4.0"}, headers=auth)
    assert r.json()["milestone"] == "v1.4.0"


def test_milestones_require_auth(client, project):
    assert client.get("/api/v1/projects/SOS/milestones").status_code == 401


# --- BETON-63: voortgang + overdue ---------------------------------------


def test_milestone_progress_counts(client, auth, project):
    """De list-endpoint telt done/totaal per milestone (levende items; done =
    closed-group state) — in één gebatchte query."""
    client.post("/api/v1/projects/SOS/milestones", json={"name": "v1.4.0"}, headers=auth)
    # project-fixture maakt SOS-1; koppel + voeg twee items toe.
    client.patch("/api/v1/items/SOS-1", json={"milestone": "v1.4.0"}, headers=auth)
    client.post(
        "/api/v1/projects/SOS/items", json={"title": "b", "milestone": "v1.4.0"}, headers=auth
    )
    client.post(
        "/api/v1/projects/SOS/items", json={"title": "c", "milestone": "v1.4.0"}, headers=auth
    )
    client.patch("/api/v1/items/SOS-2", json={"state": "done"}, headers=auth)

    ms = client.get("/api/v1/projects/SOS/milestones", headers=auth).json()[0]
    assert ms["items_total"] == 3
    assert ms["items_done"] == 1


def test_milestone_progress_ignores_archived(client, auth, project):
    """Gearchiveerde items tellen niet mee in de milestone-voortgang."""
    client.post("/api/v1/projects/SOS/milestones", json={"name": "v1.4.0"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"milestone": "v1.4.0"}, headers=auth)
    client.post(
        "/api/v1/projects/SOS/items", json={"title": "b", "milestone": "v1.4.0"}, headers=auth
    )
    client.delete("/api/v1/items/SOS-2", headers=auth)  # archiveer

    ms = client.get("/api/v1/projects/SOS/milestones", headers=auth).json()[0]
    assert ms["items_total"] == 1


def test_milestone_empty_progress_zero(client, auth, project):
    client.post("/api/v1/projects/SOS/milestones", json={"name": "v9.0.0"}, headers=auth)
    ms = next(
        m
        for m in client.get("/api/v1/projects/SOS/milestones", headers=auth).json()
        if m["name"] == "v9.0.0"
    )
    assert ms["items_total"] == 0 and ms["items_done"] == 0


def test_compact_list_carries_milestone(client, auth, project):
    """De board-lijst (compact) draagt de milestone-naam zodat de kaart een
    milestone-chip kan tonen (BETON-63)."""
    client.post("/api/v1/projects/SOS/milestones", json={"name": "v1.4.0"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"milestone": "v1.4.0"}, headers=auth)
    items = client.get("/api/v1/projects/SOS/items", headers=auth).json()
    row = next(i for i in items if i["title"] == "x")
    assert row["milestone"] == "v1.4.0"


def test_list_filter_by_milestone(client, auth, project):
    """?milestone= filtert de lijst op milestone-naam (case-insensitief)."""
    client.post("/api/v1/projects/SOS/milestones", json={"name": "v1.4.0"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"milestone": "v1.4.0"}, headers=auth)
    client.post("/api/v1/projects/SOS/items", json={"title": "zonder ms"}, headers=auth)

    items = client.get(
        "/api/v1/projects/SOS/items?milestone=v1.4.0", headers=auth
    ).json()
    assert {i["title"] for i in items} == {"x"}


def test_milestone_overdue_flag(client, auth, project):
    """due_date in het verleden + niet-afgerond → overdue; afgerond → niet."""
    client.post(
        "/api/v1/projects/SOS/milestones",
        json={"name": "v1.0.0", "due_date": "2000-01-01"},
        headers=auth,
    )
    client.post(
        "/api/v1/projects/SOS/milestones",
        json={"name": "v2.0.0", "due_date": "2999-01-01"},
        headers=auth,
    )
    rows = {m["name"]: m for m in client.get("/api/v1/projects/SOS/milestones", headers=auth).json()}
    assert rows["v1.0.0"]["overdue"] is True
    assert rows["v2.0.0"]["overdue"] is False

    client.patch(
        "/api/v1/projects/SOS/milestones/v1.0.0", json={"status": "completed"}, headers=auth
    )
    rows = {m["name"]: m for m in client.get("/api/v1/projects/SOS/milestones", headers=auth).json()}
    assert rows["v1.0.0"]["overdue"] is False
