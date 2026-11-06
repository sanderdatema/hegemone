"""Labels: CRUD per project + koppelen aan items via PATCH + filtering."""

from __future__ import annotations

import pytest


@pytest.fixture
def project(project, client, auth):
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    return project


def test_create_and_list_labels(client, auth, project):
    r = client.post(
        "/api/v1/projects/SOS/labels", json={"name": "opus", "color": "#ff0000"}, headers=auth
    )
    assert r.status_code == 201
    labels = client.get("/api/v1/projects/SOS/labels", headers=auth).json()
    assert [label_entry["name"] for label_entry in labels] == ["complex", "opus", "routine", "standaard"]


def test_duplicate_label_409(client, auth, project):
    client.post("/api/v1/projects/SOS/labels", json={"name": "opus"}, headers=auth)
    r = client.post("/api/v1/projects/SOS/labels", json={"name": "opus"}, headers=auth)
    assert r.status_code == 409


def test_delete_label(client, auth, project):
    client.post("/api/v1/projects/SOS/labels", json={"name": "opus"}, headers=auth)
    assert client.delete("/api/v1/projects/SOS/labels/opus", headers=auth).status_code == 204
    assert {label_entry["name"] for label_entry in client.get("/api/v1/projects/SOS/labels", headers=auth).json()} == {"routine", "standaard", "complex"}


def test_delete_unknown_label_404(client, auth, project):
    assert client.delete("/api/v1/projects/SOS/labels/ghost", headers=auth).status_code == 404


def test_assign_labels_to_item(client, auth, project):
    client.post("/api/v1/projects/SOS/labels", json={"name": "opus"}, headers=auth)
    client.post("/api/v1/projects/SOS/labels", json={"name": "bug"}, headers=auth)
    r = client.patch("/api/v1/items/SOS-1", json={"labels": ["opus", "bug"]}, headers=auth)
    assert r.status_code == 200
    assert sorted(r.json()["labels"]) == ["bug", "opus"]


def test_replace_labels(client, auth, project):
    client.post("/api/v1/projects/SOS/labels", json={"name": "opus"}, headers=auth)
    client.post("/api/v1/projects/SOS/labels", json={"name": "bug"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"labels": ["opus", "bug"]}, headers=auth)
    r = client.patch("/api/v1/items/SOS-1", json={"labels": ["opus"]}, headers=auth)
    assert r.json()["labels"] == ["opus"]


def test_clear_labels(client, auth, project):
    client.post("/api/v1/projects/SOS/labels", json={"name": "opus"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"labels": ["opus"]}, headers=auth)
    r = client.patch("/api/v1/items/SOS-1", json={"labels": []}, headers=auth)
    assert r.json()["labels"] == []


def test_assign_unknown_label_400(client, auth, project):
    r = client.patch("/api/v1/items/SOS-1", json={"labels": ["ghost"]}, headers=auth)
    assert r.status_code == 400


def test_filter_items_by_label(client, auth, project):
    client.post("/api/v1/projects/SOS/labels", json={"name": "opus"}, headers=auth)
    client.post("/api/v1/projects/SOS/items", json={"title": "y"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"labels": ["opus"]}, headers=auth)
    rows = client.get("/api/v1/projects/SOS/items?label=opus", headers=auth).json()
    assert [r["ref"] for r in rows] == ["SOS-1"]


def test_create_item_with_labels(client, auth, project):
    """BETON-188: labels direct meegeven bij het aanmaken van een ticket."""
    client.post("/api/v1/projects/SOS/labels", json={"name": "opus"}, headers=auth)
    client.post("/api/v1/projects/SOS/labels", json={"name": "bug"}, headers=auth)
    r = client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "nieuw ticket", "labels": ["opus", "bug"]},
        headers=auth,
    )
    assert r.status_code == 201
    assert sorted(r.json()["labels"]) == ["bug", "opus"]


def test_create_item_without_labels(client, auth, project):
    r = client.post("/api/v1/projects/SOS/items", json={"title": "geen labels"}, headers=auth)
    assert r.status_code == 201
    assert r.json()["labels"] == []


def test_create_item_with_unknown_label_400(client, auth, project):
    r = client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "x", "labels": ["ghost"]},
        headers=auth,
    )
    assert r.status_code == 400


@pytest.mark.parametrize("name", ["Kind/Bug", "Stream Deck/XL"])
def test_label_with_slash_roundtrip(client, auth, project, name):
    """BETON-449: een `/` in de naam gaf 405 op delete."""
    from urllib.parse import quote

    client.post("/api/v1/projects/SOS/labels", json={"name": name}, headers=auth)
    path = quote(name, safe="")
    r = client.post(f"/api/v1/items/SOS-1/labels/{path}", headers=auth)
    assert r.status_code == 201
    assert r.json()["labels"] == [name]
    r = client.delete(f"/api/v1/items/SOS-1/labels/{path}", headers=auth)
    assert r.status_code == 200
    assert r.json()["labels"] == []
    assert client.delete(f"/api/v1/projects/SOS/labels/{path}", headers=auth).status_code == 204
    assert {label_entry["name"] for label_entry in client.get("/api/v1/projects/SOS/labels", headers=auth).json()} == {"routine", "standaard", "complex"}
    # ook ongeëncodeerd
    client.post("/api/v1/projects/SOS/labels", json={"name": name}, headers=auth)
    assert client.delete(f"/api/v1/projects/SOS/labels/{name}", headers=auth).status_code == 204


def test_patch_label_color(client, auth, project):
    client.post("/api/v1/projects/SOS/labels", json={"name": "opus"}, headers=auth)
    r = client.patch("/api/v1/projects/SOS/labels/opus", json={"color": "#e74c3c"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["color"] == "#e74c3c"
    labels = client.get("/api/v1/projects/SOS/labels", headers=auth).json()
    assert next(label_entry for label_entry in labels if label_entry["name"] == "opus")["color"] == "#e74c3c"


def test_patch_label_color_with_slash_in_name(client, auth, project):
    client.post("/api/v1/projects/SOS/labels", json={"name": "Kind/Bug"}, headers=auth)
    r = client.patch(
        "/api/v1/projects/SOS/labels/Kind%2FBug", json={"color": "#112233"}, headers=auth
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Kind/Bug"
    assert r.json()["color"] == "#112233"


def test_patch_label_color_rejects_non_hex(client, auth, project):
    client.post("/api/v1/projects/SOS/labels", json={"name": "opus"}, headers=auth)
    r = client.patch("/api/v1/projects/SOS/labels/opus", json={"color": "rood"}, headers=auth)
    assert r.status_code == 422


def test_patch_unknown_label_404(client, auth, project):
    r = client.patch("/api/v1/projects/SOS/labels/ghost", json={"color": "#112233"}, headers=auth)
    assert r.status_code == 404


def test_patch_label_color_requires_auth(client, project):
    assert client.patch("/api/v1/projects/SOS/labels/opus", json={"color": "#112233"}).status_code == 401
