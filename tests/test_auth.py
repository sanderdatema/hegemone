"""Auth + meta-endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from betonning.server import create_app


def test_me_requires_key(client):
    assert client.get("/api/v1/me").status_code == 401


def test_me_rejects_bad_key(client):
    r = client.get("/api/v1/me", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_me_returns_current_user(client, auth):
    r = client.get("/api/v1/me", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["handle"] == "person"
    assert body["kind"] == "human"


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def _docs_app(tmp_path, **kwargs):
    """App zonder static-mount, zodat een dicht /docs echt 404 geeft en niet in
    de SPA-fallback (index.html) belandt."""
    return create_app(
        str(tmp_path / "docs.db"),
        enable_dispatcher=False,
        static_dir=tmp_path / "geen-build",
        **kwargs,
    )


def test_openapi_docs_closed_by_default(tmp_path, monkeypatch):
    """BETON-379: een installatie kan publiek bereikbaar zijn, dus het
    endpoint-overzicht staat standaard dicht."""
    monkeypatch.delenv("BETONNING_DOCS", raising=False)
    with TestClient(_docs_app(tmp_path)) as c:
        assert c.get("/openapi.json").status_code == 404
        assert c.get("/docs").status_code == 404
        assert c.get("/redoc").status_code == 404


def test_openapi_docs_open_with_env_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("BETONNING_DOCS", "1")
    with TestClient(_docs_app(tmp_path)) as c:
        assert c.get("/openapi.json").status_code == 200
        r = c.get("/docs")
        assert r.status_code == 200
        # Swagger UI draait op een inline script + CDN: geen CSP op deze pagina,
        # anders is hij blanco. De overige headers gelden er wél.
        assert "content-security-policy" not in r.headers
        assert r.headers["x-content-type-options"] == "nosniff"
