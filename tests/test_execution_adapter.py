"""Exercise the executor HTTP boundary and native hook contract without launching agents."""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

from betonning.execution_adapter import AdapterError, ExecutionAPI, ExecutionToolGuard, stage_native
from test_execution import configured as configured, worker as worker, context


@pytest.fixture
def adapter(client,configured):
    work=configured
    def dispatch(request):
        result=client.request(request.method,str(request.url),headers=dict(request.headers),content=request.content)
        return httpx.Response(result.status_code,headers=result.headers,content=result.content,request=request)
    with httpx.Client(transport=httpx.MockTransport(dispatch)) as transport:
        api=ExecutionAPI('http://testserver',work['agent_headers']['Authorization'].split(' ',1)[1],
                         work['headers']['X-Execution-Key'],client=transport)
        yield api


def guard(adapter,context_value,**extra):
    return ExecutionToolGuard(adapter,context_value,profile='worker-profile',
                              capability_probe=lambda profile:{'terminal','mcp:betonning'},
                              owner='native-worker',external_task_id='native-card-1',external_run_id='native-run-1',task_context_delivered=True,**extra)


def test_native_staging_uses_full_stdin_context_and_never_passes_credentials(client,configured):
    work=configured
    value=context(client,work)
    value['item']['title']='--yolo $(untrusted input)'
    captured=[]
    def run(argv,**kwargs):
        captured.append((argv,kwargs))
        return SimpleNamespace(returncode=0,stdout=json.dumps({'id':'native-card-1','status':'blocked','assignee':'worker-profile'}))
    task=stage_native(value,board='synthetic-board',runner=run)
    assert task['status']=='blocked'
    argv,options=captured[0]
    assert argv[-2:]==['--','--yolo $(untrusted input)']
    assert argv[argv.index('--idempotency-key')+1]=='hegemone:'+work['id']
    assert '--toolsets' not in argv
    assert '--provider' not in argv
    assert '--yolo' not in argv
    body=json.loads(options['input'])
    assert body['plan_md']==value['plan_md']
    assert len(body['plan_md'])>8000
    assert work['headers']['X-Execution-Key'] not in options['input']
    assert work['agent_headers']['Authorization'].split(' ',1)[1] not in options['input']
    assert 'shell' not in options


def test_native_staging_refuses_an_already_running_or_misrouted_task(client,configured):
    value=context(client,configured)
    def run(argv,**kwargs):
        return SimpleNamespace(returncode=0,stdout=json.dumps({'id':'native-card-1','status':'running','assignee':'worker-profile'}))
    with pytest.raises(AdapterError,match='not safely parked'):
        stage_native(value,board='synthetic-board',runner=run)


def test_tool_guard_claims_once_for_parallel_first_tools_and_revalidates_every_tool(client,auth,conn,configured,adapter):
    work=configured
    gate=guard(adapter,context(client,work))
    registered={}
    plugin=SimpleNamespace(register_hook=lambda name,callback:registered.update({name:callback}))
    gate.register(plugin)
    assert 'pre_tool_call' in registered
    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions=list(pool.map(lambda _:gate.before_tool('terminal',{'command':'synthetic'}),[1,2]))
    assert decisions==[None,None]
    assert conn.execute('SELECT COUNT(*) FROM execution_runs').fetchone()[0]==1
    assert context(client,work)['item']['state']=='in-progress'
    assert client.post(f"/api/v1/items/{work['ref']}/lock",headers=auth).status_code==200
    assert gate.before_tool('terminal',{'command':'must not run'})['action']=='block'
    assert gate.before_tool('terminal',{'command':'still must not run'})['action']=='block'
    assert gate.before_tool('kanban_block',{}) is None
    result=gate.acknowledge_stopped()
    assert result['status']=='blocked'
    assert context(client,work)['comments']==[]


def test_missing_capability_records_one_durable_block_instead_of_repeated_comments(client,conn,configured,adapter):
    work=configured
    gate=ExecutionToolGuard(adapter,context(client,work),profile='worker-profile',
                            capability_probe=lambda profile:{'mcp:betonning'},owner='native-worker',
                            external_task_id='native-card-1',external_run_id='native-run-1',task_context_delivered=True)
    for _ in range(5):
        assert gate.before_tool('terminal',{})['action']=='block'
    value=context(client,work)
    assert value['execution']['block_kind']=='capability'
    assert value['execution']['missing_requirements']==['terminal']
    assert value['comments']==[]
    assert conn.execute('SELECT COUNT(*) FROM execution_runs').fetchone()[0]==0
    assert conn.execute("SELECT COUNT(*) FROM events WHERE type='execution.blocked'").fetchone()[0]==1


def test_changed_native_snapshot_is_not_silently_reused(client,auth,configured,adapter):
    work=configured
    old=context(client,work)
    client.patch(f"/api/v1/items/{work['ref']}",headers=auth,json={'title':'New instructions'})
    gate=guard(adapter,old)
    assert gate.before_tool('terminal',{})['action']=='block'
    assert context(client,work)['execution']['status']=='pending'


def test_tool_gate_fails_closed_without_echoing_provider_or_credential_data(client,configured):
    api=SimpleNamespace(prepare=lambda *args:(_ for _ in ()).throw(RuntimeError('synthetic-secret-canary')))
    gate=guard(api,context(client,configured))
    value=gate.before_tool('terminal',{})
    assert value['action']=='block'
    assert 'synthetic-secret-canary' not in json.dumps(value)


def test_host_verified_artifact_is_recorded_but_model_text_alone_does_not_complete(client,conn,configured,adapter,tmp_path):
    work=configured
    gate=guard(adapter,context(client,work))
    assert gate.before_tool('terminal',{}) is None
    assert context(client,work)['execution']['status']=='running'
    artifact=tmp_path/'result.txt'
    artifact.write_text('Synthetic verified artifact')
    digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
    result=gate.complete([{'kind':'artifact','reference':'result.txt','sha256':digest}])
    assert result['status']=='completed'
    assert result['run']['evidence'][0]['sha256']==hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert conn.execute('SELECT COUNT(*) FROM execution_runs').fetchone()[0]==1


def test_native_guard_requires_host_confirmation_that_full_context_was_delivered(client,conn,configured,adapter):
    gate=ExecutionToolGuard(adapter,context(client,configured),profile='worker-profile',
                            capability_probe=lambda profile:{'terminal','mcp:betonning'},owner='native-worker',
                            external_task_id='native-card-1',external_run_id='native-run-1')
    assert gate.before_tool('terminal',{})['action']=='block'
    assert conn.execute('SELECT COUNT(*) FROM execution_runs').fetchone()[0]==0
