"""Per-item mute (BETON-245): een user meldt zich af voor de fanout van één item.

De subscribers-doelgroep blijft volledig afgeleid (assignee + eerdere
participants + subscribe_all); een mute is puur een filter dáárover. Pure
sqlite3-data-access, connectie als eerste arg — geen ORM.
"""

from __future__ import annotations

import sqlite3


def muted_user_ids(conn: sqlite3.Connection, item_id: int) -> set[int]:
    """De user-id's die dit item gemute hebben."""
    rows = conn.execute(
        "SELECT user_id FROM item_mutes WHERE item_id = ?", (item_id,)
    ).fetchall()
    return {row["user_id"] for row in rows}


def mute(conn: sqlite3.Connection, item_id: int, user_id: int) -> None:
    """Mute idempotent (dubbel muten is een no-op)."""
    conn.execute(
        "INSERT OR IGNORE INTO item_mutes (item_id, user_id) VALUES (?, ?)",
        (item_id, user_id),
    )


def unmute(conn: sqlite3.Connection, item_id: int, user_id: int) -> None:
    """Hef de mute op (ontmuten van iets ongemute is een no-op)."""
    conn.execute(
        "DELETE FROM item_mutes WHERE item_id = ? AND user_id = ?",
        (item_id, user_id),
    )
