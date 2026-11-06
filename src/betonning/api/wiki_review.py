"""Mensgebonden review en bescherming van gedeelde kennis (BETON-499)."""

from __future__ import annotations

import sqlite3
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from .. import db as dbm
from ..deps import current_human, get_db, require_project
from ..repo import wiki, wiki_review, events

router = APIRouter(tags=['wiki'])

class ReviewIn(BaseModel):
    approve: bool

class ProtectionIn(BaseModel):
    project: str | None = None
    slug: str = Field(max_length=100)
    protected: bool

@router.get('/wiki-proposals')
def proposals(project: str | None = None, conn: sqlite3.Connection = Depends(get_db),
              _: sqlite3.Row = Depends(current_human)):
    project_id = require_project(conn, project)['id'] if project else None
    return wiki_review.pending(conn, project_id)

@router.post('/wiki-proposals/{proposal_id}/review')
def review(proposal_id: int, body: ReviewIn, conn: sqlite3.Connection = Depends(get_db),
           user: sqlite3.Row = Depends(current_human)):
    try:
        with dbm.transaction(conn):
            return wiki_review.review(conn, proposal_id, user['id'], body.approve)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

@router.put('/wiki-protection')
def protect(body: ProtectionIn, conn: sqlite3.Connection = Depends(get_db),
            _: sqlite3.Row = Depends(current_human)):
    project_id = require_project(conn, body.project)['id'] if body.project else None
    if project_id is None and not body.protected:
        raise HTTPException(422, 'Globale kennis blijft beschermd')
    with dbm.transaction(conn):
        page = wiki.get_by_slug(conn, project_id, body.slug)
        if page is None:
            raise HTTPException(404, 'Onbekende wiki-pagina')
        conn.execute('UPDATE wiki_pages SET protected=? WHERE id=?', (body.protected, page['id']))
        events.record(conn, type='wiki.protection_changed', payload={'slug':body.slug, 'protected':body.protected})
    fresh = wiki.get_by_slug(conn, project_id, body.slug)
    assert fresh is not None
    return wiki.serialize(fresh)
