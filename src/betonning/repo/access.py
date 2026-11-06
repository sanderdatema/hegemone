"""Per-project agent-toegangsniveaus (BETON-123).

Drie niveaus, oplopend: ``none`` < ``respond`` < ``assign``.

- ``none``    — de agent wordt nooit érbij gehaald: niet toewijsbaar door
                triage/decompose én niet getriggerd via webhook-fanout.
- ``respond`` — mag @gementiond worden en reageren/tickets maken, maar wordt
                niet automatisch als assignee gekozen.
- ``assign``  — volledige deelname (de globale default).

Het effectieve niveau voor (project, agent) = per-agent override ?? per-type
default ?? globale default. Beide override-lagen zijn uitzonderingstabellen:
geen rij = val door naar de laag eronder. Mensen (kind='human') vallen buiten
dit model en zijn altijd ``assign``.
"""

from __future__ import annotations

import sqlite3

LEVELS = ("none", "respond", "assign")
DEFAULT_LEVEL = "assign"


def _row_value(row: sqlite3.Row | dict, key: str):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def effective_level(
    conn: sqlite3.Connection, project_id: int, user_row: sqlite3.Row | dict
) -> str:
    """Effectief niveau voor deze user in dit project.

    Mensen → altijd ``assign``. Voor agents: per-agent override wint van de
    per-type default, die weer van de globale default ``assign`` wint.
    """
    if _row_value(user_row, "kind") == "human":
        return DEFAULT_LEVEL

    user_id = _row_value(user_row, "id")
    if user_id is not None:
        row = conn.execute(
            "SELECT level FROM project_agent_access WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
        if row is not None:
            return row["level"]

    agent_type = _row_value(user_row, "agent_type")
    if agent_type is not None:
        row = conn.execute(
            "SELECT level FROM project_agent_type_access "
            "WHERE project_id = ? AND agent_type = ?",
            (project_id, agent_type),
        ).fetchone()
        if row is not None:
            return row["level"]

    return DEFAULT_LEVEL


def set_type_access(
    conn: sqlite3.Connection, project_id: int, agent_type: str, level: str | None
) -> None:
    """Zet (of wis) de per-type default. ``level=None`` verwijdert de rij zodat
    het type terugvalt op de globale default."""
    if level is None:
        conn.execute(
            "DELETE FROM project_agent_type_access WHERE project_id = ? AND agent_type = ?",
            (project_id, agent_type),
        )
        return
    conn.execute(
        "INSERT INTO project_agent_type_access (project_id, agent_type, level) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT (project_id, agent_type) DO UPDATE SET level = excluded.level",
        (project_id, agent_type, level),
    )


def set_agent_access(
    conn: sqlite3.Connection, project_id: int, user_id: int, level: str | None
) -> None:
    """Zet (of wis) de per-agent override. ``level=None`` (inherit) verwijdert de
    rij zodat de agent terugvalt op de per-type default."""
    if level is None:
        conn.execute(
            "DELETE FROM project_agent_access WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        )
        return
    conn.execute(
        "INSERT INTO project_agent_access (project_id, user_id, level) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT (project_id, user_id) DO UPDATE SET level = excluded.level",
        (project_id, user_id, level),
    )


def list_access(conn: sqlite3.Connection, project_id: int) -> dict:
    """Toegangsoverzicht voor de UI: per-type defaults + per-agent overrides met
    het effectieve niveau. De triage-bot valt buiten het roster."""
    type_rows = conn.execute(
        "SELECT agent_type, level FROM project_agent_type_access WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    type_defaults = {r["agent_type"]: r["level"] for r in type_rows}

    # BETON-207: de virtuele assignees (coding-agent/hermes) zijn geen echte
    # agents met codebase-toegang → buiten het access-overzicht houden.
    agents = conn.execute(
        "SELECT id, handle, agent_type FROM users "
        "WHERE active = 1 AND kind = 'agent' AND handle != 'triage' "
        "AND COALESCE(is_virtual, 0) = 0 ORDER BY handle"
    ).fetchall()
    override_rows = conn.execute(
        "SELECT user_id, level FROM project_agent_access WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    overrides = {r["user_id"]: r["level"] for r in override_rows}

    out = []
    for a in agents:
        override = overrides.get(a["id"])
        if override is not None:
            effective = override
        elif a["agent_type"] in type_defaults:
            effective = type_defaults[a["agent_type"]]
        else:
            effective = DEFAULT_LEVEL
        out.append(
            {
                "handle": a["handle"],
                "agent_type": a["agent_type"],
                "override": override,
                "effective": effective,
            }
        )
    return {"type_defaults": type_defaults, "agents": out}
