"""Labels-repository: per project + koppeling aan items."""

from __future__ import annotations

import sqlite3


def serialize(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "name": row["name"], "color": row["color"]}


def create(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    name: str,
    color: str = "#95a5a6",
) -> dict:
    cur = conn.execute(
        "INSERT INTO labels (project_id, name, color) VALUES (?, ?, ?)",
        (project_id, name, color),
    )
    row = conn.execute("SELECT * FROM labels WHERE id = ?", (cur.lastrowid,)).fetchone()
    return serialize(row)


def list_for_project(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM labels WHERE project_id = ? ORDER BY name", (project_id,)
    ).fetchall()
    return [serialize(r) for r in rows]


def get_by_name(conn: sqlite3.Connection, project_id: int, name: str) -> sqlite3.Row | None:
    # Case-insensitief (COLLATE NOCASE, BETON-35): `Bug`/`BUG` resolven naar het
    # opgeslagen label. De opgeslagen naam blijft canoniek.
    return conn.execute(
        "SELECT * FROM labels WHERE project_id = ? AND name = ? COLLATE NOCASE",
        (project_id, name),
    ).fetchone()


def set_color(conn: sqlite3.Connection, label_id: int, color: str) -> dict:
    conn.execute("UPDATE labels SET color = ? WHERE id = ?", (color, label_id))
    row = conn.execute("SELECT * FROM labels WHERE id = ?", (label_id,)).fetchone()
    return serialize(row)


def delete(conn: sqlite3.Connection, label_id: int) -> None:
    conn.execute("DELETE FROM labels WHERE id = ?", (label_id,))


def set_for_item(conn: sqlite3.Connection, item_id: int, label_ids: list[int]) -> None:
    """Vervang de labelset van een item volledig."""
    conn.execute("DELETE FROM item_labels WHERE item_id = ?", (item_id,))
    for lid in label_ids:
        conn.execute(
            "INSERT INTO item_labels (item_id, label_id) VALUES (?, ?)", (item_id, lid)
        )


def add_to_item(conn: sqlite3.Connection, item_id: int, label_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO item_labels (item_id, label_id) VALUES (?, ?)",
        (item_id, label_id),
    )


def remove_from_item(conn: sqlite3.Connection, item_id: int, label_id: int) -> None:
    conn.execute(
        "DELETE FROM item_labels WHERE item_id = ? AND label_id = ?",
        (item_id, label_id),
    )
