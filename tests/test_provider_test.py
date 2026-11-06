"""Bewuste providertest zonder externe verbindingen of ticketdata."""
import httpx
import pytest

from betonning import server, llm
from betonning.repo import users

PATH = '/api/v1/settings/installation'
KEY = 'synthetic-key-must-never-be-returned'


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    monkeypatch.setattr(server,'load_dotenv',lambda:None)
    for prefix in ['HEGEMONE_','BETONNING_']:
        for suffix in ['LLM_BASE_URL','LLM_API_KEY','LLM_MODEL','LLM_ENABLED','LLM_TIMEOUT','LLM_MAX_OUTPUT_TOKENS','LLM_TOKEN_LIMIT_FIELD','EMBED_BASE_URL','EMBED_API_KEY','EMBED_MODEL','EMBED_ENABLED','TRIAGE_ENABLED','WIKI_COMPILE_ENABLED']:
            monkeypatch.delenv(prefix+suffix,raising=False)
    monkeypatch.setenv('HEGEMONE_SETTINGS_SECRET','synthetic-provider-test-encryption-00000000000000')


def configure(client,auth):
    provider={'enabled':True,'base_url':'https://provider.example/v1','model':'example','api_key':KEY,'timeout':90}
    response=client.patch(PATH,headers=auth,json={'schema_version':1,'expected_revision':0,'settings':{'llm':provider,'embedding':provider}})
    assert response.status_code == 200


def test_small_synthetic_request_and_no_provider_output_returned(client,auth,monkeypatch):
    configure(client,auth)
    calls=[]
    def post(url,**kwargs):
        calls.append((url,kwargs))
        body={'choices':[{'message':{'content':KEY}}]} if url.endswith('completions') else {'data':[{'embedding':[0.1,0.2]}]}
        return httpx.Response(200,json=body,request=httpx.Request('POST',url))
    monkeypatch.setattr(llm.httpx,'post',post)
    for provider in ['llm','embedding']:
        response=client.post(f'{PATH}/providers/{provider}/test',headers=auth)
        assert response.status_code == 200
        assert response.json()['ok'] and response.json()['provider'] == provider
        assert response.headers['cache-control'] == 'no-store'
        assert KEY not in response.text
    assert calls[0][1]['timeout'] == 10
    assert calls[0][1]['json']['max_completion_tokens'] == 128
    assert calls[0][1]['json']['messages'] == [{'role':'user','content':'Hegemone connection test. Reply with OK.'}]
    assert calls[1][1]['timeout'] == 10
    assert calls[1][1]['json']['input'] == 'Hegemone connection test'
    assert client.app.state.llm_client._timeout == 90


def test_provider_failure_is_redacted(client,auth,monkeypatch):
    configure(client,auth)
    def post(*args,**kwargs):
        raise RuntimeError('Do not return '+KEY)
    monkeypatch.setattr(llm.httpx,'post',post)
    response=client.post(f'{PATH}/providers/llm/test',headers=auth)
    assert response.status_code == 502
    assert response.json()['error_code'] == 'provider_test_failed'
    assert KEY not in response.text
    assert response.headers['cache-control'] == 'no-store'


def test_admin_llm_scope_and_agent_gate(client,auth,conn):
    user,key=users.create(conn,handle='limited-provider-admin',display_name='Limited',kind='human')
    users.admin_update(conn,user['id'],{'api_key_scopes':['read','write','admin']})
    assert client.post(f'{PATH}/providers/llm/test',headers={'Authorization':f'Bearer {key}'}).status_code == 403
    _,key=users.create(conn,handle='provider-agent',display_name='Agent',kind='agent')
    assert client.post(f'{PATH}/providers/llm/test',headers={'Authorization':f'Bearer {key}'}).status_code == 403
    assert client.post(f'{PATH}/providers/llm/test',headers=auth).status_code == 409


def test_cookie_csrf_and_rate_limit_prevent_unrequested_calls(client,auth,monkeypatch):
    configure(client,auth)
    session=client.post('/api/v1/session',headers=auth).json()
    calls=[]
    monkeypatch.setattr(llm.httpx,'post',lambda *a,**kw:calls.append(True))
    assert client.post(f'{PATH}/providers/llm/test').status_code == 403
    class Limited:
        def check(self,*args,**kwargs): return 2
    client.app.state.llm_rate_limiter=Limited()
    response=client.post(f'{PATH}/providers/llm/test',headers={'X-CSRF-Token':session['csrf_token']})
    assert response.status_code == 429 and response.headers['retry-after']=='2'
    assert calls == []
