"""Vaste werkklassen en compacte standaardkolommen (BETON-510/511)."""

from betonning import db
from betonning.repo import labels, projects, project_template


def _migration(conn, version):
    conn.executescript(next(sql for number, sql in db._migration_files() if number == version))


def test_nieuw_project_heeft_werkklassen(client, auth):
    assert client.post('/api/v1/projects', headers=auth, json={'key': 'NIEUW', 'name': 'Nieuw'}).status_code == 201
    actual = client.get('/api/v1/projects/NIEUW/labels', headers=auth).json()
    assert {label['name'] for label in actual} == {'routine', 'standaard', 'complex'}


def test_labelmigratie_vult_alleen_ontbrekende_klassen_aan(conn):
    project = projects.create(conn, key='OUD', name='Oud')
    existing = labels.get_by_name(conn, project['id'], 'complex')
    labels.set_color(conn, existing['id'], '#123456')
    labels.delete(conn, labels.get_by_name(conn, project['id'], 'routine')['id'])
    for _ in range(2):
        _migration(conn, 50)
    actual = labels.list_for_project(conn, project['id'])
    assert {label['name'] for label in actual} == {'routine', 'standaard', 'complex'}
    assert labels.get_by_name(conn, project['id'], 'complex')['color'] == '#123456'


def test_template_migratie_behoudt_projecten_en_aangepaste_templates(conn):
    old = project_template.get(conn) + [
        dict(name=name, group='started', color='#123456', is_default=False, closed=False, blocks_work=False)
        for name in ('triage', 'blocked', 'review')
    ]
    project_template.replace(conn, old)
    project = projects.create(conn, key='OUD', name='Oud')
    _migration(conn, 51)
    assert [state['name'] for state in project_template.get(conn)] == [
        'backlog', 'todo', 'in-progress', 'deferred', 'done', 'cancelled'
    ]
    assert conn.execute('SELECT count(*) FROM states WHERE project_id=?', (project['id'],)).fetchone()[0] == 9
    custom = [dict(old[0], name='Idee')]
    project_template.replace(conn, custom)
    _migration(conn, 51)
    assert project_template.get(conn) == custom
