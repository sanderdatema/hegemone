"""Attachments: upload → serve roundtrip, whitelist/grootte, lijst (BETON-5)."""

from __future__ import annotations

import pytest

from betonning.repo import attachments as attachments_repo

PNG = b"\x89PNG\r\n\x1a\n fake-image-bytes"


@pytest.fixture
def item(client, auth):
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    r = client.post(
        "/api/v1/projects/SOS/items", json={"title": "Met bijlage"}, headers=auth
    )
    return r.json()["ref"]


def _upload(client, auth, ref, data=PNG, name="plaatje.png", ctype="image/png"):
    return client.post(
        f"/api/v1/items/{ref}/attachments",
        files={"file": (name, data, ctype)},
        headers=auth,
    )


def test_upload_then_serve_roundtrip(client, auth, item):
    r = _upload(client, auth, item)
    assert r.status_code == 201
    body = r.json()
    assert body["filename"] == "plaatje.png"
    assert body["content_type"] == "image/png"
    assert body["size"] == len(PNG)
    assert body["created_by"] == "person"
    assert body["url"].startswith("/api/v1/attachments/")

    # Serve met Bearer geeft de bytes terug (BETON-202: media-afgeschermd).
    served = client.get(body["url"], headers=auth)
    assert served.status_code == 200
    assert served.content == PNG
    assert served.headers["content-type"].startswith("image/png")


def test_serve_requires_media_access(client, auth, item):
    """BETON-202: de serve-route geeft 401 zonder Bearer én zonder media-cookie."""
    url = _upload(client, auth, item).json()["url"]
    assert client.get(url).status_code == 401


def test_serve_with_media_cookie(client, auth, item):
    """BETON-202: na POST /media-cookie (Bearer) mag een cookie-only <img>-fetch
    de bytes ophalen — de TestClient bewaart het cookie in zijn jar."""
    url = _upload(client, auth, item).json()["url"]
    assert client.post("/api/v1/media-cookie", headers=auth).status_code == 200
    served = client.get(url)  # geen Bearer: alleen het net gezette cookie
    assert served.status_code == 200
    assert served.content == PNG


def test_upload_requires_auth(client, item):
    assert _upload(client, {}, item).status_code == 401


def test_upload_rejects_binary_junk(client, auth, item):
    # Geen afbeelding, geen PDF, geen geldige UTF-8 → niet toegestaan.
    r = _upload(
        client, auth, item, data=b"MZ\x90\x00\xff\xfe", name="x.exe",
        ctype="application/octet-stream",
    )
    assert r.status_code == 415


def test_upload_rejects_empty(client, auth, item):
    r = _upload(client, auth, item, data=b"")
    assert r.status_code == 422


def test_upload_rejects_too_large(client, auth, item, monkeypatch):
    monkeypatch.setattr(attachments_repo, "MAX_SIZE", 4)
    r = _upload(client, auth, item, data=b"12345")
    assert r.status_code == 413


def test_upload_unknown_item_404(client, auth):
    assert _upload(client, auth, "SOS-999").status_code == 404


def test_upload_invalid_ref_404(client, auth):
    # Onherkenbare ref-vorm (geen KEY-seq) → ook 404, net als het items-endpoint
    # (gedeelde `deps.require_item`, BETON-324).
    assert _upload(client, auth, "garbage").status_code == 404


def test_serve_unknown_sha_404(client, auth, item):
    assert client.get("/api/v1/attachments/" + "0" * 64, headers=auth).status_code == 404


def test_list_attachments_for_item(client, auth, item):
    _upload(client, auth, item, name="a.png")
    _upload(client, auth, item, data=PNG + b"-andere", name="b.png")
    rows = client.get(f"/api/v1/items/{item}/attachments", headers=auth).json()
    assert {r["filename"] for r in rows} == {"a.png", "b.png"}


def test_identical_bytes_dedupe_to_same_url(client, auth, item):
    """Zelfde bytes → zelfde content-adres (sha), dus dezelfde serve-URL."""
    u1 = _upload(client, auth, item, name="een.png").json()["url"]
    u2 = _upload(client, auth, item, name="twee.png").json()["url"]
    assert u1 == u2


# --- Magic-bytes-sniff (BETON-380) ----------------------------------------


def test_sniff_image_type_recognises_the_whitelist():
    assert attachments_repo.sniff_image_type(b"\x89PNG\r\n\x1a\n") == "image/png"
    assert attachments_repo.sniff_image_type(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert attachments_repo.sniff_image_type(b"GIF89a...") == "image/gif"
    assert attachments_repo.sniff_image_type(b"RIFF\x00\x00\x00\x00WEBP") == "image/webp"


def test_sniff_image_type_rejects_non_images():
    assert attachments_repo.sniff_image_type(b"%PDF-1.4") is None
    assert attachments_repo.sniff_image_type(b"MZ\x90\x00") is None
    assert attachments_repo.sniff_image_type(b"") is None


def test_upload_stores_the_sniffed_type_not_the_claimed_one(client, auth, item):
    # PNG-bytes met een image/jpeg-claim: de bytes winnen.
    r = _upload(client, auth, item, data=PNG, name="x.jpg", ctype="image/jpeg")
    assert r.status_code == 201
    assert r.json()["content_type"] == "image/png"


def test_upload_rejects_non_image_bytes_claiming_to_be_png(client, auth, item):
    # Dit kwam er vóór BETON-380 langs de whitelist heen: de header loog.
    r = _upload(client, auth, item, data=b"MZ\x90\x00 niet-echt", name="x.png",
                ctype="image/png")
    assert r.status_code == 415


# --- Serve-headers (BETON-380) --------------------------------------------


def test_serve_sets_nosniff_disposition_and_private_immutable_cache(client, auth, item):
    url = _upload(client, auth, item, name="plaatje.png").json()["url"]
    r = client.get(url, headers=auth)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"] == 'inline; filename="plaatje.png"'
    # Content-addressed URL: dezelfde URL geeft altijd dezelfde bytes.
    assert r.headers["cache-control"] == "private, max-age=31536000, immutable"


def test_serve_sanitises_the_filename_in_the_disposition(client, auth, item):
    url = _upload(client, auth, item, name='ra"re;naam .png').json()["url"]
    r = client.get(url, headers=auth)
    disposition = r.headers["content-disposition"]
    assert '"' not in disposition.removeprefix('inline; filename="').removesuffix('"')
    assert ";" not in disposition.split("filename=")[1]


# --- Meer typen dan afbeeldingen (BETON-374) ------------------------------

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n"
LOG = "2026-09-02 12:00 INFO alles goed\n".encode()
JSON = b'{"ok": true, "n": 3}'


def test_sniff_type_is_content_derived():
    # Volgorde: afbeelding → PDF → JSON (alleen met {/[) → tekst → niets.
    assert attachments_repo.sniff_type(PNG) == "image/png"
    assert attachments_repo.sniff_type(PDF) == "application/pdf"
    assert attachments_repo.sniff_type(JSON) == "application/json"
    assert attachments_repo.sniff_type(b"  [1, 2]") == "application/json"
    assert attachments_repo.sniff_type(LOG) == "text/plain"
    # Een logregel die toevallig een JSON-scalar is blijft tekst.
    assert attachments_repo.sniff_type(b"123") == "text/plain"
    # Kapotte JSON tussen accolades is geen JSON, maar wel tekst.
    assert attachments_repo.sniff_type(b"{niet echt json}") == "text/plain"
    assert attachments_repo.sniff_type(b"\x00\x01\x02\xff") is None


def test_sniff_type_ignores_the_filename_so_dedupe_blijft_kloppen(client, auth, item):
    """Dezelfde bytes onder twee namen → één type en dus één content-adres.

    `get_by_sha` doet `LIMIT 1` op de aanname dat één sha één content_type is;
    typen op extensie zou die aanname breken.
    """
    a = _upload(client, auth, item, data=JSON, name="log.txt", ctype="text/plain").json()
    b = _upload(client, auth, item, data=JSON, name="log.json", ctype="text/plain").json()
    assert a["content_type"] == b["content_type"] == "application/json"
    assert a["url"] == b["url"]


def test_get_by_sha_picks_the_oldest_row_by_id(client, auth, item, conn):
    """BETON-394: twee items met identieke bytes → twee attachment-rijen met
    hetzelfde sha256 maar verschillende `filename`. `get_by_sha` moet
    deterministisch dezelfde rij teruggeven — de OUDSTE (kleinste id).

    Een test die alleen de huidige uitkomst vastlegt bewijst niets: SQLite's
    b-tree scant een tabel zonder ORDER BY in de praktijk al in rowid-volgorde,
    dus zo'n test slaagt ook zonder de fix. Deze test controleert daarom de
    daadwerkelijk uitgevoerde SQL (via `set_trace_callback`) op een expliciete
    `ORDER BY` — dat faalt op de oude `LIMIT 1` zonder ordening, ongeacht welke
    volgorde SQLite toevallig aanhoudt."""
    a = _upload(client, auth, item, data=JSON, name="eerst.json").json()
    _upload(client, auth, item, data=JSON, name="daarna.json").json()

    row = attachments_repo.get_by_sha(conn, a["url"].rsplit("/", 1)[-1])
    assert row["filename"] == "eerst.json"

    queries: list[str] = []
    conn.set_trace_callback(queries.append)
    try:
        attachments_repo.get_by_sha(conn, a["url"].rsplit("/", 1)[-1])
    finally:
        conn.set_trace_callback(None)
    assert any("order by" in q.lower() for q in queries), (
        "get_by_sha() moet expliciet ordenen — anders is de gekozen rij bij "
        "meerdere kandidaten een implementatiedetail van de query-planner, "
        "geen garantie."
    )


@pytest.mark.parametrize(
    "data,name,claimed,expected",
    [
        (LOG, "server.log", "application/octet-stream", "text/plain"),
        (b"a,b\n1,2\n", "cijfers.csv", "text/csv", "text/plain"),
        (b"# Kop\n\ntekst\n", "notitie.md", "text/markdown", "text/plain"),
        (JSON, "payload.json", "application/json", "application/json"),
        (PDF, "rapport.pdf", "application/pdf", "application/pdf"),
    ],
)
def test_upload_accepts_text_log_json_and_pdf(
    client, auth, item, data, name, claimed, expected
):
    r = _upload(client, auth, item, data=data, name=name, ctype=claimed)
    assert r.status_code == 201, r.text
    assert r.json()["content_type"] == expected


def test_non_images_are_served_as_attachment_images_inline(client, auth, item):
    """De kern van BETON-374: alleen een afbeelding mag inline op onze origin."""
    png_url = _upload(client, auth, item, data=PNG, name="p.png").json()["url"]
    log_url = _upload(client, auth, item, data=LOG, name="server.log").json()["url"]
    pdf_url = _upload(client, auth, item, data=PDF, name="rapport.pdf").json()["url"]

    r_png = client.get(png_url, headers=auth)
    assert r_png.headers["content-disposition"] == 'inline; filename="p.png"'

    r_log = client.get(log_url, headers=auth)
    assert r_log.content == LOG
    assert r_log.headers["content-disposition"] == 'attachment; filename="server.log"'
    assert r_log.headers["content-type"].startswith("text/plain")
    assert "charset=utf-8" in r_log.headers["content-type"]
    assert r_log.headers["x-content-type-options"] == "nosniff"

    r_pdf = client.get(pdf_url, headers=auth)
    assert r_pdf.headers["content-disposition"] == 'attachment; filename="rapport.pdf"'
    assert r_pdf.headers["content-type"].startswith("application/pdf")


def test_svg_never_gets_an_image_type(client, auth, item):
    """SVG is XML met scriptcapaciteit en staat niet op de whitelist.

    Hij komt niet als `image/svg+xml` binnen (dus nooit inline geserveerd) maar
    als gewone tekst, met `attachment` + `nosniff` — een download, geen pagina.
    """
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    body = _upload(
        client, auth, item, data=svg, name="x.svg", ctype="image/svg+xml"
    ).json()
    assert body["content_type"] == "text/plain"
    r = client.get(body["url"], headers=auth)
    assert r.headers["content-disposition"] == 'attachment; filename="x.svg"'
    assert not r.headers["content-type"].startswith("image/")


def test_text_above_its_own_limit_is_413(client, auth, item, monkeypatch):
    """De per-type-limiet is scherper dan de globale MAX_SIZE (10 MB)."""
    monkeypatch.setitem(attachments_repo.TYPE_LIMITS, "text/plain", 8)
    r = _upload(client, auth, item, data=b"veel te veel tekst", name="a.log")
    assert r.status_code == 413
    # Een afbeelding met zijn eigen (ongewijzigde) limiet komt er nog wel in.
    assert _upload(client, auth, item, data=PNG).status_code == 201
