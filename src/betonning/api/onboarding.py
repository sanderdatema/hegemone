"""Geauthenticeerde vervolgsteps na het eenmalige installatieproces."""
from __future__ import annotations
import sqlite3
from fastapi import APIRouter, Depends, HTTPException, Response
from .. import db
from ..deps import current_human, get_db
from ..models import ProjectCreate
from ..repo import onboarding, projects

router = APIRouter(tags=['onboarding'])


@router.get('/onboarding')
def status(response: Response, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(current_human)) -> dict:
    response.headers['Cache-Control'] = 'no-store'
    return onboarding.get(conn, user['id'])


@router.post('/onboarding/project', status_code=201)
def create_project(body: ProjectCreate, conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(current_human)) -> dict:
    with db.transaction(conn):
        state = onboarding.get(conn, user['id'])
        # Een herhaalde request hervat de voltooide stap zonder dubbel project.
        if state['step'] == 'agents' and state['project_key'] == body.key:
            return state
        if state['step'] != 'project':
            raise HTTPException(409, 'Projectstap is niet actief')
        if projects.get_by_key(conn, body.key) is not None:
            raise HTTPException(409, 'Projectcode is al in gebruik')
        projects.create(conn, key=body.key, name=body.name, description=body.description)
        onboarding.project_created(conn, user['id'], body.key)
        return onboarding.get(conn, user['id'])


@router.post('/onboarding/complete')
def complete(conn: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(current_human)) -> dict:
    with db.transaction(conn):
        if onboarding.get(conn, user['id'])['step'] == 'project':
            raise HTTPException(409, 'Maak eerst een project aan')
        onboarding.complete(conn, user['id'])
        return onboarding.get(conn, user['id'])
