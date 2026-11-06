"""Compatibel sleutelbeleid: bestaande keys zijn volledig, scopes zijn opt-in."""

from __future__ import annotations

import json
from datetime import datetime, timezone

SCOPES = frozenset({"read", "write", "memory:write", "llm", "admin"})


def value(user, key, default=None):
    try:
        return user[key]
    except (KeyError, IndexError, TypeError):
        return default


def scopes(user):
    raw = value(user, "api_key_scopes")
    return SCOPES if raw is None else frozenset(json.loads(raw))


def projects(user):
    raw = value(user, "api_key_projects")
    return None if raw is None else frozenset(json.loads(raw))


def valid(user, now=None):
    if not user or not user["active"] or value(user, "is_virtual", False):
        return False
    expires = value(user, "api_key_expires_at")
    if expires is None:
        return True
    try:
        until = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        return until.tzinfo is not None and until > (now or datetime.now(timezone.utc))
    except ValueError:
        return False
