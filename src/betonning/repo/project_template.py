"""Globale kolomtemplate voor nieuwe projecten (BETON-490)."""

from __future__ import annotations

import json
import sqlite3


def get(conn: sqlite3.Connection) -> list[dict]:
    """Geef de opgeslagen template of de oorspronkelijke standaardkolommen."""
    row = conn.execute("SELECT states_json FROM project_template WHERE id = 1").fetchone()
    if row:
        return json.loads(row["states_json"])
    from .projects import DEFAULT_STATES

    return [
        dict(name=name, group=group, color=color, is_default=bool(default),
             closed=bool(closed), blocks_work=bool(blocks))
        for name, group, color, default, closed, blocks in DEFAULT_STATES
    ]


def replace(conn: sqlite3.Connection, states: list[dict]) -> None:
    """Sla een gevalideerde template op; de aanroeper beheert de transactie."""
    conn.execute(
        "INSERT INTO project_template (id, states_json) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET states_json = excluded.states_json",
        (json.dumps(states),),
    )
