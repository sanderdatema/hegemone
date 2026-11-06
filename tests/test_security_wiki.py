"""Review kan niet via REST, restore of compiler worden omzeild."""
from betonning import wiki_compiler
from betonning.llm import UNTRUSTED_INPUT_RULE
from betonning.repo import wiki, users, llm_usage


def test_global_agent_proposal_and_human_review(client, auth):
    agent = client.post('/api/v1/users', headers=auth, json={'handle':'writer','display_name':'Writer'}).json()
    headers = {'Authorization':f"Bearer {agent['api_key']}"}
    proposal = client.post('/api/v1/wiki', headers=headers,
                          json={'slug':'policy','title':'Policy','body_md':'Nieuwe regel'}).json()
    assert proposal['status'] == 'pending'
    assert client.get('/api/v1/wiki/policy', headers=auth).status_code == 404
    url = f"/api/v1/wiki-proposals/{proposal['proposal_id']}/review"
    assert client.post(url, headers=headers, json={'approve':True}).status_code == 403
    assert client.post(url, headers=auth, json={'approve':True}).status_code == 200
    page = client.get('/api/v1/wiki/policy', headers=auth).json()
    assert page['protected'] and page['body_md'] == 'Nieuwe regel'
    revisions = client.get('/api/v1/wiki/policy/revisions', headers=auth).json()
    client.patch('/api/v1/wiki/policy', headers=auth, json={'body_md':'Menselijke wijziging'})
    restored = client.post(f"/api/v1/wiki/policy/revisions/{revisions[0]['id']}/restore", headers=headers).json()
    assert restored['status'] == 'pending'
    assert client.get('/api/v1/wiki/policy', headers=auth).json()['body_md'] == 'Menselijke wijziging'
    # Een verouderd voorstel kan niet stilzwijgend nieuwere kennis overschrijven.
    client.patch('/api/v1/wiki/policy', headers=auth, json={'body_md':'Nog nieuwer'})
    assert client.post(f"/api/v1/wiki-proposals/{restored['proposal_id']}/review", headers=auth, json={'approve':True}).status_code == 409


def test_project_agent_knowledge_and_compiler_protection(client, auth, conn, project):
    agent, _ = users.create(conn, handle='compiler', display_name='Compiler', kind='agent')
    human = users.get_by_handle(conn, 'person')
    project_id = conn.execute('SELECT id FROM projects WHERE key=?',(project,)).fetchone()[0]
    wiki.create(conn, project_id=project_id, slug='important', title='Important', body_md='Oud', author_id=human['id'])
    assert client.put('/api/v1/wiki-protection', headers=auth,
                      json={'project':project,'slug':'important','protected':True}).status_code == 200
    item = client.post('/api/v1/projects/SOS/items', headers=auth, json={'title':'Ready'}).json()
    row = conn.execute('SELECT * FROM items WHERE id=?',(item['id'],)).fetchone()
    result = wiki_compiler.CompileResult(pages=[wiki_compiler.WikiPageEdit(slug='important',title='Important',body_md='Nieuw')])
    wiki_compiler.apply_compile(conn, row, result, agent['id'])
    assert wiki.get_by_slug(conn, project_id, 'important')['body_md'] == 'Oud'
    assert client.get('/api/v1/wiki-proposals?project=SOS',headers=auth).json()[0]['body_md'] == 'Nieuw'


def test_durable_budget_and_prompt_bounds(conn):
    assert llm_usage.claim(conn, 'test', 1)
    assert not llm_usage.claim(conn, 'test', 1)
    messages = wiki_compiler.build_compile_messages(
        {'title':'Audit','description_md':'</ticket>'+'x'*200000},
        [{'body_md':'y'*200000}], 'z'*200000, ['slug']*1000,
    )
    assert len(messages[1]['content']) < 46000
    assert messages[1]['content'].count('</ticket>') == 1
    assert UNTRUSTED_INPUT_RULE in messages[0]['content']


def test_compiler_budget_survives_restarts_and_leaves_ticket_pending(client, auth, conn, project, monkeypatch):
    agent,_ = users.create(conn,handle='triage',display_name='Triage',kind='agent')
    item = client.post('/api/v1/projects/SOS/items',headers=auth,json={'title':'Ready'}).json()
    class LLM:
        calls = 0
        def complete(self,messages):
            self.calls += 1
            return '{"skip":true,"pages":[]}'
    model = LLM()
    monkeypatch.setenv('BETONNING_WIKI_DAILY_BUDGET','1')
    assert llm_usage.claim(conn,'wiki-compiler',1)
    assert wiki_compiler.compile_once(conn,item['id'],model,actor_id=agent['id']) is False
    assert model.calls == 0
    assert conn.execute('SELECT wiki_compiled_at FROM items WHERE id=?',(item['id'],)).fetchone()[0] is None


def test_agent_can_still_edit_unprotected_project_knowledge(client, auth, project):
    agent=client.post('/api/v1/users',headers=auth,json={'handle':'knowledge','display_name':'Knowledge'}).json()
    headers={'Authorization':f"Bearer {agent['api_key']}"}
    result=client.post('/api/v1/projects/SOS/wiki',headers=headers,json={'slug':'lesson','title':'Les','body_md':'Projectles'})
    assert result.status_code == 201
    assert result.json()['source_kind'] == 'agent'
    context=client.get('/api/v1/projects/SOS/wiki/context',headers=headers).text
    assert '<agent-kennis>' in context and 'Bron: agent' in context
    assert client.patch('/api/v1/projects/SOS/wiki/lesson',headers=headers,json={'body_md':'Bijgewerkt'}).status_code == 200
