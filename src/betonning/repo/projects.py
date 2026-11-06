"""Projects-repository + default states bij aanmaak."""

from __future__ import annotations

import sqlite3

from . import states as states_repo
from . import project_template, model_classes

# Default state-set voor een nieuw project
# (naam, groep, kleur, is_default, closed, blocks_work).
# Alleen de zes basiskolommen; extra kolommen kunnen via de template.
DEFAULT_STATES = [
    ("backlog", "backlog", "#95a5a6", 1, 0, 1),
    ("todo", "unstarted", "#3498db", 0, 0, 0),
    ("in-progress", "started", "#f1c40f", 0, 0, 0),
    ("deferred", "backlog", "#34495e", 0, 0, 1),
    ("done", "completed", "#2ecc71", 0, 1, 0),
    ("cancelled", "cancelled", "#7f8c8d", 0, 1, 0),
]


def serialize(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "key": row["key"],
        "name": row["name"],
        "created_at": row["created_at"],
        "description": row["description"],
        "next_seq": row["next_seq"],
        "archived_at": row["archived_at"],
        "triage_enabled": bool(row["triage_enabled"]),
        "wiki_compile_enabled": bool(row["wiki_compile_enabled"]),
    }


def set_triage_enabled(
    conn: sqlite3.Connection, project_id: int, enabled: bool
) -> sqlite3.Row | None:
    """Zet de per-project triage-opt-in (fase 3, BETON-22)."""
    conn.execute(
        "UPDATE projects SET triage_enabled = ? WHERE id = ?",
        (1 if enabled else 0, project_id),
    )
    return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


def set_wiki_compile_enabled(
    conn: sqlite3.Connection, project_id: int, enabled: bool
) -> sqlite3.Row | None:
    """Zet de per-project wiki-compiler-opt-in (BETON-24)."""
    conn.execute(
        "UPDATE projects SET wiki_compile_enabled = ? WHERE id = ?",
        (1 if enabled else 0, project_id),
    )
    return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


def backfill_untriage(conn: sqlite3.Connection, project_id: int) -> int:
    """Markeer de niet-gearchiveerde items van een project opnieuw als
    niet-getriaged (triaged_at → NULL) zodat de triage-loop ze (opnieuw)
    verwerkt. Geeft het aantal opnieuw-ingeplande items terug.

    Reset ook triage_attempts/triage_error_at (BETON-121): anders blijven
    items die eerder in quarantaine belandden (bv. door een tijdelijke
    LLM-storing) voor altijd overgeslagen door find_untriaged(), ook na een
    handmatige backfill.

    Gesloten items (done/cancelled) worden overgeslagen (BETON-32): een backfill
    mag afgeronde tickets niet opnieuw laten triagen en heropenen."""
    cur = conn.execute(
        "UPDATE items SET triaged_at = NULL, triage_attempts = 0, triage_error_at = NULL "
        "WHERE project_id = ? AND archived_at IS NULL "
        "  AND (state_id IS NULL OR state_id NOT IN ("
        "        SELECT id FROM states WHERE project_id = ? AND "
        f"{states_repo.state_closed_sql('states')}))",
        (project_id, project_id),
    )
    return cur.rowcount


def backfill_uncompiled(conn: sqlite3.Connection, project_id: int) -> int:
    """Markeer de afgeronde (closed-state) items van een project opnieuw als
    niet-gecompileerd (wiki_compiled_at → NULL) zodat de wiki-compiler ze
    (opnieuw) verwerkt. Geeft het aantal opnieuw-ingeplande items terug."""
    cur = conn.execute(
        f"""UPDATE items SET wiki_compiled_at = NULL
           WHERE project_id = ? AND archived_at IS NULL AND state_id IN (
               SELECT id FROM states WHERE project_id = ?
                 AND {states_repo.state_closed_sql('states')}
           )""",
        (project_id, project_id),
    )
    return cur.rowcount


def create(
    conn: sqlite3.Connection,
    *,
    key: str,
    name: str,
    description: str = "",
    with_default_states: bool = True,
) -> dict:
    cur = conn.execute(
        "INSERT INTO projects (key, name, description) VALUES (?, ?, ?)",
        (key, name, description),
    )
    project_id = cur.lastrowid
    if with_default_states:
        for order, state in enumerate(project_template.get(conn)):
            conn.execute(
                """INSERT INTO states
                       (project_id, name, grp, color, sort_order, is_default, closed, blocks_work)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (project_id, state["name"], state["group"], state["color"], order,
                 state["is_default"], state["closed"], state["blocks_work"]),
            )
    for name in model_classes.CLASSES:
        conn.execute("INSERT INTO labels (project_id, name, color) VALUES (?, ?, ?)",
                     (project_id, name, "#95a5a6"))
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return serialize(row)


def update(
    conn: sqlite3.Connection, project_id: int, fields: dict
) -> sqlite3.Row | None:
    """Werk naam/omschrijving van een project bij (alleen meegegeven velden)."""
    allowed = {"name", "description"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if sets:
        cols = ", ".join(f"{k} = ?" for k in sets)
        conn.execute(
            f"UPDATE projects SET {cols} WHERE id = ?",
            (*sets.values(), project_id),
        )
    return conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()


def get_by_key(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    # Case-insensitief (COLLATE NOCASE, BETON-12): `beton` resolvet naar `BETON`.
    # Centraal punt zodat álle refs (relaties, deep-links) én project-
    # paden meeprofiteren; de opgeslagen key blijft canoniek (uppercase).
    return conn.execute(
        "SELECT * FROM projects WHERE key = ? COLLATE NOCASE", (key,)
    ).fetchone()


def list_all(
    conn: sqlite3.Connection, *, include_archived: bool = False
) -> list[dict]:
    where = "" if include_archived else "WHERE archived_at IS NULL"
    rows = conn.execute(f"SELECT * FROM projects {where} ORDER BY key").fetchall()
    return [serialize(r) for r in rows]


def archive(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    """Markeer een project als gearchiveerd (idempotent op reeds-gearchiveerd)."""
    conn.execute(
        "UPDATE projects SET archived_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE id = ? AND archived_at IS NULL",
        (project_id,),
    )
    return conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()


def restore(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    """Haal een project terug uit het archief (idempotent)."""
    conn.execute(
        "UPDATE projects SET archived_at = NULL WHERE id = ?",
        (project_id,),
    )
    return conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()


def next_seq(conn: sqlite3.Connection, project_id: int) -> int:
    """Reserveer en geef het volgende sequence-nummer terug (atomair)."""
    row = conn.execute(
        "UPDATE projects SET next_seq = next_seq + 1 WHERE id = ? "
        "RETURNING next_seq - 1 AS seq",
        (project_id,),
    ).fetchone()
    return row["seq"]
