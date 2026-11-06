"""API-key generatie en hashing + media-toegangstokens.

We slaan nooit de ruwe key op — alleen de sha256-hex. De client stuurt de key
als Bearer-token; de server hasht en zoekt de user op de hash.

Media-tokens (BETON-202): de attachment-/avatar-serve-routes zijn auth-loze
capability-URL's zodat een `<img>` in de browser werkt. Publiek bereikbaar zou
dat betekenen dat iedereen met de URL de bytes kan ophalen. Een HMAC-getekend,
verlopend media-token in een HttpOnly-cookie schermt die routes af zónder de
URL's te veranderen: de browser stuurt het cookie same-origin automatisch mee,
agents/`bt`/MCP blijven de Bearer-key gebruiken.
"""

from __future__ import annotations

from .config import env

import hashlib
import hmac
import secrets
import time


def generate_api_key() -> str:
    """Genereer een nieuwe, URL-veilige API-key."""
    return "bt_" + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    """Hash een API-key naar sha256-hex voor opslag/vergelijking."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# Random per-proces fallback-secret als BETONNING_MEDIA_SECRET niet gezet is.
# Cookies overleven dan geen herstart (de UI herzet ze bij de volgende boot);
# op prod hoort het secret expliciet gezet te zijn zodat cookies restarts overleven.
_MEDIA_SECRET_FALLBACK = secrets.token_urlsafe(32)


def _media_secret() -> str:
    return env("BETONNING_MEDIA_SECRET") or _MEDIA_SECRET_FALLBACK


def _media_sig(msg: str) -> str:
    return hmac.new(_media_secret().encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_media_token(expires_at: int, user_id: int, key_fragment: str) -> str:
    """Getekend media-token ``<exp>.<user_id>.<fragment>.<hmac>``.

    Sinds BETON-383 draagt het token *wie* het cookie kreeg (`user_id`) en een
    fragment van diens `api_key_hash`. Daarmee is het cookie intrekbaar: rouleert
    de key of wordt de user gedeactiveerd, dan valt de cookie-toegang om zonder
    dat er een aparte intrekkingslijst nodig is (zie `deps.require_media_access`).

    Het oude 2-delige formaat (`<exp>.<hmac>`) wordt niet meer geaccepteerd. Dat
    ongeldigt bestaande cookies; de UI zet het cookie bij elke boot opnieuw, dus
    dat kost hooguit één boot.
    """
    msg = f"{int(expires_at)}.{int(user_id)}.{key_fragment}"
    return f"{msg}.{_media_sig(msg)}"


def verify_media_token(
    token: str | None, *, now: int | None = None
) -> tuple[int, str] | None:
    """``(user_id, key_fragment)`` bij een geldig, niet-verlopen token; anders None.

    Constante-tijd-vergelijking van de handtekening; ``now`` injecteerbaar voor
    tests (default = huidige unix-tijd)."""
    if not token or not token.isascii() or len(token) > 512:
        return None
    parts = token.split(".")
    if len(parts) != 4:
        return None
    raw_exp, raw_user_id, fragment, sig = parts
    msg = f"{raw_exp}.{raw_user_id}.{fragment}"
    if not hmac.compare_digest(sig, _media_sig(msg)):
        return None
    try:
        exp = int(raw_exp)
        user_id = int(raw_user_id)
    except ValueError:
        return None
    current = int(time.time()) if now is None else now
    if current >= exp:
        return None
    return user_id, fragment
