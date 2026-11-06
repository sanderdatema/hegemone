"""Avatar-upload per user/agent (BETON-71): upload → serve roundtrip,
whitelist/grootte, human-only, serialize-url, delete → terug naar initialen."""

from __future__ import annotations

import pytest

from betonning.repo import attachments as attachments_repo
from betonning.repo import users as users_repo

PNG = b"\x89PNG\r\n\x1a\n fake-avatar-bytes"


@pytest.fixture
def agent_key(conn) -> str:
    _, key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent"
    )
    conn.commit()
    return key


@pytest.fixture
def agent_auth(agent_key) -> dict:
    return {"Authorization": f"Bearer {agent_key}"}


def _upload(client, auth, handle, data=PNG, name="avatar.png", ctype="image/png"):
    return client.post(
        f"/api/v1/users/{handle}/avatar",
        files={"file": (name, data, ctype)},
        headers=auth,
    )


def test_upload_sets_avatar_url_and_serves_bytes(client, auth):
    # person (mens) bestaat via de user_key/auth-fixture.
    r = _upload(client, auth, "person")
    assert r.status_code == 200
    body = r.json()
    assert body["avatar_url"] is not None
    assert body["avatar_url"].startswith("/api/v1/users/person/avatar?v=")

    # De users-lijst draagt de avatar_url ook.
    users = client.get("/api/v1/users", headers=auth).json()
    person = next(u for u in users if u["handle"] == "person")
    assert person["avatar_url"] == body["avatar_url"]

    # Serve met Bearer geeft de bytes terug (BETON-202: media-afgeschermd).
    served = client.get(body["avatar_url"], headers=auth)
    assert served.status_code == 200
    assert served.content == PNG
    assert served.headers["content-type"].startswith("image/png")


def test_serve_requires_media_access(client, auth):
    """BETON-202: avatar-serve geeft 401 zonder Bearer én zonder media-cookie."""
    url = _upload(client, auth, "person").json()["avatar_url"]
    assert client.get(url).status_code == 401
    # Met een gezet media-cookie mag een cookie-only fetch wél.
    assert client.post("/api/v1/media-cookie", headers=auth).status_code == 200
    assert client.get(url).status_code == 200


def test_upload_rejects_non_image(client, auth):
    """De avatar-route blijft afbeeldings-only, óók nu attachments meer typen
    accepteren (BETON-374): hij sniff't met `sniff_image_type`, niet met
    `sniff_type`. Een PDF en een logbestand komen er allebei niet in."""
    r = _upload(client, auth, "person", data=b"%PDF-1.4", name="x.pdf",
                ctype="application/pdf")
    assert r.status_code == 415
    r = _upload(client, auth, "person", data=b"gewoon tekst\n", name="x.log",
                ctype="text/plain")
    assert r.status_code == 415


def test_upload_rejects_empty(client, auth):
    assert _upload(client, auth, "person", data=b"").status_code == 422


def test_upload_rejects_too_large(client, auth, monkeypatch):
    monkeypatch.setattr(attachments_repo, "MAX_SIZE", 4)
    assert _upload(client, auth, "person", data=b"12345").status_code == 413


def test_upload_unknown_handle_404(client, auth):
    assert _upload(client, auth, "nietbestaand").status_code == 404


def test_upload_requires_human(client, auth, agent_auth):
    # Agent-key mag geen avatar zetten (agent-beheer is voorbehouden aan de mens).
    assert _upload(client, agent_auth, "claude").status_code == 403


def test_upload_requires_auth(client):
    assert _upload(client, {}, "person").status_code == 401


def test_serve_unknown_user_404(client, auth):
    assert client.get("/api/v1/users/nietbestaand/avatar", headers=auth).status_code == 404


def test_serve_avatarless_user_404(client, auth):
    # person bestaat maar heeft (nog) geen avatar.
    assert client.get("/api/v1/users/person/avatar", headers=auth).status_code == 404


def test_delete_resets_to_initials(client, auth):
    _upload(client, auth, "person")
    r = client.delete("/api/v1/users/person/avatar", headers=auth)
    assert r.status_code == 200
    assert r.json()["avatar_url"] is None
    # Serve geeft nu 404 (geen avatar meer).
    assert client.get("/api/v1/users/person/avatar", headers=auth).status_code == 404


def test_delete_requires_human(client, auth, agent_auth):
    _upload(client, auth, "claude")  # mens zet avatar op de agent
    assert client.delete("/api/v1/users/claude/avatar", headers=agent_auth).status_code == 403


def test_delete_unknown_handle_404(client, auth):
    assert client.delete("/api/v1/users/nietbestaand/avatar", headers=auth).status_code == 404


def test_serialize_avatar_url_none_without_avatar(conn):
    user, _ = users_repo.create(conn, handle="leeg", display_name="Leeg", kind="agent")
    assert user["avatar_url"] is None


# --- Magic-bytes-sniff (BETON-380) ----------------------------------------


def test_upload_stores_the_sniffed_type_not_the_claimed_one(client, auth):
    # PNG-bytes met een image/gif-claim: de bytes winnen, de serve-route levert PNG.
    assert _upload(client, auth, "person", data=PNG, name="x.gif",
                   ctype="image/gif").status_code == 200
    served = client.get("/api/v1/users/person/avatar", headers=auth)
    assert served.headers["content-type"].startswith("image/png")


def test_upload_rejects_non_image_bytes_claiming_to_be_png(client, auth):
    r = _upload(client, auth, "person", data=b"MZ\x90\x00 niet-echt", name="x.png",
                ctype="image/png")
    assert r.status_code == 415


# --- Serve-headers (BETON-380) --------------------------------------------


def test_serve_sets_nosniff_and_a_revalidating_private_cache(client, auth):
    _upload(client, auth, "person")
    r = client.get("/api/v1/users/person/avatar", headers=auth)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"] == 'inline; filename="person-avatar"'
    # Deze URL is op handle gekeyd en dus mutabel: geen `immutable`, anders
    # haalt de browser een vervangen avatar een jaar lang niet op.
    assert r.headers["cache-control"] == "private, max-age=0, must-revalidate"
    assert "immutable" not in r.headers["cache-control"]
