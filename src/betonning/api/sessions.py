"""Browserlogin met een key-uitwisseling, HttpOnly-cookie en CSRF-token."""

from __future__ import annotations

import sqlite3
from fastapi import APIRouter, Depends, Request, Response
from .. import db as dbm
from ..deps import current_human, get_db
from ..repo import browser_sessions as sessions, users
from .media import _is_https

router = APIRouter(tags=['auth'])

@router.post('/session')
def login(request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db),
          user: sqlite3.Row = Depends(current_human)):
    with dbm.transaction(conn):
        sessions.revoke(conn, request.cookies.get(sessions.COOKIE))
        raw, expires = sessions.create(conn, user)
    response.set_cookie(sessions.COOKIE, raw, httponly=True, samesite='strict',
                        secure=_is_https(request), max_age=sessions.TTL, path='/api/v1')
    response.headers['Cache-Control'] = 'no-store'
    return {'user': users.serialize(user), 'csrf_token': sessions.csrf(raw), 'expires_at': expires}

@router.get('/session')
def session(request: Request, response: Response, user: sqlite3.Row = Depends(current_human)):
    response.headers['Cache-Control'] = 'no-store'
    raw = getattr(request.state, 'session_token', None)
    return {'user': users.serialize(user), 'csrf_token': sessions.csrf(raw) if raw else None,
            'expires_at': getattr(request.state, 'auth_expires_at', None)}
