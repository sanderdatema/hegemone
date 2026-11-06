"""Mensgebonden configuratie-export en eenmalige preview → bevestiging."""
import hashlib
import json
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .. import db, installation_runtime
from ..configuration_transfer import Document, export_document, plan, apply_document
from ..deps import get_db
from ..repo import configuration as repo, events, users
from .installation import installation_admin

router = APIRouter(tags=['settings'])


def instance_id(app):
    with app.state.runtime_lock:
        if not hasattr(app.state, 'configuration_instance'):
            app.state.configuration_instance = secrets.token_hex(16)
        return app.state.configuration_instance


class Confirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    preview_token: SecretStr = Field(min_length=32, max_length=256)
    confirmed: Literal[True]

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('Expliciete bevestiging ontbreekt')
        return value


@router.get('/settings/configuration/export')
def export(response: Response, conn=Depends(get_db), _=Depends(installation_admin)):
    response.headers['Cache-Control'] = 'no-store'
    return export_document(conn)


@router.post('/settings/configuration/preview')
def preview(document: Document, request: Request, response: Response, conn=Depends(get_db), user=Depends(installation_admin)):
    response.headers['Cache-Control'] = 'no-store'
    with db.transaction(conn):
        summary = plan(conn, document)
        token = secrets.token_urlsafe(32)
        expires = repo.save_preview(conn, hashlib.sha256(token.encode()).hexdigest(), user['id'],
            instance_id(request.app), document.model_dump(), repo.baseline(conn))
    return {**summary, 'preview_token': token, 'expires_at': expires}


@router.post('/settings/configuration/confirm')
def confirm(body: Confirmation, request: Request, response: Response, conn=Depends(get_db), user=Depends(installation_admin)):
    response.headers['Cache-Control'] = 'no-store'
    token_hash = hashlib.sha256(body.preview_token.get_secret_value().encode()).hexdigest()
    with db.transaction(conn):
        record = repo.pending_preview(conn, token_hash, user['id'], instance_id(request.app))
        if record is None:
            raise HTTPException(409, 'Importpreview is verlopen, gebruikt of niet beschikbaar')
        if record['baseline_hash'] != repo.baseline(conn):
            raise HTTPException(409, 'Configuratie is gewijzigd; maak een nieuwe importpreview')
        document = Document.model_validate(json.loads(record['document_json']))
        summary = plan(conn, document)
        if not summary['can_apply']:
            raise HTTPException(409, 'Los de importconflicten op vóór bevestiging')
        result = apply_document(conn, document, user['id'])
        prepared = installation_runtime.prepare(request.app, result)
        if prepared.llm is not None and (prepared.triage or prepared.wiki):
            actor = users.get_by_handle(conn, 'triage')
            if actor is None:
                users.create(conn, handle='triage', display_name='Triage', kind='agent')
            elif actor['kind'] != 'agent' or not actor['active']:
                raise HTTPException(422, 'De interne triage-agent is niet beschikbaar')
        repo.consume(conn, token_hash)
        events.record(conn, type='configuration.imported', actor_id=user['id'], payload={'version':1, 'changes':len(summary['changes'])})
    installation_runtime.publish(request.app, prepared)
    return {'applied': True, 'changes': len(summary['changes']), 'revision': result['revision']}
