"""Gerichte upgrade-/herstelgates met uitsluitend tijdelijke fixturedata."""
from pathlib import Path
import shutil

from fastapi.testclient import TestClient

from betonning import db
from betonning.server import create_app
from betonning.repo import users, projects, items, states


def application(directory: Path):
    return create_app(
        directory/'hegemone.db', attachments_dir=directory/'attachments',
        enable_dispatcher=False, enable_mcp=False, enable_triage=False,
        enable_wiki_compile=False, llm_client=None, embed_client=None,
    )


def test_upgrade_vanaf_schema_51_behoudt_toegang_en_tickets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path/'upgrade'
    directory.mkdir()
    conn = db.connect(directory/'hegemone.db')
    try:
        # Bewust de vorige releasegrens, niet de huidige migratierunner.
        for version, sql in db._migration_files():
            if version <= 51:
                conn.executescript(sql)
        conn.execute('PRAGMA user_version = 51')
        human, key = users.create(conn, handle='operator', display_name='Operator', kind='human')
        project = projects.create(conn, key='UPG', name='Existing project')
        started = states.get_by_name(conn, project['id'], 'in-progress')
        item = items.create(conn, project_id=project['id'], title='Existing ticket',
                            state_id=started['id'], created_by=human['id'], plan_md='Preserve this plan')
        identity = (human['id'], project['id'], item['id'])
    finally:
        conn.close()
    auth = {'Authorization': 'Bearer ' + key}
    with TestClient(application(directory)) as client:
        assert client.get('/api/v1/me', headers=auth).json()['id'] == identity[0]
        listing = client.get('/api/v1/projects', headers=auth).json()
        assert next(project for project in listing if project['key'] == 'UPG')['id'] == identity[1]
        restored = client.get('/api/v1/items/UPG-1', headers=auth).json()
        assert restored['id'] == identity[2]
        assert restored['state'] == 'in-progress'
        assert client.get('/api/v1/items/UPG-1/plan', headers=auth).json()['plan_md'] == 'Preserve this plan'
        assert client.get('/api/v1/onboarding', headers=auth).json()['required'] is False
        assert client.get('/api/v1/setup').json()['required'] is False


def test_stopped_directory_backup_herstelt_volledige_appdata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HEGEMONE_SETUP_TOKEN', 'synthetic-restore-setup-token-fixture-0001')
    monkeypatch.setenv('HEGEMONE_MEDIA_SECRET', 'synthetic-persistent-media-fixture-0001')
    original = tmp_path/'original'
    original.mkdir()
    with TestClient(application(original)) as client:
        result = client.post('/api/v1/setup', headers={'X-Setup-Token': 'synthetic-restore-setup-token-fixture-0001'},
                             json={'handle': 'operator', 'display_name': 'Operator'})
        assert result.status_code == 201
        key = result.json()['api_key']
        auth = {'Authorization': 'Bearer ' + key}
        assert client.post('/api/v1/onboarding/project', headers=auth, json={'key': 'BACK', 'name': 'Backup project'}).status_code == 201
        assert client.post('/api/v1/onboarding/complete', headers=auth).status_code == 200
        created = client.post('/api/v1/projects/BACK/items', headers=auth,
                              json={'title': 'Preserved ticket', 'state': 'in-progress', 'labels': ['routine']})
        assert created.status_code == 201
        ref = created.json()['ref']
        assert client.post('/api/v1/items/'+ref+'/comments', headers=auth, json={'body_md': 'Preserved discussion'}).status_code == 201
        upload = client.post('/api/v1/items/'+ref+'/attachments', headers=auth,
                             files={'file': ('fixture.txt', b'preserved attachment', 'text/plain')})
        assert upload.status_code == 201
        media_url = upload.json()['url']
        assert client.post('/api/v1/projects/BACK/wiki', headers=auth,
                           json={'slug': 'knowledge', 'title': 'Knowledge', 'body_md': 'Preserved knowledge'}).status_code == 201
    # De app is gesloten en alle verbindingen zijn vrij vóór het kopiëren.
    backup = tmp_path/'backup'
    shutil.copytree(original, backup)
    restored = tmp_path/'restored'
    shutil.copytree(backup, restored)
    with TestClient(application(restored)) as client:
        assert client.get('/api/v1/me', headers=auth).json()['handle'] == 'operator'
        ticket = client.get('/api/v1/items/'+ref, headers=auth).json()
        assert ticket['title'] == 'Preserved ticket'
        assert ticket['state'] == 'in-progress'
        assert ticket['labels'] == ['routine']
        assert any(comment['body_md'] == 'Preserved discussion' for comment in ticket['comments'])
        assert client.get(media_url, headers=auth).content == b'preserved attachment'
        page = client.get('/api/v1/projects/BACK/wiki/knowledge', headers=auth)
        assert page.status_code == 200 and page.json()['body_md'] == 'Preserved knowledge'
        assert client.get('/api/v1/onboarding', headers=auth).json()['required'] is False
        assert client.get('/api/v1/setup').json()['required'] is False
