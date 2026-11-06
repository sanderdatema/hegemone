"""Duurzaam LLM-callbudget, atomair gereserveerd vóór een provider-aanroep."""

from __future__ import annotations

import sqlite3


def claim(conn: sqlite3.Connection, category: str, limit: int) -> bool:
    if limit <= 0:
        return False
    row = conn.execute(
        "INSERT INTO llm_daily_usage(day,category,spent) VALUES(date('now'),?,1) "
        "ON CONFLICT(day,category) DO UPDATE SET spent=spent+1 "
        "WHERE spent < ? RETURNING spent", (category, limit),
    ).fetchone()
    return row is not None
