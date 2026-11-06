"""Body-size-limiet (BETON-380): te grote JSON → 413, multipart eigen cap."""

from __future__ import annotations

import pytest

from betonning import bodylimit


@pytest.fixture
def item(client, auth):
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    r = client.post("/api/v1/projects/SOS/items", json={"title": "Iets"}, headers=auth)
    return r.json()["ref"]


def test_oversized_json_body_is_refused(client, auth, item):
    big = "x" * (bodylimit.DEFAULT_MAX_BODY + 1024)
    r = client.patch(f"/api/v1/items/{item}", json={"description_md": big}, headers=auth)
    assert r.status_code == 413


def test_body_under_the_limit_passes(client, auth, item):
    # Een geldige omschrijving past zowel binnen de veldlimiet als de transportcap.
    body = "y" * 50000
    r = client.patch(f"/api/v1/items/{item}", json={"description_md": body}, headers=auth)
    assert r.status_code == 200
    assert len(r.json()["description_md"]) == len(body)


def test_multipart_gets_a_wider_cap_than_json(client, auth, item):
    # Een upload die boven de JSON-cap (2 MiB) uitkomt maar onder de
    # attachment-cap blijft, mag niet door de body-limiet geweigerd worden.
    png = b"\x89PNG\r\n\x1a\n" + b"z" * (3 * 1024 * 1024)
    r = client.post(
        f"/api/v1/items/{item}/attachments",
        files={"file": ("groot.png", png, "image/png")},
        headers=auth,
    )
    assert r.status_code == 201


def test_multipart_above_the_attachment_cap_is_refused(client, auth, item):
    # Boven MAX_SIZE + slack slaat de middleware toe, vóór de multipart-parser.
    png = b"\x89PNG\r\n\x1a\n" + b"z" * (12 * 1024 * 1024)
    r = client.post(
        f"/api/v1/items/{item}/attachments",
        files={"file": ("veel-te-groot.png", png, "image/png")},
        headers=auth,
    )
    assert r.status_code == 413


def test_limit_for_picks_the_multipart_cap_on_multipart_content_type():
    mw = bodylimit.BodySizeLimitMiddleware(None, max_body=100, multipart_max=9999)
    assert mw._limit_for({b"content-type": b"application/json"}) == 100
    assert mw._limit_for({b"content-type": b"multipart/form-data; boundary=x"}) == 9999
    assert mw._limit_for({}) == 100


def test_get_without_body_is_untouched(client, auth):
    # De SSE-stream en gewone GET's hebben geen body en mogen nooit op receive
    # blijven hangen.
    assert client.get("/api/v1/users", headers=auth).status_code == 200
    assert client.get("/health").status_code == 200


def test_field_limit_is_separate_from_transport_cap(client, auth, item):
    result = client.patch(f"/api/v1/items/{item}", json={"description_md":"x"*60001}, headers=auth)
    assert result.status_code == 422
