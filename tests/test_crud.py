"""Fase B — beheer-endpoints: relatie/comment verwijderen, archiveren, labels."""

from __future__ import annotations

import pytest

from betonning.repo import users as users_repo


@pytest.fixture
def project(project, client, auth):
    for _ in range(3):
        client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    client.post("/api/v1/projects/SOS/labels", json={"name": "bug"}, headers=auth)
    client.post("/api/v1/projects/SOS/labels", json={"name": "ui"}, headers=auth)
    return project


# --- Relaties verwijderen --------------------------------------------------


def test_delete_relation_removes_both_directions(client, auth, project):
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-2"},
        headers=auth,
    )
    r = client.request(
        "DELETE",
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-2"},
        headers=auth,
    )
    assert r.status_code == 200
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["relations"]["blocks"] == []
    assert client.get("/api/v1/items/SOS-2", headers=auth).json()["relations"]["blocked_by"] == []


def test_delete_relation_from_reverse_side(client, auth, project):
    # Aangemaakt als blocked_by, verwijderd via de omgekeerde verwoording.
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocked_by", "target": "SOS-2"},
        headers=auth,
    )
    r = client.request(
        "DELETE",
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocked_by", "target": "SOS-2"},
        headers=auth,
    )
    assert r.status_code == 200
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["relations"]["blocked_by"] == []


def test_delete_missing_relation_404(client, auth, project):
    r = client.request(
        "DELETE",
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-2"},
        headers=auth,
    )
    assert r.status_code == 404


def test_delete_relation_writes_event(client, auth, project):
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-2"},
        headers=auth,
    )
    client.request(
        "DELETE",
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-2"},
        headers=auth,
    )
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert events[-1]["type"] == "relation.deleted"


# --- Comments bewerken/verwijderen -----------------------------------------


def _comment(client, auth, ref, body):
    return client.post(f"/api/v1/items/{ref}/comments", json={"body_md": body}, headers=auth)


def test_edit_own_comment(client, auth, project):
    cid = _comment(client, auth, "SOS-1", "eerste").json()["id"]
    r = client.patch(
        f"/api/v1/items/SOS-1/comments/{cid}", json={"body_md": "aangepast"}, headers=auth
    )
    assert r.status_code == 200
    assert r.json()["body_md"] == "aangepast"
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert detail["comments"][0]["body_md"] == "aangepast"


def test_delete_own_comment(client, auth, project):
    cid = _comment(client, auth, "SOS-1", "weg").json()["id"]
    r = client.delete(f"/api/v1/items/SOS-1/comments/{cid}", headers=auth)
    assert r.status_code == 204
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["comments"] == []


def test_cannot_edit_other_users_comment(client, auth, conn, project):
    cid = _comment(client, auth, "SOS-1", "van person").json()["id"]
    _, other_key = users_repo.create(conn, handle="mallory", display_name="M", kind="agent")
    other = {"Authorization": f"Bearer {other_key}"}
    r = client.patch(
        f"/api/v1/items/SOS-1/comments/{cid}", json={"body_md": "hack"}, headers=other
    )
    assert r.status_code == 403
    r = client.delete(f"/api/v1/items/SOS-1/comments/{cid}", headers=other)
    assert r.status_code == 403


def test_edit_comment_wrong_item_404(client, auth, project):
    cid = _comment(client, auth, "SOS-1", "hoi").json()["id"]
    r = client.patch(
        f"/api/v1/items/SOS-2/comments/{cid}", json={"body_md": "x"}, headers=auth
    )
    assert r.status_code == 404


def test_agent_cannot_edit_own_comment_on_closed_item(client, auth, conn, project):
    """BETON-305: een bewerking kan nieuwe mentions toevoegen en dus opnieuw
    fanouten — dezelfde ruis als een nieuwe comment. Geldt ook voor de eigen
    comment van een agent, en zonder sluiter-uitzondering (die geldt alleen
    voor de afsluit-comment zelf, niet voor het wijzigen achteraf)."""
    _, key = users_repo.create(conn, handle="lobke", display_name="Lobke", kind="agent")
    conn.commit()
    agent = {"Authorization": f"Bearer {key}"}
    cid = _comment(client, agent, "SOS-1", "voor het sluiten").json()["id"]
    client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=auth)

    r = client.patch(
        f"/api/v1/items/SOS-1/comments/{cid}", json={"body_md": "toch anders"}, headers=agent
    )
    assert r.status_code == 409


def test_human_can_edit_own_comment_on_closed_item(client, auth, project):
    cid = _comment(client, auth, "SOS-1", "van person").json()["id"]
    client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=auth)
    r = client.patch(
        f"/api/v1/items/SOS-1/comments/{cid}", json={"body_md": "toch anders"}, headers=auth
    )
    assert r.status_code == 200


# --- Archiveren ------------------------------------------------------------


def test_archive_hides_from_list_and_search(client, auth, project):
    client.patch("/api/v1/items/SOS-1", json={"title": "vindbaar-token"}, headers=auth)
    r = client.delete("/api/v1/items/SOS-1", headers=auth)
    assert r.status_code == 204
    refs = [i["ref"] for i in client.get("/api/v1/projects/SOS/items", headers=auth).json()]
    assert "SOS-1" not in refs
    found = client.get("/api/v1/search?q=vindbaar-token", headers=auth).json()
    assert found == []


def test_archived_still_reachable_by_ref(client, auth, project):
    client.delete("/api/v1/items/SOS-1", headers=auth)
    r = client.get("/api/v1/items/SOS-1", headers=auth)
    assert r.status_code == 200
    assert r.json()["archived_at"] is not None


def test_archived_opt_in_visible(client, auth, project):
    client.delete("/api/v1/items/SOS-1", headers=auth)
    refs = [
        i["ref"]
        for i in client.get("/api/v1/projects/SOS/items?archived=true", headers=auth).json()
    ]
    assert "SOS-1" in refs


def test_archive_writes_event(client, auth, project):
    client.delete("/api/v1/items/SOS-1", headers=auth)
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert events[-1]["type"] == "item.archived"


# --- Herstel uit archief (BETON-59) ---------------------------------------


def test_restore_unarchives_item(client, auth, project):
    """POST /restore haalt archived_at weg en zet het item terug op het board."""
    client.delete("/api/v1/items/SOS-1", headers=auth)
    r = client.post("/api/v1/items/SOS-1/restore", headers=auth)
    assert r.status_code == 200
    assert r.json()["archived_at"] is None
    refs = [i["ref"] for i in client.get("/api/v1/projects/SOS/items", headers=auth).json()]
    assert "SOS-1" in refs


def test_restore_writes_event(client, auth, project):
    client.delete("/api/v1/items/SOS-1", headers=auth)
    client.post("/api/v1/items/SOS-1/restore", headers=auth)
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert events[-1]["type"] == "item.restored"


def test_restore_non_archived_is_noop(client, auth, project):
    """Een niet-gearchiveerd item herstellen doet niets en schrijft geen event."""
    before = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    r = client.post("/api/v1/items/SOS-1/restore", headers=auth)
    assert r.status_code == 200
    assert r.json()["archived_at"] is None
    after = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert len(after) == len(before)


def test_restore_unknown_404(client, auth, project):
    assert client.post("/api/v1/items/SOS-999/restore", headers=auth).status_code == 404


def test_restore_requires_auth(client, project):
    assert client.post("/api/v1/items/SOS-1/restore").status_code == 401


# --- Hard delete (BETON-19) ------------------------------------------------


def test_hard_delete_removes_item_permanently(client, auth, project):
    client.patch("/api/v1/items/SOS-1", json={"title": "weg-token"}, headers=auth)
    r = client.delete("/api/v1/items/SOS-1?hard=true", headers=auth)
    assert r.status_code == 204
    # Onvindbaar per ref, ook niet met ?archived=true, en niet in zoek.
    assert client.get("/api/v1/items/SOS-1", headers=auth).status_code == 404
    refs = [
        i["ref"]
        for i in client.get("/api/v1/projects/SOS/items?archived=true", headers=auth).json()
    ]
    assert "SOS-1" not in refs
    assert client.get("/api/v1/search?q=weg-token", headers=auth).json() == []


def test_hard_delete_detaches_children(client, auth, project):
    # SOS-2 wordt subtaak van SOS-1; SOS-1 hard verwijderen mag niet blokkeren
    # op de parent-FK en laat SOS-2 top-level achter.
    client.patch("/api/v1/items/SOS-2", json={"parent": "SOS-1"}, headers=auth)
    r = client.delete("/api/v1/items/SOS-1?hard=true", headers=auth)
    assert r.status_code == 204
    detail = client.get("/api/v1/items/SOS-2", headers=auth)
    assert detail.status_code == 200
    assert detail.json()["parent"] is None


def test_hard_delete_writes_audit_event_without_item(client, auth, conn, project):
    import json

    client.delete("/api/v1/items/SOS-1?hard=true", headers=auth)
    # Het item is weg, dus het spoor staat als event met item_id=NULL in de db.
    row = conn.execute(
        "SELECT payload FROM events WHERE type = 'item.deleted' AND item_id IS NULL"
    ).fetchone()
    assert row is not None
    assert json.loads(row["payload"])["ref"] == "SOS-1"


def test_hard_delete_missing_404(client, auth, project):
    assert client.delete("/api/v1/items/SOS-999?hard=true", headers=auth).status_code == 404


def test_hard_delete_forbidden_for_agent(client, auth, conn, project):
    """BETON-377: onherroepelijk verwijderen is mens-only. Archiveren mag wel."""
    _, agent_key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent", agent_type="coding"
    )
    conn.commit()
    agent_auth = {"Authorization": f"Bearer {agent_key}"}
    r = client.delete("/api/v1/items/SOS-1?hard=true", headers=agent_auth)
    assert r.status_code == 403
    # Item bestaat nog gewoon.
    assert client.get("/api/v1/items/SOS-1", headers=auth).status_code == 200


def test_archive_allowed_for_agent(client, auth, conn, project):
    """Archiveren (zonder hard=true) blijft voor agents toegestaan."""
    _, agent_key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent", agent_type="coding"
    )
    conn.commit()
    agent_auth = {"Authorization": f"Bearer {agent_key}"}
    r = client.delete("/api/v1/items/SOS-1", headers=agent_auth)
    assert r.status_code == 204
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["archived_at"] is not None


# --- Labels toevoegen/verwijderen ------------------------------------------


def test_add_and_remove_label(client, auth, project):
    r = client.post("/api/v1/items/SOS-1/labels/bug", headers=auth)
    assert r.status_code == 201
    assert r.json()["labels"] == ["bug"]
    r = client.post("/api/v1/items/SOS-1/labels/ui", headers=auth)
    assert r.json()["labels"] == ["bug", "ui"]
    r = client.delete("/api/v1/items/SOS-1/labels/bug", headers=auth)
    assert r.json()["labels"] == ["ui"]


def test_add_label_is_idempotent(client, auth, project):
    client.post("/api/v1/items/SOS-1/labels/bug", headers=auth)
    r = client.post("/api/v1/items/SOS-1/labels/bug", headers=auth)
    assert r.json()["labels"] == ["bug"]


def test_add_unknown_label_400(client, auth, project):
    r = client.post("/api/v1/items/SOS-1/labels/bestaat-niet", headers=auth)
    assert r.status_code == 400


def test_label_change_writes_event(client, auth, project):
    client.post("/api/v1/items/SOS-1/labels/bug", headers=auth)
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert events[-1]["type"] == "item.updated"
    assert events[-1]["payload"]["labels"] == {"from": [], "to": ["bug"]}


def test_endpoints_require_auth(client, project):
    assert client.delete("/api/v1/items/SOS-1").status_code == 401
    assert client.post("/api/v1/items/SOS-1/labels/bug").status_code == 401
