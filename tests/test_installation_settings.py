"""Installatieconfiguratie met synthetische keys en geïsoleerde testdatabase."""
import json

import pytest

from betonning.installation_config import decrypt_key, SettingsSecretError
from betonning.repo import installation_settings as store, users

PATH = '/api/v1/settings/installation'
KEY = 'synthetic-provider-key-for-settings-tests'


@pytest.fixture(autouse=True)
def encryption_secret(monkeypatch):
    monkeypatch.setenv('HEGEMONE_SETTINGS_SECRET', 'synthetic-encryption-material-0000000000000000')


def patch(client, auth, settings, revision=0, **extra):
    return client.patch(PATH, json={'schema_version': 1, 'expected_revision': revision, 'settings': settings, **extra}, headers=auth)


def test_empty_installation_and_human_admin_guard(client, auth, conn):
    response = client.get(PATH, headers=auth)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    data = response.json()
    assert data['revision'] == 0 and data['schema_version'] == 1
    assert data['settings']['language'] == 'en'
    assert not data['settings']['llm']['enabled']
    assert not data['settings']['llm']['has_api_key']
    _, key = users.create(conn, handle='settings-agent', display_name='Agent', kind='agent')
    agent = {'Authorization': f'Bearer {key}'}
    assert client.get(PATH, headers=agent).status_code == 403
    assert patch(client, agent, {'language': 'nl'}).status_code == 403
    assert store.get(conn) is None


def test_secret_is_encrypted_write_only_and_not_in_audit(client, auth, conn):
    response = patch(client, auth, {'llm': {'enabled': True, 'base_url': 'https://provider.example/v1/', 'model': 'test-model', 'api_key': KEY}})
    assert response.status_code == 200
    data = response.json()
    assert data['revision'] == 1
    assert data['settings']['llm']['base_url'] == 'https://provider.example/v1'
    assert data['settings']['llm']['has_api_key']
    assert 'api_key' not in data['settings']['llm']
    assert KEY not in response.text
    row = store.get(conn)
    assert KEY.encode() not in row['llm_key']
    assert KEY not in json.dumps(row['settings'])
    assert decrypt_key(row['llm_key']) == KEY
    event = conn.execute("SELECT payload FROM events WHERE type='installation.settings.updated'").fetchone()[0]
    assert KEY not in event and row['llm_key'].decode() not in event
    assert 'llm.api_key' in json.loads(event)['fields']
    assert KEY not in client.get(PATH, headers=auth).text


def test_partial_update_preserves_key_disable_and_explicit_clear(client, auth, conn):
    assert patch(client, auth, {'llm': {'api_key': KEY, 'enabled': True}}).status_code == 200
    assert patch(client, auth, {'llm': {'enabled': False}, 'language': 'nl'}, 1).status_code == 200
    assert decrypt_key(store.get(conn)['llm_key']) == KEY
    assert client.get(PATH, headers=auth).json()['settings']['llm']['has_api_key']
    assert patch(client, auth, {'llm': {'api_key': None}}, 2).status_code == 200
    assert store.get(conn)['llm_key'] is None
    assert not client.get(PATH, headers=auth).json()['settings']['llm']['has_api_key']


def test_revision_conflict_and_invalid_update_are_atomic(client, auth, conn):
    assert patch(client, auth, {'language': 'nl'}).status_code == 200
    assert patch(client, auth, {'language': 'en'}).status_code == 409
    assert patch(client, auth, {'language': 'en', 'llm': {'base_url': 'https://user:synthetic@example.com/v1'}}, 1).status_code == 422
    row = store.get(conn)
    assert row['revision'] == 1 and row['settings']['language'] == 'nl'
    assert conn.execute("SELECT COUNT(*) FROM events WHERE type='installation.settings.updated'").fetchone()[0] == 1


def test_no_durable_secret_refuses_secret_save_but_allows_nonsecret_settings(client, auth, monkeypatch, conn):
    for name in ['HEGEMONE_SETTINGS_SECRET', 'BETONNING_SETTINGS_SECRET', 'HEGEMONE_MEDIA_SECRET', 'BETONNING_MEDIA_SECRET']:
        monkeypatch.delenv(name, raising=False)
    assert not client.get(PATH, headers=auth).json()['secret_storage_ready']
    assert patch(client, auth, {'llm': {'api_key': KEY}}).status_code == 503
    assert store.get(conn) is None
    assert patch(client, auth, {'language': 'nl'}).status_code == 200


def test_validation_never_echoes_key_from_root_or_nested_input(client, auth):
    for body in [
        {'schema_version': 7, 'expected_revision': 0, 'settings': {'llm': {'api_key': KEY}}},
        {'schema_version': 1, 'settings': {'llm': {'api_key': KEY}}},
        {'schema_version': 1, 'expected_revision': 0, 'settings': {'llm': {'api_key': KEY + '\n'}}},
    ]:
        response = client.patch(PATH, json=body, headers=auth)
        assert response.status_code == 422
        assert KEY not in response.text
        assert all('input' not in error and 'ctx' not in error for error in response.json()['detail'])


def test_wrong_encryption_key_has_generic_error(client, auth, conn, monkeypatch):
    assert patch(client, auth, {'embedding': {'api_key': KEY}}).status_code == 200
    ciphertext = store.get(conn)['embedding_key']
    monkeypatch.setenv('HEGEMONE_SETTINGS_SECRET', 'different-synthetic-encryption-material-00000000')
    with pytest.raises(SettingsSecretError, match='kan niet worden ontsleuteld') as error:
        decrypt_key(ciphertext)
    assert KEY not in str(error.value)
    assert client.get(PATH, headers=auth).status_code == 200


def test_human_scoped_key_without_admin_cannot_read_or_write(client, auth, conn):
    user, key = users.create(conn, handle='settings-reader', display_name='Reader', kind='human')
    users.admin_update(conn, user['id'], {'api_key_scopes': ['read', 'write']})
    headers = {'Authorization': f'Bearer {key}'}
    assert client.get(PATH, headers=headers).status_code == 403
    assert patch(client, headers, {'language': 'nl'}).status_code == 403


def test_cookie_update_requires_csrf(client, auth):
    session = client.post('/api/v1/session', headers=auth).json()
    body = {'schema_version': 1, 'expected_revision': 0, 'settings': {'language': 'nl'}}
    assert client.patch(PATH, json=body).status_code == 403
    response = client.patch(PATH, json=body, headers={'X-CSRF-Token': session['csrf_token']})
    assert response.status_code == 200
    assert response.json()['settings']['language'] == 'nl'


def test_saved_config_survives_new_app_instance(client, auth, db_path):
    from fastapi.testclient import TestClient
    from betonning.server import create_app
    assert patch(client, auth, {'embedding': {'api_key': KEY}, 'language': 'nl'}).status_code == 200
    with TestClient(create_app(db_path, enable_dispatcher=False, enable_mcp=False, enable_triage=False, enable_wiki_compile=False, llm_client=None, embed_client=None)) as restarted:
        data = restarted.get(PATH, headers=auth).json()
        assert data['revision'] == 1 and data['settings']['language'] == 'nl'
        assert data['settings']['embedding']['has_api_key']
        assert KEY not in json.dumps(data)


@pytest.mark.parametrize('url', ['', ' https://provider.example/v1', 'https://provider.example/a b'])
def test_invalid_public_url_is_rejected_without_writes(client, auth, conn, url):
    response = patch(client, auth, {'public_url': url})
    assert response.status_code == 422
    assert response.headers['cache-control'] == 'no-store'
    assert store.get(conn) is None
