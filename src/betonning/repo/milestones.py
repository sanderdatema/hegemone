"""Milestones-repository: versie-workflow per project (v1.4.0 etc.)."""

from __future__ import annotations

import sqlite3

from . import states as states_repo
from ..db import today as db_today


def _is_overdue(due_date: str | None, status: str, today: str) -> bool:
    """Een milestone is te laat als hij een due_date in het verleden heeft en nog
    niet is afgerond. ISO-datums vergelijken lexicografisch."""
    return bool(due_date and status != "completed" and due_date[:10] < today)


def serialize(
    row: sqlite3.Row,
    *,
    done: int | None = None,
    total: int | None = None,
    today: str,
) -> dict:
    """Milestone-dict. Met `done`/`total` komt de voortgangsteller mee (BETON-63);
    `overdue` hangt puur van due_date + status af en zit er altijd in."""
    data = {
        "id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "due_date": row["due_date"],
        "overdue": _is_overdue(row["due_date"], row["status"], today),
    }
    if total is not None:
        data["items_done"] = done or 0
        data["items_total"] = total
    return data


def _progress_bulk(
    conn: sqlite3.Connection, project_id: int
) -> dict[int, tuple[int, int]]:
    """(done, total) per milestone voor een heel project in één query (geen N+1).

    total = alle levende (niet-gearchiveerde) items in de milestone; done = items
    in een closed-group state (completed/cancelled), net als de subtaak-teller."""
    rows = conn.execute(
        f"""SELECT i.milestone_id AS mid, COUNT(*) AS total,
                  SUM(CASE WHEN {states_repo.state_closed_sql('st')} THEN 1 ELSE 0 END) AS done
           FROM items i LEFT JOIN states st ON st.id = i.state_id
           WHERE i.milestone_id IS NOT NULL AND i.archived_at IS NULL
             AND i.project_id = ?
           GROUP BY i.milestone_id""",
        (project_id,),
    ).fetchall()
    return {r["mid"]: (int(r["done"] or 0), int(r["total"] or 0)) for r in rows}


def get_by_name(conn: sqlite3.Connection, project_id: int, name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM milestones WHERE project_id = ? AND name = ?",
        (project_id, name),
    ).fetchone()


def create(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    name: str,
    due_date: str | None = None,
) -> dict:
    cur = conn.execute(
        "INSERT INTO milestones (project_id, name, due_date) VALUES (?, ?, ?)",
        (project_id, name, due_date),
    )
    row = conn.execute(
        "SELECT * FROM milestones WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return serialize(row, today=db_today(conn))


def list_for_project(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    """Milestones + voortgangsteller (items_done/items_total) + overdue (BETON-63).

    De voortgang komt uit één gebatchte query (`_progress_bulk`), dus geen N+1."""
    rows = conn.execute(
        "SELECT * FROM milestones WHERE project_id = ? ORDER BY name", (project_id,)
    ).fetchall()
    progress = _progress_bulk(conn, project_id)
    today = db_today(conn)
    out = []
    for r in rows:
        done, total = progress.get(r["id"], (0, 0))
        out.append(serialize(r, done=done, total=total, today=today))
    return out


_PATCHABLE = {"status": "status", "due_date": "due_date"}


def update(conn: sqlite3.Connection, milestone_id: int, fields: dict) -> dict:
    sets = []
    values = []
    for name, value in fields.items():
        col = _PATCHABLE.get(name)
        if col is None:
            continue
        sets.append(f"{col} = ?")
        values.append(value)
    if sets:
        values.append(milestone_id)
        conn.execute(f"UPDATE milestones SET {', '.join(sets)} WHERE id = ?", values)
    row = conn.execute(
        "SELECT * FROM milestones WHERE id = ?", (milestone_id,)
    ).fetchone()
    return serialize(row, today=db_today(conn))


def delete(conn: sqlite3.Connection, milestone_id: int) -> None:
    """Verwijdert de milestone en ontkoppelt gekoppelde items (BETON-336).

    Geen ``ON DELETE SET NULL`` op de FK (table-recreate-migratie breekt op de
    gevulde prod-db), dus de ontkoppeling gebeurt hier expliciet vóór de DELETE.
    """
    conn.execute(
        "UPDATE items SET milestone_id = NULL WHERE milestone_id = ?", (milestone_id,)
    )
    conn.execute("DELETE FROM milestones WHERE id = ?", (milestone_id,))
