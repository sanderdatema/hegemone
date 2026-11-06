"""Eenmalige eerste beheerder; expliciet token, geen publieke registratie."""
from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from .. import db, setup_policy
from ..deps import get_db
from ..repo import users, browser_sessions, onboarding
from .media import _is_https

router = APIRouter(tags=['setup'])


class SetupCreate(BaseModel):
    locale: Literal["en", "nl"] = "en"
    handle: str = Field(min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=100)

    @field_validator('handle')
    @classmethod
    def valid_handle(cls, value: str) -> str:
        return users.validate_handle(value)

    @field_validator('display_name')
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('Naam mag niet leeg zijn')
        return value.strip()


def require_setup(request: Request) -> None:
    error = setup_policy.authorize(request)
    if error:
        raise HTTPException(*error)


def installed(conn: sqlite3.Connection) -> bool:
    # Ook een gedeactiveerde beheerder houdt publieke setup gesloten.
    return conn.execute("SELECT 1 FROM users WHERE kind='human' LIMIT 1").fetchone() is not None


@router.get('/setup')
def status(response: Response, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    response.headers['Cache-Control'] = 'no-store'
    done = installed(conn)
    return {'required': not done, 'enabled': not done and setup_policy.enabled()}


@router.post('/setup', status_code=201, dependencies=[Depends(require_setup)])
def initialize(body: SetupCreate, request: Request, response: Response,
               conn: sqlite3.Connection = Depends(get_db)) -> dict:
    with db.transaction(conn):
        if installed(conn):
            raise HTTPException(409, 'Installatie is al voltooid')
        if users.get_by_handle(conn, body.handle) is not None:
            raise HTTPException(409, 'Handle is al in gebruik')
        user, api_key = users.create(conn, handle=body.handle, display_name=body.display_name, kind='human')
        onboarding.start(conn, user['id'], body.locale)
        raw, expires = browser_sessions.create(conn, users.get(conn, user['id']))
    response.set_cookie(browser_sessions.COOKIE, raw, httponly=True, samesite='strict',
                        secure=_is_https(request), max_age=browser_sessions.TTL, path='/api/v1')
    response.headers['Cache-Control'] = 'no-store'
    # Eenmalig bewaren voor een volgende login; niet opslaan in browserstorage.
    return {'user': user, 'api_key': api_key, 'csrf_token': browser_sessions.csrf(raw), 'expires_at': expires}
