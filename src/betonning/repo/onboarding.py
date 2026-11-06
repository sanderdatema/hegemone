"""Hervatbare eerste onboarding; bestaande gebruikers starten geen wizard."""
from __future__ import annotations
import sqlite3


def start(conn: sqlite3.Connection, user_id: int, locale: str) -> None:
    conn.execute('INSERT INTO onboarding (user_id, locale) VALUES (?, ?)', (user_id, locale))


def get(conn: sqlite3.Connection, user_id: int) -> dict:
    row = conn.execute('SELECT step, locale, project_key FROM onboarding WHERE user_id=?', (user_id,)).fetchone()
    if row is None:
        return {'required': False, 'step': 'complete', 'locale': 'en', 'project_key': None}
    return {**dict(row), 'required': row['step'] != 'complete'}


def project_created(conn: sqlite3.Connection, user_id: int, project_key: str) -> None:
    conn.execute("UPDATE onboarding SET step='agents', project_key=? WHERE user_id=? AND step='project'", (project_key, user_id))


def complete(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("UPDATE onboarding SET step='complete' WHERE user_id=? AND step='agents'", (user_id,))
