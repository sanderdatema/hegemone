"""Per-item follow (BETON-369): een mens meldt zich aan voor één item.

Spiegelbeeld van `repo/mutes.py` (BETON-245): een mute haalt je uit de
afgeleide fanout-doelgroep, een follow zet je erin. De doelgroep blijft verder
afgeleid — dit is een expliciete toevoeging, geen vervanging.

Muten wint van volgen: `webhooks.fanout` trekt de mutes af ná de union, dus wie
een item volgt én gemute heeft krijgt niets. Dat is de juiste volgorde — muten
is de sterkere, nadrukkelijker gemaakte keuze.

Pure sqlite3-data-access, connectie als eerste arg — geen ORM. De bulk-lookup
(`followed_item_ids`) bestaat om N+1 te vermijden: de inbox weegt honderden
event-rijen in één keer.
"""

from __future__ import annotations

import sqlite3


def follow(conn: sqlite3.Connection, item_id: int, user_id: int) -> None:
    """Volg idempotent (dubbel volgen is een no-op)."""
    conn.execute(
        "INSERT OR IGNORE INTO item_follows (item_id, user_id) VALUES (?, ?)",
        (item_id, user_id),
    )


def unfollow(conn: sqlite3.Connection, item_id: int, user_id: int) -> None:
    """Stop met volgen (ontvolgen van iets ongevolgds is een no-op)."""
    conn.execute(
        "DELETE FROM item_follows WHERE item_id = ? AND user_id = ?",
        (item_id, user_id),
    )


def is_following(conn: sqlite3.Connection, item_id: int, user_id: int | None) -> bool:
    if user_id is None:
        return False
    return (
        conn.execute(
            "SELECT 1 FROM item_follows WHERE item_id = ? AND user_id = ?",
            (item_id, user_id),
        ).fetchone()
        is not None
    )


def follower_ids(conn: sqlite3.Connection, item_id: int) -> set[int]:
    """De user-id's die dit item volgen."""
    rows = conn.execute(
        "SELECT user_id FROM item_follows WHERE item_id = ?", (item_id,)
    ).fetchall()
    return {row["user_id"] for row in rows}


def followed_item_ids(conn: sqlite3.Connection, user_id: int) -> set[int]:
    """De item-id's die deze user volgt — één query voor de hele inbox-scan.

    Bewust niet begrensd op een item-lijst: een mens volgt er hooguit een handvol,
    en zo blijft het één query ongeacht de venstergrootte.
    """
    rows = conn.execute(
        "SELECT item_id FROM item_follows WHERE user_id = ?", (user_id,)
    ).fetchall()
    return {row["item_id"] for row in rows}
