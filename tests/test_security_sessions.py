"""Browser-CSRF en expliciete agentrechten (BETON-505)."""
import pytest


def test_browser_session_csrf_logout(client, auth):
    result = client.post('/api/v1/session', headers=auth)
    assert result.status_code == 200
    assert 'HttpOnly' in result.headers['set-cookie']
    assert 'api_key' not in result.json()
    csrf = result.json()['csrf_token']
    assert client.get('/api/v1/me').status_code == 200
    assert client.post('/api/v1/projects', json={'key':'NO','name':'No'}).status_code == 403
    headers = {'X-CSRF-Token':csrf, 'Origin':'https://evil.example'}
    assert client.post('/api/v1/projects', headers=headers, json={'key':'NO','name':'No'}).status_code == 403
    headers = {'X-CSRF-Token':csrf, 'Origin':'http://testserver'}
    assert client.post('/api/v1/projects', headers=headers, json={'key':'YES','name':'Yes'}).status_code == 201
    assert client.post('/api/v1/logout', headers=headers).status_code == 200
    assert client.get('/api/v1/me').status_code == 401


def test_browser_session_revocation(client, auth):
    assert client.post('/api/v1/session', headers=auth).status_code == 200
    assert client.post('/api/v1/users/person/api-key/rotate', headers=auth).status_code == 200
    assert client.get('/api/v1/me').status_code == 401


def test_scoped_key_and_expiry(client, auth, project):
    client.post('/api/v1/projects', headers=auth, json={'key':'OTHER','name':'Other'})
    own = client.post('/api/v1/projects/SOS/items', headers=auth, json={'title':'Allowed'}).json()['ref']
    other = client.post('/api/v1/projects/OTHER/items', headers=auth, json={'title':'Secret'}).json()['ref']
    agent = client.post('/api/v1/users', headers=auth, json={'handle':'limited','display_name':'Limited'}).json()
    headers = {'Authorization':f"Bearer {agent['api_key']}"}
    policy = {'api_key_scopes':['read'], 'api_key_projects':['SOS']}
    assert client.patch('/api/v1/users/limited', headers=auth, json=policy).status_code == 200
    assert client.get('/api/v1/items/'+own, headers=headers).status_code == 200
    assert client.get('/api/v1/items/'+other, headers=headers).status_code == 403
    assert [p['key'] for p in client.get('/api/v1/projects', headers=headers).json()] == ['SOS']
    assert client.get('/api/v1/search?q=Secret', headers=headers).status_code == 403
    assert client.post('/api/v1/projects/SOS/items', headers=headers, json={'title':'No'}).status_code == 403
    assert client.patch('/api/v1/users/limited', headers=headers, json={'api_key_scopes':None}).status_code == 403
    assert client.patch('/api/v1/users/limited', headers=auth,
                        json={'api_key_expires_at':'2000-01-01T00:00:00Z'}).status_code == 200
    assert client.get('/api/v1/me', headers=headers).status_code == 401


def test_browser_ttl_and_no_agent_login(client, auth, monkeypatch):
    result = client.post('/api/v1/session', headers=auth)
    from betonning.repo import browser_sessions
    monkeypatch.setattr(browser_sessions.time, 'time', lambda: result.json()['expires_at'] + 1)
    assert client.get('/api/v1/me').status_code == 401
    agent = client.post('/api/v1/users', headers=auth, json={'handle':'agent','display_name':'Agent'}).json()
    assert client.post('/api/v1/session', headers={'Authorization':f"Bearer {agent['api_key']}"}).status_code == 403


def test_media_respects_project_scope_and_invalid_tokens(client, auth, project):
    client.post('/api/v1/projects/SOS/items',headers=auth,json={'title':'Own'}).json()
    client.post('/api/v1/projects',headers=auth,json={'key':'OTHER','name':'Other'})
    other = client.post('/api/v1/projects/OTHER/items',headers=auth,json={'title':'Other'}).json()
    attachment = client.post(f"/api/v1/items/{other['ref']}/attachments",headers=auth,
                             files={'file':('test.txt',b'other secret','text/plain')}).json()
    agent = client.post('/api/v1/users',headers=auth,json={'handle':'media-agent','display_name':'Media'}).json()
    client.patch('/api/v1/users/media-agent',headers=auth,json={'api_key_scopes':['read'],'api_key_projects':['SOS']})
    headers={'Authorization':f"Bearer {agent['api_key']}"}
    assert client.get(attachment['url'],headers=headers).status_code == 403
    from betonning.security import verify_media_token
    assert verify_media_token('é.fake') is None


def test_scoped_agent_cannot_move_or_link_to_another_project(client, auth, project):
    client.post('/api/v1/projects',headers=auth,json={'key':'OTHER','name':'Other'})
    own = client.post('/api/v1/projects/SOS/items',headers=auth,json={'title':'Own'}).json()['ref']
    other = client.post('/api/v1/projects/OTHER/items',headers=auth,json={'title':'Secret'}).json()['ref']
    agent = client.post('/api/v1/users',headers=auth,json={'handle':'writer','display_name':'Writer'}).json()
    client.patch('/api/v1/users/writer',headers=auth,json={'api_key_projects':['SOS']})
    headers={'Authorization':f"Bearer {agent['api_key']}"}
    assert client.post('/api/v1/items/'+own+'/move',headers=headers,json={'project':'OTHER'}).status_code == 403
    assert client.post('/api/v1/items/'+own+'/relations',headers=headers,json={'type':'relates_to','target':other}).status_code == 403
    client.post('/api/v1/items/'+own+'/relations',headers=auth,json={'type':'relates_to','target':other})
    data=client.get('/api/v1/items/'+own,headers=headers).json()
    assert not any(data['relations_detail'].values())


def test_browser_session_blijft_dertig_dagen_geldig(client, auth, monkeypatch):
    from betonning.repo import browser_sessions
    now = browser_sessions.time.time()
    result = client.post('/api/v1/session', headers=auth)
    assert result.status_code == 200
    assert result.json()['expires_at'] == pytest.approx(now + 30 * 86400, abs=5)
    assert 'Max-Age=2592000' in result.headers['set-cookie']
    for elapsed in (3601, 7 * 86400, 29 * 86400):
        monkeypatch.setattr(browser_sessions.time, 'time', lambda: now + elapsed)
        assert client.get('/api/v1/session').status_code == 200
        assert client.get('/api/v1/me').status_code == 200
    monkeypatch.setattr(browser_sessions.time, 'time', lambda: now + 30 * 86400 + 5)
    assert client.get('/api/v1/me').status_code == 401
