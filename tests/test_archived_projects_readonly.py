"""Archived content stays readable and immutable across API and worker entry points."""
from __future__ import annotations

import sqlite3

import pytest

from betonning import db, triage_commands, triage_worker, wiki_compiler
from betonning.repo import items, projects, triage_chat, users, wiki, wiki_review


@pytest.fixture
def frozen(client, auth, conn, project):
    client.post('/api/v1/projects', json={'key': 'LIVE', 'name': 'Active project'}, headers=auth)
    item = client.post('/api/v1/projects/SOS/items', json={'title': 'Preserved ticket', 'state': 'done'}, headers=auth).json()
    live = client.post('/api/v1/projects/LIVE/items', json={'title': 'Active ticket'}, headers=auth).json()
    comment = client.post('/api/v1/items/SOS-1/comments', json={'body_md': 'Preserved comment'}, headers=auth).json()
    question = client.post('/api/v1/items/SOS-1/comments', json={'body_md': 'A question for @person?', 'kind': 'question'}, headers=auth).json()
    client.post('/api/v1/projects/SOS/labels', json={'name': 'example'}, headers=auth)
    client.post('/api/v1/projects/SOS/milestones', json={'name': 'Example milestone'}, headers=auth)
    client.post('/api/v1/projects/SOS/wiki', json={'slug': 'guide', 'title': 'Guide', 'body_md': 'Preserved knowledge'}, headers=auth)
    pid = projects.get_by_key(conn, 'SOS')['id']
    projects.set_wiki_compile_enabled(conn, pid, True)
    projects.set_triage_enabled(conn, pid, True)
    actor = users.get_by_handle(conn, 'person')['id']
    proposal = wiki_review.submit(conn, pid, 'guide', 'Proposed guide', 'Proposed knowledge', actor)
    session = triage_chat.active_session(conn, pid)
    message = triage_chat.add_message(conn, session['id'], 'user', author_id=actor, body_md='Preserved conversation')
    assert client.delete('/api/v1/projects/SOS', headers=auth).status_code == 204
    return {'pid': pid, 'item': item, 'live': live, 'comment': comment, 'question': question,
            'proposal': proposal, 'message': message, 'actor': actor}


@pytest.mark.parametrize('method,path,body', [
    ('patch', '/projects/SOS', {'name': 'Changed'}),
    ('delete', '/projects/SOS', None),
    ('post', '/projects/SOS/items', {'title': 'New ticket'}),
    ('patch', '/items/SOS-1', {'title': 'Changed'}),
    ('post', '/items/SOS-1/comments', {'body_md': 'New comment'}),
    ('post', '/items/SOS-1/move', {'project': 'LIVE'}),
    ('post', '/items/LIVE-1/move', {'project': 'SOS'}),
    ('post', '/items/LIVE-1/relations', {'type': 'relates_to', 'target': 'SOS-1'}),
    ('delete', '/items/SOS-1', None),
    ('post', '/items/SOS-1/restore', None),
    ('post', '/items/SOS-1/lock', None),
    ('post', '/items/SOS-1/unlock', {'headroom': 5}),
    ('post', '/items/SOS-1/guardrail', {'guardrail_md': 'Changed'}),
    ('post', '/items/SOS-1/labels/example', None),
    ('delete', '/items/SOS-1/labels/example', None),
    ('post', '/projects/SOS/states', {'name': 'extra', 'group': 'started'}),
    ('patch', '/projects/SOS/states/todo', {'name': 'Changed'}),
    ('delete', '/projects/SOS/states/todo', None),
    ('post', '/projects/SOS/labels', {'name': 'Changed'}),
    ('delete', '/projects/SOS/labels/example', None),
    ('post', '/projects/SOS/milestones', {'name': 'Changed'}),
    ('patch', '/projects/SOS/milestones/Example milestone', {'status': 'completed'}),
    ('put', '/projects/SOS/triage', {'enabled': True}),
    ('post', '/projects/SOS/triage/backfill', None),
    ('put', '/projects/SOS/wiki-compile', {'enabled': True}),
    ('post', '/projects/SOS/wiki-compile/backfill', None),
    ('post', '/projects/SOS/wiki', {'slug': 'new', 'title': 'New'}),
    ('patch', '/projects/SOS/wiki/guide', {'body_md': 'Changed'}),
    ('delete', '/projects/SOS/wiki/guide', None),
    ('put', '/wiki-protection', {'project': 'SOS', 'slug': 'guide', 'protected': True}),
    ('post', '/projects/SOS/triage-chat', {'message': 'Change it'}),
    ('post', '/projects/SOS/triage-chat/archive', None),
    ('post', '/items/SOS-1/enrich', None),
    ('post', '/items/SOS-1/decompose', None),
    ('post', '/items/SOS-1/decompose/apply', {'subtasks': []}),
])
def test_api_rejects_project_writes(client, auth, conn, frozen, method, path, body):
    before = dict(items.get_by_ref(conn, 'SOS-1'))
    response = client.request(method, '/api/v1' + path, json=body, headers=auth)
    assert response.status_code == 409, response.text
    assert response.json()['error_code'] == 'project_archived_readonly'
    assert dict(items.get_by_ref(conn, 'SOS-1')) == before


def test_comment_question_review_and_upload_paths(client, auth, conn, frozen, tmp_path):
    cid, qid = frozen['comment']['id'], frozen['question']['id']
    for method, path, body in [
        ('patch', f'/items/SOS-1/comments/{cid}', {'body_md': 'Changed'}),
        ('delete', f'/items/SOS-1/comments/{cid}', None),
        ('post', f'/comments/{qid}/answer', {'text': 'Changed'}),
        ('post', f'/comments/{qid}/withdraw', {'reason': 'Changed'}),
        ('patch', f'/comments/{qid}/answer', {'text': 'Changed'}),
        ('post', f"/wiki-proposals/{frozen['proposal']['proposal_id']}/review", {'approve': True}),
        ('post', f"/triage-chat/{frozen['message']['id']}/confirm", None),
    ]:
        response = client.request(method, '/api/v1' + path, json=body, headers=auth)
        assert response.status_code == 409, response.text
        assert response.json()['error_code'] == 'project_archived_readonly'
    response = client.post('/api/v1/items/SOS-1/attachments', files={'file': ('example.txt', b'Synthetic content', 'text/plain')}, headers=auth)
    assert response.status_code == 409
    assert client.get('/api/v1/items/SOS-1/attachments', headers=auth).json() == []


@pytest.mark.parametrize('path', [
    '/items/SOS-1', '/items/SOS-1/plan', '/items/SOS-1/activity',
    '/items/SOS-1/attachments', '/projects/SOS/items', '/projects/SOS/states',
    '/projects/SOS/wiki', '/projects/SOS/wiki/guide', '/projects/SOS/triage-chat',
])
def test_archived_content_remains_readable(client, auth, frozen, path):
    assert client.get('/api/v1' + path, headers=auth).status_code == 200


def test_reading_an_empty_archived_chat_does_not_create_a_session(client, auth, conn, project):
    assert client.delete('/api/v1/projects/SOS', headers=auth).status_code == 204
    result = client.get('/api/v1/projects/SOS/triage-chat', headers=auth)
    assert result.status_code == 200
    assert result.json()['messages'] == []
    assert result.json()['session_id'] is None
    assert conn.execute('SELECT COUNT(*) FROM triage_chat_sessions').fetchone()[0] == 0


def test_restore_reenables_content_writes_and_personal_reads_work(client, auth, frozen):
    assert client.post('/api/v1/items/SOS-1/read', headers=auth).status_code == 200
    assert client.post('/api/v1/projects/SOS/restore', headers=auth).status_code == 200
    assert client.patch('/api/v1/items/SOS-1', json={'title': 'Changed after restore'}, headers=auth).status_code == 200
    assert client.post('/api/v1/projects/SOS/items', json={'title': 'New after restore'}, headers=auth).status_code == 201
    assert client.patch('/api/v1/projects/SOS/wiki/guide', json={'body_md': 'Changed after restore'}, headers=auth).status_code == 200


def test_database_guard_rejects_stale_writers_and_rolls_back_whole_transaction(conn, frozen):
    for sql, params in [
        ('UPDATE items SET title = ? WHERE id = ?', ('Changed', frozen['item']['id'])),
        ('UPDATE items SET project_id = ? WHERE id = ?', (frozen['pid'], frozen['live']['id'])),
        ('DELETE FROM comments WHERE id = ?', (frozen['comment']['id'],)),
        ('UPDATE projects SET archived_at = NULL, name = ? WHERE id = ?', ('Changed', frozen['pid'])),
    ]:
        with pytest.raises(sqlite3.IntegrityError, match='archived_project_readonly'):
            with db.transaction(conn):
                conn.execute('UPDATE items SET title = ? WHERE id = ?', ('Must roll back', frozen['live']['id']))
                conn.execute(sql, params)
        assert items.get_by_ref(conn, 'LIVE-1')['title'] == 'Active ticket'
    assert projects.is_archived(conn, frozen['pid'])


def test_chat_commands_refuse_archived_targets(conn, frozen):
    command = triage_commands.Command(verb='set_priority', project_id=frozen['pid'], selector={'refs': ['SOS-1']}, params={'priority': 'high'})
    assert triage_commands.validate(conn, command)
    with pytest.raises(sqlite3.IntegrityError, match='archived_project_readonly'):
        triage_commands.execute(conn, command, frozen['actor'], fanout=False)


class NoExternalCalls:
    def complete(self, messages):
        raise AssertionError('Archived work must not call an AI provider')


def test_archived_items_do_not_start_background_work(conn, frozen):
    assert frozen['item']['id'] not in wiki_compiler.find_uncompiled(conn, debounce_seconds=0, limit=100)
    assert frozen['item']['id'] not in triage_worker.find_untriaged(conn, debounce_seconds=0, limit=100)
    wiki_compiler.compile_once(conn, frozen['item']['id'], NoExternalCalls(), actor_id=frozen['actor'])
    triage_worker.triage_once(conn, frozen['item']['id'], NoExternalCalls(), None, triage_user_id=frozen['actor'])
    assert items.get_by_ref(conn, 'SOS-1')['wiki_compiled_at'] is None
    assert wiki_compiler._record_failure(conn, frozen['item']['id']) == 0
    assert triage_worker._record_failure(conn, table='items', attempts_col='triage_attempts', error_col='triage_error_at', row_id=frozen['item']['id']) == 0


def test_archive_during_compilation_rolls_back_result_and_does_not_quarantine(conn, client, auth, frozen):
    import json

    assert client.post('/api/v1/projects/SOS/restore', headers=auth).status_code == 200

    class ArchiveDuringCall:
        def complete(self, messages):
            projects.archive(conn, frozen['pid'])
            return json.dumps({'skip': False, 'pages': [{'slug': 'late', 'title': 'Late page', 'body_md': 'Must not persist'}]})

    with pytest.raises(sqlite3.IntegrityError, match='archived_project_readonly'):
        wiki_compiler.compile_once(conn, frozen['item']['id'], ArchiveDuringCall(), actor_id=frozen['actor'])
    assert wiki.get_by_slug(conn, frozen['pid'], 'late') is None
    assert items.get_by_ref(conn, 'SOS-1')['wiki_compiled_at'] is None
    assert wiki_compiler._record_failure(conn, frozen['item']['id']) == 0
    assert items.get_by_ref(conn, 'SOS-1')['wiki_compile_attempts'] == 0


@pytest.mark.parametrize('ref', ['SOS-999', 'SOS-invalid'])
def test_unknown_item_in_an_archived_project_keeps_its_not_found_response(client, auth, frozen, ref):
    response = client.patch(f'/api/v1/items/{ref}', json={'title': 'Unknown'}, headers=auth)
    assert response.status_code == 404


def test_archive_guard_accepts_zero_padded_existing_refs(client, auth, frozen):
    response = client.patch('/api/v1/items/SOS-0001', json={'title': 'Changed'}, headers=auth)
    assert response.status_code == 409
    assert response.json()['error_code'] == 'project_archived_readonly'
