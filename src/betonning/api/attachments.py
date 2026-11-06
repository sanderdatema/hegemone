"""Attachments-endpoints: upload (multipart), serve (media-afgeschermd), lijst.

De serve-route gebruikt geen Bearer-dependency (een <img> in de browser kan geen
Authorization-header sturen), maar is sinds BETON-202 wél afgeschermd via
`require_media_access`: een geldige Bearer-key óf een HttpOnly media-cookie. De
URL blijft content-addressed op sha256 (ongewijzigd, dus geen markdown-breuk);
anonieme publieke bezoekers krijgen 401. Upload en lijst zijn Bearer-auth'd.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile

from .. import db as db_module
from .. import storage
from .. import uploads
from ..media_headers import media_headers
from ..deps import (
    current_user,
    get_attachments_dir,
    get_db,
    require_item as _require_item,
    require_media_access,
)
from ..repo import attachments as attachments_repo

router = APIRouter(tags=["attachments"])


@router.post("/items/{ref}/attachments", status_code=201)
async def upload_attachment(
    ref: str,
    file: UploadFile,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
    base: str = Depends(get_attachments_dir),
) -> dict:
    item = _require_item(conn, ref)
    data = await uploads.read_limited(file, attachments_repo.MAX_SIZE)
    if not data:
        raise HTTPException(status_code=422, detail="Leeg bestand")
    # De geclaimde Content-Type is een bewering van de client; de inhoud beslist
    # (BETON-380/374). Wat we sniffen is ook wat we opslaan.
    content_type = attachments_repo.sniff_type(data)
    if content_type is None:
        raise HTTPException(
            status_code=415,
            detail=f"Type niet toegestaan: {file.content_type or 'onbekend'}",
        )
    # `read_limited` bewaakt alleen de globale bovengrens; de scherpere per-type-
    # limiet kan pas ná het sniffen (BETON-374).
    limit = attachments_repo.limit_for(content_type)
    if len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"Bestand te groot voor {content_type} (max {limit // (1024 * 1024)} MB)",
        )

    sha = storage.sha256_hex(data)
    with db_module.transaction(conn):
        reason = attachments_repo.quota_error(
            conn, user["id"], item["project_id"], len(data)
        )
        if reason:
            raise HTTPException(413, reason)
        storage.write_bytes(base, sha, data)
        att = attachments_repo.create(
            conn,
            project_id=item["project_id"],
            item_id=item["id"],
            filename=file.filename or sha,
            content_type=content_type,
            size=len(data),
            sha256=sha,
            created_by=user["id"],
        )
    return att


@router.get("/items/{ref}/attachments")
def list_attachments(
    ref: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    item = _require_item(conn, ref)
    return attachments_repo.list_for_item(conn, item["id"])


@router.get("/attachments/{sha256}")
def serve_attachment(
    sha256: str,
    conn: sqlite3.Connection = Depends(get_db),
    base: str = Depends(get_attachments_dir),
    _: None = Depends(require_media_access),
) -> Response:
    # Content-addressed URL, afgeschermd met Bearer óf media-cookie (BETON-202):
    # de URL verandert niet (geen markdown-breuk), maar anonieme publieke
    # bezoekers krijgen 401. Onbekende hash → 404.
    row = attachments_repo.get_by_sha(conn, sha256)
    if row is None:
        raise HTTPException(status_code=404, detail="Onbekende attachment")
    data = storage.read_bytes(base, sha256)
    if data is None:
        raise HTTPException(status_code=404, detail="Bytes ontbreken op disk")
    content_type = row["content_type"]
    # Alleen afbeeldingen inline; tekst, JSON en PDF worden gedownload
    # (BETON-374) — inline op onze eigen origin is een andere risicoklasse.
    is_image = attachments_repo.is_image(content_type)
    if content_type in attachments_repo.TEXT_TYPES:
        content_type = f"{content_type}; charset=utf-8"
    return Response(
        content=data,
        media_type=content_type,
        headers=media_headers(
            row["filename"],
            immutable=True,
            disposition="inline" if is_image else "attachment",
        ),
    )
