"""Vroege authenticatie, duurzame schrijfquota en begrensde API/streamlast."""

from __future__ import annotations

from .api_error_codes import error_payload

from collections import Counter
import hmac
from urllib.parse import urlsplit
from starlette.requests import Request
from . import db as dbm, credential_policy, security, bodylimit, setup_policy
from .ratelimit import RateLimiter
from .repo import users, browser_sessions, resource_usage


class WriteQuotaExceeded(Exception):
    """De body mag de applicatie niet bereiken nadat het schrijfbudget op is."""


class ResourceGuardMiddleware:
    def __init__(self, app, owner):
        self.app, self.owner = app, owner
        self.rate = RateLimiter()
        self.streams: Counter[int] = Counter()
        self.writes: Counter[int] = Counter()
        self.uploads: Counter[int] = Counter()
        self.denied: Counter[int] = Counter()
        owner.state.resource_metrics = self

    async def reject(self, send, status, detail):
        import json

        self.denied[status] += 1
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", b"60"),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": json.dumps(error_payload(detail)).encode(),
            }
        )

    def principal(self, scope, *, write):
        request = Request(scope)
        auth = request.headers.get("authorization", "")
        raw_session = request.cookies.get(browser_sessions.COOKIE)
        raw_media = request.cookies.get("bt_media") if not write else None
        if not auth and not raw_session and not raw_media:
            return None
        if len(auth) > 256:
            return None
        conn = dbm.connect(self.owner.state.db_path)
        scope.setdefault("state", {})["db_conn"] = conn
        if auth.lower().startswith("bearer "):
            return users.get_by_api_key(conn, auth[7:].strip())
        if auth:
            return None
        session = browser_sessions.resolve(conn, raw_session)
        if session:
            if write:
                origin = request.headers.get("origin")
                token = request.headers.get("x-csrf-token", "")
                if (
                    origin
                    and urlsplit(origin).netloc.lower() != request.url.netloc.lower()
                ):
                    raise PermissionError("Ongeldige herkomst van browsermutatie")
                if not token.isascii() or not hmac.compare_digest(
                    token, browser_sessions.csrf(raw_session)
                ):
                    raise PermissionError("Ontbrekend of ongeldig CSRF-token")
            return session[0]
        media = security.verify_media_token(raw_media)
        if media:
            user = users.get(conn, media[0])
            if user is not None and credential_policy.valid(user) and hmac.compare_digest(
                (user["api_key_hash"] or "")[:16], media[1]
            ):
                return user
        return None

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not self.owner.state.enable_api_limits:
            await self.app(scope, receive, send)
            return
        write = scope.get("method") not in ("GET", "HEAD", "OPTIONS")
        if not path.startswith(("/api/v1", "/mcp")):
            if write:
                await self.reject(send, 405, "Deze route accepteert geen mutaties")
            else:
                await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        try:
            limit = bodylimit.BodySizeLimitMiddleware(self.app)._limit_for(headers)
            if int(headers.get(b"content-length", b"0")) > limit:
                await bodylimit._send_413(send)
                return
        except ValueError:
            pass
        if path == "/api/v1/setup" and scope.get("method") == "POST":
            error = setup_policy.authorize(Request(scope))
            if error:
                await self.reject(send, *error)
                return
            if self.rate.check("installation", rate_per_hour=10, burst=3):
                await self.reject(send, 429, "Te veel installatieverzoeken")
                return
            await self.app(scope, receive, send)
            return
        leased, working, uploading = False, False, False
        ident = 0
        try:
            try:
                user = self.principal(scope, write=write)
            except PermissionError as exc:
                await self.reject(send, 403, str(exc))
                return
            if write and user is None:
                detail = (
                    (
                        "Ongeldige API-key"
                        if headers.get(b"authorization")
                        else "Ontbrekende API-key"
                    )
                    if path.startswith("/mcp")
                    else "Aanmelding vereist vóór het verwerken van de body"
                )
                await self.reject(send, 401, detail)
                return
            if user is None:
                await self.app(scope, receive, send)
                return
            ident = user["id"]
            factor = 3 if user["kind"] == "human" else 1
            upload = write and path.endswith(("/attachments", "/avatar"))
            category = (
                "upload"
                if upload
                else (
                    "mcp" if path.startswith("/mcp") else ("write" if write else "read")
                )
            )
            rate, burst = {
                "upload": (30, 10),
                "write": (600, 120),
                "read": (6000, 300),
                "mcp": (3600, 120),
            }[category]
            reset = (
                path.startswith("/api/v1/security-usage/") and user["kind"] == "human"
            )
            if not reset and self.rate.check(
                f"{ident}:{category}", rate_per_hour=rate * factor, burst=burst * factor
            ):
                await self.reject(
                    send, 429, "Verzoeklimiet bereikt; probeer later opnieuw"
                )
                return
            if write and not path.startswith("/mcp"):
                if self.writes[ident] >= 8 or sum(self.writes.values()) >= 16:
                    await self.reject(send, 429, "Te veel gelijktijdige mutaties")
                    return
                self.writes[ident] += 1
                working = True
            if upload:
                if self.uploads[ident] >= 2 or sum(self.uploads.values()) >= 4:
                    await self.reject(send, 429, "Te veel gelijktijdige uploads")
                    return
                self.uploads[ident] += 1
                uploading = True
            streaming = not write and (
                path.endswith("/events/stream") or path.startswith("/mcp")
            )
            if streaming:
                if self.streams[ident] >= 8 or sum(self.streams.values()) >= 64:
                    await self.reject(send, 429, "Te veel gelijktijdige streams")
                    return
                self.streams[ident] += 1
                leased = True
            total = 0
            conn = scope["state"]["db_conn"]
            claimed = False

            async def counted_receive():
                nonlocal total, claimed
                message = await receive()
                if write and message["type"] == "http.request":
                    total += len(message.get("body", b""))
                    if not message.get("more_body", False) and not claimed:
                        claimed = True
                        reset = (
                            path.startswith("/api/v1/security-usage/")
                            and user["kind"] == "human"
                        )
                        if not reset and not resource_usage.claim(conn, user, total):
                            raise WriteQuotaExceeded()
                return message

            try:
                await self.app(scope, counted_receive, send)
            except WriteQuotaExceeded:
                await self.reject(
                    send,
                    429,
                    "Schrijfquota bereikt; een mens kan het budget herstellen",
                )
        finally:
            if working:
                self.writes[ident] -= 1
                if not self.writes[ident]:
                    del self.writes[ident]
            if uploading:
                self.uploads[ident] -= 1
                if not self.uploads[ident]:
                    del self.uploads[ident]
            if leased:
                self.streams[ident] -= 1
                if not self.streams[ident]:
                    del self.streams[ident]
            conn = scope.get("state", {}).pop("db_conn", None)
            if conn is not None:
                conn.close()
