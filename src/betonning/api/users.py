"""Agent-/user-beheer (BETON-72): CRUD voorbehouden aan de mens (current_human).

Aanmaken geeft de ruwe API-key ÉÉN keer terug (voor de Hermes-config); daarna
wordt alleen de hash bewaard. Deactiveren is een soft-delete (active=0), geen
hard-delete: users worden gerefereerd door items/comments/events."""

from __future__ import annotations

import sqlite3
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field, field_validator, model_validator

from .. import db as db_module
from .. import storage
from .. import uploads, webhooks
from ..media_headers import media_headers
from ..deps import current_human, get_attachments_dir, get_db, require_media_access
from ..repo import attachments as attachments_repo
from ..repo import users as users_repo

router = APIRouter(tags=["users"])

_KINDS = ("human", "agent")
_AGENT_TYPES = ("coding", "hermes")


class UserCreate(BaseModel):
    handle: str
    display_name: str = Field(max_length=120)
    kind: str = "agent"
    agent_type: str | None = None
    description: str | None = Field(default=None, max_length=4000)
    webhook_url: str | None = Field(default=None, max_length=2048)
    webhook_secret: str | None = None

    @field_validator("handle")
    @classmethod
    def _norm_handle(cls, v: str) -> str:
        return users_repo.validate_handle(v)

    @field_validator("display_name")
    @classmethod
    def _norm_name(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("display_name mag niet leeg zijn")
        return v.strip()

    @field_validator("kind")
    @classmethod
    def _norm_kind(cls, v: str) -> str:
        v = (v or "agent").strip().lower()
        if v not in _KINDS:
            raise ValueError(f"kind moet één van {_KINDS} zijn")
        return v

    @field_validator("agent_type")
    @classmethod
    def _norm_agent_type(cls, v):
        if v is None:
            return v
        v = v.strip().lower()
        if v not in _AGENT_TYPES:
            raise ValueError(f"agent_type moet één van {_AGENT_TYPES} zijn")
        return v

    @model_validator(mode="after")
    def _agent_type_requires_agent_kind(self):
        if self.agent_type is not None and self.kind != "agent":
            raise ValueError("agent_type mag alleen gezet worden als kind='agent'")
        return self


class UserUpdate(BaseModel):
    api_key_expires_at: str | None = None
    api_key_scopes: list[str] | None = None
    api_key_projects: list[str] | None = None

    @field_validator("api_key_scopes")
    @classmethod
    def valid_scopes(cls, value):
        from ..credential_policy import SCOPES

        if value is not None and (
            len(value) > 5 or any(s not in SCOPES for s in value)
        ):
            raise ValueError("Onbekende credentialscope")
        return value

    @field_validator("api_key_projects")
    @classmethod
    def valid_projects(cls, value):
        if value is None:
            return None
        if len(value) > 100 or any(
            not re.fullmatch(r"[A-Z0-9]{1,20}", key) for key in value
        ):
            raise ValueError("Ongeldige projectscopes")
        return value

    @field_validator("api_key_expires_at")
    @classmethod
    def valid_expiry(cls, value):
        if value is None:
            return None
        until = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if until.tzinfo is None:
            raise ValueError("Vervaldatum vereist een tijdzone")
        return until.isoformat()

    display_name: str | None = Field(default=None, max_length=120)
    kind: str | None = None
    agent_type: str | None = None
    description: str | None = Field(default=None, max_length=4000)
    active: bool | None = None
    webhook_url: str | None = Field(default=None, max_length=2048)
    webhook_secret: str | None = None

    @field_validator("kind")
    @classmethod
    def _norm_kind(cls, v):
        if v is None:
            return v
        v = v.strip().lower()
        if v not in _KINDS:
            raise ValueError(f"kind moet één van {_KINDS} zijn")
        return v

    @field_validator("agent_type")
    @classmethod
    def _norm_agent_type(cls, v):
        if v is None:
            return v
        v = v.strip().lower()
        if v not in _AGENT_TYPES:
            raise ValueError(f"agent_type moet één van {_AGENT_TYPES} zijn")
        return v

    # Let op: of `agent_type` samen met `kind='human'` mag, hangt bij een PATCH
    # ook af van de bestáánde kind van de target-user (die dit pure model niet
    # kent) — die combinatie-check gebeurt daarom in de route (update_user).


def _check_webhook_url(url: str | None) -> None:
    """422 als de URL niet door de webhook-poort komt (BETON-378). Leeg = wissen,
    dat mag altijd. Deze route blijft de plek waar een mens de webhook van een
    Hermes-agent zet (BETON-83/84) — alleen het doel wordt begrensd."""
    reason = webhooks.webhook_url_error(url)
    if reason is not None:
        raise HTTPException(status_code=422, detail=reason)


@router.post("/users", status_code=201)
def create_user(
    body: UserCreate,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    """Maak een user/agent aan; geeft de ruwe api_key ÉÉN keer terug. 409 bij
    een dubbele handle."""
    if users_repo.get_by_handle(conn, body.handle) is not None:
        raise HTTPException(status_code=409, detail=f"Handle @{body.handle} bestaat al")
    _check_webhook_url(body.webhook_url)
    try:
        user, api_key = users_repo.create(
            conn,
            handle=body.handle,
            display_name=body.display_name,
            kind=body.kind,
            agent_type=body.agent_type,
            description=body.description,
            webhook_url=body.webhook_url,
            webhook_secret=body.webhook_secret,
        )
    except sqlite3.IntegrityError as exc:  # race op de unieke handle
        raise HTTPException(
            status_code=409, detail=f"Handle @{body.handle} bestaat al"
        ) from exc
    # De ruwe key alleen hier — nooit meer opvraagbaar.
    return {**user, "api_key": api_key}


@router.patch("/users/{handle}")
def update_user(
    handle: str,
    body: UserUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    """Werk display_name/kind/agent_type/description/active/webhook bij. 404 bij
    onbekende handle, 422 als agent_type gezet wordt op een (bestaande of
    nieuwe) kind='human'."""
    target = users_repo.get_by_handle(conn, handle)
    if target is None:
        raise HTTPException(status_code=404, detail="Onbekende user")
    updates = body.model_dump(exclude_unset=True)
    if "webhook_url" in updates:
        _check_webhook_url(updates["webhook_url"])
    if updates.get("agent_type") is not None:
        effective_kind = updates.get("kind", target["kind"])
        if effective_kind != "agent":
            raise HTTPException(
                status_code=422,
                detail="agent_type mag alleen gezet worden als kind='agent'",
            )
    fresh = users_repo.admin_update(conn, target["id"], updates)
    return users_repo.serialize_admin(fresh)


@router.get("/users/{handle}")
def get_user(
    handle: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    """Detail incl. `webhook_url` (BETON-113) — mens-only, zodat de beheer-UI
    de URL kan voorinvullen. `webhook_secret` blijft ook hier write-only."""
    target = users_repo.get_by_handle(conn, handle)
    if target is None:
        raise HTTPException(status_code=404, detail="Onbekende user")
    return users_repo.serialize_admin(target)


@router.post("/users/{handle}/api-key/rotate")
def rotate_user_api_key(
    handle: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    """Roteer de API-key van een user. Human-only; de nieuwe ruwe key komt
    precies één keer terug en de oude key is direct ongeldig."""
    with db_module.transaction(conn):
        try:
            rotated = users_repo.rotate_api_key(conn, handle)
        except users_repo.VirtualUserError:
            raise HTTPException(
                status_code=422, detail="Een virtuele queue heeft geen API-key"
            ) from None
    if rotated is None:
        raise HTTPException(status_code=404, detail="Onbekende user")
    user, api_key = rotated
    return {**user, "api_key": api_key}


@router.delete("/users/{handle}", status_code=204)
def delete_user(
    handle: str,
    conn: sqlite3.Connection = Depends(get_db),
    human: sqlite3.Row = Depends(current_human),
) -> None:
    """Deactiveer een user (soft-delete, active=0). 404 bij onbekende handle;
    400 als de mens zichzelf probeert te deactiveren (zou uitsluiten)."""
    target = users_repo.get_by_handle(conn, handle)
    if target is None:
        raise HTTPException(status_code=404, detail="Onbekende user")
    if target["id"] == human["id"]:
        raise HTTPException(status_code=400, detail="Je kunt jezelf niet deactiveren")
    users_repo.deactivate(conn, target["id"])


# --- Avatar (BETON-71) -----------------------------------------------------
# Upload/delete zijn human-only (agent-beheer). De serve-route heeft bewust géén
# auth: een <img> kan geen Bearer meesturen. De bytes staan content-addressed op
# disk (gedeeld met attachments); we hergebruiken de afbeeldings-whitelist en
# -groottelimiet uit repo/attachments.


@router.post("/users/{handle}/avatar")
async def upload_avatar(
    handle: str,
    file: UploadFile,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
    base: str = Depends(get_attachments_dir),
) -> dict:
    """Zet (of vervang) de avatar van een user. Human-only. 404 bij onbekende
    handle, 415 bij een niet-afbeelding, 413 als het bestand te groot is."""
    target = users_repo.get_by_handle(conn, handle)
    if target is None:
        raise HTTPException(status_code=404, detail="Onbekende user")
    data = await uploads.read_limited(file, attachments_repo.MAX_SIZE)
    if not data:
        raise HTTPException(status_code=422, detail="Leeg bestand")
    # Magic bytes beslissen, niet de geclaimde header (BETON-380).
    content_type = attachments_repo.sniff_image_type(data[:16])
    if content_type is None:
        raise HTTPException(
            status_code=415,
            detail=f"Type niet toegestaan: {file.content_type or 'onbekend'}",
        )

    sha = storage.sha256_hex(data)
    storage.write_bytes(base, sha, data)
    with db_module.transaction(conn):
        fresh = users_repo.set_avatar(
            conn, target["id"], sha256=sha, content_type=content_type
        )
    return users_repo.serialize(fresh)


@router.get("/users/{handle}/avatar")
def serve_avatar(
    handle: str,
    conn: sqlite3.Connection = Depends(get_db),
    base: str = Depends(get_attachments_dir),
    _: None = Depends(require_media_access),
) -> Response:
    # Media-afgeschermd (BETON-202): Bearer óf media-cookie zodat <img src> werkt
    # maar anonieme publieke bezoekers 401 krijgen. 404 als de user niet bestaat
    # of geen avatar heeft.
    target = users_repo.get_by_handle(conn, handle)
    if target is None or not target["avatar_sha256"]:
        raise HTTPException(status_code=404, detail="Geen avatar")
    data = storage.read_bytes(base, target["avatar_sha256"])
    if data is None:
        raise HTTPException(status_code=404, detail="Bytes ontbreken op disk")
    return Response(
        content=data,
        media_type=target["avatar_content_type"] or "application/octet-stream",
        headers=media_headers(f"{handle}-avatar", immutable=False),
    )


@router.delete("/users/{handle}/avatar")
def delete_avatar(
    handle: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    """Wis de avatar (terug naar initialen). Human-only. 404 bij onbekende handle.
    De bytes op disk blijven staan (content-addressed/dedup)."""
    target = users_repo.get_by_handle(conn, handle)
    if target is None:
        raise HTTPException(status_code=404, detail="Onbekende user")
    with db_module.transaction(conn):
        fresh = users_repo.clear_avatar(conn, target["id"])
    return users_repo.serialize(fresh)
