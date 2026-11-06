"""Media-toegang (BETON-202/383): media-token sign/verify, het /media-cookie
endpoint en de user-binding (intrekbaar bij key-rotatie/deactivatie)."""

from __future__ import annotations

import pytest

from betonning import security
from betonning.repo import users as users_repo

FRAGMENT = "abc123def4567890"


# --- security.sign/verify_media_token -------------------------------------


def test_media_token_roundtrip_returns_user_and_fragment():
    token = security.sign_media_token(2_000_000_000, 7, FRAGMENT)
    assert security.verify_media_token(token, now=1_000_000_000) == (7, FRAGMENT)


def test_media_token_expired():
    token = security.sign_media_token(1_000, 7, FRAGMENT)
    assert security.verify_media_token(token, now=2_000) is None


def test_media_token_tampered_signature():
    token = security.sign_media_token(2_000_000_000, 7, FRAGMENT)
    msg, _, _sig = token.rpartition(".")
    assert security.verify_media_token(f"{msg}.{'0' * 64}", now=1_000_000_000) is None


def test_media_token_tampered_expiry_invalidates_signature():
    # De expiry naar de toekomst schuiven breekt de handtekening (HMAC dekt exp).
    token = security.sign_media_token(1_000, 7, FRAGMENT)
    _msg, _, sig = token.rpartition(".")
    forged = f"9999999999.7.{FRAGMENT}.{sig}"
    assert security.verify_media_token(forged, now=2_000) is None


def test_media_token_swapped_user_id_invalidates_signature():
    # Iemand anders' id in het token zetten breekt de handtekening (BETON-383).
    token = security.sign_media_token(2_000_000_000, 7, FRAGMENT)
    _msg, _, sig = token.rpartition(".")
    forged = f"2000000000.99.{FRAGMENT}.{sig}"
    assert security.verify_media_token(forged, now=1_000_000_000) is None


def test_old_two_part_token_format_is_rejected():
    # Vóór BETON-383 was het token `<exp>.<hmac>`. Dat formaat wordt niet meer
    # geaccepteerd; bestaande cookies vallen om (de UI herzet ze bij boot).
    msg = "2000000000"
    old = f"{msg}.{security._media_sig(msg)}"
    assert security.verify_media_token(old, now=1_000_000_000) is None


def test_media_token_garbage():
    assert security.verify_media_token(None) is None
    assert security.verify_media_token("") is None
    assert security.verify_media_token("geen-punt") is None
    assert security.verify_media_token("x.y") is None
    assert security.verify_media_token("a.b.c.d") is None


# --- POST /media-cookie ----------------------------------------------------


def test_media_cookie_requires_auth(client):
    assert client.post("/api/v1/media-cookie").status_code == 401


def test_media_cookie_sets_httponly_samesite_cookie(client, auth):
    r = client.post("/api/v1/media-cookie", headers=auth)
    assert r.status_code == 200
    set_cookie = r.headers["set-cookie"]
    assert "bt_media=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=strict" in set_cookie.lower()
    assert "path=/api/v1" in set_cookie.lower()
    # Over http (geen X-Forwarded-Proto) géén Secure-vlag, anders werkt LAN niet.
    assert "secure" not in set_cookie.lower()


def test_media_cookie_secure_when_forwarded_https(client, auth):
    r = client.post(
        "/api/v1/media-cookie",
        headers={**auth, "X-Forwarded-Proto": "https"},
    )
    assert r.status_code == 200
    assert "secure" in r.headers["set-cookie"].lower()


# --- Cookie-toegang is intrekbaar (BETON-383) ------------------------------


@pytest.fixture
def avatar_url(client, auth) -> str:
    """Een avatar op person, zodat er een media-route is om tegenaan te lopen."""
    png = b"\x89PNG\r\n\x1a\n fake"
    r = client.post(
        "/api/v1/users/person/avatar",
        files={"file": ("a.png", png, "image/png")},
        headers=auth,
    )
    assert r.status_code == 200
    return "/api/v1/users/person/avatar"


def test_cookie_grants_access_after_media_cookie(client, auth, avatar_url):
    assert client.get(avatar_url).status_code == 401
    assert client.post("/api/v1/media-cookie", headers=auth).status_code == 200
    assert client.get(avatar_url).status_code == 200


def test_cookie_stops_working_after_key_rotation(client, conn, auth, avatar_url):
    client.post("/api/v1/media-cookie", headers=auth)
    assert client.get(avatar_url).status_code == 200

    users_repo.rotate_api_key(conn, "person")
    conn.commit()
    # Het cookie draagt een fragment van de oude hash -> geen toegang meer.
    assert client.get(avatar_url).status_code == 401


def test_cookie_stops_working_after_deactivation(client, conn, auth, avatar_url):
    client.post("/api/v1/media-cookie", headers=auth)
    assert client.get(avatar_url).status_code == 200

    person = users_repo.get_by_handle(conn, "person")
    users_repo.deactivate(conn, person["id"])
    conn.commit()
    assert client.get(avatar_url).status_code == 401


def test_cookie_of_one_user_does_not_work_for_another(client, conn, auth, avatar_url):
    """Een gesmeed token met een ander user_id haalt niets uit: het fragment
    hoort bij die andere user en matcht diens hash niet."""
    users_repo.create(conn, handle="claude", display_name="C", kind="agent")
    conn.commit()
    claude = users_repo.get_by_handle(conn, "claude")
    person = users_repo.get_by_handle(conn, "person")

    token = security.sign_media_token(
        2_000_000_000, claude["id"], person["api_key_hash"][:16]
    )
    client.cookies.set("bt_media", token, path="/api/v1")
    assert client.get(avatar_url).status_code == 401


def test_expired_cookie_is_refused(client, conn, auth, avatar_url):
    person = users_repo.get_by_handle(conn, "person")
    token = security.sign_media_token(1_000, person["id"], person["api_key_hash"][:16])
    client.cookies.set("bt_media", token, path="/api/v1")
    assert client.get(avatar_url).status_code == 401


def test_bearer_path_is_unaffected(client, auth, avatar_url):
    # Agents/MCP halen bytes met hun Bearer op; dat pad verandert niet.
    assert client.get(avatar_url, headers=auth).status_code == 200


# --- POST /logout ----------------------------------------------------------


def test_logout_clears_the_media_cookie(client, auth):
    assert client.post("/api/v1/media-cookie", headers=auth).status_code == 200
    r = client.post("/api/v1/logout", headers=auth)
    assert r.status_code == 200
    set_cookie = r.headers["set-cookie"].lower()
    assert "bt_media=" in set_cookie
    assert "max-age=0" in set_cookie
    assert "path=/api/v1" in set_cookie


def test_logout_revokes_media_access(client, auth, avatar_url):
    client.post("/api/v1/media-cookie", headers=auth)
    assert client.get(avatar_url).status_code == 200
    client.post("/api/v1/logout", headers=auth)
    assert client.get(avatar_url).status_code == 401


def test_logout_requires_auth(client):
    assert client.post("/api/v1/logout").status_code == 401
