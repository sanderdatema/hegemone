"""UI-serving: users-endpoint (mention-autocomplete) + statische SPA."""

from __future__ import annotations

from fastapi.testclient import TestClient

from betonning import db as db_module
from betonning.server import create_app


def test_list_users(client, auth):
    r = client.get("/api/v1/users", headers=auth)
    assert r.status_code == 200
    handles = [u["handle"] for u in r.json()]
    assert "person" in handles


def test_list_users_requires_auth(client):
    assert client.get("/api/v1/users").status_code == 401


def test_static_index_served(tmp_path):
    db_path = str(tmp_path / "ui.db")
    db_module.init_db(db_path).close()
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>Betonning UI</h1>", encoding="utf-8")

    app = create_app(db_path, enable_dispatcher=False, static_dir=static)
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "Betonning UI" in r.text
        # index.html mag niet gecachet worden (deep-links na deploy vers laden).
        assert r.headers["cache-control"] == "no-cache"
        # API blijft voorrang houden ondanks de mount op "/".
        assert c.get("/health").json() == {"status": "ok"}


def test_kickstart_is_public_agent_json(tmp_path):
    db_path = str(tmp_path / "ui.db")
    db_module.init_db(db_path).close()
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>Betonning UI</h1>", encoding="utf-8")

    app = create_app(db_path, enable_dispatcher=False, static_dir=static)
    with TestClient(app) as c:
        r = c.get("/kickstart")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        body = r.json()
        assert body["service"] == "Betonning"
        assert body["api_base"] == "/api/v1"
        assert body["mcp_url"] == "/mcp/"
        assert body["auth"]["header"] == "Authorization: Bearer <api-key>"
        assert body["first_steps"]
        assert "memory" in body["instructions_md"]
        assert "Betonning UI" not in r.text

        head = c.head("/kickstart")
        assert head.status_code == 200
        assert head.headers["content-type"].startswith("application/json")
        assert head.text == ""


def test_spa_fallback_serves_index(tmp_path):
    """Onbekende paden (deep-links zoals /SOS/42) vallen terug op index.html."""
    db_path = str(tmp_path / "ui.db")
    db_module.init_db(db_path).close()
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>Betonning UI</h1>", encoding="utf-8")

    app = create_app(db_path, enable_dispatcher=False, static_dir=static)
    with TestClient(app) as c:
        # Diep project/ticket-pad → SPA-fallback naar index.html.
        r = c.get("/SOS/42")
        assert r.status_code == 200
        assert "Betonning UI" in r.text
        assert r.headers["cache-control"] == "no-cache"
        # Los projectpad werkt ook.
        assert c.get("/SOS").status_code == 200
        # API blijft voorrang houden: onbekende API-route valt niet terug op de UI.
        assert c.get("/api/v1/onbekend").status_code == 404
        assert "Betonning UI" not in c.get("/api/v1/onbekend").text
        assert c.get("/health").json() == {"status": "ok"}


def test_no_static_dir_ok(tmp_path):
    db_path = str(tmp_path / "ui.db")
    db_module.init_db(db_path).close()
    app = create_app(db_path, enable_dispatcher=False, static_dir=tmp_path / "afwezig")
    with TestClient(app) as c:
        # Zonder build blijft de API gewoon werken; "/" bestaat niet.
        assert c.get("/health").json() == {"status": "ok"}
        assert c.get("/").status_code == 404


# --- Security-headers (BETON-379) ------------------------------------------


def _ui_app(tmp_path):
    """App met een minimale static-build, zodat "/" een HTML-response geeft."""
    db_path = str(tmp_path / "hdr.db")
    db_module.init_db(db_path).close()
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>Betonning UI</h1>", encoding="utf-8")
    return create_app(db_path, enable_dispatcher=False, static_dir=static)


def test_security_headers_on_html(tmp_path):
    with TestClient(_ui_app(tmp_path)) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "same-origin"
        assert "camera=()" in r.headers["permissions-policy"]
        csp = r.headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        # De UI heeft deze bronnen echt nodig: inline style-attributen (Svelte
        # `style:`), data:-SVG in app.css, blob:-voorbeeld voor upload en
        # externe https-afbeeldingen uit markdown.
        assert "style-src 'self' 'unsafe-inline'" in csp
        assert "img-src 'self' data: blob: https:" in csp


def test_security_headers_on_api_json_without_csp(tmp_path):
    with TestClient(_ui_app(tmp_path)) as c:
        r = c.get("/health")
        assert r.status_code == 200
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        # CSP alleen op HTML; op JSON voegt hij niets toe.
        assert "content-security-policy" not in r.headers


def test_security_headers_on_401(tmp_path):
    """Ook een geweigerde media-serve (BETON-202) draagt de headers."""
    with TestClient(_ui_app(tmp_path)) as c:
        r = c.get("/api/v1/attachments/" + "0" * 64)
        assert r.status_code == 401
        assert r.headers["x-content-type-options"] == "nosniff"


def test_hsts_only_when_https(tmp_path):
    with TestClient(_ui_app(tmp_path)) as c:
        # Plain http (lokaal/achter de tunnel): geen HSTS.
        assert "strict-transport-security" not in c.get("/").headers
        # De tunnel geeft het echte protocol door in X-Forwarded-Proto.
        r = c.get("/", headers={"X-Forwarded-Proto": "https"})
        assert r.headers["strict-transport-security"] == (
            "max-age=31536000; includeSubDomains"
        )
        # Meerdere hops: de eerste waarde telt.
        r = c.get("/", headers={"X-Forwarded-Proto": "https, http"})
        assert "strict-transport-security" in r.headers


def test_docs_paths_leak_nothing_with_a_static_build(tmp_path):
    """Prod-vorm: mét een build vangt de SPA-fallback /docs en /openapi.json op.

    Dan is het geen 404 maar de UI-pagina — het schema lekt hoe dan ook niet,
    maar een post-deploy-check moet naar de body kijken, niet naar de status.
    """
    with TestClient(_ui_app(tmp_path)) as c:
        r = c.get("/openapi.json")
        assert "openapi" not in r.text
        assert "Betonning UI" in r.text
        assert "swagger" not in c.get("/docs").text.lower()
