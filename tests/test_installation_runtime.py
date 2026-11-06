"""Effectieve providerconfiguratie; uitsluitend fake netwerk en fixturedata."""
import asyncio
import json
import threading

import httpx
import pytest

from betonning import config, installation_runtime as runtime, llm, webhooks, server
from betonning.repo import users

PATH = '/api/v1/settings/installation'
KEY = 'synthetic-runtime-provider-key'


@pytest.fixture(autouse=True)
def clean_config(monkeypatch):
    monkeypatch.setattr(server, 'load_dotenv', lambda: None)
    for prefix in ['HEGEMONE_', 'BETONNING_']:
        for suffix in ['LLM_BASE_URL','LLM_API_KEY','LLM_MODEL','LLM_ENABLED','LLM_TIMEOUT','EMBED_BASE_URL','EMBED_API_KEY','EMBED_MODEL','EMBED_ENABLED','EMBED_TIMEOUT','AI_LANGUAGE','PUBLIC_URL','TRIAGE_ENABLED','WIKI_COMPILE_ENABLED']:
            monkeypatch.delenv(prefix + suffix, raising=False)
    monkeypatch.setenv('HEGEMONE_SETTINGS_SECRET', 'synthetic-runtime-encryption-key-0000000000000')


def save(client, auth, settings, revision=0):
    return client.patch(PATH, headers=auth, json={'schema_version':1, 'expected_revision':revision, 'settings':settings})


def provider():
    return {'enabled': True, 'base_url':'https://provider.example/v1','model':'saved-model','api_key':KEY}


def test_saved_provider_reaches_real_request_path_and_disable_blocks_new_calls(client, auth, project, monkeypatch):
    captured = []
    def post(url, **kwargs):
        captured.append((url, kwargs))
        return httpx.Response(200, json={'choices':[{'message':{'content':json.dumps({'kind':'proposal','description':'Generated'})}}]}, request=httpx.Request('POST',url))
    monkeypatch.setattr(llm.httpx, 'post', post)
    item = client.post(f'/api/v1/projects/{project}/items', headers=auth, json={'title':'Eigen titel'}).json()
    assert client.post(f"/api/v1/items/{item['ref']}/enrich",headers=auth).status_code == 503
    saved = save(client,auth,{'llm':provider(),'ai_language':'nl'})
    assert saved.status_code == 200
    assert saved.json()['runtime']['providers']['llm']['ready']
    response = client.post(f"/api/v1/items/{item['ref']}/enrich", headers=auth)
    assert response.status_code == 200 and response.json()['proposal'] == 'Generated'
    assert captured[0][0] == 'https://provider.example/v1/chat/completions'
    assert captured[0][1]['headers']['Authorization'] == f'Bearer {KEY}'
    assert captured[0][1]['json']['model'] == 'saved-model'
    assert 'natural-language text in Dutch' in captured[0][1]['json']['messages'][0]['content']
    assert save(client,auth,{'llm':{'enabled':False}},1).status_code == 200
    assert client.post(f"/api/v1/items/{item['ref']}/enrich",headers=auth).status_code == 503
    assert len(captured) == 1


def test_environment_overrides_saved_values_and_empty_key_disables_without_fallback(client, auth, monkeypatch):
    monkeypatch.setenv('BETONNING_LLM_MODEL','old-model')
    monkeypatch.setenv('HEGEMONE_LLM_MODEL','deployment-model')
    response = save(client,auth,{'llm':provider()})
    assert response.status_code == 200
    assert client.app.state.llm_client._model == 'deployment-model'
    assert 'model' in response.json()['runtime']['providers']['llm']['overrides']
    monkeypatch.setenv('BETONNING_LLM_API_KEY', 'synthetic-legacy-key')
    monkeypatch.setenv('HEGEMONE_LLM_API_KEY','')
    response = save(client,auth,{'language':'nl'},1)
    assert response.status_code == 200
    assert not response.json()['runtime']['providers']['llm']['ready']
    assert client.app.state.llm_client is None
    assert config.raw_env('HEGEMONE_LLM_API_KEY') == ''


def test_runtime_context_is_local_and_restores_environment_defaults(client, auth):
    assert save(client,auth,{'public_url':'https://public.example','ai_language':'nl'}).status_code == 200
    snapshot = client.app.state.installation_runtime
    with config.runtime_context(snapshot.values):
        assert config.ai_language() == 'nl'
        assert webhooks._public_url() == 'https://public.example'
    assert config.ai_language() == 'en'
    assert webhooks._public_url() == 'http://localhost:8000'


def test_injected_clients_and_flags_remain_authoritative(client, auth):
    class Fake:
        pass
    fake = Fake()
    client.app.state.runtime_overrides.update(llm_client=fake, embed_client=None, enable_triage=False)
    response = save(client,auth,{'llm':provider(),'triage_enabled':True})
    assert response.status_code == 200
    assert client.app.state.llm_client is fake
    assert not client.app.state.enable_triage
    assert response.json()['runtime']['providers']['llm']['source'] == 'injected'


def test_reconfiguration_interrupts_new_worker_calls_without_error_quarantine(client, auth):
    assert save(client,auth,{'llm':provider()}).status_code == 200
    old = client.app.state.installation_runtime
    guarded = runtime.WorkerProvider(client.app,old,'llm')
    assert save(client,auth,{'llm':{'enabled':False}},1).status_code == 200
    with pytest.raises(runtime.RuntimeReconfigured):
        guarded.complete([{'role':'user','content':'Never sent'}])


def test_worker_switch_waits_for_previous_worker_and_keeps_budget(client, auth, monkeypatch):
    from betonning import triage_worker
    started, release, stopped = threading.Event(), threading.Event(), threading.Event()
    counts = {'active':0,'max':0,'runs':0}
    budgets = []
    async def fake_loop(db_path, stop, llm_client, embed_client, **kwargs):
        counts['active'] += 1
        counts['max'] = max(counts['max'],counts['active'])
        counts['runs'] += 1
        budgets.append(kwargs['budget'])
        started.set()
        await stop.wait()
        if counts['runs'] == 1:
            await asyncio.to_thread(release.wait, 3)
        counts['active'] -= 1
        if counts['runs'] >= 2:
            stopped.set()
    monkeypatch.setattr(triage_worker,'triage_loop',fake_loop)
    assert save(client,auth,{'llm':provider(),'triage_enabled':True}).status_code == 200
    assert started.wait(2)
    started.clear()
    try:
        assert save(client,auth,{'llm':{'model':'replacement-model'}},1).status_code == 200
        assert counts['runs'] == 1
    finally:
        release.set()
    assert started.wait(2)
    assert counts['max'] == 1 and len(budgets) == 2
    assert budgets[0] is budgets[1]
    assert save(client,auth,{'llm':{'enabled':False}},2).status_code == 200
    assert stopped.wait(2)
    assert counts['active'] == 0 and counts['runs'] == 2


def test_active_provider_survives_restart_and_embedding_uses_saved_settings(client, auth, db_path, monkeypatch):
    from fastapi.testclient import TestClient
    response = save(client,auth,{'llm':provider(),'embedding':{**provider(),'timeout':12}})
    assert response.status_code == 200
    calls = []
    def post(url, **kwargs):
        calls.append((url,kwargs))
        return httpx.Response(200,json={'data':[{'embedding':[0.1,0.2]}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(llm.httpx,'post',post)
    assert client.app.state.embed_client.embed('Eigen invoer') == [0.1,0.2]
    assert calls[0][0].endswith('/embeddings') and calls[0][1]['timeout'] == 12
    with TestClient(server.create_app(db_path, enable_dispatcher=False, enable_mcp=False, enable_triage=False, enable_wiki_compile=False)) as restarted:
        data = restarted.get(PATH,headers=auth).json()
        assert data['runtime']['providers']['llm']['ready']
        assert restarted.app.state.llm_client._model == 'saved-model'
        assert KEY not in json.dumps(data)


def test_unreadable_key_has_recoverable_status_and_can_be_cleared(client, auth, monkeypatch):
    assert save(client,auth,{'llm':provider()}).status_code == 200
    monkeypatch.setenv('HEGEMONE_SETTINGS_SECRET','different-synthetic-runtime-key-0000000000000')
    response = save(client,auth,{'language':'nl'},1)
    assert response.status_code == 200
    assert response.json()['runtime']['providers']['llm']['error'] == 'secret_unavailable'
    assert client.app.state.llm_client is None
    response = save(client,auth,{'llm':{'api_key':None}},2)
    assert response.status_code == 200
    assert response.json()['runtime']['providers']['llm']['error'] is None


def test_missing_internal_actor_is_created_and_conflicting_human_rolls_back(client, auth, conn, monkeypatch):
    from betonning import triage_worker
    async def fake_loop(db_path, stop, *args, **kwargs):
        await stop.wait()
    monkeypatch.setattr(triage_worker,'triage_loop',fake_loop)
    assert users.get_by_handle(conn,'triage') is None
    assert save(client,auth,{'llm':provider(),'triage_enabled':True}).status_code == 200
    actor = users.get_by_handle(conn,'triage')
    assert actor['kind'] == 'agent'
    users.admin_update(conn,actor['id'],{'kind':'human'})
    response = save(client,auth,{'language':'nl'},1)
    assert response.status_code == 422
    assert client.get(PATH,headers=auth).json()['revision'] == 1


def test_reconfigured_batch_is_not_recorded_as_provider_failure(client, auth, project, conn, db_path, monkeypatch):
    from betonning import triage_worker
    client.post(f'/api/v1/projects/{project}/items',headers=auth,json={'title':'Eigen taak'}).json()
    assert save(client,auth,{'llm':provider()}).status_code == 200
    guarded = runtime.WorkerProvider(client.app,client.app.state.installation_runtime,'llm')
    assert save(client,auth,{'llm':{'enabled':False}},1).status_code == 200
    item_id = conn.execute('SELECT id FROM items WHERE seq=1').fetchone()[0]
    monkeypatch.setattr(triage_worker,'find_untriaged',lambda *a,**kw:[item_id])
    def once(conn, item_id, llm_client, *args, **kwargs):
        llm_client.complete([{'role':'user','content':'Never sent'}])
    monkeypatch.setattr(triage_worker,'triage_once',once)
    before = dict(conn.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone())
    with pytest.raises(runtime.RuntimeReconfigured):
        triage_worker._run_batch(db_path,guarded,None,users.get_by_handle(conn,'person')['id'],0,1)
    after = dict(conn.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone())
    assert before == after


def test_shutdown_during_worker_switch_does_not_start_replacement(monkeypatch):
    from types import SimpleNamespace
    from betonning import triage_worker
    async def scenario():
        started, draining, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        starts = []
        async def fake_loop(db_path, stop, *args, **kwargs):
            starts.append(True)
            started.set()
            await stop.wait()
            draining.set()
            await release.wait()
        monkeypatch.setattr(triage_worker,'triage_loop',fake_loop)
        def snapshot(revision):
            return runtime.Snapshot(revision,{},object(),None,True,False,{},[])
        state = SimpleNamespace(installation_runtime=snapshot(0),runtime_changed=asyncio.Event(),db_path='unused',triage_debounce=0,triage_interval=1)
        app = SimpleNamespace(state=state)
        stop = asyncio.Event()
        task = asyncio.create_task(runtime.supervise(app,stop))
        await asyncio.wait_for(started.wait(),1)
        state.installation_runtime = snapshot(1)
        state.runtime_changed.set()
        await asyncio.wait_for(draining.wait(),1)
        stop.set()
        release.set()
        await asyncio.wait_for(task,1)
        assert len(starts) == 1
    asyncio.run(scenario())
