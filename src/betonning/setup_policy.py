"""Expliciete, eenmalige installatie-authenticatie vóór bodyverwerking."""
from __future__ import annotations

import hmac
import os
from urllib.parse import urlsplit

from starlette.requests import Request


def enabled() -> bool:
    token = os.environ.get('HEGEMONE_SETUP_TOKEN', '')
    return 32 <= len(token) <= 256 and token.isascii() and not any(c.isspace() for c in token)


def authorize(request: Request) -> tuple[int, str] | None:
    """Token is los van gewone credentials en gaat nooit in een URL."""
    if not enabled():
        return 503, 'Installatie is niet ingeschakeld; configureer een geldig setup-token'
    expected = os.environ['HEGEMONE_SETUP_TOKEN']
    supplied = request.headers.get('x-setup-token', '')
    if not supplied.isascii() or not hmac.compare_digest(expected, supplied):
        return 401, 'Ongeldig setup-token'
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).netloc.lower() != request.url.netloc.lower():
        return 403, 'Ongeldige herkomst van installatieverzoek'
    return None
