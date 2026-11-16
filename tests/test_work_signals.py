"""Factual next-action metadata for the board and item detail."""
from conftest import _create
from betonning.repo import items, users


def test_work_signals_questions_blockers_and_closed(client, auth, project, conn):
    task = _create(client, auth, project, title='Waiting task').json()
    blocker = _create(client, auth, project, title='Prerequisite').json()
    response = client.post(f"/api/v1/items/{task['ref']}/relations", headers=auth,
                           json={'type': 'blocked_by', 'target': blocker['ref']})
    assert response.status_code in (200, 201), response.text
    user = users.get_by_handle(conn, 'person')
    row = items.get_by_ref(conn, task['ref'])
    from betonning.repo import comments
    comments.create(conn, item_id=row['id'], author_id=user['id'], body_md='@person Which option?', kind='question')
    conn.commit()
    signals = items.work_signals_bulk(conn, [row['id']], user['id'])[row['id']]
    assert signals['blocked_by'] == [blocker['ref']]
    assert signals['question_for_viewer']
    other, _ = users.create(conn, handle='observer', display_name='Observer', kind='human')
    assert not items.work_signals_bulk(conn, [row['id']], other['id'])[row['id']]['question_for_viewer']
    assert not items.work_signals_bulk(conn, [row['id']])[row['id']]['question_for_viewer']
    client.patch(f"/api/v1/items/{blocker['ref']}", headers=auth, json={'state':'done'})
    assert items.work_signals_bulk(conn, [row['id']], user['id'])[row['id']]['blocked_by'] == []
    detail = client.get(f"/api/v1/items/{task['ref']}", headers=auth).json()
    listing = client.get(f'/api/v1/projects/{project}/items', headers=auth).json()
    assert next(i for i in listing if i['ref']==task['ref'])['work_signals'] == detail['work_signals']
    assert next(i for i in listing if i['ref']==blocker['ref'])['work_signals']['closed']


def test_work_signals_are_batched_and_expose_no_execution_credentials(client, auth, project, conn):
    task = _create(client, auth, project, title='Managed task').json()
    row = items.get_by_ref(conn, task['ref'])
    agent, _ = users.create(conn, handle='executor', display_name='Executor', kind='agent')
    conn.execute("INSERT INTO execution_requests(id,item_id,user_id,profile,binding_generation,intent_event_id,revision,status,reason,responsible,resume_condition) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 ('fixture-request',row['id'],agent['id'],'fixture',1,0,'revision','blocked','Missing tool','person','Enable capability'))
    conn.commit()
    seen=[]
    conn.set_trace_callback(seen.append)
    data=items.work_signals_bulk(conn,[row['id']]*20)
    conn.set_trace_callback(None)
    assert len([q for q in seen if q.startswith('SELECT')]) == 2
    assert data[row['id']]['execution'] == {'status':'blocked','reason':'Missing tool','responsible':'person','resume_condition':'Enable capability'}
