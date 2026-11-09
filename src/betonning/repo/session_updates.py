"""Read-only human activity for a client's explicit ticket cursors."""
from __future__ import annotations

from .. import credential_policy
from ..outbound import outbound
from . import items

MAX_WATCHED = 32


def read_updates(conn, user, cursors: dict[str, int | None]) -> dict:
    allowed = credential_policy.projects(user)
    updated, notices, unavailable = {}, [], []
    for ref, after in cursors.items():
        key, seq = items.parse_ref(ref)
        if allowed is not None and key.upper() not in allowed:
            unavailable.append(ref)
            continue
        # One snapshot per ticket: watermark and human event cannot race each other.
        row = conn.execute(
            "SELECT p.key || '-' || i.seq AS ref, "
            "COALESCE((SELECT MAX(id) FROM events WHERE item_id=i.id),0) AS cursor, "
            "e.type,u.handle AS actor FROM items i JOIN projects p ON p.id=i.project_id "
            "LEFT JOIN events e ON e.id=(SELECT MAX(h.id) FROM events h JOIN users a ON a.id=h.actor_id "
            "WHERE h.item_id=i.id AND h.id>? AND a.kind='human' AND a.id!=? "
            "AND h.type IN ('comment.created','comment.updated','question.answered')) "
            "LEFT JOIN users u ON u.id=e.actor_id "
            "WHERE p.key=? COLLATE NOCASE AND i.seq=? AND i.archived_at IS NULL AND p.archived_at IS NULL",
            (after,user['id'],key,str(seq)),
        ).fetchone()
        if row is None:
            unavailable.append(ref)
            continue
        updated[row['ref']] = row['cursor']
        if row['type'] is not None:
            notices.append({'ref':row['ref'],'actor':row['actor'],
                            'kind':'answer' if row['type']=='question.answered' else 'comment'})
    return {'cursors':updated,'updates':notices,'unavailable':unavailable,
            'notice':outbound('session_updates.notice',tickets=', '.join(n['ref'] for n in notices)) if notices else None}
