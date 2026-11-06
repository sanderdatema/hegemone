"""Per-item read-state (BETON-294): tot welk event-id heeft een user één item gezien.

Naast de globale watermark (`users.last_seen_event_id`, migratie 019) houdt
`item_reads` een watermark per (user, item) bij. Een item is gelezen als zijn
hoogste *vreemde* event-id (dus zonder de eigen activiteit van de user) onder de
globale óf de per-item-watermark ligt. Zo blijft de bestaande inbox werken en komt
de per-kaart-markering (BETON-281/286) erbovenop.

Pure sqlite3-data-access, connectie als eerste arg — geen ORM. De bulk-lookups
bestaan om N+1 te vermijden: het board serialiseert honderden items in één keer.

**Comment-filter (BETON-281):** `has_unread`/`unread_bulk` voeden alléén de
kaart-/lijst-markering (`repo/items.py:serialize`/`_compact_rows`) — dat is de
enige plek die ze aanroept. Het beleid is expliciet "alleen ongelezen
_comments_ markeren de kaart", geen ruis van labels/state-wissels/toewijzingen
(BETON-288/291 hebben die ruis net weggenomen). Vandaar het harde filter op
`events.type IN ('comment.created', 'comment.updated')` hieronder — een
verwijderd comment (`comment.deleted`) telt bewust niet mee (niets nieuws om te
lezen). De bredere, ongefilterde `_foreign_max`/inbox-route blijft intact voor
BETON-286 (`repo/inbox.py` gebruikt `watermarks_bulk` rechtstreeks met zijn
eigen `_reason`-filter — nooit deze comment-gefilterde functies).
"""

from __future__ import annotations

import sqlite3

_UNREAD_EVENT_TYPES = ("comment.created", "comment.updated")


def _in_clause(ids) -> str:
    """``?,?,?``-placeholders voor een SQL ``IN (...)`` over ``len(ids)`` waarden.

    Geeft alleen de placeholder-string terug — de empty-guard (``{}``/``set()``/
    ``[]``, per aanroeper verschillend) blijft bij de caller, want die return-
    waarde varieert per functie.
    """
    return ",".join("?" * len(ids))


def mark_read(
    conn: sqlite3.Connection, item_id: int, user_id: int, event_id: int
) -> int:
    """Zet de per-item-watermark op ``event_id`` (nooit omlaag — net als
    ``inbox.mark_seen``). Geeft de nieuwe markerwaarde terug."""
    conn.execute(
        """INSERT INTO item_reads (user_id, item_id, last_seen_event_id)
           VALUES (?, ?, ?)
           ON CONFLICT (user_id, item_id) DO UPDATE SET
               last_seen_event_id = MAX(last_seen_event_id, excluded.last_seen_event_id),
               updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
        (user_id, item_id, event_id),
    )
    row = conn.execute(
        "SELECT last_seen_event_id FROM item_reads WHERE user_id = ? AND item_id = ?",
        (user_id, item_id),
    ).fetchone()
    return row["last_seen_event_id"] if row else event_id


def last_event_id(conn: sqlite3.Connection, item_id: int) -> int:
    """Het hoogste event-id op dit item (inclusief eigen activiteit), of 0.

    Dit is wat ``POST /items/{ref}/read`` als watermark wegschrijft: "alles op dit
    item gezien". Bewust níet gefilterd op actor — de eigen events tellen ook als
    gezien."""
    row = conn.execute(
        "SELECT MAX(id) AS m FROM events WHERE item_id = ?", (item_id,)
    ).fetchone()
    return (row["m"] if row else None) or 0


def watermark(conn: sqlite3.Connection, item_id: int, user_id: int) -> int:
    """De per-item-watermark van deze user (0 als hij het item nooit las)."""
    row = conn.execute(
        "SELECT last_seen_event_id FROM item_reads WHERE user_id = ? AND item_id = ?",
        (user_id, item_id),
    ).fetchone()
    return row["last_seen_event_id"] if row else 0


def watermarks_bulk(
    conn: sqlite3.Connection, item_ids: list[int], user_id: int
) -> dict[int, int]:
    """Per-item-watermarks voor een lijst items — gebatcht (één query).

    Ontbrekende item-id's (nooit gezien) zitten niet in de return-dict; de
    aanroeper valt dan terug op 0. Gebruikt door de inbox (BETON-286) om
    `read` per event af te leiden zonder N+1 op `item_reads`.
    """
    if not item_ids:
        return {}
    placeholders = _in_clause(item_ids)
    rows = conn.execute(
        f"""SELECT item_id AS item_id, last_seen_event_id AS seen FROM item_reads
            WHERE user_id = ? AND item_id IN ({placeholders})""",
        [user_id, *item_ids],
    ).fetchall()
    return {r["item_id"]: r["seen"] for r in rows}


def _global_watermark(conn: sqlite3.Connection, user_id: int) -> int:
    row = conn.execute(
        "SELECT last_seen_event_id FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return (row["last_seen_event_id"] if row else 0) or 0


def _foreign_max(conn: sqlite3.Connection, item_id: int, user_id: int) -> int:
    """Hoogste **comment**-event-id op dit item dat *niet* van de user zelf komt
    (BETON-281: alleen comments markeren de kaart, geen labels/state/toewijzing).

    Je eigen activiteit maakt een item nooit ongelezen (anders is elk item dat je
    aanraakt meteen weer "ongelezen")."""
    placeholders = _in_clause(_UNREAD_EVENT_TYPES)
    row = conn.execute(
        f"""SELECT MAX(id) AS m FROM events
            WHERE item_id = ? AND (actor_id IS NULL OR actor_id != ?)
              AND type IN ({placeholders})""",
        (item_id, user_id, *_UNREAD_EVENT_TYPES),
    ).fetchone()
    return (row["m"] if row else None) or 0


def has_unread(conn: sqlite3.Connection, item_id: int, user_id: int | None) -> bool:
    """Heeft dit item ongelezen activiteit voor deze user?

    Zonder user (bv. een serialisatie buiten een request-context) is er geen
    read-state te bepalen → False.
    """
    if user_id is None:
        return False
    foreign = _foreign_max(conn, item_id, user_id)
    if foreign == 0:
        return False
    threshold = max(_global_watermark(conn, user_id), watermark(conn, item_id, user_id))
    return foreign > threshold


def unread_bulk(
    conn: sqlite3.Connection, item_ids: list[int], user_id: int | None
) -> set[int]:
    """Item-id's met ongelezen **comment**-activiteit voor deze user — gebatcht
    (BETON-281: alleen comments markeren de kaart, geen labels/state/toewijzing).

    Drie query's voor de hele lijst (vreemde max per item, per-item-watermarks,
    globale watermark) i.p.v. een handvol per item; spiegelt
    ``items._open_questions_bulk`` (BETON-275). Zonder user: lege set.
    """
    if user_id is None or not item_ids:
        return set()
    placeholders = _in_clause(item_ids)
    type_placeholders = _in_clause(_UNREAD_EVENT_TYPES)
    foreign_rows = conn.execute(
        f"""SELECT item_id AS item_id, MAX(id) AS m FROM events
            WHERE item_id IN ({placeholders})
              AND (actor_id IS NULL OR actor_id != ?)
              AND type IN ({type_placeholders})
            GROUP BY item_id""",
        [*item_ids, user_id, *_UNREAD_EVENT_TYPES],
    ).fetchall()
    read_rows = conn.execute(
        f"""SELECT item_id AS item_id, last_seen_event_id AS seen FROM item_reads
            WHERE user_id = ? AND item_id IN ({placeholders})""",
        [user_id, *item_ids],
    ).fetchall()
    seen_by_item = {r["item_id"]: r["seen"] for r in read_rows}
    global_seen = _global_watermark(conn, user_id)
    return {
        r["item_id"]
        for r in foreign_rows
        if (r["m"] or 0) > max(global_seen, seen_by_item.get(r["item_id"], 0))
    }
