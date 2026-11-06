"""Comments: plaatsen, terugzien in item-detail, event geschreven."""

from __future__ import annotations

import pytest


@pytest.fixture
def project(project, client, auth):
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    return project


def test_add_comment(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "hoi **daar**"}, headers=auth
    )
    assert r.status_code == 201
    body = r.json()
    assert body["body_md"] == "hoi **daar**"
    assert body["author"] == "person"


def test_comment_appears_in_detail(client, auth, project):
    client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "eerste"}, headers=auth
    )
    client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "tweede"}, headers=auth
    )
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert [c["body_md"] for c in detail["comments"]] == ["eerste", "tweede"]


def test_comment_writes_event(client, auth, project):
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "x"}, headers=auth)
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert events[-1]["type"] == "comment.created"


def test_empty_comment_rejected(client, auth, project):
    r = client.post("/api/v1/items/SOS-1/comments", json={"body_md": ""}, headers=auth)
    assert r.status_code == 422


def test_comment_requires_auth(client, project):
    assert (
        client.post("/api/v1/items/SOS-1/comments", json={"body_md": "x"}).status_code
        == 401
    )


def test_comment_unknown_item_404(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-999/comments", json={"body_md": "x"}, headers=auth
    )
    assert r.status_code == 404


# --- Idempotency-vangnet (BETON-217) ----------------------------------------


def test_duplicate_comment_within_window_is_idempotent(client, auth, project):
    """Een double-submit (zelfde auteur, identieke body, binnen ~10s) plaatst
    géén tweede comment: de bestaande komt terug, zonder extra event — dat
    voorkomt dubbele agent-fanout (BRAND-150: 4 identieke comments in 12ms)."""
    r1 = client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "dubbelklik"}, headers=auth
    )
    r2 = client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "dubbelklik"}, headers=auth
    )
    assert r1.json()["id"] == r2.json()["id"]
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert [c["body_md"] for c in detail["comments"]] == ["dubbelklik"]
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert sum(1 for e in events if e["type"] == "comment.created") == 1


def test_different_body_within_window_creates_new_comment(client, auth, project):
    client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "eerste"}, headers=auth
    )
    r = client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "tweede"}, headers=auth
    )
    assert r.status_code == 201
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert len(detail["comments"]) == 2


def test_same_body_from_other_author_creates_new_comment(client, auth, conn, project):
    """De dedup geldt per auteur — een tweede user mag exact hetzelfde zeggen."""
    from betonning.repo import users as users_repo

    _, key = users_repo.create(conn, handle="lobke", display_name="Lobke", kind="agent")
    conn.commit()
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "eens"}, headers=auth)
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "eens"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 201
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert len(detail["comments"]) == 2


# --- BETON-305: agents reageren niet meer op een gesloten item -------------


def _agent_key(conn, handle):
    from betonning.repo import users as users_repo

    _, key = users_repo.create(conn, handle=handle, display_name=handle, kind="agent")
    conn.commit()
    return key


def _agent_headers(conn, handle):
    return {"Authorization": f"Bearer {_agent_key(conn, handle)}"}


def test_agent_cannot_comment_on_done_item(client, auth, conn, project):
    client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=auth)
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "hallo"},
        headers=_agent_headers(conn, "lobke"),
    )
    assert r.status_code == 409


def test_agent_cannot_comment_on_cancelled_item(client, auth, conn, project):
    client.patch("/api/v1/items/SOS-1", json={"state": "cancelled"}, headers=auth)
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "hallo"},
        headers=_agent_headers(conn, "lobke"),
    )
    assert r.status_code == 409


def test_agent_cannot_comment_on_future_deferred_item(client, auth, conn, project):
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2999-01-01"}, headers=auth
    )
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "hallo"},
        headers=_agent_headers(conn, "lobke"),
    )
    assert r.status_code == 409


def test_agent_can_comment_on_past_deferred_item(client, auth, conn, project):
    """Een verstreken deferred_until blokkeert niet, ook niet als de state zelf
    nog niet is teruggevlipt door de reactivate-self-heal."""
    conn.execute(
        "UPDATE items SET deferred_until = '2000-01-01T00:00:00.000Z' "
        "WHERE id = (SELECT id FROM items WHERE seq = 1)"
    )
    conn.commit()
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "hallo"},
        headers=_agent_headers(conn, "lobke"),
    )
    assert r.status_code == 201


def test_agent_can_comment_on_backlog_item(client, auth, conn, project):
    """`blocks_work`-states (backlog/triage/blocked) blokkeren niet — dat is
    een ander mechanisme (uitvoeringsbeleid), geen gesloten ticket."""
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "hallo"},
        headers=_agent_headers(conn, "lobke"),
    )
    assert r.status_code == 201


def test_human_can_comment_on_done_item(client, auth, project):
    client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=auth)
    r = client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "toch nog iets"}, headers=auth
    )
    assert r.status_code == 201


def test_closing_agent_may_still_place_one_comment(client, conn, project):
    """De agent die het item zelf op done zette mag zijn afsluit-comment nog
    plaatsen (Persons uitzondering) — maar geen tweede."""
    headers = _agent_headers(conn, "lobke")
    client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=headers)

    r1 = client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "klaar"}, headers=headers
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "nog iets"}, headers=headers
    )
    assert r2.status_code == 409


def test_other_agent_still_blocked_after_closer_commented(client, conn, project):
    headers = _agent_headers(conn, "lobke")
    client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=headers)
    client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "klaar"}, headers=headers
    )

    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "ik ook nog wat"},
        headers=_agent_headers(conn, "joop"),
    )
    assert r.status_code == 409


def test_reopen_allows_agent_comment_again(client, auth, conn, project):
    client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"state": "todo"}, headers=auth)
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "heropend, want..."},
        headers=_agent_headers(conn, "lobke"),
    )
    assert r.status_code == 201


def test_item_without_state_not_blocked(client, auth, conn, project):
    conn.execute(
        "UPDATE items SET state_id = NULL WHERE id = (SELECT id FROM items WHERE seq = 1)"
    )
    conn.commit()
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "hallo"},
        headers=_agent_headers(conn, "lobke"),
    )
    assert r.status_code == 201
