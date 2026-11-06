"""Chat-met-triage-repository (BETON-120).

Gesprekken zijn geschaald als de wiki: `project_id IS NULL` = de globale thread,
anders per project. Binnen een scope is er telkens hooguit één actieve
(niet-gearchiveerde) sessie — `active_session` maakt 'm lui aan; `archive_session`
sluit 'm af ("Nieuw gesprek") zodat de volgende beurt een verse sessie met lege
context start. Pure sqlite3, connectie als eerste arg, geen ORM.

Zoals de andere repos committen deze functies zelf niet — de caller beheert de
transactie (`db.transaction()`), zodat bv. een engine-beurt (bericht opslaan +
commando's uitvoeren + antwoord opslaan) atomisch blijft.
"""

from __future__ import annotations

import json
import sqlite3


def serialize_message(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "author_id": row["author_id"],
        "body_md": row["body_md"],
        "proposal": json.loads(row["proposal"]) if row["proposal"] else None,
        "status": row["status"],
        "created_at": row["created_at"],
    }


def active_session(conn: sqlite3.Connection, project_id: int | None) -> sqlite3.Row:
    """De nieuwste niet-gearchiveerde sessie voor deze scope; lui aangemaakt als
    er nog geen is."""
    if project_id is None:
        row = conn.execute(
            "SELECT * FROM triage_chat_sessions "
            "WHERE project_id IS NULL AND archived_at IS NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM triage_chat_sessions "
            "WHERE project_id = ? AND archived_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
    if row is not None:
        return row
    cur = conn.execute(
        "INSERT INTO triage_chat_sessions (project_id) VALUES (?)", (project_id,)
    )
    return conn.execute(
        "SELECT * FROM triage_chat_sessions WHERE id = ?", (cur.lastrowid,)
    ).fetchone()


def archive_session(conn: sqlite3.Connection, session_id: int) -> None:
    """Sluit de sessie af ('Nieuw gesprek'); de volgende `active_session`-call voor
    die scope maakt een verse sessie aan."""
    conn.execute(
        "UPDATE triage_chat_sessions SET archived_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE id = ? AND archived_at IS NULL",
        (session_id,),
    )


def list_messages(
    conn: sqlite3.Connection, session_id: int, limit: int | None = None
) -> list[sqlite3.Row]:
    """Berichten van een sessie, oplopend op id (chronologisch)."""
    if limit is None:
        return conn.execute(
            "SELECT * FROM triage_chat_messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    # Laatste `limit` berichten, maar wel chronologisch teruggeven.
    rows = conn.execute(
        "SELECT * FROM triage_chat_messages WHERE session_id = ? "
        "ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return list(reversed(rows))


def add_message(
    conn: sqlite3.Connection,
    session_id: int,
    role: str,
    author_id: int | None,
    body_md: str,
    *,
    proposal: dict | None = None,
    status: str = "final",
) -> sqlite3.Row:
    cur = conn.execute(
        "INSERT INTO triage_chat_messages "
        "(session_id, role, author_id, body_md, proposal, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            session_id,
            role,
            author_id,
            body_md,
            json.dumps(proposal) if proposal is not None else None,
            status,
        ),
    )
    return conn.execute(
        "SELECT * FROM triage_chat_messages WHERE id = ?", (cur.lastrowid,)
    ).fetchone()


def set_message_status(conn: sqlite3.Connection, message_id: int, status: str) -> None:
    conn.execute(
        "UPDATE triage_chat_messages SET status = ? WHERE id = ?", (status, message_id)
    )


def get_message(conn: sqlite3.Connection, message_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM triage_chat_messages WHERE id = ?", (message_id,)
    ).fetchone()


def get_pending(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
    """Het laatste bericht met status='pending' in deze sessie, of None."""
    return conn.execute(
        "SELECT * FROM triage_chat_messages "
        "WHERE session_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()


def record_action(
    conn: sqlite3.Connection,
    *,
    message_id: int | None,
    commanded_by: int,
    verb: str,
    project_id: int | None,
    params: dict,
    target_refs: list[str],
) -> sqlite3.Row:
    cur = conn.execute(
        "INSERT INTO triage_chat_actions "
        "(message_id, commanded_by, verb, project_id, params, target_refs) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            message_id,
            commanded_by,
            verb,
            project_id,
            json.dumps(params),
            json.dumps(target_refs),
        ),
    )
    return conn.execute(
        "SELECT * FROM triage_chat_actions WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
