"""Body-size-limiet als pure ASGI-middleware (BETON-380).

Zonder limiet accepteert de app een JSON-body van willekeurige grootte: Starlette
leest hem volledig in het geheugen vóór de handler iets ziet. Eén request van een
paar honderd MB is genoeg om de LXC (44-64 MB RSS) om te duwen.

Twee caps, want de twee soorten verkeer zijn niet vergelijkbaar:

- **JSON en de rest**: `DEFAULT_MAX_BODY` (2 MiB, `BETONNING_MAX_BODY`). Ruim
  boven het grootste legitieme veld — `description_md` haalt ~53k tekens, wiki-
  bodies en `plan_md` zitten in de 60k-range.
- **multipart/form-data**: `MAX_SIZE` van een attachment plus wat slack voor de
  multipart-omhulling. Het plan wilde multipart overslaan, maar dán is er nergens
  een grootte-check *vóór* het inlezen: Starlette's multipart-parser consumeert de
  hele body (en spoolt boven ~1 MiB naar disk) voordat de handler draait. Een
  ruimere cap in plaats van géén cap maakt de check echt zonder uploads te breken.

Pure ASGI-wrapper i.p.v. `BaseHTTPMiddleware`: die maakt de chunked-tak onnodig
omslachtig. `content-length` kan te grote verzoeken direct afwijzen. Werkelijk ontvangen
bytes worden daarnaast altijd geteld. Hoogstens vier bodies worden tegelijk
gebufferd, met een ontvangstdrempel van 15 seconden.
"""

from __future__ import annotations

from .config import env
from .api_error_codes import error_payload
import json

import asyncio

DEFAULT_MAX_BODY = 2 * 1024 * 1024  # 2 MiB voor JSON en overig
MULTIPART_SLACK = 1024 * 1024  # ruimte voor multipart-headers/boundaries


async def _send_413(send) -> None:
    body = json.dumps(error_payload("Body te groot")).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitMiddleware:
    """Weiger requests met een te grote body (413), vóór de app hem leest."""

    def __init__(
        self, app, *, max_body: int | None = None, multipart_max: int | None = None
    ):
        self.app = app
        self._max_body = max_body
        self._multipart_max = multipart_max
        self._inflight = 0

    @property
    def max_body(self) -> int:
        if self._max_body is not None:
            return self._max_body
        return int(env("BETONNING_MAX_BODY", DEFAULT_MAX_BODY))

    @property
    def multipart_max(self) -> int:
        if self._multipart_max is not None:
            return self._multipart_max
        # Lazy import: repo.attachments trekt geen app-state mee, maar zo blijft
        # de limiet één bron met de upload-handler.
        from .repo import attachments as attachments_repo

        return attachments_repo.MAX_SIZE + MULTIPART_SLACK

    def _limit_for(self, headers: dict[bytes, bytes]) -> int:
        content_type = headers.get(b"content-type", b"").lower()
        if b"multipart/form-data" in content_type:
            return self.multipart_max
        return self.max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        limit = self._limit_for(headers)

        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                if int(raw_length) > limit:
                    await _send_413(send)
                    return
            except ValueError:
                pass
        if scope.get("method", "GET").upper() in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        if self._inflight >= 4:
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", b"1"),
                    ],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": json.dumps(
                        error_payload("Te veel gelijktijdige bodies")
                    ).encode(),
                }
            )
            return
        self._inflight += 1
        reading = True
        try:
            # Tel werkelijk ontvangen bytes, ook bij een onjuiste Content-Length.
            # Coalescen voorkomt een onbegrensde lijst met piepkleine chunks.
            body = bytearray()
            try:
                async with asyncio.timeout(15):
                    while True:
                        message = await receive()
                        if message["type"] != "http.request":
                            return
                        body.extend(message.get("body", b""))
                        if len(body) > limit:
                            await _send_413(send)
                            return
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                await send(
                    {"type": "http.response.start", "status": 408, "headers": []}
                )
                await send({"type": "http.response.body", "body": b""})
                return
            pending: bytes | None = bytes(body)
            body.clear()
            self._inflight -= 1
            reading = False

            async def replaying_receive():
                nonlocal pending
                if pending is not None:
                    data, pending = pending, None
                    return {"type": "http.request", "body": data, "more_body": False}
                return await receive()

            await self.app(scope, replaying_receive, send)
        finally:
            if reading:
                self._inflight -= 1
