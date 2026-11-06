"""Eerste installatie blijft expliciet, eenmalig en onafhankelijk van handles."""
import asyncio
from types import SimpleNamespace

import pytest

from betonning.resource_limits import ResourceGuardMiddleware
from betonning.repo import users

TOKEN = 'synthetic-setup-token-for-tests-only-0001'
HEADERS = {'X-Setup-Token': TOKEN}
BODY = {'handle': 'operator', 'display_name': 'Operator'}


@pytest.fixture
def setup_enabled(monkeypatch):
    monkeypatch.setenv('HEGEMONE_SETUP_TOKEN', TOKEN)


def test_setup_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv('HEGEMONE_SETUP_TOKEN', raising=False)
    assert client.get('/api/v1/setup').json() == {'required': True, 'enabled': False}
    assert client.post('/api/v1/setup', headers=HEADERS, json=BODY).status_code == 503


@pytest.mark.parametrize('token', ['', 'short', 'x' * 257, 'x' * 32 + ' '])
def test_weak_configuration_does_not_enable_setup(client, monkeypatch, token):
    monkeypatch.setenv('HEGEMONE_SETUP_TOKEN', token)
    assert client.get('/api/v1/setup').json()['enabled'] is False


def test_setup_creates_session_and_only_once(client, setup_enabled):
    assert client.get('/api/v1/setup').json() == {'required': True, 'enabled': True}
    result = client.post('/api/v1/setup', headers=HEADERS, json=BODY)
    assert result.status_code == 201
    data = result.json()
    assert data['user']['kind'] == 'human'
    assert 'api_key_hash' not in data['user']
    assert result.headers['cache-control'] == 'no-store'
    assert 'HttpOnly' in result.headers['set-cookie']
    assert client.get('/api/v1/me').json()['handle'] == 'operator'
    assert client.get('/api/v1/setup').json() == {'required': False, 'enabled': False}
    assert client.post('/api/v1/setup', headers=HEADERS, json=BODY).status_code == 409
    # De eenmalige key werkt voor volgende aanmelding; cookies zijn niet nodig.
    client.cookies.clear()
    assert client.get('/api/v1/me', headers={'Authorization': 'Bearer ' + data['api_key']}).status_code == 200


def test_deactivation_never_reopens_setup(client, conn, setup_enabled):
    user, _ = users.create(conn, handle='former', display_name='Former', kind='human')
    users.deactivate(conn, user['id'])
    assert client.get('/api/v1/setup').json()['required'] is False
    assert client.post('/api/v1/setup', headers=HEADERS, json=BODY).status_code == 409


def test_setup_rejects_wrong_token_and_origin(client, setup_enabled):
    for headers, expected in [({}, 401), ({'X-Setup-Token': 'wrong'}, 401),
                              ({**HEADERS, 'Origin': 'https://attacker.example'}, 403)]:
        assert client.post('/api/v1/setup', headers=headers, json=BODY).status_code == expected
    assert client.get('/api/v1/setup').json()['required'] is True


def test_setup_collision_does_not_leave_partial_user(client, conn, setup_enabled):
    users.create(conn, handle='operator', display_name='Agent', kind='agent')
    assert client.post('/api/v1/setup', headers=HEADERS, json=BODY).status_code == 409
    assert client.get('/api/v1/setup').json()['required'] is True
    assert conn.execute('SELECT count(*) FROM browser_sessions').fetchone()[0] == 0


def test_invalid_handle_is_atomic(client, setup_enabled):
    assert client.post('/api/v1/setup', headers=HEADERS, json={**BODY, 'handle': 'invalid space'}).status_code == 422
    assert client.get('/api/v1/setup').json()['required'] is True


def test_setup_guard_rejects_before_body(client, db_path, setup_enabled):
    async def forbidden(*args):
        raise AssertionError('Body mag niet worden verwerkt')
    owner = SimpleNamespace(state=SimpleNamespace(db_path=db_path, enable_api_limits=True))
    middleware = ResourceGuardMiddleware(forbidden, owner)
    messages = []
    async def send(message):
        messages.append(message)
    asyncio.run(middleware({'type': 'http', 'method': 'POST', 'path': '/api/v1/setup', 'headers': []}, forbidden, send))
    assert messages[0]['status'] == 401


def test_setup_with_production_guards(client, setup_enabled):
    client.app.state.enable_api_limits = True
    result = client.post('/api/v1/setup', headers={**HEADERS, 'Origin': 'http://testserver'}, json=BODY)
    assert result.status_code == 201
    csrf = result.json()['csrf_token']
    created = client.post('/api/v1/projects', headers={'X-CSRF-Token': csrf},
                          json={'key': 'FIRST', 'name': 'First project'})
    assert created.status_code == 201
    assert client.post('/api/v1/setup', headers=HEADERS, json=BODY).status_code == 409


def test_parallel_setup_has_exactly_one_winner(client, setup_enabled):
    from concurrent.futures import ThreadPoolExecutor
    # Beide requests gebruiken een eigen requestconnectie en dezelfde database.
    def create(handle):
        return client.post('/api/v1/setup', headers=HEADERS, json={**BODY, 'handle': handle}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ['first', 'second']))
    assert sorted(results) == [201, 409]
