"""Versieerbare installatieopslag; versleuteling en validatie horen erboven."""
from __future__ import annotations

import json
import sqlite3


def get(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute('SELECT * FROM installation_settings WHERE id = 1').fetchone()
    if row is None:
        return None
    result = dict(row)
    result['settings'] = json.loads(result.pop('settings_json'))
    return result


def replace(conn: sqlite3.Connection, *, settings: dict, llm_key: bytes | None,
            embedding_key: bytes | None, revision: int, actor_id: int) -> dict:
    """Aanroeper bewaakt revision en transactie; deze laag slaat alleen op."""
    conn.execute(
        "INSERT INTO installation_settings (id, schema_version, revision, settings_json, llm_key, embedding_key, updated_by) "
        "VALUES (1, 1, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
        "revision=excluded.revision, settings_json=excluded.settings_json, llm_key=excluded.llm_key, "
        "embedding_key=excluded.embedding_key, updated_by=excluded.updated_by, "
        "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
        (revision, json.dumps(settings), llm_key, embedding_key, actor_id),
    )
    row = get(conn)
    assert row is not None
    return row
