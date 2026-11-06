"""Eigen instellingen: GET/PATCH /users/me/settings (BETON-49)."""

from __future__ import annotations


def test_get_settings_defaults(client, auth):
    r = client.get("/api/v1/users/me/settings", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["handle"] == "person"
    assert body["webhook_url"] is None
    assert body["has_webhook_secret"] is False
    assert body["subscribe_all"] is False
    assert body["telegram_chat_id"] is None
    assert body["active"] is True
    assert body["description"] is None


def test_get_settings_echoes_description(client, auth):
    # description hoort bij de eigen instellingen (BETON-173): het paneel leest
    # 'm hier, dus de GET moet de zojuist opgeslagen waarde teruggeven.
    client.patch(
        "/api/v1/users/me/settings", json={"description": "Product owner."}, headers=auth
    )
    r = client.get("/api/v1/users/me/settings", headers=auth)
    assert r.status_code == 200
    assert r.json()["description"] == "Product owner."


def test_patch_settings_updates_webhook(client, auth):
    r = client.patch(
        "/api/v1/users/me/settings",
        json={"webhook_url": "https://example.invalid/hook", "webhook_secret": "s3cret"},
        headers=auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["webhook_url"] == "https://example.invalid/hook"
    assert body["has_webhook_secret"] is True
    # Het geheim zelf lekt nooit in de response.
    assert "webhook_secret" not in body


def test_patch_settings_partial_leaves_other_fields(client, auth):
    client.patch(
        "/api/v1/users/me/settings", json={"subscribe_all": True}, headers=auth
    )
    r = client.patch(
        "/api/v1/users/me/settings", json={"telegram_chat_id": "12345"}, headers=auth
    )
    body = r.json()
    assert body["subscribe_all"] is True
    assert body["telegram_chat_id"] == "12345"


def test_settings_require_auth(client):
    r = client.get("/api/v1/users/me/settings")
    assert r.status_code == 401


def test_agent_can_patch_own_description(client, conn, auth):
    """BETON-97: een agent kan zijn eigen description self-service aanpassen."""
    from betonning.repo import users as users_repo

    _, agent_key = users_repo.create(
        conn, handle="lobke", display_name="Lobke", kind="agent"
    )
    agent_auth = {"Authorization": f"Bearer {agent_key}"}

    r = client.patch(
        "/api/v1/users/me/settings",
        json={"description": "Frontend-specialist."},
        headers=agent_auth,
    )
    assert r.status_code == 200

    # Zichtbaar op de eigen user via /me...
    me = client.get("/api/v1/me", headers=agent_auth).json()
    assert me["handle"] == "lobke"
    assert me["description"] == "Frontend-specialist."

    # ...en via /users, zonder een andere user te raken.
    users = {u["handle"]: u for u in client.get("/api/v1/users", headers=auth).json()}
    assert users["lobke"]["description"] == "Frontend-specialist."
    assert users["person"]["description"] is None


# --- Bezorgkanaal is mensenwerk (BETON-378) --------------------------------


def _agent_auth(conn, handle="lobke"):
    from betonning.repo import users as users_repo

    _, key = users_repo.create(conn, handle=handle, display_name=handle, kind="agent")
    return {"Authorization": f"Bearer {key}"}


def test_agent_cannot_set_own_webhook_url(client, conn):
    """Een agent die zijn eigen webhook zet, kiest waar de server naartoe
    verbindt én wie andermans payloads meeleest (BETON-378)."""
    agent_auth = _agent_auth(conn)
    r = client.patch(
        "/api/v1/users/me/settings",
        json={"webhook_url": "https://evil.invalid/hook"},
        headers=agent_auth,
    )
    assert r.status_code == 403

    # ...en er is niets opgeslagen.
    settings = client.get("/api/v1/users/me/settings", headers=agent_auth).json()
    assert settings["webhook_url"] is None


def test_agent_cannot_clear_own_webhook_url(client, conn):
    """Ook een lege waarde is een wijziging van het kanaal → 403, niet stilweg
    genegeerd."""
    agent_auth = _agent_auth(conn)
    r = client.patch(
        "/api/v1/users/me/settings", json={"webhook_url": None}, headers=agent_auth
    )
    assert r.status_code == 403


def test_agent_cannot_set_own_webhook_secret_or_telegram(client, conn):
    agent_auth = _agent_auth(conn)
    for field, value in (("webhook_secret", "s3cret"), ("telegram_chat_id", "42")):
        r = client.patch(
            "/api/v1/users/me/settings", json={field: value}, headers=agent_auth
        )
        assert r.status_code == 403, field


def test_agent_keeps_own_non_channel_settings(client, conn):
    """subscribe_all/description blijven self-service voor een agent."""
    agent_auth = _agent_auth(conn)
    r = client.patch(
        "/api/v1/users/me/settings",
        json={"subscribe_all": True, "description": "Docs."},
        headers=agent_auth,
    )
    assert r.status_code == 200
    assert r.json()["subscribe_all"] is True
    assert r.json()["description"] == "Docs."


def test_human_can_still_set_own_channel(client, auth):
    """De mens zet zijn eigen kanaal gewoon — de poort geldt alleen voor agents."""
    r = client.patch(
        "/api/v1/users/me/settings",
        json={"webhook_url": "https://example.invalid/hook", "telegram_chat_id": "42"},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["webhook_url"] == "https://example.invalid/hook"
    assert r.json()["telegram_chat_id"] == "42"


def test_human_own_webhook_url_is_validated(client, auth):
    r = client.patch(
        "/api/v1/users/me/settings",
        json={"webhook_url": "http://127.0.0.1:8000/hook"},
        headers=auth,
    )
    assert r.status_code == 422
