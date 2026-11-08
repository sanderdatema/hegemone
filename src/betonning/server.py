"""FastAPI app-factory + lifespan.

Migraties draaien één keer bij startup. Verder opent elke request zijn eigen
connectie (zie deps.get_db) — WAL houdt lezers vrij en serialiseert schrijvers
op SQLite-niveau.

De webhook-dispatcher draait als asyncio-achtergrondtaak in deze lifespan
(uit te zetten met enable_dispatcher=False, bv. in tests).
"""

from __future__ import annotations

from .config import ai_language, env, installation_language

import asyncio
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from .api_error_codes import localized_http_error, localized_validation_error, database_integrity_error
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import bodylimit, resource_limits, installation_runtime
from .repo import installation_settings
from . import db as db_module
from . import deferred_worker
from . import embeddings as embeddings_module
from . import llm as llm_module
from . import mcp_stats
from . import ratelimit as ratelimit_module
from . import triage_worker
from . import webhooks
from . import wiki_compiler
from .api import router as api_router
from .repo import users as users_repo

_UNSET = object()  # onderscheidt "niet meegegeven" (→ env) van expliciet None (tests)


class _UICache(StaticFiles):
    """StaticFiles met SPA-fallback die index.html/HTML nooit laat cachen.

    De gehashte JS/CSS-assets mogen lang gecachet worden (unieke naam per build),
    maar index.html verwijst ernaar en moet na een deploy meteen vers zijn —
    anders opent een oude, gecachte pagina (bv. via een notificatie-deep-link)
    zonder de nieuwste code.

    SPA-fallback: onbekende GET-paden (bv. `/SOS/42`) vallen terug op index.html
    zodat client-side routing en direct laden/refreshen van een ticket-URL werkt.
    /api/v1 en /health worden eerder gematcht en komen hier nooit.
    """

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            fallback = (
                exc.status_code == 404
                and scope.get("method", "GET") in ("GET", "HEAD")
                # API-paden nooit naar de UI laten terugvallen; die horen JSON-404 te geven.
                and not path.startswith("api/")
            )
            if not fallback:
                raise
            response = await super().get_response("index.html", scope)
        if path == "index.html" or response.media_type == "text/html":
            response.headers["Cache-Control"] = "no-cache"
        return response


# Security-headers (BETON-379) worden door de app gezet, zodat de beveiliging
# niet afhangt van de gekozen reverse proxy.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

HSTS_HEADER = "max-age=31536000; includeSubDomains"

# CSP alleen op HTML. `script-src 'self'` kan omdat de Vite-build géén inline
# script emit (geverifieerd op de gebouwde index.html: één `<script type=module
# src=…>`). `'unsafe-inline'` bij style-src is wél nodig: Svelte `style:`-
# directives zetten inline style-attributen. `img-src` heeft `data:` (SVG-icoon
# in app.css), `blob:` (afbeeldingsvoorbeeld vóór upload, NewItem.svelte) en
# `https:` — markdown rendert `![](https://…)` in tickets/comments/wiki.
CSP_HEADER = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "object-src 'none'",
    )
)


class SecurityHeadersMiddleware:
    """Pure ASGI-middleware die de security-headers op elke response zet.

    Bewust géén `BaseHTTPMiddleware`: die wikkelt responses in een task group en
    zit de oneindige SSE-stream (`api/stream.py`) in de weg. Hier haken we alleen
    op `http.response.start` in, dus streaming blijft ongemoeid.

    CSP gaat alleen op `text/html`-responses (op JSON/SSE voegt hij niets toe) en
    nooit op de OpenAPI-docs: Swagger UI draait op een inline `<script>` + CDN en
    zou onder `script-src 'self'` een blanco pagina geven. De docs staan standaard
    uit; als iemand ze aanzet moeten ze werken.
    """

    def __init__(self, app, *, csp_exempt: tuple[str, ...] = ()):
        self.app = app
        self.csp_exempt = tuple(p for p in csp_exempt if p)

    def _hsts(self, scope) -> bool:
        """HSTS alleen als de request echt over https binnenkwam.

        Achter de tunnel is `scope["scheme"]` http; de eerste waarde van
        `X-Forwarded-Proto` is dan de waarheid. Zonder die check zou een lokale
        http-only omgeving zichzelf op https vastzetten.
        """
        if scope.get("scheme") == "https":
            return True
        proto = Headers(scope=scope).get("x-forwarded-proto", "")
        return proto.split(",")[0].strip().lower() == "https"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        hsts = self._hsts(scope)
        path = scope.get("path", "")
        csp_ok = not any(path.startswith(prefix) for prefix in self.csp_exempt)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if hsts:
                    headers.setdefault("Strict-Transport-Security", HSTS_HEADER)
                if csp_ok and headers.get("content-type", "").startswith("text/html"):
                    headers.setdefault("Content-Security-Policy", CSP_HEADER)
            await send(message)

        await self.app(scope, receive, send_wrapper)


def docs_enabled() -> bool:
    """OpenAPI-docs staan standaard uit (BETON-379).

    De documentatie kan op een publieke installatie het volledige endpoint-
    overzicht tonen. Lokaal aan te zetten met
    `BETONNING_DOCS=1`.
    """
    return env("BETONNING_DOCS", "").lower() in ("1", "true", "yes", "on")


DEFAULT_DB_PATH = "betonning.db"
DEFAULT_STATIC_DIR = Path(__file__).parent / "static"


def kickstart_payload() -> dict:
    """Publiek startpunt voor agents die Betonning nog niet kennen."""
    return {
        "service": "Betonning",
        "purpose": (
            "Lokaal FastAPI + SQLite ticketsysteem met MCP/REST en een "
            "persistente LLM-wiki voor agents."
        ),
        "api_base": "/api/v1",
        "mcp_url": "/mcp/",
        "auth": {
            "required_for": ["REST API", "MCP tools", "wiki context"],
            "header": "Authorization: Bearer <api-key>",
            "note": (
                "Alleen /kickstart is publiek. Gebruik voor alle operationele "
                "calls je eigen Betonning API-key, zodat activity-attributie klopt. "
                "Op /mcp/ is de Bearer-header al bij initialize verplicht; zonder "
                "geldige key krijg je 401 en komt er geen sessie tot stand."
            ),
        },
        "first_steps": [
            "Laad eerst memory: MCP load_memory(project='BETON') of GET /api/v1/projects/{KEY}/wiki/context.",
            "Kies de project-scope en lees tickets via MCP of REST; refs zijn globaal zoals BETON-155.",
            "Pak je een ticket op, zet het meteen op in-progress.",
            "Werk via voorstel/preview/bevestiging wanneer een flow dat vereist.",
            "Rond af met een comment met wijziging, tests en eventuele restpunten, en zet het ticket op done.",
        ],
        "instructions_md": (
            "# Betonning agent-kickstart\n\n"
            "Gebruik Betonning als taak-tracker en persistent geheugen. Begin elke "
            "taak met het laden van de wiki-memory voor de juiste project-key. "
            "Praat met Betonning via MCP of via de REST API onder `/api/v1`; stuur "
            "altijd `Authorization: Bearer <api-key>` mee behalve op dit publieke "
            "kickstart-endpoint.\n\n"
            "Belangrijke conventies: comments en ticketteksten zijn Nederlands; refs "
            "zijn globaal (`KEY-seq`); `/mcp/` heeft een trailing slash; zet actief "
            "werk op `in-progress`; sluit af met een korte comment en status `done`."
        ),
    }


def load_dotenv(path: str | Path = ".env") -> None:
    """Laad KEY=VALUE-regels uit .env in os.environ (zonder bestaande te overschrijven).

    Dependency-vrij; alleen actief als het bestand bestaat. Op de LXC wordt de
    token via systemd EnvironmentFile gezet, lokaal via .env.
    """
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Migraties één keer draaien; requests openen daarna hun eigen connectie.
    conn = db_module.init_db(app.state.db_path)
    try:
        installation_runtime.publish(app, installation_runtime.prepare(app, installation_settings.get(conn)))
    finally:
        conn.close()
    app.state.runtime_loop = asyncio.get_running_loop()
    app.state.runtime_changed = asyncio.Event()

    tasks = []
    stop = asyncio.Event()
    if app.state.enable_dispatcher:
        tasks.append(asyncio.create_task(webhooks.dispatcher_loop(app.state.db_path, stop)))
        # Deferred-reactivatie (BETON-39): zet verlopen deferred-items tijd-gedreven
        # terug naar de actieve kolommen. Geen LLM nodig; volgt de dispatcher-schakelaar
        # zodat tests zonder achtergrondtaken hem ook uitzetten.
        tasks.append(
            asyncio.create_task(
                deferred_worker.reactivate_loop(
                    app.state.db_path,
                    stop,
                    interval_seconds=app.state.deferred_interval,
                )
            )
        )
    tasks.append(asyncio.create_task(installation_runtime.supervise(app, stop)))
    # MCP-server (BETON-24) draait mee in de app op /mcp; z'n streamable-http
    # session-manager moet in de lifespan lopen. Alleen als gemount (mcp geïnstalleerd).
    mcp = getattr(app.state, "mcp", None)
    try:
        if mcp is not None:
            async with mcp.session_manager.run():
                yield
        else:
            yield
    finally:
        stop.set()
        app.state.mcp_stats.flush()
        for task in tasks:
            await task


def create_app(
    db_path: str | Path | None = None,
    *,
    enable_dispatcher: bool = True,
    static_dir: str | Path | None = None,
    attachments_dir: str | Path | None = None,
    llm_client=_UNSET,
    embed_client=_UNSET,
    enable_triage: bool | None = None,
    enable_wiki_compile: bool | None = None,
    enable_mcp: bool | None = None,
    enable_api_limits: bool = True,
    docs: bool | None = None,
) -> FastAPI:
    load_dotenv()
    installation_language()
    ai_language()  # Ongeldige uitvoertaal vóór appstart weigeren.
    db_path = db_path if db_path is not None else env("BETONNING_DB", DEFAULT_DB_PATH)
    # OpenAPI-docs standaard dicht (BETON-379): alles is publiek bereikbaar, dus
    # /docs, /redoc en /openapi.json gaven anoniem het hele endpoint-overzicht weg.
    show_docs = docs_enabled() if docs is None else docs
    app = FastAPI(
        title="Hegemone",
        version="0.1.0",
        description="Kanban, tickets and shared knowledge for people and agents.",
        lifespan=lifespan,
        docs_url="/docs" if show_docs else None,
        redoc_url="/redoc" if show_docs else None,
        openapi_url="/openapi.json" if show_docs else None,
    )

    installation_runtime.initialize(app)
    app.state.runtime_overrides = {}
    for name, value in [('llm_client', llm_client), ('embed_client', embed_client)]:
        if value is not _UNSET:
            app.state.runtime_overrides[name] = value
    for name, value in [('enable_triage', enable_triage), ('enable_wiki_compile', enable_wiki_compile)]:
        if value is not None:
            app.state.runtime_overrides[name] = value
    app.state.db_path = str(db_path)
    app.state.enable_api_limits = enable_api_limits
    app.state.mcp_stats = mcp_stats.McpStats()
    # Attachments-bytes staan naast de DB tenzij expliciet gezet (op prod dus
    # /var/lib/betonning/attachments — al binnen ReadWritePaths).
    resolved_att = (
        attachments_dir
        or env("BETONNING_ATTACHMENTS_DIR")
        or (Path(db_path).parent / "attachments")
    )
    app.state.attachments_dir = str(resolved_att)
    # LLM-client (verrijking, later ook triage-bot): uit env tenzij expliciet
    # meegegeven (tests injecteren een fake of None).
    app.state.llm_client = (
        llm_module.client_from_env() if llm_client is _UNSET else llm_client
    )
    app.state.embed_client = (
        embeddings_module.client_from_env() if embed_client is _UNSET else embed_client
    )
    # Per-user token-bucket voor de LLM-endpoints (BETON-387). Aan app.state en
    # niet aan een module-global: elke TestClient start zo met een schone
    # limiter, terwijl het in productie (één uvicorn-worker) nog steeds de hele
    # installatie dekt. De ingebouwde triage-worker komt hier niet langs — die
    # roept de client rechtstreeks aan en heeft zijn eigen dagbudget.
    app.state.llm_rate_limiter = ratelimit_module.RateLimiter()
    app.state.webhook_test_limiter = ratelimit_module.RateLimiter()
    # Triage-bot standaard uit; aan via env of expliciet (create_app-arg).
    if enable_triage is None:
        enable_triage = env("BETONNING_TRIAGE_ENABLED", "").lower() in (
            "1", "true", "yes", "on",
        )
    app.state.enable_triage = enable_triage
    app.state.triage_debounce = int(
        env("BETONNING_TRIAGE_DEBOUNCE", triage_worker.DEFAULT_DEBOUNCE_SECONDS)
    )
    app.state.triage_interval = int(
        env("BETONNING_TRIAGE_INTERVAL", triage_worker.DEFAULT_INTERVAL_SECONDS)
    )
    # Wiki-compiler (BETON-24) standaard uit; aan via env of expliciet.
    if enable_wiki_compile is None:
        enable_wiki_compile = env("BETONNING_WIKI_COMPILE_ENABLED", "").lower() in (
            "1", "true", "yes", "on",
        )
    app.state.enable_wiki_compile = enable_wiki_compile
    app.state.wiki_compile_debounce = int(
        env("BETONNING_WIKI_COMPILE_DEBOUNCE", wiki_compiler.DEFAULT_DEBOUNCE_SECONDS)
    )
    app.state.wiki_compile_interval = int(
        env("BETONNING_WIKI_COMPILE_INTERVAL", wiki_compiler.DEFAULT_INTERVAL_SECONDS)
    )
    app.state.enable_dispatcher = enable_dispatcher
    app.state.deferred_interval = int(
        env("BETONNING_DEFERRED_INTERVAL", deferred_worker.DEFAULT_INTERVAL_SECONDS)
    )
    app.add_exception_handler(StarletteHTTPException, localized_http_error)
    app.add_exception_handler(RequestValidationError, localized_validation_error)
    app.add_exception_handler(sqlite3.IntegrityError, database_integrity_error)
    app.include_router(api_router)

    # Body-size-limiet (BETON-380): weigert een te grote body vóór de app hem
    # leest. Multipart krijgt een ruimere cap dan JSON (zie bodylimit.py).
    app.add_middleware(installation_runtime.RuntimeContextMiddleware, owner=app)
    app.add_middleware(bodylimit.BodySizeLimitMiddleware)
    app.add_middleware(resource_limits.ResourceGuardMiddleware, owner=app)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/kickstart", tags=["meta"])
    def kickstart() -> dict:
        return kickstart_payload()

    @app.head("/kickstart", include_in_schema=False)
    def kickstart_head() -> Response:
        return Response(media_type="application/json")

    # MCP-server (BETON-24) op /mcp: memory-provider voor MCP-native agents.
    # Vóór de static-catch-all zodat /mcp voorrang houdt. Optioneel: alleen als de
    # 'mcp'-extra geïnstalleerd is (de dev/prod-venv heeft die; anders overgeslagen).
    if enable_mcp is None:
        enable_mcp = env("BETONNING_MCP_MOUNT", "1").lower() in (
            "1", "true", "yes", "on",
        )
    app.state.mcp = _mount_mcp(app) if enable_mcp else None

    # De gebouwde Svelte-UI (ui/ → static/) als die er is. Als laatste gemount
    # zodat /api/v1 en /health voorrang houden; html=True serveert index.html.
    resolved = Path(static_dir) if static_dir is not None else DEFAULT_STATIC_DIR
    if resolved.is_dir():
        app.mount("/", _UICache(directory=str(resolved), html=True), name="ui")

    app.add_middleware(
        SecurityHeadersMiddleware,
        # Swagger UI/ReDoc draaien op een inline script + CDN; onder de CSP zou
        # dat een blanco pagina geven. De overige headers gelden er wél.
        csp_exempt=("/docs", "/redoc") if show_docs else (),
    )
    return app


class RequireBearer:
    """ASGI-poort vóór de MCP-mount: geen geldige Bearer-key → 401 (BETON-381).

    Zonder deze poort accepteert de streamable-http-transport een `initialize`
    zónder header en bestaat er dus een anonieme MCP-sessie; de tools vielen dan
    terug op de service-key. De check zit op de mount (niet in de tools) zodat er
    per constructie geen sessie ontstaat om mee te beginnen.

    Eigen connectie per request: dit draait buiten de FastAPI-dependency-boom, dus
    `deps.get_db` is hier niet beschikbaar.
    """

    def __init__(self, app, inner):
        self.app = app  # de FastAPI-app: draagt state.db_path
        self.inner = inner
        self._initialize_lock = asyncio.Lock()

    @staticmethod
    async def _deny(send, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    def _handle(self, key: str, conn=None) -> tuple[str, int, str] | None:
        owns_connection = conn is None
        conn = conn or db_module.connect(self.app.state.db_path)
        try:
            row = users_repo.get_by_api_key(conn, key)
            return (row["handle"], row["id"], row["api_key_hash"]) if row is not None else None
        finally:
            if owns_connection:
                conn.close()

    async def _count(self, scope, receive, handle: str):
        """Tel de request per JSON-RPC-methode (BETON-467). Leest de body voor
        POST, buffert de berichten en geeft een `receive` terug die ze opnieuw
        afspeelt, zodat de app de stream ongemoeid krijgt. Nooit loggen."""
        stats = self.app.state.mcp_stats
        http_method = scope.get("method", "?")
        if http_method != "POST":
            stats.record(http_method, None, handle)
            return receive
        buffered, body, size, more = [], b"", 0, True
        while more and size <= mcp_stats.MAX_PEEK_BYTES:
            msg = await receive()
            buffered.append(msg)
            if msg["type"] != "http.request":
                more = False
                break
            body += msg.get("body", b"")
            size += len(msg.get("body", b""))
            more = msg.get("more_body", False)
        rpc = mcp_stats.method_of(body) if not more else "?"
        stats.record(http_method, rpc, handle)

        async def replay():
            if buffered:
                return buffered.pop(0)
            return await receive()

        return replay

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":  # lifespan e.d. ongemoeid doorlaten
            await self.inner(scope, receive, send)
            return
        auth = Headers(scope=scope).get("authorization", "")
        if not auth.lower().startswith("bearer "):
            await self._deny(send, "Ontbrekende API-key")
            return
        identity = self._handle(auth[7:].strip(), scope.get("state", {}).get("db_conn"))
        if identity is None:
            await self._deny(send, "Ongeldige API-key")
            return
        handle, user_id, fingerprint = identity
        from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
        from mcp.server.auth.provider import AccessToken
        # De SDK bindt sessies aan deze identiteit. Ook rotatie verandert haar.
        scope = dict(scope, user=AuthenticatedUser(AccessToken(
            token=fingerprint, client_id=fingerprint, subject=str(user_id), scopes=["mcp"],
        )))
        receive = await self._count(scope, receive, handle)
        if scope.get("method") == "POST" and not Headers(scope=scope).get("mcp-session-id"):
            async with self._initialize_lock:
                manager = self.app.state.mcp.session_manager
                # Begrens per key naast de globale SDK-limiet (SDK 1.30.x).
                count = sum(owner["client_id"] == fingerprint
                            for owner in manager._session_owners.values())
                if count >= 16:
                    body = b'{"detail":"Te veel MCP-sessies voor deze identiteit"}'
                    await send({"type": "http.response.start", "status": 429,
                                "headers": [(b"content-type", b"application/json"), (b"retry-after", b"300")]})
                    await send({"type": "http.response.body", "body": body})
                    return
                await self.inner(scope, receive, send)
        else:
            await self.inner(scope, receive, send)


def _mount_mcp(app: FastAPI):
    """Mount de MCP-server op /mcp en geef de FastMCP-instance terug (of None als
    de 'mcp'-extra niet geïnstalleerd is)."""
    try:
        from . import mcp_server
    except ImportError:
        return None
    mcp = mcp_server.build_server()
    # streamable_http_app() bouwt een Starlette-subapp met een interne route op
    # streamable_http_path; met "/" wordt het endpoint /mcp/ (mount + interne root).
    # De session-manager (lazy) runt in de lifespan. Agents gebruiken de URL mét
    # trailing slash: http://<host>/mcp/.
    mcp.settings.streamable_http_path = "/"
    app.mount("/mcp", app=RequireBearer(app, mcp.streamable_http_app()))
    return mcp


# Module-level app voor `uvicorn betonning.server:app`.
app = create_app()
