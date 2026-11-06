"""Duurzame, conservatieve schrijfquota; een geaccepteerde body telt éénmaal."""

from __future__ import annotations

from ..config import env

import sqlite3


def claim(conn: sqlite3.Connection, user, amount: int) -> bool:
    if amount <= 0:
        return True
    factor = 3 if user['kind'] == 'human' else 1
    daily = int(env('BETONNING_API_DAILY_BYTES', 50 * 1024 * 1024)) * factor
    total = int(env('BETONNING_API_TOTAL_BYTES', 512 * 1024 * 1024)) * factor
    if amount > daily or amount > total:
        return False
    row = conn.execute(
        "INSERT INTO api_write_usage(user_id,total_bytes,day,day_bytes) VALUES(?,?,date('now'),?) "
        "ON CONFLICT(user_id) DO UPDATE SET total_bytes=total_bytes+excluded.total_bytes, "
        "day_bytes=(CASE WHEN day=date('now') THEN day_bytes ELSE 0 END)+excluded.day_bytes, day=date('now') "
        "WHERE total_bytes+excluded.total_bytes <= ? "
        "AND (CASE WHEN day=date('now') THEN day_bytes ELSE 0 END)+excluded.day_bytes <= ? RETURNING user_id",
        (user['id'],amount,amount,total,daily),
    ).fetchone()
    return row is not None
