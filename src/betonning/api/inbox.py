"""Inbox-endpoints (BETON-55): events die de ingelogde user raken + read-marker.

- ``GET /inbox`` — relevante events (mentions, toewijzingen, comments op je items)
  met gelezen/ongelezen + ongelezen-teller voor de topbar-badge. ``?instructions=true``
  (BETON-296) voegt per entry hetzelfde opdrachtblok toe als een webhook-delivery
  (`instruction.expected_action`/`do`/`do_not`/`read`/`reply`) — opt-in, want elke
  instructie kost een extra lookup en de meeste consumenten (de UI) hebben er niets aan.
- ``POST /inbox/seen`` — zet de read-marker op (minstens) een event-id.
- ``GET /me/issues`` — cross-project lijst van open items van de user (My Issues).
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from .. import db as db_module
from ..deps import current_user, get_db
from ..repo import inbox as inbox_repo
from ..repo import items as items_repo
from ..repo import users as users_repo

router = APIRouter(tags=["inbox"])


@router.get("/inbox")
def get_inbox(
    limit: int = Query(default=50, ge=1, le=200),
    instructions: bool = Query(default=False),
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    return inbox_repo.list_for_user(
        conn, user, limit=limit, include_instructions=instructions
    )


class InboxSeen(BaseModel):
    event_id: int


@router.post("/inbox/seen")
def mark_inbox_seen(
    body: InboxSeen,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    with db_module.transaction(conn):
        marker = inbox_repo.mark_seen(conn, user["id"], body.event_id)
    return {"last_seen_event_id": marker}


@router.get("/me/issues")
def my_issues(
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    """Open items (cross-project) die aan de ingelogde user toegewezen zijn.

    BETON-207: een coding-/Hermes-agent ziet óók de gedeelde virtuele queue die
    bij z'n type past, zodat de virtuele toewijzing vindbaar is."""
    return items_repo.list_assigned_open(
        conn, users_repo.visible_queue_ids(conn, user), viewer_id=user["id"]
    )
