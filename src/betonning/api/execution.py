"""Executor control plane. It never launches a process or changes provider access."""
from __future__ import annotations

import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .. import credential_policy, db
from ..api_error_codes import CATALOG
from ..deps import current_human, current_user, get_db, require_item, require_project
from ..repo import execution as repo, users

router = APIRouter(tags=['execution'])
Capability = Annotated[str, Field(pattern=r'^[a-z][a-z0-9:_.-]{0,79}$')]
Profile = Annotated[str, Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')]
Digest = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class BindingIn(Input):
    enabled: bool
    profile: Profile
    capabilities: list[Capability] = Field(default_factory=list, max_length=32)


class ClaimIn(Input):
    context_digest: Digest
    profile: Profile
    capabilities_checked: list[Capability] = Field(max_length=32)
    task_read: Literal[True]
    owner: str = Field(min_length=1, max_length=120)
    external_task_id: str | None = Field(default=None, max_length=300)


class FenceIn(Input):
    fence: int = Field(ge=1)


class StartIn(FenceIn):
    context_digest: Digest
    external_run_id: str | None = Field(default=None, max_length=300)


class BlockIn(Input):
    kind: Literal['capability','transport','human','task']
    reason: str = Field(min_length=1, max_length=2000)
    missing_requirements: list[Capability] = Field(default_factory=list, max_length=32)
    responsible: str = Field(min_length=1, max_length=120)
    resume_condition: str = Field(min_length=1, max_length=1000)
    fence: int = Field(default=0, ge=0)
    question_id: int | None = Field(default=None, ge=1)


class Evidence(Input):
    kind: Literal['artifact','test','revision']
    reference: str = Field(min_length=1, max_length=2048)
    sha256: Digest | None = None


class CompleteIn(FenceIn):
    evidence: list[Evidence] = Field(min_length=1, max_length=20)


class ResumeIn(Input):
    reason: str = Field(min_length=1, max_length=2000)
    previous_worker_stopped: bool = False
    previous_effects_reviewed: bool = False


def _failure(exc):
    # Specific codes are translated by the ordinary English/Dutch API catalog.
    from ..execution_errors import code_for
    code = code_for(str(exc))
    raise HTTPException(403 if isinstance(exc, repo.ExecutionDenied) else 409, CATALOG[code]['nl']) from exc


def _target(conn, ref, request_id, user, *, own=False):
    item = require_item(conn,ref)
    try:
        result = repo.get(conn,request_id)
    except LookupError as exc:
        raise HTTPException(404,'Onbekend uitvoerverzoek') from exc
    if result['item_id']!=item['id']:
        raise HTTPException(404,'Onbekend uitvoerverzoek')
    if (own or user['kind']!='human') and result['user_id']!=user['id']:
        _failure(repo.ExecutionDenied('Execution belongs to another identity'))
    return result


def _fresh_executor(conn, user, request):
    fresh = users.get(conn,user['id'])
    if (fresh is None or not credential_policy.valid(fresh)
            or not hmac.compare_digest(fresh['api_key_hash'],user['api_key_hash'])):
        raise repo.ExecutionDenied('Executor identity was revoked')
    return fresh, repo.authenticate(conn,fresh,request.headers.get('x-execution-key',''))


def _mutate(conn, user, request, ref, execution_id, callback):
    rejection = None
    result = None
    with db.transaction(conn):
        try:
            actor, config = _fresh_executor(conn,user,request)
            target = _target(conn,ref,execution_id,actor,own=True)
        except repo.ExecutionDenied as exc:
            _failure(exc)
        # Persist reconciliation even when the attempted action is rejected. A
        # savepoint rolls back that action, not a detected revocation/lost owner.
        repo.observe_item(conn,target['item_id'])
        target = repo.get(conn,execution_id)
        conn.execute('SAVEPOINT execution_action')
        try:
            result = callback(target,actor,config,request.headers.get('x-execution-owner',''))
        except (repo.ExecutionConflict, repo.ExecutionDenied) as exc:
            conn.execute('ROLLBACK TO execution_action')
            rejection = exc
        finally:
            conn.execute('RELEASE execution_action')
    if rejection is not None:
        _failure(rejection)
    return repo.serialize(conn,result)


@router.post('/users/{handle}/execution')
def configure(handle: str, body: BindingIn, response: Response,
              conn=Depends(get_db), human=Depends(current_human)):
    response.headers['Cache-Control']='no-store'
    user = users.get_by_handle(conn,handle)
    if user is None:
        raise HTTPException(404,'Onbekende user')
    try:
        with db.transaction(conn):
            value, key = repo.configure(conn,user,enabled=body.enabled,profile=body.profile,
                                        capabilities=body.capabilities,actor_id=human['id'])
    except repo.ExecutionConflict as exc:
        _failure(exc)
    return {'binding':value,'execution_key':key}


@router.get('/users/{handle}/execution')
def get_binding(handle: str, response: Response, conn=Depends(get_db), human=Depends(current_human)):
    response.headers['Cache-Control']='no-store'
    user = users.get_by_handle(conn,handle)
    if user is None:
        raise HTTPException(404,'Onbekende user')
    return repo.binding_public(repo.binding(conn,user['id']))


@router.get('/projects/{key}/executions')
def list_requests(key: str, limit: int = Query(100, ge=1, le=100), conn=Depends(get_db), user=Depends(current_user)):
    project = require_project(conn,key)
    return repo.list_for_project(conn,project['id'],None if user['kind']=='human' else user['id'],limit)


@router.post('/projects/{key}/executions/poll')
def poll(key: str, request: Request, after_item_id: int = Query(0,ge=0), limit: int = Query(100,ge=1,le=100),
         conn=Depends(get_db), user=Depends(current_user)):
    project = require_project(conn,key)
    try:
        with db.transaction(conn):
            actor, _config = _fresh_executor(conn,user,request)
            return repo.poll(conn,project['id'],actor['id'],after_item_id=after_item_id,limit=limit)
    except repo.ExecutionDenied as exc:
        _failure(exc)


@router.get('/items/{ref}/executions/{execution_id}')
def get_context(ref: str, execution_id: str, conn=Depends(get_db), user=Depends(current_user)):
    return repo.context(conn,_target(conn,ref,execution_id,user))


@router.post('/items/{ref}/executions/{execution_id}/claim')
def claim(ref: str, execution_id: str, body: ClaimIn, request: Request, conn=Depends(get_db), user=Depends(current_user)):
    return _mutate(conn,user,request,ref,execution_id,lambda target,actor,config,nonce: repo.claim(
        conn,target,actor,config,digest=body.context_digest,profile=body.profile,
        capabilities=body.capabilities_checked,owner=body.owner,nonce=nonce,external_task_id=body.external_task_id))


@router.post('/items/{ref}/executions/{execution_id}/start')
def start(ref: str, execution_id: str, body: StartIn, request: Request, conn=Depends(get_db), user=Depends(current_user)):
    return _mutate(conn,user,request,ref,execution_id,lambda target,actor,config,nonce: repo.start(
        conn,target,actor,nonce=nonce,fence=body.fence,digest=body.context_digest,external_run_id=body.external_run_id))


@router.post('/items/{ref}/executions/{execution_id}/heartbeat')
def heartbeat(ref: str, execution_id: str, body: FenceIn, request: Request, conn=Depends(get_db), user=Depends(current_user)):
    return _mutate(conn,user,request,ref,execution_id,lambda target,actor,config,nonce: repo.heartbeat(
        conn,target,actor,nonce=nonce,fence=body.fence))


@router.post('/items/{ref}/executions/{execution_id}/block')
def block(ref: str, execution_id: str, body: BlockIn, request: Request, conn=Depends(get_db), user=Depends(current_user)):
    return _mutate(conn,user,request,ref,execution_id,lambda target,actor,config,nonce: repo.block(
        conn,target,actor,kind=body.kind,reason=body.reason,missing=body.missing_requirements,
        responsible=body.responsible,resume_condition=body.resume_condition,
        nonce=nonce,fence=body.fence,question_id=body.question_id))


@router.post('/items/{ref}/executions/{execution_id}/stop')
def stop(ref: str, execution_id: str, body: FenceIn, request: Request, conn=Depends(get_db), user=Depends(current_user)):
    return _mutate(conn,user,request,ref,execution_id,lambda target,actor,config,nonce: repo.stop(
        conn,target,actor,nonce=nonce,fence=body.fence))


@router.post('/items/{ref}/executions/{execution_id}/complete')
def complete(ref: str, execution_id: str, body: CompleteIn, request: Request, conn=Depends(get_db), user=Depends(current_user)):
    return _mutate(conn,user,request,ref,execution_id,lambda target,actor,config,nonce: repo.complete(
        conn,target,actor,nonce=nonce,fence=body.fence,evidence=[value.model_dump() for value in body.evidence]))


@router.post('/items/{ref}/executions/{execution_id}/resume')
def resume(ref: str, execution_id: str, body: ResumeIn, conn=Depends(get_db), human=Depends(current_human)):
    try:
        with db.transaction(conn):
            target = _target(conn,ref,execution_id,human)
            result = repo.resume(conn,target,actor_id=human['id'],reason=body.reason,
                                 worker_stopped=body.previous_worker_stopped,effects_reviewed=body.previous_effects_reviewed)
    except repo.ExecutionConflict as exc:
        _failure(exc)
    return repo.serialize(conn,result)
