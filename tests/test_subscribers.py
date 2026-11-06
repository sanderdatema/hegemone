"""Subscribers-overzicht + per-item mute (BETON-245).

De fanout-doelgroep is afgeleid (assignee + eerdere participants + subscribe_all);
een mute filtert een user daaruit. We toetsen: mute → geen delivery, unmute →
weer wel, en de subscribers-union met muted-vlag.
"""

from __future__ import annotations

import pytest

from betonning.repo import users as users_repo


@pytest.fixture(autouse=True)
def _no_trigger_delay(monkeypatch):
    monkeypatch.setenv("BETONNING_TRIGGER_DELAY", "0")


def _deliveries_for(conn, handle):
    return conn.execute(
        "SELECT wd.* FROM webhook_deliveries wd JOIN users u ON u.id = wd.user_id "
        "WHERE u.handle = ? ORDER BY wd.id",
        (handle,),
    ).fetchall()


def _webhook_user(conn, handle, *, subscribe_all=False):
    _, key = users_repo.create(
        conn,
        handle=handle,
        display_name=handle,
        kind="agent",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s3cret",
        subscribe_all=subscribe_all,
    )
    return key


@pytest.fixture
def project(project, client, auth):
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    return project


# --- Mute grijpt in de fanout in -----------------------------------------


def test_mute_removes_assignee_from_fanout(client, auth, conn, project):
    """Kern van BETON-245: de gemute assignee krijgt geen delivery meer, terwijl
    hij dat zónder mute wél zou krijgen (discriminerende assertie)."""
    _webhook_user(conn, "hermes")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    # Baseline: een gewone comment (van iemand anders) bereikt de assignee. Wis
    # eerst de assign-delivery zodat de telling puur de comment-fanout is.
    conn.execute("DELETE FROM webhook_deliveries")
    conn.commit()
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "eerste"}, headers=auth)
    assert len(_deliveries_for(conn, "hermes")) == 1

    # Mute hermes op dit item.
    resp = client.post("/api/v1/items/SOS-1/subscribers/hermes/mute", headers=auth)
    assert resp.status_code == 204

    conn.execute("DELETE FROM webhook_deliveries")
    conn.commit()
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "tweede"}, headers=auth)
    assert _deliveries_for(conn, "hermes") == []


def test_unmute_restores_fanout(client, auth, conn, project):
    _webhook_user(conn, "hermes")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    client.post("/api/v1/items/SOS-1/subscribers/hermes/mute", headers=auth)
    resp = client.delete("/api/v1/items/SOS-1/subscribers/hermes/mute", headers=auth)
    assert resp.status_code == 204

    conn.execute("DELETE FROM webhook_deliveries")
    conn.commit()
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=auth)
    assert len(_deliveries_for(conn, "hermes")) == 1


def test_mute_removes_subscribe_all_user_from_fanout(client, auth, conn, project):
    """Ook een subscribe_all-meelezer valt uit de fanout als hij gemute is."""
    _webhook_user(conn, "triage", subscribe_all=True)
    client.post("/api/v1/items/SOS-1/subscribers/triage/mute", headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"priority": "high"}, headers=auth)
    assert _deliveries_for(conn, "triage") == []


def test_mute_is_per_item(client, auth, conn, project):
    """Muten op item A raakt de fanout van item B niet."""
    _webhook_user(conn, "hermes")
    client.post("/api/v1/projects/SOS/items", json={"title": "y"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    client.patch("/api/v1/items/SOS-2", json={"assignee": "hermes"}, headers=auth)
    client.post("/api/v1/items/SOS-1/subscribers/hermes/mute", headers=auth)

    conn.execute("DELETE FROM webhook_deliveries")
    conn.commit()
    client.post("/api/v1/items/SOS-2/comments", json={"body_md": "hoi"}, headers=auth)
    assert len(_deliveries_for(conn, "hermes")) == 1


# --- Subscribers-overzicht -----------------------------------------------


def test_subscribers_union_with_muted_flag(client, auth, conn, project):
    """De union bevat assignee + participants + subscribe_all; muted-vlag klopt."""
    users_repo.create(conn, handle="hermes", display_name="Hermes", kind="agent")
    users_repo.create(conn, handle="triage", display_name="Triage", kind="agent",
                      subscribe_all=True)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "hermes"}, headers=auth)
    # person is de maker (via auth) → participant.

    res = client.get("/api/v1/items/SOS-1/subscribers", headers=auth).json()
    subs = {s["handle"]: s["muted"] for s in res["subscribers"]}
    assert "hermes" in subs and "triage" in subs and "person" in subs
    assert all(v is False for v in subs.values())

    client.post("/api/v1/items/SOS-1/subscribers/hermes/mute", headers=auth)
    res = client.get("/api/v1/items/SOS-1/subscribers", headers=auth).json()
    subs = {s["handle"]: s["muted"] for s in res["subscribers"]}
    assert subs["hermes"] is True
    assert subs["triage"] is False


def test_mute_unknown_user_404(client, auth, conn, project):
    resp = client.post("/api/v1/items/SOS-1/subscribers/nobody/mute", headers=auth)
    assert resp.status_code == 404


def test_subscribers_requires_auth(client, project):
    assert client.get("/api/v1/items/SOS-1/subscribers").status_code == 401


def test_subscribers_unknown_item_404(client, auth, project):
    assert client.get("/api/v1/items/SOS-999/subscribers", headers=auth).status_code == 404


def test_agent_may_only_mute_itself(client, auth, conn, project):
    """Een agent dempt zichzelf (MCP `mute_item`), nooit een ander: anders
    haalt hij een mens of een andere agent stil uit de fanout."""
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    _, key = users_repo.create(conn, handle="lobke", display_name="Lobke", kind="agent")
    conn.commit()
    lobke = {"Authorization": f"Bearer {key}"}

    assert client.post("/api/v1/items/SOS-1/subscribers/person/mute",
                       headers=lobke).status_code == 403
    assert client.delete("/api/v1/items/SOS-1/subscribers/person/mute",
                         headers=lobke).status_code == 403
    assert client.post("/api/v1/items/SOS-1/subscribers/lobke/mute",
                       headers=lobke).status_code == 204
    assert client.delete("/api/v1/items/SOS-1/subscribers/lobke/mute",
                         headers=lobke).status_code == 204
