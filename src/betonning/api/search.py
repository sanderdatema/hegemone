"""Zoek-endpoint: FTS5 over alle projecten, compacte resultaten."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from ..deps import current_user, get_db
from ..repo import items as items_repo

router = APIRouter(tags=["search"])


@router.get("/search")
def search(
    q: str,
    limit: int | None = Query(default=None, ge=1, le=500),
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    return items_repo.search(conn, q, limit=limit, viewer_id=user["id"])


@router.get("/ref-candidates")
def ref_candidates(
    q: str,
    project: str | None = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    """Ticket-ref-autocomplete voor het ``#``-menu (BETON-254).

    ``q`` is de ruwe tekst na de ``#`` (bv. ``B1`` / ``42`` / ``SOS``);
    ``project`` is de key van het huidige project (bepaalt de scope bij een
    query van alleen cijfers). Zie ``items_repo.ref_candidates``.
    """
    return items_repo.ref_candidates(
        conn, q, project_key=project, limit=limit, viewer_id=user["id"]
    )
