"""Executor authorization, durable requests, fencing, blocking and recovery."""
from __future__ import annotations

import json

import pytest

from betonning import db
from betonning.repo import execution, items, users


@pytest.fixture
def worker(conn):
    user, key = users.create(conn,handle='worker',display_name='Worker',kind='agent')
    return user, {'Authorization':f'Bearer {key}'}


@pytest.fixture
def configured(client,auth,conn,project,worker):
    user, headers = worker
    response = client.post('/api/v1/users/worker/execution',headers=auth,json={
        'enabled':True,'profile':'worker-profile','capabilities':['terminal','mcp:betonning']})
    assert response.status_code==200,response.text
    private = {**headers,'X-Execution-Key':response.json()['execution_key'],'X-Execution-Owner':'synthetic-owner-proof'}
    created = client.post('/api/v1/projects/SOS/items',headers=auth,json={
        'title':'Synthetic execution task','state':'todo','assignee':'worker',
        'description_md':'A fully described synthetic task.','plan_md':'Read, execute, verify.\n'+'detail\n'*2000})
    assert created.status_code==201,created.text
    request = client.get('/api/v1/projects/SOS/executions',headers=auth).json()[0]
    return {'user':user,'headers':private,'agent_headers':headers,'id':request['id'],'ref':created.json()['ref']}


def path(work,action=''):
    return f"/api/v1/items/{work['ref']}/executions/{work['id']}" + (f'/{action}' if action else '')


def context(client,work):
    response=client.get(path(work),headers=work['agent_headers'])
    assert response.status_code==200,response.text
    return response.json()


def claim(client,work,headers=None,**overrides):
    value=context(client,work)
    body={'context_digest':value['context_digest'],'profile':'worker-profile',
          'capabilities_checked':['terminal','mcp:betonning'],'task_read':True,
          'owner':'runner-a','external_task_id':'native-task-1',**overrides}
    return client.post(path(work,'claim'),headers=headers or work['headers'],json=body)


def start(client,work,claimed=None,**overrides):
    claimed=claimed or claim(client,work).json()
    return client.post(path(work,'start'),headers=work['headers'],json={
        'fence':claimed['fence'],'context_digest':context(client,work)['context_digest'],
        'external_run_id':'native-run-1',**overrides})


def test_assignment_is_durable_but_notification_never_starts_execution(client,auth,conn,configured):
    work=configured
    value=context(client,work)
    assert len(value['plan_md'])>8000
    assert value['item']['description_md']=='A fully described synthetic task.'
    assert value['execution']['status']=='pending'
    assert value['item']['state']=='todo'
    assert value['comments']==[]
    assert conn.execute('SELECT COUNT(*) FROM execution_runs').fetchone()[0]==0
    assert 'token_hash' not in json.dumps(value)
    conn2=db.connect(client.app.state.db_path)
    try:
        assert execution.latest(conn2,items.get_by_ref(conn2,work['ref'])['id'])['id']==work['id']
    finally:
        conn2.close()


def test_only_a_configured_executor_with_separate_proof_can_claim(client,auth,configured):
    work=configured
    assert claim(client,work,headers=work['agent_headers']).status_code==403
    assert claim(client,work,headers=auth).status_code==403
    assert claim(client,work,profile='wrong-profile').status_code==403
    assert claim(client,work,capabilities_checked=['mcp:betonning']).status_code==409
    assert claim(client,work,context_digest='0'*64).status_code==409
    assert claim(client,work).status_code==200


def test_claim_start_and_completion_are_fenced_and_idempotent(client,auth,conn,configured):
    work=configured
    first=claim(client,work)
    assert first.status_code==200,first.text
    assert claim(client,work).json()['fence']==first.json()['fence']
    other={**work['headers'],'X-Execution-Owner':'another-synthetic-owner'}
    assert claim(client,work,headers=other,owner='runner-b').status_code==409
    assert context(client,work)['item']['state']=='todo'
    started=start(client,work,first.json())
    assert started.status_code==200,started.text
    assert context(client,work)['item']['state']=='in-progress'
    assert start(client,work,first.json()).status_code==200
    assert start(client,work,first.json(),external_run_id='different-run').status_code==409
    assert conn.execute('SELECT COUNT(*) FROM execution_runs').fetchone()[0]==1
    evidence=[{'kind':'artifact','reference':'synthetic-result.txt','sha256':'a'*64}]
    body={'fence':first.json()['fence'],'evidence':evidence}
    result=client.post(path(work,'complete'),headers=work['headers'],json=body)
    assert result.status_code==200,result.text
    assert client.post(path(work,'complete'),headers=work['headers'],json=body).status_code==200
    assert client.post(path(work,'complete'),headers=work['headers'],json={**body,'evidence':[]}).status_code==422
    client.patch(f"/api/v1/items/{work['ref']}",headers=work['agent_headers'],json={'state':'done'})
    client.post(f"/api/v1/items/{work['ref']}/comments",headers=work['agent_headers'],json={'body_md':'Completed with synthetic verification.'})
    assert conn.execute('SELECT COUNT(*) FROM execution_requests').fetchone()[0]==1


def blocked(client,work,kind='capability',**extra):
    return client.post(path(work,'block'),headers=work['headers'],json={
        'kind':kind,'reason':'Terminal access is unavailable.','missing_requirements':['terminal'],
        'responsible':'administrator','resume_condition':'Restore access for the existing profile.',**extra})


def poll(client,work):
    return client.post('/api/v1/projects/SOS/executions/poll',headers=work['headers'])


def test_parallel_claims_have_exactly_one_owner(client,auth,conn,configured):
    from concurrent.futures import ThreadPoolExecutor

    work=configured
    def attempt(index):
        return claim(client,work,headers={**work['headers'],'X-Execution-Owner':f'owner-proof-{index}'},owner=f'runner-{index}').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,[1,2]))
    assert sorted(results)==[200,409]
    assert conn.execute('SELECT COUNT(*) FROM execution_runs').fetchone()[0]==1


def test_capability_block_is_deduplicated_and_configuration_change_releases_it(client,auth,conn,configured):
    work=configured
    for _ in range(6):
        response=blocked(client,work)
        assert response.status_code==200,response.text
        assert poll(client,work).json()['requests'][0]['status']=='blocked'
    assert context(client,work)['comments']==[]
    assert conn.execute("SELECT COUNT(*) FROM events WHERE type='execution.blocked'").fetchone()[0]==1
    assert conn.execute('SELECT COUNT(*) FROM execution_runs').fetchone()[0]==0
    assert claim(client,work).status_code==409
    response=blocked(client,work,reason='Terminal access and a workspace are unavailable.')
    assert response.status_code==200
    assert conn.execute("SELECT COUNT(*) FROM events WHERE type='execution.blocked'").fetchone()[0]==2
    changed=client.post('/api/v1/users/worker/execution',headers=auth,json={
        'enabled':True,'profile':'worker-profile','capabilities':['terminal','mcp:betonning']})
    assert changed.status_code==200
    assert poll(client,work).status_code==403
    work['headers']['X-Execution-Key']=changed.json()['execution_key']
    assert poll(client,work).json()['requests'][0]['status']=='pending'
    assert claim(client,work).status_code==200


def test_transport_retries_are_bounded_and_do_not_create_comments(client,auth,conn,configured):
    work=configured
    for attempt in range(1,execution.MAX_TRANSPORT_ATTEMPTS+1):
        response=blocked(client,work,kind='transport',reason='Synthetic transport failure')
        assert response.status_code==200,response.text
        assert response.json()['transport_attempts']==attempt
        assert blocked(client,work,kind='transport').json()['transport_attempts']==attempt
        if attempt<execution.MAX_TRANSPORT_ATTEMPTS:
            conn.execute('UPDATE execution_requests SET retry_at=0 WHERE id=?',(work['id'],))
            assert poll(client,work).json()['requests'][0]['status']=='pending'
        else:
            assert response.json()['retry_at'] is None
            assert poll(client,work).json()['requests'][0]['status']=='blocked'
    assert context(client,work)['comments']==[]


def test_lost_unstarted_claim_expires_without_replaying_a_started_run(client,auth,conn,configured):
    work=configured
    old=claim(client,work).json()
    conn.execute('UPDATE execution_runs SET lease_until=0')
    assert poll(client,work).json()['requests'][0]['status']=='pending'
    assert start(client,work,old).status_code==409
    fresh=claim(client,work).json()
    assert fresh['fence']==old['fence']+1
    assert start(client,work,fresh).status_code==200


def test_lost_running_owner_requires_explicit_recovery(client,auth,conn,configured):
    work=configured
    old=claim(client,work).json()
    assert start(client,work,old).status_code==200
    conn.execute('UPDATE execution_runs SET lease_until=0')
    assert poll(client,work).json()['requests'][0]['block_kind']=='recovery'
    assert blocked(client,work,kind='transport').status_code==409
    assert claim(client,work).status_code==409
    assert client.delete(f"/api/v1/items/{work['ref']}?hard=true",headers=auth).status_code==409
    assert client.post(path(work,'resume'),headers=work['headers'],json={'reason':'Attempted agent recovery.','previous_worker_stopped':True,'previous_effects_reviewed':True}).status_code==403
    assert client.post(path(work,'resume'),headers=auth,json={'reason':'Investigated the stopped synthetic worker.'}).status_code==409
    result=client.post(path(work,'resume'),headers=auth,json={
        'reason':'Verified worker exit and checked the synthetic artifact.',
        'previous_worker_stopped':True,'previous_effects_reviewed':True})
    assert result.status_code==200,result.text
    newer=claim(client,work).json()
    assert newer['fence']>old['fence']
    assert start(client,work,old).status_code==409
    assert start(client,work,newer).status_code==200


def test_transport_retry_cannot_replay_partially_executed_work(client,auth,configured):
    work=configured
    claimed=claim(client,work).json()
    assert start(client,work,claimed).status_code==200
    assert blocked(client,work,kind='transport',fence=claimed['fence']).status_code==409
    assert blocked(client,work,kind='task',fence=claimed['fence'],reason='Synthetic task failure').status_code==200
    assert blocked(client,work,kind='transport').status_code==409


def test_human_question_keeps_existing_assignment_and_resumes_after_answer(client,auth,conn,configured):
    work=configured
    claimed=claim(client,work).json()
    assert start(client,work,claimed).status_code==200
    question=client.post(f"/api/v1/items/{work['ref']}/comments",headers=work['agent_headers'],json={
        'kind':'question','body_md':'Which synthetic route, @person?'})
    assert question.status_code==201,question.text
    qid=question.json()['id']
    value=context(client,work)
    assert value['item']['assignee']=='person'
    assert value['execution']['status']=='stopping'
    assert blocked(client,work,kind='human',fence=claimed['fence'],question_id=qid,reason='A human decision is needed.').status_code==200
    assert claim(client,work).status_code==409
    answer=client.post(f'/api/v1/comments/{qid}/answer',headers=auth,json={'text':'Use the left route.'})
    assert answer.status_code==200,answer.text
    value=context(client,work)
    assert value['item']['assignee']=='worker'
    assert value['execution']['id']==work['id']
    assert value['execution']['status']=='pending'
    assert len(value['attempts'])==1
    assert claim(client,work).status_code==200


@pytest.mark.parametrize('change', ['revision','lock','archive','reassign','access','credentials'])
def test_revocation_stops_a_running_owner_without_allowing_a_second_one(client,auth,conn,configured,change):
    work=configured
    claimed=claim(client,work).json()
    assert start(client,work,claimed).status_code==200
    if change=='revision':
        assert client.patch(f"/api/v1/items/{work['ref']}",headers=auth,json={'title':'Changed synthetic task'}).status_code==200
    elif change=='lock':
        assert client.post(f"/api/v1/items/{work['ref']}/lock",headers=auth).status_code==200
    elif change=='archive':
        assert client.delete('/api/v1/projects/SOS',headers=auth).status_code==204
    elif change=='reassign':
        assert client.patch(f"/api/v1/items/{work['ref']}",headers=auth,json={'assignee':'person'}).status_code==200
    elif change=='access':
        assert client.put('/api/v1/projects/SOS/access/agent/worker',headers=auth,json={'level':'respond'}).status_code==200
    else:
        assert client.patch('/api/v1/users/worker',headers=auth,json={'api_key_scopes':['read']}).status_code==200
    response=client.post(path(work,'heartbeat'),headers=work['headers'],json={'fence':claimed['fence']})
    assert response.status_code in (403,409),response.text
    assert conn.execute('SELECT COUNT(*) FROM execution_runs').fetchone()[0]==1
    if change!='credentials':
        assert context(client,work)['execution']['status']=='stopping'
        assert claim(client,work).status_code in (403,409)


def test_own_comments_and_status_updates_do_not_create_another_request(client,auth,conn,configured):
    work=configured
    claimed=claim(client,work).json()
    assert start(client,work,claimed).status_code==200
    for index in range(3):
        assert client.post(f"/api/v1/items/{work['ref']}/comments",headers=work['agent_headers'],json={'body_md':f'Synthetic progress {index}'}).status_code==201
        assert client.patch(f"/api/v1/items/{work['ref']}",headers=work['agent_headers'],json={'state':'in-progress'}).status_code==200
    assert conn.execute('SELECT COUNT(*) FROM execution_requests').fetchone()[0]==1
    assert conn.execute('SELECT COUNT(*) FROM execution_runs').fetchone()[0]==1


def test_execution_binding_is_human_only_and_never_discloses_stored_proofs(client,auth,configured):
    work=configured
    denied=client.post('/api/v1/users/worker/execution',headers=work['agent_headers'],json={
        'enabled':True,'profile':'worker-profile','capabilities':[]})
    assert denied.status_code==403
    value=client.get('/api/v1/users/worker/execution',headers=auth)
    assert value.status_code==200
    assert value.headers['cache-control']=='no-store'
    assert 'execution_key' not in value.json()
    assert 'token_hash' not in json.dumps(value.json())


def test_mentions_are_not_execution_assignments_and_default_agents_are_unchanged(client,auth,conn,project,worker):
    item=client.post('/api/v1/projects/SOS/items',headers=auth,json={'title':'Advice only','state':'todo','description_md':'Advice from @worker, please.'})
    assert item.status_code==201
    assert conn.execute('SELECT COUNT(*) FROM execution_requests').fetchone()[0]==0
    client.patch(f"/api/v1/items/{item.json()['ref']}",headers=auth,json={'assignee':'worker'})
    assert conn.execute('SELECT COUNT(*) FROM execution_requests').fetchone()[0]==0


def test_push_and_pull_notifications_do_not_grant_managed_execution(client,auth,conn,configured):
    from betonning import webhooks
    from betonning.repo import events

    work=configured
    item=items.get_by_ref(conn,work['ref'])
    recipient=users.get_by_handle(conn,'worker')
    human=users.get_by_handle(conn,'person')
    with db.transaction(conn):
        event=events.record(conn,type='item.updated',item_id=item['id'],actor_id=human['id'],
                            payload={'assignee':{'from':None,'to':'worker'}})
    push=webhooks.build_delivery_payload(conn,event,recipient)
    pull=webhooks.build_agent_instructions(conn,event,recipient)
    assert push['expected_action']==pull['expected_action']=='none'
    assert push['execution']['id']==work['id']
    assert push['execution']['status']=='pending'
    assert push['instructions']==pull['instructions']
    assert 'execution_key' not in json.dumps(push)
    assert context(client,work)['item']['state']=='todo'
    assert context(client,work)['comments']==[]


def test_managed_mentions_for_advice_still_respond_without_creating_work(client,auth,conn,configured):
    from betonning import webhooks
    work=configured
    created=client.post('/api/v1/projects/SOS/items',headers=auth,json={'title':'Advice only','state':'todo','assignee':'person'}).json()
    item=items.get_by_ref(conn,created['ref'])
    recipient=users.get_by_handle(conn,'worker')
    comment=client.post(f"/api/v1/items/{created['ref']}/comments",headers=auth,json={'body_md':'Advice, @worker?'}).json()
    event=conn.execute("SELECT * FROM events WHERE item_id=? AND type='comment.created' ORDER BY id DESC LIMIT 1",(item['id'],)).fetchone()
    assert comment['id']
    assert webhooks.build_delivery_payload(conn,event,recipient)['expected_action']=='respond'
    assert execution.latest(conn,item['id']) is None
    assert context(client,work)['execution']['status']=='pending'


def test_queued_reassignment_creates_a_fresh_intent(client,auth,conn,configured):
    work=configured
    assert client.patch(f"/api/v1/items/{work['ref']}",headers=auth,json={'assignee':'person'}).status_code==200
    assert context(client,work)['execution']['status']=='cancelled'
    assert claim(client,work).status_code==409
    assert client.patch(f"/api/v1/items/{work['ref']}",headers=auth,json={'assignee':'worker'}).status_code==200
    new=execution.latest(conn,items.get_by_ref(conn,work['ref'])['id'])
    assert new['id']!=work['id']
    assert new['status']=='pending'


def test_configured_but_unauthorized_executor_is_visibly_blocked(client,auth,conn,configured):
    work=configured
    client.patch('/api/v1/users/worker',headers=auth,json={'api_key_scopes':['read']})
    other=client.post('/api/v1/projects/SOS/items',headers=auth,json={'title':'Needs an authorized executor','state':'todo','assignee':'worker'}).json()
    request=execution.latest(conn,items.get_by_ref(conn,other['ref'])['id'])
    assert request['status']=='blocked'
    assert request['block_kind']=='policy'
    assert request['responsible']=='administrator'
    assert context(client,work)['comments']==[]


def test_project_scoped_executor_does_not_need_or_gain_admin_scope(client,auth,conn,configured):
    work=configured
    changed=client.patch('/api/v1/users/worker',headers=auth,json={'api_key_scopes':['read','write'],'api_key_projects':['SOS']})
    assert changed.status_code==200
    assert poll(client,work).status_code==200
    assert claim(client,work).status_code==200
    assert client.put('/api/v1/projects/SOS/triage',headers=work['headers'],json={'enabled':True}).status_code==403
    client.post('/api/v1/projects',headers=auth,json={'key':'OTHER','name':'Other project'})
    assert client.post('/api/v1/projects/OTHER/executions/poll',headers=work['headers']).status_code==403


def test_human_can_see_and_recover_a_lost_owner_without_an_executor_poll(client,auth,conn,configured):
    work=configured
    claimed=claim(client,work).json()
    assert start(client,work,claimed).status_code==200
    conn.execute('UPDATE execution_runs SET lease_until=0')
    before=conn.execute('SELECT status FROM execution_requests WHERE id=?',(work['id'],)).fetchone()[0]
    assert before=='running'
    visible=client.get(f"/api/v1/items/{work['ref']}",headers=auth).json()['execution']
    assert visible['status']=='blocked'
    assert visible['block_kind']=='recovery'
    assert conn.execute('SELECT status FROM execution_requests WHERE id=?',(work['id'],)).fetchone()[0]=='running'
    response=client.post(path(work,'resume'),headers=auth,json={
        'reason':'Verified stopped synthetic worker and inspected prior effects.',
        'previous_worker_stopped':True,'previous_effects_reviewed':True})
    assert response.status_code==200,response.text
    assert response.json()['status']=='pending'
