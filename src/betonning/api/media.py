"""Media-toegangscookie (BETON-202).

De browser kan geen Bearer-header op een `<img>` zetten, dus schermen we de
auth-loze attachment-/avatar-serve-routes af met een HttpOnly media-cookie. Dit
endpoint zet dat cookie voor de ingelogde user; de serve-routes accepteren het
naast de gewone Bearer-key (zie `deps.require_media_access`).
"""

from __future__ import annotations

import sqlite3
import time

from fastapi import APIRouter, Depends, Request, Response

from .. import security
from ..deps import get_db
from ..repo import browser_sessions
from ..deps import (
    MEDIA_COOKIE_NAME,
    MEDIA_COOKIE_PATH,
    MEDIA_COOKIE_TTL,
    current_user,
    media_key_fragment,
)

router = APIRouter(tags=["media"])


def _is_https(request: Request) -> bool:
    """Schema van de oorspronkelijke request: `X-Forwarded-Proto` van de reverse
    proxy, anders het schema waarop we hem binnenkregen."""
    forwarded = request.headers.get("x-forwarded-proto")
    scheme = forwarded.split(",")[0].strip() if forwarded else request.url.scheme
    return scheme == "https"


@router.post("/media-cookie")
def set_media_cookie(
    request: Request,
    response: Response,
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    """Zet het media-toegangscookie voor de ingelogde user (Bearer-auth).

    HttpOnly + SameSite=Strict; de `Secure`-vlag volgt het schema van de
    binnenkomende request (`X-Forwarded-Proto` van de reverse proxy, anders
    `request.url.scheme`), zodat het cookie zowel op LAN-http als publiek-https
    werkt. De UI roept dit bij elke boot aan."""
    exp = int(time.time()) + MEDIA_COOKIE_TTL
    token = security.sign_media_token(exp, user["id"], media_key_fragment(user))
    response.set_cookie(
        key=MEDIA_COOKIE_NAME,
        value=token,
        max_age=MEDIA_COOKIE_TTL,
        httponly=True,
        samesite="strict",
        secure=_is_https(request),
        path=MEDIA_COOKIE_PATH,
    )
    return {"status": "ok"}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    _: sqlite3.Row = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Wis het media-cookie (BETON-383).

    De browser bewaart de key zelf in localStorage; die wist de UI lokaal. Het
    media-cookie is HttpOnly en kan alleen de server weghalen — zonder dit
    endpoint bleef het na uitloggen gewoon staan tot het verliep. De attributen
    moeten die van `set_cookie` spiegelen, anders matcht de browser het cookie
    niet en blijft het staan."""
    browser_sessions.revoke(conn, request.cookies.get(browser_sessions.COOKIE))
    response.delete_cookie(browser_sessions.COOKIE, path="/api/v1", httponly=True, samesite="strict", secure=_is_https(request))
    response.delete_cookie(
        key=MEDIA_COOKIE_NAME,
        path=MEDIA_COOKIE_PATH,
        httponly=True,
        samesite="strict",
        secure=_is_https(request),
    )
    return {"status": "ok"}
