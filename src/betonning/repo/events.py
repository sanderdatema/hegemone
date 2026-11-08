"""Events-repository: append-only activity log.

Elke mutatie schrijft hier een event. Het voedt de `/activity`-feed (fase 2)
en straks de webhook-fanout (fase 3). Payload is vrije JSON per event-type.
"""

from __future__ import annotations

import json
import sqlite3

from .users import handle_of

# BETON-321: het idempotente marker-write-patroon ("beoordeeld"/"opgeknipt"/
# "getriaged" etc.) werd op elke plek opnieuw hand-gerold, met spelling-drift
# in het strftime-literal (mét/zonder spatie na de komma). Eén canonieke
# spelling hier; `_touch` gebruikt hem voor de WHERE-id-AND-col-IS-NULL-vorm.
# Precedent voor tabel/kolom-parametrisatie: triage_worker._record_failure.
NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


def _touch(conn: sqlite3.Connection, table: str, col: str, item_id: int) -> None:
    """Zet `col` op `table` naar nu — idempotent (alleen als hij nog NULL is).

    Vervangt de hand-gerolde marker-writes zoals `items.triaged_at`,
    `items.decomposed_at` en `comments.evaluated_at`. Tweede aanroep is een
    no-op: de eerst gezette timestamp blijft staan."""
    conn.execute(
        f"UPDATE {table} SET {col} = {NOW_SQL} WHERE id = ? AND {col} IS NULL",
        (item_id,),
    )


def record(
    conn: sqlite3.Connection,
    *,
    type: str,
    item_id: int | None = None,
    actor_id: int | None = None,
    payload: dict | None = None,
) -> sqlite3.Row:
    """Log een event. Geeft de opgeslagen rij terug."""
    if not conn.in_transaction:
        from .. import db
        with db.transaction(conn):
            return record(conn, type=type, item_id=item_id, actor_id=actor_id, payload=payload)
    cur = conn.execute(
        "INSERT INTO events (type, item_id, actor_id, payload) VALUES (?, ?, ?, ?)",
        (type, item_id, actor_id, json.dumps(payload or {})),
    )
    event = conn.execute("SELECT * FROM events WHERE id = ?", (cur.lastrowid,)).fetchone()
    if item_id is not None and not type.startswith("execution.") and type not in ("question.answered", "question.withdrawn"):
        from . import execution
        execution.observe_item(conn, item_id)
    return event


def serialize(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "actor": handle_of(conn, row["actor_id"]),
        "payload": json.loads(row["payload"]),
        "created_at": row["created_at"],
    }


def list_for_item(conn: sqlite3.Connection, item_id: int) -> list[sqlite3.Row]:
    """Events voor één item, oplopend (oudste eerst)."""
    return conn.execute(
        "SELECT * FROM events WHERE item_id = ? ORDER BY id", (item_id,)
    ).fetchall()


def list_for_project(
    conn: sqlite3.Connection,
    project_id: int,
    project_key: str,
    *,
    since_id: int | None = None,
    actor_id: int | None = None,
    types: list[str] | None = None,
    limit: int = 100,
) -> list[sqlite3.Row]:
    """Events voor één project, nieuwste eerst (activiteitenfeed, BETON-372).

    Een gewoon event scoped via de join op `items.project_id` — events kennen
    zelf geen project_id. Een `item.deleted`-event heeft `item_id IS NULL`
    (het item bestaat dan niet meer, BETON-19) en wordt daarom gescoped via de
    ref-prefix in zijn payload (`{"ref": "KEY-42", ...}`)."""
    # GLOB, niet LIKE: een projectkey mag zelf een hyphen bevatten
    # (`parse_ref`'s "(.+)-(\\d+)" laat dat toe), dus "KEY-[0-9]*" i.p.v.
    # "KEY-%" — anders zou LIKE ook "KEY-EXTRA-42" van een ander project
    # matchen (en "_" als 1-teken-wildcard lezen). GLOB is case-sensitive,
    # maar `project_key` is hier altijd de canonieke (opgeslagen) key, dus dat
    # is geen gat.
    clauses = [
        "(i.project_id = ? OR (e.item_id IS NULL "
        "AND json_extract(e.payload, '$.ref') GLOB ?))"
    ]
    params: list = [project_id, f"{project_key}-[0-9]*"]
    if since_id is not None:
        clauses.append("e.id > ?")
        params.append(since_id)
    if actor_id is not None:
        clauses.append("e.actor_id = ?")
        params.append(actor_id)
    if types:
        placeholders = ",".join("?" for _ in types)
        clauses.append(f"e.type IN ({placeholders})")
        params.extend(types)
    params.append(limit)
    return conn.execute(
        f"""
        SELECT e.* FROM events e
        LEFT JOIN items i ON i.id = e.item_id
        WHERE {" AND ".join(clauses)}
        ORDER BY e.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()


def serialize_bulk(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict]:
    """Serialiseer events gebatcht (BETON-372): één actor- en één item-query
    voor de hele lijst i.p.v. `serialize()` per event — spiegelt het patroon van
    `repo/items.py:_compact_rows`. Elk resultaat draagt naast de kale event-vorm
    ook `ref`/`title` van het bijbehorende item, zodat de UI ernaar kan linken
    zonder zelf nog een lookup te doen."""
    actor_ids = {r["actor_id"] for r in rows if r["actor_id"] is not None}
    item_ids = {r["item_id"] for r in rows if r["item_id"] is not None}

    actors: dict[int, str] = {}
    if actor_ids:
        placeholders = ",".join("?" for _ in actor_ids)
        for row in conn.execute(
            f"SELECT id, handle FROM users WHERE id IN ({placeholders})",
            list(actor_ids),
        ):
            actors[row["id"]] = row["handle"]

    items: dict[int, dict] = {}
    if item_ids:
        placeholders = ",".join("?" for _ in item_ids)
        for row in conn.execute(
            f"""
            SELECT i.id AS item_id, i.title AS title,
                   p.key || '-' || i.seq AS ref
            FROM items i JOIN projects p ON p.id = i.project_id
            WHERE i.id IN ({placeholders})
            """,
            list(item_ids),
        ):
            items[row["item_id"]] = {"ref": row["ref"], "title": row["title"]}

    out = []
    for r in rows:
        payload = json.loads(r["payload"])
        info = items.get(r["item_id"]) if r["item_id"] is not None else None
        if info is not None:
            ref, title = info["ref"], info["title"]
        else:
            # item.deleted (item_id NULL, BETON-19): ref/titel zitten al in de
            # payload — het item is er niet meer om ze uit op te halen.
            ref, title = payload.get("ref"), payload.get("title")
        out.append(
            {
                "id": r["id"],
                "type": r["type"],
                "actor": actors.get(r["actor_id"]),
                "ref": ref,
                "title": title,
                "payload": payload,
                "created_at": r["created_at"],
            }
        )
    return out
