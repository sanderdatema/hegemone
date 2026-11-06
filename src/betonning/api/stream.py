"""Live event-stream (SSE) bovenop de events-tabel.

De UI abonneert met `?since=<event_id>` en krijgt elk nieuw event als
`data: {...}` met een `id:`-regel zodat ze bij een herverbinding kunnen
hervatten. Elke ~poll-ronde zonder events sturen we een heartbeat-comment
zodat proxies de verbinding niet dichttrekken.
"""

from __future__ import annotations

import asyncio
import json
import hmac
import time
import sqlite3

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from ..deps import current_user, get_db
from .. import db as db_module, credential_policy
from ..repo import events as events_repo
from ..repo import items as items_repo
from ..repo import relations as relations_repo
from ..repo import users as users_repo
from ..security import hash_api_key

router = APIRouter(tags=["stream"])

POLL_INTERVAL = 1.0
BATCH_SIZE = 100
MAX_REPLAY_EVENTS = 5000


def _enrich_item(
    conn: sqlite3.Connection,
    data: dict,
    item_id: int | None,
    viewer_id: int | None = None,
) -> None:
    """Verrijk een SSE-frame met een compacte item-snapshot voor de UI.

    Alleen op het SSE-pad (níet in ``events_repo.serialize`` of ``record``), zodat
    de webhook-fanout en `/activity` ongemoeid blijven. De UI past een event dan
    incrementeel op het board toe (BETON-186) zonder een volledige reload: het
    frame draagt `ref`, `project` (project-key) en `item` (compact) mee. Bij een
    inmiddels hard-verwijderd item (item_id=None of weg) blijven die velden weg
    en valt de UI terug op een volledige reload.

    ``viewer_id`` (BETON-294): de stream is per abonnee, dus de snapshot draagt de
    ``has_unread`` van díe user. Zonder viewer zou een live event de vlag op de
    kaart juist wissen i.p.v. zetten."""
    if item_id is None:
        return
    row = items_repo.get(conn, item_id)
    if row is None:
        return
    full = items_repo.serialize(conn, row, viewer_id)
    # BETON-344: `serialize()` draagt zelf geen relaties (net als bij de volle
    # GET /items/{ref}-respons, api/items.py:get_item, is dat een losse
    # `for_item`-call) — nodig zodat de kaart-snapshot ze kan meesturen.
    full["relations"] = relations_repo.for_item(conn, item_id)
    data["ref"] = full["ref"]
    data["project"] = full["project"]
    data["item"] = items_repo.compact(full)


def _load_batch(db_path, last, project, viewer_id):
    """Een eindige batch serialiseren buiten de event-loop, met eigen connectie."""
    conn = db_module.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT e.* FROM events e LEFT JOIN items i ON i.id=e.item_id "
            "LEFT JOIN projects p ON p.id=i.project_id "
            "WHERE e.id > ? AND (? IS NULL OR p.key=?) ORDER BY e.id LIMIT ?",
            (last, project, project, BATCH_SIZE),
        ).fetchall()
        result = []
        for row in rows:
            data = events_repo.serialize(conn, row)
            data["item_id"] = row["item_id"]
            _enrich_item(conn, data, row["item_id"], viewer_id)
            result.append((row["id"], data))
        return result
    finally:
        conn.close()


async def _event_generator(
    request: Request,
    db_path: str,
    since: int,
    from_latest: bool = False,
    viewer_id: int | None = None,
    key_fingerprint: str | None = None,
    expires_at: float | None = None,
    project: str | None = None,
    browser_session_hash: str | None = None,
):
    """Yield SSE-frames voor events met id > `since`, tot de client weggaat.

    Met ``from_latest`` begint de stream bij het huidige laatste event-id i.p.v.
    de meegegeven `since`. De UI gebruikt dit bij de eerste verbinding (BETON-186):
    ze heeft net een volledige ``loadBoard()`` gedaan, dus de hele
    event-historie opnieuw afspelen (en per event een item-snapshot serialiseren)
    is onnodig. Bij een herverbinding hervat ze wél vanaf het laatst geziene id."""
    conn = db_module.connect(db_path)

    def authorized():
        if expires_at is not None and time.time() >= expires_at:
            return False
        if browser_session_hash is not None:
            active_session = conn.execute(
                "SELECT 1 FROM browser_sessions WHERE token_hash=? AND expires_at>?",
                (browser_session_hash, time.time()),
            ).fetchone()
            if active_session is None:
                return False
        if key_fingerprint is None:
            return True  # alleen interne/testaanroepen zonder principal
        if viewer_id is None:
            return False
        user = users_repo.get(conn, viewer_id)
        if user is None or not credential_policy.valid(user) or "read" not in credential_policy.scopes(
            user
        ):
            return False
        allowed = credential_policy.projects(user)
        if allowed is not None and (project is None or project not in allowed):
            return False
        return hmac.compare_digest(user["api_key_hash"], key_fingerprint)

    last = since
    if from_latest:
        row = conn.execute("SELECT MAX(id) AS m FROM events").fetchone()
        last = row["m"] or 0
    try:
        while True:
            if not authorized() or await request.is_disconnected():
                break
            latest = conn.execute("SELECT MAX(id) FROM events").fetchone()[0] or 0
            if latest - last > MAX_REPLAY_EVENTS:
                last = latest
                yield f'id: {last}\ndata: {{"type":"stream.resync","id":{last}}}\n\n'
            rows = await asyncio.to_thread(
                _load_batch, db_path, last, project, viewer_id
            )
            # Projectgebonden credentials zien geen cross-project eventpayloads.
            if key_fingerprint is not None and viewer_id is not None:
                principal = users_repo.get(conn, viewer_id)
                if credential_policy.projects(principal) is not None:
                    for _, data in rows:
                        payload = data.get("payload") or {}
                        if isinstance(payload, dict):
                            for field in ("target", "ref", "from", "to", "project"):
                                payload.pop(field, None)
                        if data.get("item"):
                            data["item"].pop("relations", None)
            for event_id, data in rows:
                if not authorized():
                    return
                last = event_id
                yield f"id: {event_id}\ndata: {json.dumps(data)}\n\n"
            if not rows:
                yield ": heartbeat\n\n"
            await asyncio.sleep(0 if len(rows) == BATCH_SIZE else POLL_INTERVAL)
    finally:
        conn.close()


@router.get("/events/stream")
async def stream(
    request: Request,
    since: int = Query(default=0, ge=0),
    from_: str | None = Query(default=None, alias="from"),
    project: str | None = Query(default=None, max_length=20),
    user: sqlite3.Row = Depends(current_user),
    __: sqlite3.Connection = Depends(get_db),
) -> StreamingResponse:
    return StreamingResponse(
        _event_generator(
            request,
            request.app.state.db_path,
            since,
            from_latest=from_ == "latest",
            viewer_id=user["id"],
            key_fingerprint=user["api_key_hash"],
            expires_at=getattr(request.state, "auth_expires_at", None),
            project=project,
            browser_session_hash=hash_api_key(request.state.session_token)
            if getattr(request.state, "session_token", None)
            else None,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
