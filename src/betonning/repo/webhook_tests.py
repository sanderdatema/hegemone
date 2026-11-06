"""Gerichte testdeliveries; dezelfde wachtrij, zonder algemene fan-out."""

import json


def enqueue(conn, event_id, user_id):
    cursor = conn.execute(
        "INSERT INTO webhook_deliveries(event_id,user_id,channel,not_before) VALUES(?,?,'webhook',strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
        (event_id, user_id),
    )
    return cursor.lastrowid


def pending(conn, user_id):
    row = conn.execute(
        "SELECT d.id,e.payload FROM webhook_deliveries d JOIN events e ON e.id=d.event_id "
        "WHERE d.user_id=? AND d.status='pending' AND e.type='webhook.test' ORDER BY d.id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    return {"id": row["id"], "payload": json.loads(row["payload"])} if row else None


def cancel(conn, delivery_id):
    conn.execute(
        "UPDATE webhook_deliveries SET status='cancelled',last_error='testdoel gewijzigd of uitgeschakeld' WHERE id=? AND status='pending'",
        (delivery_id,),
    )


def status(conn, delivery_id, user_id):
    row = conn.execute(
        "SELECT d.id,d.status,d.attempts,d.next_retry_at,d.last_error FROM webhook_deliveries d JOIN events e ON e.id=d.event_id "
        "WHERE d.id=? AND d.user_id=? AND e.type='webhook.test'",
        (delivery_id, user_id),
    ).fetchone()
    if row is None:
        return None
    result = {key: row[key] for key in ["id", "status", "attempts", "next_retry_at"]}
    error = row["last_error"] or ""
    result["http_status"] = (
        int(error[5:])
        if len(error) == 8 and error.startswith("HTTP ") and error[5:].isdigit()
        else None
    )
    return result
