"""Webhook-deliveries: inzicht + replay (BETON-52).

Bedoeld voor troubleshooting: welke deliveries zijn (definitief) mislukt, en
opnieuw in de queue zetten zonder te wachten op de volgende agent-actie.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from .. import webhooks, db
from ..repo import inbox as inbox_repo
from ..repo import webhook_tests, users, events
from .installation import installation_admin
from ..deps import current_human, get_db

router = APIRouter(tags=["deliveries"])


@router.get("/webhook-deliveries")
def list_deliveries(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> list[dict]:
    """Lijst deliveries, recentste eerst. ``?status=failed`` filtert op status.

    Mens-only (BETON-384): deliveries zijn troubleshooting-inzicht in de héle
    fanout, niet per agent gescopeerd — een agent heeft er geen use-case voor
    en de UI is al mens-only."""
    return webhooks.list_deliveries(conn, status=status, limit=limit)


@router.post("/webhook-deliveries/{delivery_id}/replay")
def replay_delivery(
    delivery_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    """Reset een delivery (attempts/not_before) zodat de dispatcher hem opnieuw oppikt."""
    result = webhooks.replay_delivery(conn, delivery_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Onbekende delivery: {delivery_id}")
    return result


@router.get("/webhook-health")
def webhook_health(
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> list[dict]:
    """Per webhook-agent: laatste geslaagde levering + aantal mislukte sinds die
    (BETON-457). Voedt het statusbolletje in Agents; mens-only zoals de rest."""
    return inbox_repo.webhook_health(conn)


@router.post('/users/{handle}/webhook-test', status_code=202)
def queue_webhook_test(handle: str, request: Request, response: Response,
                       conn=Depends(get_db), actor=Depends(installation_admin)):
    response.headers['Cache-Control'] = 'no-store'
    retry = request.app.state.webhook_test_limiter.check(f'user:{actor["id"]}', rate_per_hour=30)
    if retry:
        raise HTTPException(429, 'Verzoeklimiet bereikt; probeer later opnieuw', headers={'Retry-After':str(max(1,int(retry)))})
    with db.transaction(conn):
        user = users.get_by_handle(conn, handle)
        if user is None or user['kind'] != 'agent' or user['is_virtual'] or not user['active'] or not user['webhook_url']:
            raise HTTPException(409, 'Configureer en activeer eerst een webhookagent')
        reason = webhooks.webhook_url_error(user['webhook_url'])
        if reason:
            raise HTTPException(422, reason)
        fingerprint = webhooks.test_target_fingerprint(user)
        pending = webhook_tests.pending(conn, user['id'])
        if pending and pending['payload'].get('test_target') == fingerprint:
            return webhook_tests.status(conn, pending['id'], user['id'])
        if pending:
            webhook_tests.cancel(conn, pending['id'])
        event = events.record(conn, type='webhook.test', actor_id=actor['id'], payload={'target':handle,'test_target':fingerprint})
        delivery_id = webhook_tests.enqueue(conn, event['id'], user['id'])
    return webhook_tests.status(conn, delivery_id, user['id'])


@router.get('/users/{handle}/webhook-test/{delivery_id}')
def webhook_test_status(handle: str, delivery_id: int, response: Response,
                        conn=Depends(get_db), _=Depends(installation_admin)):
    response.headers['Cache-Control'] = 'no-store'
    user = users.get_by_handle(conn, handle)
    result = webhook_tests.status(conn, delivery_id, user['id']) if user else None
    if result is None:
        raise HTTPException(404, 'Onbekende webhooktest')
    return result
