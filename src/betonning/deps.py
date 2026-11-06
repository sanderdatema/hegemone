"""FastAPI-dependencies: db-connectie (per request) en Bearer-auth.

Eén connectie per request: WAL laat lezers nooit blokkeren en serialiseert
schrijvers op SQLite-niveau (busy_timeout). FastAPI cachet dependencies binnen
één request, dus current_user en de endpoint delen dezelfde connectie.
"""

from __future__ import annotations

import hmac
from urllib.parse import urlsplit
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import db as db_module
from . import ratelimit as ratelimit_module
from . import security, credential_policy
from .repo import browser_sessions
from .repo import items as items_repo
from .repo import projects as projects_repo
from .repo import users as users_repo

bearer_scheme = HTTPBearer(auto_error=False)

# Naam + levensduur van het media-toegangscookie (BETON-202). Scope beperkt tot
# /api/v1 zodat het cookie alleen naar de API gaat, niet naar de UI-assets.
MEDIA_COOKIE_NAME = "bt_media"
MEDIA_COOKIE_PATH = "/api/v1"
MEDIA_COOKIE_TTL = 24 * 3600  # 24 uur (BETON-383: korter, want user-gebonden)
# Hoeveel tekens van de api_key_hash het token meedraagt. Genoeg om een
# gerouleerde key te herkennen, te weinig om de hash te reconstrueren.
MEDIA_KEY_FRAGMENT_LEN = 16


def media_key_fragment(user: sqlite3.Row) -> str:
    """Fragment van de api_key_hash dat het media-token aan déze key bindt."""
    return (user["api_key_hash"] or "")[:MEDIA_KEY_FRAGMENT_LEN]


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    existing = getattr(request.state, "db_conn", None)
    if existing is not None:
        yield existing
        return
    conn = db_module.connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_attachments_dir(request: Request) -> str:
    """Map waar attachment-bytes op disk staan (content-addressed)."""
    return request.app.state.attachments_dir


def require_llm_client(request: Request):
    """De geconfigureerde LLM-client, of 503 als er geen geconfigureerd is
    (BETON-324). Vervangt de herhaalde inline `if llm is None: raise
    HTTPException(503, ...)`-guard op de enrich/decompose/triage-chat-endpoints."""
    snapshot = getattr(request.state, "installation_runtime", None)
    llm = snapshot.llm if snapshot is not None else request.app.state.llm_client
    if llm is None:
        raise HTTPException(status_code=503, detail="Geen LLM geconfigureerd")
    return llm


def require_item(conn: sqlite3.Connection, ref: str) -> sqlite3.Row:
    """Haal een item op via zijn ref, of 404 (BETON-324).

    Eén bron voor het `get_by_ref → 404`-patroon dat eerder apart in
    `api/items.py` en `api/attachments.py` stond. Een ongeldige ref-vorm
    (`ValueError` uit `parse_ref`) en een onbekende-maar-geldige ref geven
    allebei 404, met een net iets ander detail zodat het onderscheid in logs
    zichtbaar blijft."""
    try:
        item = items_repo.get_by_ref(conn, ref)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Ongeldige ref: {ref}")
    if item is None:
        raise HTTPException(status_code=404, detail=f"Onbekend item: {ref}")
    return item


def require_project(conn: sqlite3.Connection, key: str) -> sqlite3.Row:
    """Haal een project op via zijn key, of 404. Zelfde rol als `require_item`;
    vervangt de losse kopieën in `api/projects.py`, `api/wiki.py` en
    `api/triage_chat.py`."""
    project = projects_repo.get_by_key(conn, key)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Onbekend project: {key}")
    return project


@contextmanager
def llm_errors_as_502(
    exc_types: type[Exception] | tuple[type[Exception], ...] = Exception,
):
    """Vertaal een LLM-upstream-fout naar een 502 met context (BETON-324).

    `exc_types` laat de aanroeper kiezen wat als "LLM-fout" telt: de rauwe
    enrich/decompose-endpoints roepen `llm.complete` rechtstreeks aan en vangen
    alles af (default `Exception`); de triage-chat-motor wrapt upstream-fouten
    zelf al in `LLMError`, dus die aanroeper geeft alleen dat type mee zodat
    andere uitzonderingen (bv. `ProposalNotPending`) ongemoeid blijven."""
    try:
        yield
    except exc_types as exc:
        raise HTTPException(status_code=502, detail=f"LLM-fout: {exc}") from exc


def _enforce_policy(request, user, conn):
    scopes = credential_policy.scopes(user)
    method, path = request.method, request.url.path
    read = method in ("GET", "HEAD", "OPTIONS")
    needed = (
        "read"
        if read or path in ("/api/v1/session", "/api/v1/logout", "/api/v1/media-cookie")
        else "write"
    )
    if not read and path.endswith(("/enrich", "/decompose")):
        needed = "llm"
    if needed not in scopes:
        raise HTTPException(403, "Deze sleutel mist de benodigde scope")
    if not read and "/wiki" in path and "memory:write" not in scopes:
        raise HTTPException(403, "Deze sleutel mag geen kennis wijzigen")
    if not read and (
        path.startswith(("/api/v1/users", "/api/v1/settings", "/api/v1/security-usage"))
        or path.startswith(("/api/v1/wiki-proposals", "/api/v1/wiki-protection"))
    ):
        if "admin" not in scopes:
            raise HTTPException(403, "Deze sleutel mist beheerscope")
    allowed = credential_policy.projects(user)
    if allowed is None:
        return
    params = request.path_params
    key = params.get("key")
    if path == "/api/v1/wiki-proposals":
        key = request.query_params.get("project")
    if params.get("ref"):
        key = str(params["ref"]).rsplit("-", 1)[0]
    if params.get("comment_id"):
        row = conn.execute(
            "SELECT p.key FROM comments c JOIN items i ON i.id=c.item_id JOIN projects p ON p.id=i.project_id WHERE c.id=?",
            (params["comment_id"],),
        ).fetchone()
        key = row["key"] if row else ""
    if params.get("sha256"):
        keys = {
            row["key"]
            for row in conn.execute(
                "SELECT p.key FROM attachments a JOIN projects p ON p.id=a.project_id WHERE a.sha256=?",
                (params["sha256"],),
            )
        }
        if keys.intersection(allowed):
            return
        raise HTTPException(403, "Media valt buiten de projectscopes")
    if key is None and path == "/api/v1/events/stream":
        key = request.query_params.get("project")
    if key is not None:
        if (
            path.startswith("/api/v1/projects/")
            and not read
            and "/items" not in path
            and "/wiki" not in path
        ):
            if "admin" not in scopes:
                raise HTTPException(403, "Projectinstellingen vereisen beheerscope")
        if str(key).upper() not in allowed:
            raise HTTPException(403, "Project valt buiten de sleutelrechten")
        return
    if path.startswith("/api/v1/wiki-proposals"):
        raise HTTPException(403, "Review valt buiten de projectscopes")
    shared_read = path in (
        "/api/v1/projects",
        "/api/v1/settings/model-classes",
    ) or path.startswith(("/api/v1/wiki", "/api/v1/me", "/api/v1/users"))
    if read and shared_read:
        return
    if path in ("/api/v1/session", "/api/v1/logout", "/api/v1/media-cookie"):
        return
    raise HTTPException(403, "Gebruik een expliciet toegestane projectroute")


async def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    conn: sqlite3.Connection = Depends(get_db),
) -> sqlite3.Row:
    """Eigen Bearer-key of kortlevende browsersessie met CSRF op mutaties."""
    user = None
    if credentials is not None and len(credentials.credentials) > 256:
        raise HTTPException(401, "Ongeldige API-key")
    if credentials is not None and credentials.credentials:
        user = users_repo.get_by_api_key(conn, credentials.credentials)
    else:
        raw = request.cookies.get(browser_sessions.COOKIE)
        result = browser_sessions.resolve(conn, raw)
        if result is not None:
            user, expires = result
            request.state.session_token = raw
            request.state.auth_expires_at = expires
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origin = request.headers.get("origin")
                if (
                    origin
                    and urlsplit(origin).netloc.lower() != request.url.netloc.lower()
                ):
                    raise HTTPException(403, "Ongeldige herkomst van browsermutatie")
                csrf = request.headers.get("x-csrf-token", "")
                if not csrf.isascii() or not hmac.compare_digest(
                    csrf, browser_sessions.csrf(raw)
                ):
                    raise HTTPException(403, "Ontbrekend of ongeldig CSRF-token")
    if user is None:
        raise HTTPException(401, "Ontbrekende, verlopen of ongeldige aanmelding")
    _enforce_policy(request, user, conn)
    allowed = credential_policy.projects(user)
    if allowed is not None and request.method not in ("GET", "HEAD", "OPTIONS"):
        if "application/json" in request.headers.get("content-type", ""):
            try:
                body = await request.json()
            except ValueError:
                body = None
            if isinstance(body, dict):
                for field in ("project", "target", "parent", "target_ref"):
                    candidate = body.get(field)
                    if candidate:
                        target_key = (
                            str(candidate).rsplit("-", 1)[0]
                            if field != "project"
                            else str(candidate)
                        )
                        if target_key.upper() not in allowed:
                            raise HTTPException(
                                403, "Doel valt buiten de projectscopes"
                            )
    request.state.user_id = user["id"]
    return user


def require_media_access(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    conn: sqlite3.Connection = Depends(get_db),
) -> None:
    """Poort voor de media-serve-routes (attachments/avatars, BETON-202).

    Toegang met een geldige Bearer-key (agents/`bt`/MCP) óf een geldig
    media-cookie (browser-`<img>`, same-origin). Zonder beide: 401. Zo blijven de
    content-addressed URL's ongewijzigd (geen markdown-breuk) terwijl anonieme
    publieke bezoekers de bytes niet meer kunnen ophalen."""
    if credentials is not None and credentials.credentials:
        user = users_repo.get_by_api_key(conn, credentials.credentials)
        if user is not None:
            _enforce_policy(request, user, conn)
            return
    token = request.cookies.get(MEDIA_COOKIE_NAME)
    verified = security.verify_media_token(token)
    if verified is not None:
        # Het cookie noemt een user; die moet nog bestaan, nog actief zijn en nog
        # dezelfde key hebben (BETON-383). `users_repo.get` filtert zelf niet op
        # `active` — alleen `get_by_api_key` doet dat — dus dat checken we hier.
        user_id, fragment = verified
        user = users_repo.get(conn, user_id)
        if (
            user is not None
            and credential_policy.valid(user)
            and hmac.compare_digest(fragment, media_key_fragment(user))
        ):
            _enforce_policy(request, user, conn)
            return
    raise HTTPException(status_code=401, detail="Geen toegang tot media")


def current_human(user: sqlite3.Row = Depends(current_user)) -> sqlite3.Row:
    """Als current_user, maar 403 tenzij de user een mens is (BETON-72).

    Agent-beheer (users CRUD) is voorbehouden aan de mens: agents mogen elkaar
    niet aanmaken/bewerken/deactiveren."""
    if user["kind"] != "human":
        raise HTTPException(status_code=403, detail="Alleen voor mensen")
    return user


def llm_rate_limited(
    request: Request,
    user: sqlite3.Row = Depends(current_user),
) -> sqlite3.Row:
    """Poort voor de endpoints die een LLM-call doen (BETON-387).

    Token-bucket per user; 429 met `Retry-After` als de emmer leeg is. Mensen
    krijgen `ratelimit.HUMAN_FACTOR` keer het agent-plafond — een mens klikt zelf
    op Verrijk/Opknippen, een agent kan in een lus zitten.

    De **ingebouwde triage-worker raakt dit nooit**: die roept `llm.complete`
    rechtstreeks aan (in-process, als user `triage`) en komt dus niet langs een
    dependency. Zijn plafond is het dagbudget in `triage_worker`.

    De poort staat vóór de handler, dus een 404/409 (onbekend item, al opgeknipt)
    kost óók een token. Bewust: het alternatief is de check ná de validatie in
    elke handler herhalen, en op 30/uur is het verschil te klein om die
    complexiteit te rechtvaardigen."""
    limiter = getattr(request.app.state, "llm_rate_limiter", None)
    if limiter is None:
        return user
    rate = ratelimit_module.llm_rate_per_hour()
    if user["kind"] == "human":
        rate *= ratelimit_module.HUMAN_FACTOR
    retry_after = limiter.check(f"user:{user['id']}", rate_per_hour=rate)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail=(
                f"LLM-limiet bereikt (max {rate} per uur). "
                f"Probeer over {int(retry_after)}s opnieuw."
            ),
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )
    return user
