"""Achtergrond-loop die verlopen `deferred_until`-items reactiveert (BETON-39).

Een item dat "tot <datum>" wachtte hoort daarna vanzelf terug te keren naar de
actieve kolommen, ook als niemand het item toevallig opent. De self-heal in
`GET /items/{ref}` dekt alleen gelezen items; deze loop maakt de reactivatie
tijd-gedreven. Geen LLM nodig, dus draait altijd mee in de lifespan.
"""

from __future__ import annotations

import asyncio
import logging

from . import db as db_module
from . import webhooks
from .repo import items as items_repo

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 60


def _run_sweep(db_path: str) -> list[dict]:
    """Eén reactivatie-sweep in een eigen transactie; geeft de geraakte items
    terug. Schrijft ook het item.updated-event + webhook-fanout (BETON-164)."""
    conn = db_module.connect(db_path)
    try:
        with db_module.transaction(conn):
            affected = items_repo.reactivate_deferred(conn)
            webhooks.notify_reactivations(conn, affected)
            return affected
    finally:
        conn.close()


async def reactivate_loop(
    db_path: str,
    stop_event: asyncio.Event,
    *,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
) -> None:
    """Periodieke self-heal: reactiveert verlopen deferred-items tot stop gezet is."""
    while not stop_event.is_set():
        try:
            affected = await asyncio.to_thread(_run_sweep, db_path)
            if affected:
                logger.info("Deferred-reactivatie: %d item(s) teruggezet", len(affected))
        except Exception:  # noqa: BLE001 — loop mag nooit sneuvelen
            logger.exception("Deferred-reactivatie-sweep mislukte")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass
