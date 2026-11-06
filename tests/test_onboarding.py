"""Onboarding is hervatbaar en geldt uitsluitend voor nieuwe setupbeheerders."""
from betonning.repo import users

TOKEN = 'synthetic-onboarding-token-test-only-0001'


def start(client, monkeypatch, locale='en'):
    monkeypatch.setenv('HEGEMONE_SETUP_TOKEN', TOKEN)
    result = client.post('/api/v1/setup', headers={'X-Setup-Token': TOKEN},
                         json={'handle': 'operator', 'display_name': 'Operator', 'locale': locale})
    assert result.status_code == 201
    return {'X-CSRF-Token': result.json()['csrf_token']}


def test_onboarding_hervat_en_voltooit(client, monkeypatch):
    headers = start(client, monkeypatch, 'nl')
    initial = client.get('/api/v1/onboarding').json()
    assert initial['step'] == 'project' and initial['locale'] == 'nl'
    assert client.post('/api/v1/onboarding/complete', headers=headers).status_code == 409
    body = {'key': 'TEAM', 'name': 'Team'}
    for _ in range(2):
        result = client.post('/api/v1/onboarding/project', headers=headers, json=body)
        assert result.status_code == 201
        assert result.json()['step'] == 'agents'
    assert len(client.get('/api/v1/projects').json()) == 1
    assert client.get('/api/v1/onboarding').json()['project_key'] == 'TEAM'
    assert client.post('/api/v1/onboarding/complete', headers=headers).json()['required'] is False
    assert client.get('/api/v1/onboarding').json()['step'] == 'complete'


def test_bestaande_gebruiker_geen_wizard(client, auth):
    assert client.get('/api/v1/onboarding', headers=auth).json()['required'] is False
    assert client.post('/api/v1/onboarding/project', headers=auth, json={'key': 'NO', 'name': 'No'}).status_code == 409


def test_onboarding_auth_en_rol(client, conn):
    assert client.get('/api/v1/onboarding').status_code == 401
    _, key = users.create(conn, handle='worker', display_name='Worker', kind='agent')
    headers = {'Authorization': 'Bearer ' + key}
    assert client.get('/api/v1/onboarding', headers=headers).status_code == 403
    assert client.post('/api/v1/onboarding/project', headers=headers, json={'key': 'NO', 'name': 'No'}).status_code == 403


def test_projectvalidatie_laat_stap_ongewijzigd(client, monkeypatch):
    headers = start(client, monkeypatch)
    assert client.post('/api/v1/onboarding/project', headers=headers, json={'key': 'invalid space', 'name': 'No'}).status_code == 422
    assert client.get('/api/v1/onboarding').json()['step'] == 'project'
