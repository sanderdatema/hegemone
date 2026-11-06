"""States-repository: per project."""

from __future__ import annotations

import sqlite3

# "Afgesloten" = de state-GROEP, niet `states.closed`. `closed` is een UI-
# eigenschap (de kolom is inklapbaar); een inklapbare "Parkeren"-kolom in groep
# `started` is niet afgesloten. Eén definitie voor elke "is dit ticket dicht?"-
# query, zoals `question_open_sql` en `GUARDRAIL_ACTIVE` dat voor hun begrip doen
# (BETON-483).
CLOSED_GROUPS = ("completed", "cancelled")
_CLOSED_GROUPS_SQL = ", ".join(f"'{g}'" for g in CLOSED_GROUPS)


def is_closed_group(group: str | None) -> bool:
    """Python-kant van `state_closed_sql`: een item zonder state is niet dicht."""
    return group in CLOSED_GROUPS


def state_closed_sql(alias: str) -> str:
    """SQL-conditie: de state van dit item is afgesloten. NULL-veilig: bij een
    `LEFT JOIN` zonder state (grp NULL) is dit 0, dus `NOT state_closed_sql(..)`
    laat state-loze items gewoon meedoen."""
    return f"COALESCE({alias}.grp IN ({_CLOSED_GROUPS_SQL}), 0)"


def state_open_sql(alias: str) -> str:
    """Spiegel van `state_closed_sql`: niet afgesloten (of zonder state)."""
    return f"NOT {state_closed_sql(alias)}"


def serialize(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "group": row["grp"],
        "color": row["color"],
        "sort_order": row["sort_order"],
        "is_default": bool(row["is_default"]),
        "closed": bool(row["closed"]),
        "blocks_work": bool(row["blocks_work"]),
    }


def create(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    name: str,
    group: str,
    color: str = "#95a5a6",
    sort_order: int = 0,
    is_default: bool = False,
    closed: bool = False,
    blocks_work: bool = False,
) -> dict:
    cur = conn.execute(
        """INSERT INTO states
           (project_id, name, grp, color, sort_order, is_default, closed, blocks_work)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            project_id, name, group, color, sort_order, int(is_default), int(closed),
            int(blocks_work),
        ),
    )
    row = conn.execute("SELECT * FROM states WHERE id = ?", (cur.lastrowid,)).fetchone()
    return serialize(row)


def list_for_project(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM states WHERE project_id = ? ORDER BY sort_order, id",
        (project_id,),
    ).fetchall()
    return [serialize(r) for r in rows]


def get_by_name(conn: sqlite3.Connection, project_id: int, name: str) -> sqlite3.Row | None:
    # Case-insensitief (COLLATE NOCASE, BETON-35): `Todo`/`TODO` resolven naar de
    # opgeslagen state ongeacht hoofdletters. De opgeslagen naam blijft canoniek.
    return conn.execute(
        "SELECT * FROM states WHERE project_id = ? AND name = ? COLLATE NOCASE",
        (project_id, name),
    ).fetchone()


def count_items(conn: sqlite3.Connection, state_id: int) -> int:
    """Aantal items dat nog in deze state staat — bepaalt of verwijderen mag."""
    row = conn.execute(
        "SELECT COUNT(*) AS total FROM items WHERE state_id = ?", (state_id,)
    ).fetchone()
    return row["total"]


def delete(conn: sqlite3.Connection, state_id: int) -> None:
    """Verwijdert een state (kolom). De caller bewaakt dat er geen items meer
    in staan (BETON-351) — anders zou een item onzichtbaar worden (state_id
    zonder rij), wat erger is dan het verlies van een milestone-tag."""
    conn.execute("DELETE FROM states WHERE id = ?", (state_id,))


def update(conn: sqlite3.Connection, state_id: int, fields: dict) -> dict:
    """Werk de configureerbare metadata van een state bij.

    Ondersteunt ``name`` (hernoemen; uniciteit checkt de caller), ``color``,
    ``sort_order`` en ``blocks_work`` (BETON-177). Items verwijzen naar de
    state via ``state_id``, dus hernoemen is veilig voor bestaande items."""
    allowed = {"name", "color", "sort_order", "blocks_work"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if sets:
        cols = ", ".join(f"{key} = ?" for key in sets)
        values = [
            int(value) if key == "blocks_work" else value
            for key, value in sets.items()
        ]
        conn.execute(
            f"UPDATE states SET {cols} WHERE id = ?",
            (*values, state_id),
        )
    row = conn.execute("SELECT * FROM states WHERE id = ?", (state_id,)).fetchone()
    return serialize(row)
