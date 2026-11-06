"""Intrekbare, server-side browsersessies; nooit een API-key in de cookie."""

from __future__ import annotations

import hmac
import secrets
import time
from .. import security, credential_policy

COOKIE = "bt_session"
TTL = 30 * 24 * 3600  # Dertig dagen; uitloggen en keyrotatie trekken direct in.


def csrf(raw):
    return security._media_sig("browser-csrf:" + raw)


def create(conn, user, now=None):
    now = time.time() if now is None else now
    raw = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM browser_sessions WHERE expires_at <= ?", (now,))
    # Maximaal tien browsersessies; de oudste vervalt bij een extra login.
    old = conn.execute(
        "SELECT token_hash FROM browser_sessions WHERE user_id=? ORDER BY expires_at DESC LIMIT -1 OFFSET 9",
        (user["id"],),
    ).fetchall()
    for row in old:
        conn.execute(
            "DELETE FROM browser_sessions WHERE token_hash=?", (row["token_hash"],)
        )
    conn.execute(
        "INSERT INTO browser_sessions(token_hash,user_id,key_fingerprint,expires_at) VALUES(?,?,?,?)",
        (security.hash_api_key(raw), user["id"], user["api_key_hash"], now + TTL),
    )
    return raw, now + TTL


def resolve(conn, raw, now=None):
    if not raw or len(raw) > 128:
        return None
    row = conn.execute(
        "SELECT * FROM browser_sessions WHERE token_hash=?",
        (security.hash_api_key(raw),),
    ).fetchone()
    now = time.time() if now is None else now
    if not row or row["expires_at"] <= now:
        return None
    user = conn.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
    if not credential_policy.valid(user) or not hmac.compare_digest(
        user["api_key_hash"], row["key_fingerprint"]
    ):
        return None
    return user, row["expires_at"]


def revoke(conn, raw):
    if raw:
        conn.execute(
            "DELETE FROM browser_sessions WHERE token_hash=?",
            (security.hash_api_key(raw),),
        )
