"""Durable task handoff, fenced executor ownership and explicit recovery.

Only a human-configured executor can claim work. Notification delivery never
claims a task. Call mutations inside the caller's BEGIN IMMEDIATE transaction.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time

from .. import credential_policy
from ..execution_errors import message
from . import access, comments, items, projects, users

LEASE_SECONDS = 120
MAX_TRANSPORT_ATTEMPTS = 3
ACTIVE = ('pending', 'claimed', 'running', 'stopping', 'blocked')


class ExecutionConflict(ValueError):
    pass


class ExecutionDenied(PermissionError):
    pass


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _log(conn, request, event_name: str, actor_id=None, **payload):
    # No comment, fanout or recursive handoff trigger for technical transitions.
    conn.execute(
        'INSERT INTO events(type,item_id,actor_id,payload) VALUES(?,?,?,?)',
        (f'execution.{event_name}', request['item_id'], actor_id,
         _json({'execution_id': request['id'], **payload})),
    )


def binding(conn, user_id: int):
    return conn.execute('SELECT * FROM execution_bindings WHERE user_id=?', (user_id,)).fetchone()


def binding_public(row):
    return None if row is None else {
        'enabled': bool(row['enabled']), 'profile': row['profile'],
        'capabilities': json.loads(row['capabilities']), 'generation': row['generation'],
    }


def authenticate(conn, user, token: str):
    row = binding(conn, user['id'])
    if (row is None or not row['enabled'] or not row['token_hash'] or not token
            or len(token) > 256 or not hmac.compare_digest(_hash(token), row['token_hash'])):
        raise ExecutionDenied('Execution authorization required')
    return row


def configure(conn, user, *, enabled: bool, profile: str, capabilities: list[str], actor_id: int):
    if user['kind'] != 'agent' or user['is_virtual'] or (enabled and not user['active']):
        raise ExecutionConflict('An active, non-virtual agent is required')
    token = secrets.token_urlsafe(32) if enabled else None
    old = binding(conn, user['id'])
    generation = old['generation'] + 1 if old else 1
    conn.execute(
        "INSERT INTO execution_bindings(user_id,enabled,profile,capabilities,generation,token_hash) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,"
        "profile=excluded.profile,capabilities=excluded.capabilities,generation=excluded.generation,"
        "token_hash=excluded.token_hash,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
        (user['id'], int(enabled), profile, _json(sorted(set(capabilities))), generation,
         _hash(token) if token else None),
    )
    # Configuration is an explicit prerequisite change, not a delivery retry.
    item_ids = {r['id'] for r in conn.execute('SELECT id FROM items WHERE assignee_id=?', (user['id'],))}
    item_ids.update(r['item_id'] for r in conn.execute(
        "SELECT item_id FROM execution_requests WHERE user_id=? AND status NOT IN ('completed','cancelled')",
        (user['id'],)))
    for item_id in item_ids:
        observe_item(conn, item_id, prerequisite_changed=True)
    conn.execute('INSERT INTO events(type,actor_id,payload) VALUES(?,?,?)', (
        'execution.configured', actor_id, _json({'handle': user['handle'], 'enabled': enabled, 'generation': generation})))
    return binding_public(binding(conn, user['id'])), token


def revision(conn, item) -> str:
    # Mutable execution state/own comments must not generate another task.
    fields = ('project_id','title','description_md','plan_md','priority','workload',
              'parent_id','milestone_id','due_date','deferred_until','guardrail_md','guardrail_review_by')
    content = {key: item[key] for key in fields}
    content['labels'] = [r['label_id'] for r in conn.execute(
        'SELECT label_id FROM item_labels WHERE item_id=? ORDER BY label_id', (item['id'],))]
    content['relations'] = [tuple(r) for r in conn.execute(
        'SELECT item_id,related_item_id,type FROM relations WHERE item_id=? OR related_item_id=? ORDER BY id',
        (item['id'], item['id']))]
    content['attachments'] = [r['sha256'] for r in conn.execute(
        'SELECT sha256 FROM attachments WHERE item_id=? ORDER BY id', (item['id'],))]
    return _hash(_json(content))


def intent_event(conn, item) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(e.id),0) FROM events e LEFT JOIN users u ON u.id=e.actor_id "
        "WHERE e.item_id=? AND (e.type IN ('item.created','item.moved') OR (e.type='item.updated' AND ("
        "json_type(e.payload,'$.assignee')='object' OR (u.kind='human' AND "
        "json_extract(e.payload,'$.state.to') IN (SELECT name FROM states WHERE project_id=? AND grp='unstarted')))))",
        (item['id'], item['project_id']),
    ).fetchone()
    return row[0]


def _policy(conn, item, user, config) -> str | None:
    if item is None:
        return message('no_task')
    if projects.is_archived(conn, item['project_id']) or item['archived_at'] or item['locked_at']:
        return message('archived_locked')
    state = conn.execute('SELECT * FROM states WHERE id=?', (item['state_id'],)).fetchone() if item['state_id'] else None
    if state is None or state['grp'] in ('completed','cancelled') or state['blocks_work']:
        return message('state_blocked')
    if config is None or not config['enabled'] or not credential_policy.valid(user) or user['kind'] != 'agent':
        return message('executor_disabled')
    allowed = credential_policy.projects(user)
    project = conn.execute('SELECT key FROM projects WHERE id=?', (item['project_id'],)).fetchone()
    if (not {'read','write'} <= credential_policy.scopes(user)
            or (allowed is not None and project['key'] not in allowed)
            or access.effective_level(conn, item['project_id'], user) != 'assign'):
        return message('project_permission')
    blocked = conn.execute(
        "SELECT 1 FROM relations r JOIN items parent ON parent.id=r.item_id "
        "LEFT JOIN states s ON s.id=parent.state_id WHERE "
        "(r.related_item_id=? AND r.type='blocks' AND (s.grp IS NULL OR s.grp NOT IN ('completed','cancelled'))) "
        "OR (r.item_id=? AND r.type='duplicate_of') LIMIT 1", (item['id'],item['id']),
    ).fetchone()
    if blocked:
        return message('relation_blocked')
    return None


def latest(conn, item_id: int):
    return conn.execute('SELECT * FROM execution_requests WHERE item_id=? ORDER BY rowid DESC LIMIT 1', (item_id,)).fetchone()


def get(conn, request_id: str):
    row = conn.execute('SELECT * FROM execution_requests WHERE id=?', (request_id,)).fetchone()
    if row is None:
        raise LookupError('Unknown execution request')
    return row


def _update(conn, request, **fields):
    names = ','.join(f'{name}=?' for name in fields)
    conn.execute(f"UPDATE execution_requests SET {names},updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                 (*fields.values(),request['id']))
    return get(conn, request['id'])


def _end_run(conn, request, phase: str, now: float):
    if request['run_id'] is not None:
        conn.execute('UPDATE execution_runs SET phase=?,ended_at=? WHERE id=? AND ended_at IS NULL',
                     (phase,now,request['run_id']))


def _blocked(conn, request, *, kind: str, reason: str, missing=(), responsible=None,
             resume_condition: str, question_id=None, retry_at=None, now=None):
    value = {'kind':kind,'reason':reason,'missing':sorted(set(missing)),
             'responsible':responsible,'resume_condition':resume_condition,'question_id':question_id}
    digest = _hash(_json(value))
    if request['status'] == 'blocked' and request['block_digest'] == digest:
        return request
    _end_run(conn, request, 'recovery' if kind == 'recovery' else 'blocked', time.time() if now is None else now)
    updated = _update(conn, request, status='blocked', block_kind=kind, reason=reason,
                      missing_requirements=_json(value['missing']), responsible=responsible,
                      resume_condition=resume_condition, block_digest=digest, question_id=question_id, retry_at=retry_at)
    _log(conn, updated, 'blocked', kind=kind, reason=reason, missing=value['missing'], responsible=responsible)
    return updated


def _pending(conn, request, item, config):
    updated = _update(conn, request, status='pending', revision=revision(conn,item),
                      intent_event_id=intent_event(conn,item), profile=config['profile'],
                      binding_generation=config['generation'], run_id=None, block_kind=None,
                      block_digest=None, reason=None, missing_requirements='[]', responsible=None,
                      resume_condition=None, retry_at=None, question_id=None)
    _log(conn, updated, 'ready')
    return updated


def observe_item(conn, item_id: int, *, prerequisite_changed: bool = False, now: float | None = None):
    """Idempotent reconciliation under the same write lock as the source event."""
    now = time.time() if now is None else now
    item = items.get(conn,item_id)
    if item is None:
        return None
    request = latest(conn,item_id)
    if request is not None and request['status'] in ACTIVE:
        user = users.get(conn,request['user_id'])
        config = binding(conn,request['user_id'])
        reason = _policy(conn,item,user,config)
        questions = comments.open_questions_for_item(conn,item_id)
        human_wait = bool(questions) and (item['assignee_id'] == request['user_id'] or any(
            q['prior_assignee_id'] == request['user_id'] for q in questions))
        same_owner = item['assignee_id'] == request['user_id']
        changed = revision(conn,item) != request['revision']
        generation_changed = config is not None and config['generation'] != request['binding_generation']
        if request['status'] in ('claimed','running','stopping'):
            run = conn.execute('SELECT * FROM execution_runs WHERE id=?',(request['run_id'],)).fetchone()
            if run and run['lease_until'] <= now:
                if request['status'] == 'claimed' and run['started_at'] is None and not reason and same_owner and not human_wait:
                    _end_run(conn,request,'expired',now)
                    return _pending(conn,request,item,config)
                return _blocked(conn,request,kind='recovery',reason=message('owner_lost'),
                                resume_condition=message('owner_recovery'),now=now)
            if reason or not same_owner or changed or human_wait or generation_changed:
                if request['status'] != 'stopping':
                    request = _update(conn,request,status='stopping',block_kind='human' if human_wait else 'policy',
                                      reason=reason or (message('human_answer') if human_wait else message('source_changed')),
                                      resume_condition=message('owner_ack_required'))
                    _log(conn,request,'stop_requested',reason=request['reason'])
                return request
            return request
        if request['status'] == 'blocked' and request['block_kind'] == 'recovery':
            return request
        if human_wait:
            return _blocked(conn,request,kind='human',reason=message('human_answer'),
                            question_id=questions[0]['id'],responsible=users.handle_of(conn,item['assignee_id']),
                            resume_condition=message('answer_existing'),now=now)
        if reason and same_owner:
            return _blocked(conn,request,kind='policy',reason=reason,responsible='administrator',
                            resume_condition=message('permission_resume'),now=now)
        if not same_owner:
            updated = _update(conn,request,status='cancelled',reason=reason or message('assignment_changed'))
            _log(conn,updated,'cancelled',reason=updated['reason'])
            request = updated
        elif request['status'] == 'blocked':
            if request['block_kind'] in ('human','policy') or (prerequisite_changed and request['block_kind'] in ('capability','policy')):
                return _pending(conn,request,item,config)
            if request['block_kind'] == 'transport' and request['retry_at'] is not None and request['retry_at'] <= now:
                return _pending(conn,request,item,config)
            return request
        else:
            if changed or generation_changed:
                return _pending(conn,request,item,config)
            return request
    user = users.get(conn,item['assignee_id']) if item['assignee_id'] else None
    if user is None or user['kind'] != 'agent':
        return request
    config = binding(conn,user['id'])
    if config is None or item['archived_at'] or projects.is_archived(conn,item['project_id']):
        return request
    state = conn.execute('SELECT * FROM states WHERE id=?', (item['state_id'],)).fetchone() if item['state_id'] else None
    if state is None or state['grp'] != 'unstarted':
        return request
    intent = intent_event(conn,item)
    if request is not None and request['user_id'] == user['id'] and request['intent_event_id'] == intent:
        return request
    request_id = secrets.token_hex(16)
    conn.execute('INSERT INTO execution_requests(id,item_id,user_id,profile,binding_generation,intent_event_id,revision,status) VALUES(?,?,?,?,?,?,?,?)',
                 (request_id,item_id,user['id'],config['profile'],config['generation'],intent,revision(conn,item),'pending'))
    request = get(conn,request_id)
    _log(conn,request,'requested')
    return observe_item(conn,item_id,now=now)


def context(conn, request):
    item = items.get(conn,request['item_id'])
    if item is None:
        raise LookupError('Unknown task')
    attempts = [serialize_run(row) for row in conn.execute('SELECT * FROM execution_runs WHERE request_id=? ORDER BY fence', (request['id'],))]
    config = binding(conn,request['user_id'])
    return {'execution': serialize(conn,request), 'attempts': attempts,
            'required_capabilities':json.loads(config['capabilities']) if config is not None else [],
            'item': items.serialize(conn,item),
            'plan_md': item['plan_md'], 'context_digest': revision(conn,item),
            'comments': [comments.serialize(conn,row) for row in comments.list_for_item(conn,item['id'])]}


def serialize_run(run):
    return {key:run[key] for key in ('id','fence','owner','phase','external_task_id','external_run_id',
                                    'claimed_at','started_at','lease_until','ended_at')} | {'evidence':json.loads(run['evidence'])}


def serialize(conn, request):
    run = conn.execute('SELECT * FROM execution_runs WHERE id=?',(request['run_id'],)).fetchone() if request['run_id'] else None
    result = {key:request[key] for key in ('id','profile','intent_event_id','revision','status','block_kind','reason',
                                        'responsible','resume_condition','fence','transport_attempts','retry_at','question_id')} | {
        'assignee':users.handle_of(conn,request['user_id']),
        'missing_requirements':json.loads(request['missing_requirements']),
        'run': None if run is None else serialize_run(run),
    }
    # Read-only projection: an absent/revoked executor need not poll to make its
    # lost lease visible. The next authorized mutation persists reconciliation.
    if request['status'] in ('claimed','running','stopping'):
        item = items.get(conn,request['item_id'])
        user = users.get(conn,request['user_id'])
        policy = _policy(conn,item,user,binding(conn,request['user_id']))
        if run is not None and run['lease_until'] <= time.time():
            safe_unstarted = (request['status']=='claimed' and run['started_at'] is None
                              and not policy and item is not None and user is not None and item['assignee_id']==user['id']
                              and not comments.open_questions_for_item(conn,item['id']))
            if safe_unstarted:
                result.update(status='pending')
            else:
                result.update(status='blocked',block_kind='recovery',reason=message('owner_lost'),
                              resume_condition=message('owner_recovery'))
        elif policy:
            result.update(status='stopping',block_kind='policy',reason=policy,
                          resume_condition=message('owner_ack_required'))
    return result


def list_for_project(conn, project_id: int, user_id: int | None, limit: int = 100):
    query = ("SELECT r.*,p.key || '-' || i.seq AS item_ref FROM execution_requests r "
             "JOIN items i ON i.id=r.item_id JOIN projects p ON p.id=i.project_id WHERE i.project_id=?")
    params: list = [project_id]
    if user_id is not None:
        query += ' AND r.user_id=?'
        params.append(user_id)
    rows = conn.execute(query+' ORDER BY r.rowid DESC LIMIT ?',(*params,limit)).fetchall()
    return [serialize(conn,row) | {'ref':row['item_ref']} for row in rows]


def poll(conn, project_id: int, user_id: int, *, after_item_id: int = 0, limit: int = 100):
    ids = conn.execute(
        'SELECT i.id FROM items i WHERE i.project_id=? AND i.id>? AND '
        '(i.assignee_id=? OR EXISTS(SELECT 1 FROM execution_requests r WHERE r.item_id=i.id AND r.user_id=?)) '
        'ORDER BY i.id LIMIT ?', (project_id,after_item_id,user_id,user_id,limit),
    ).fetchall()
    result = []
    for row in ids:
        request = observe_item(conn,row['id'])
        if request is not None and request['user_id']==user_id:
            item = items.serialize(conn,items.get_required(conn,row['id']))
            result.append(serialize(conn,request) | {'ref':item['ref']})
    return {'requests':result, 'next_after_item_id':ids[-1]['id'] if len(ids)==limit else None}


def _owner(conn, request, user, nonce: str, fence: int, *, allow_ended=False, now=None):
    if request['user_id'] != user['id']:
        raise ExecutionDenied('Execution belongs to another identity')
    run = conn.execute('SELECT * FROM execution_runs WHERE id=?',(request['run_id'],)).fetchone()
    if (run is None or fence != request['fence'] or not nonce or len(nonce)>256
            or not hmac.compare_digest(_hash(nonce),run['nonce_hash'])
            or (not allow_ended and (run['ended_at'] is not None or run['lease_until'] <= (time.time() if now is None else now)))):
        raise ExecutionConflict('Execution owner or fence is stale')
    return run


def claim(conn, request, user, config, *, digest: str, profile: str, capabilities: list[str],
          owner: str, nonce: str, external_task_id: str | None = None, now=None):
    now = time.time() if now is None else now
    observe_item(conn,request['item_id'],now=now)
    request = get(conn,request['id'])
    item = items.get_required(conn,request['item_id'])
    if request['user_id'] != user['id'] or profile != config['profile']:
        raise ExecutionDenied('Execution identity or profile does not match')
    reason = _policy(conn,item,user,config)
    if reason or item['assignee_id'] != user['id'] or comments.open_questions_for_item(conn,item['id']):
        raise ExecutionConflict(reason or 'Assignment or human input prevents execution')
    if digest != revision(conn,item):
        raise ExecutionConflict('Read the full current task and plan before claiming')
    missing = set(json.loads(config['capabilities'])) - set(capabilities)
    if missing:
        raise ExecutionConflict('Required capabilities were not verified')
    if request['status'] == 'claimed':
        run = _owner(conn,request,user,nonce,request['fence'],now=now)
        if run['owner'] != owner:
            raise ExecutionConflict('Another owner holds the claim')
        return request
    if request['status'] != 'pending':
        raise ExecutionConflict('Execution is not ready to claim')
    if not nonce or len(nonce)>256:
        raise ExecutionDenied('Execution owner proof is required')
    fence = request['fence']+1
    cur = conn.execute('INSERT INTO execution_runs(request_id,fence,owner,nonce_hash,phase,external_task_id,claimed_at,lease_until) VALUES(?,?,?,?,?,?,?,?)',
                       (request['id'],fence,owner,_hash(nonce),'claimed',external_task_id,now,now+LEASE_SECONDS))
    updated = _update(conn,request,status='claimed',run_id=cur.lastrowid,fence=fence,revision=digest,
                      intent_event_id=intent_event(conn,item))
    _log(conn,updated,'claimed',actor_id=user['id'],fence=fence)
    return updated


def start(conn, request, user, *, nonce: str, fence: int, digest: str, external_run_id=None, now=None):
    now = time.time() if now is None else now
    observe_item(conn,request['item_id'],now=now)
    request = get(conn,request['id'])
    run = _owner(conn,request,user,nonce,fence,now=now)
    item = items.get_required(conn,request['item_id'])
    config = binding(conn,user['id'])
    if (request['status'] not in ('claimed','running') or _policy(conn,item,user,config)
            or item['assignee_id'] != user['id'] or comments.open_questions_for_item(conn,item['id'])
            or digest != request['revision'] or digest != revision(conn,item)):
        raise ExecutionConflict('Execution was changed, blocked or revoked')
    if request['status'] == 'running':
        if run['external_run_id'] != external_run_id:
            raise ExecutionConflict('External run identity changed')
        return request
    # Respect custom project states. Only the actual executor start changes ticket state.
    target = conn.execute("SELECT id FROM states WHERE project_id=? AND grp='started' AND blocks_work=0 ORDER BY sort_order,id LIMIT 1",
                          (item['project_id'],)).fetchone()
    if target is None:
        raise ExecutionConflict('Project has no executable started state')
    conn.execute("UPDATE execution_runs SET phase='running',started_at=?,lease_until=?,external_run_id=? WHERE id=?",
                 (now,now+LEASE_SECONDS,external_run_id,request['run_id']))
    updated = _update(conn,request,status='running')
    items.update(conn,item['id'],{'state_id':target['id']})
    _log(conn,updated,'started',actor_id=user['id'],fence=fence)
    return updated


def heartbeat(conn, request, user, *, nonce: str, fence: int, now=None):
    now = time.time() if now is None else now
    observe_item(conn,request['item_id'],now=now)
    request = get(conn,request['id'])
    _owner(conn,request,user,nonce,fence,now=now)
    if request['status'] not in ('claimed','running'):
        raise ExecutionConflict('Execution must stop; no new work is authorized')
    conn.execute('UPDATE execution_runs SET lease_until=? WHERE id=?',(now+LEASE_SECONDS,request['run_id']))
    return request


def block(conn, request, user, *, kind: str, reason: str, missing: list[str], responsible: str,
          resume_condition: str, nonce: str, fence: int, question_id=None, now=None):
    now = time.time() if now is None else now
    if request['user_id'] != user['id']:
        raise ExecutionDenied('Execution belongs to another identity')
    if request['status']=='blocked' and request['block_kind']=='recovery':
        raise ExecutionConflict('Explicit recovery is required for a lost execution owner')
    if request['status'] in ('claimed','running','stopping'):
        run = _owner(conn,request,user,nonce,fence,allow_ended=True)
    else:
        run = conn.execute('SELECT * FROM execution_runs WHERE id=?',(request['run_id'],)).fetchone() if request['run_id'] else None
        if request['status'] not in ('pending','blocked'):
            raise ExecutionConflict('Execution is no longer active')
    if kind == 'transport':
        if run is not None and run['started_at'] is not None:
            raise ExecutionConflict('Transport retries after execution require explicit recovery')
        if request['status']=='blocked' and request['block_kind']=='transport':
            return _blocked(conn,request,kind=kind,reason=reason,missing=missing,responsible=responsible,
                            resume_condition=resume_condition,retry_at=request['retry_at'],now=now)
        attempts = request['transport_attempts']+1
        request = _update(conn,request,transport_attempts=attempts)
        retry_at = now + min(300, 5 * 2**(attempts-1)) if attempts < MAX_TRANSPORT_ATTEMPTS else None
    else:
        retry_at = None
    if kind == 'human':
        question = comments.get(conn,question_id) if question_id else None
        if question is None or question['item_id']!=request['item_id'] or question['kind']!='question':
            raise ExecutionConflict('Use the existing human question workflow first')
    return _blocked(conn,request,kind=kind,reason=reason,missing=missing,responsible=responsible,
                    resume_condition=resume_condition,question_id=question_id,retry_at=retry_at,now=now)


def stop(conn, request, user, *, nonce: str, fence: int, now=None):
    _owner(conn,request,user,nonce,fence,allow_ended=True)
    if request['status'] in ('completed','cancelled') or (request['status']=='blocked' and request['block_kind']!='recovery'):
        return request
    now = time.time() if now is None else now
    _end_run(conn,request,'stopped',now)
    if request['status']=='stopping' and request['block_kind'] in ('human','policy'):
        waiting = comments.open_questions_for_item(conn,request['item_id'])
        updated = _blocked(conn,request,kind=request['block_kind'],reason=request['reason'],
                           question_id=waiting[0]['id'] if waiting else None,
                           resume_condition=message('question_or_policy'),now=now)
        return observe_item(conn,updated['item_id'],now=now)
    updated = _update(conn,request,status='cancelled',reason=message('owner_stopped'))
    _log(conn,updated,'stopped',actor_id=user['id'])
    return updated


def resume(conn, request, *, actor_id: int, reason: str, worker_stopped: bool, effects_reviewed: bool):
    observe_item(conn,request['item_id'])
    request = get(conn,request['id'])
    if request['status'] not in ('blocked','stopping'):
        raise ExecutionConflict('Execution is not blocked')
    if request['status']=='stopping' or request['block_kind']=='recovery':
        if not worker_stopped or not effects_reviewed:
            raise ExecutionConflict('Confirm the prior worker stopped and previous effects were reviewed')
    item = items.get_required(conn,request['item_id'])
    user = users.get(conn,request['user_id'])
    config = binding(conn,request['user_id'])
    gate = _policy(conn,item,user,config)
    if gate or item['assignee_id']!=request['user_id'] or comments.open_questions_for_item(conn,item['id']):
        raise ExecutionConflict(gate or 'Assignment or human input prevents resuming')
    _end_run(conn,request,'stopped',time.time())
    updated = _pending(conn,request,item,config)
    _log(conn,updated,'resumed',actor_id=actor_id,reason=reason)
    return updated


def complete(conn, request, user, *, nonce: str, fence: int, evidence: list[dict], now=None):
    now = time.time() if now is None else now
    observe_item(conn,request['item_id'],now=now)
    request = get(conn,request['id'])
    if request['status']=='completed':
        run = _owner(conn,request,user,nonce,fence,allow_ended=True)
        if json.loads(run['evidence']) != evidence:
            raise ExecutionConflict('Completion evidence cannot be changed after completion')
        return request
    _owner(conn,request,user,nonce,fence,now=now)
    if request['status']!='running' or not evidence:
        raise ExecutionConflict('Only a live running execution can declare completion with evidence')
    conn.execute("UPDATE execution_runs SET phase='completed',ended_at=?,evidence=? WHERE id=?",
                 (now,_json(evidence),request['run_id']))
    updated = _update(conn,request,status='completed',intent_event_id=intent_event(conn,items.get_required(conn,request['item_id'])))
    _log(conn,updated,'completed',actor_id=user['id'],fence=fence)
    return updated
