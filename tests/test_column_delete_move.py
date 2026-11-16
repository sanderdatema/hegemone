"""Column removal preserves tickets and uses the ordinary update lifecycle."""
import pytest
from conftest import _create
from betonning import webhooks
from betonning.repo import users


def source(client, auth, project):
    response = client.post(f'/api/v1/projects/{project}/states',headers=auth,
                           json={'name':'Review','group':'started'})
    assert response.status_code == 201
    return f'/api/v1/projects/{project}/states/Review'


def test_moves_existing_tickets_and_preserves_identity_and_audit(client,auth,project):
    url=source(client,auth,project)
    task=_create(client,auth,project,title='A task',state='Review',plan_md='Keep the plan').json()
    result=client.delete(url,headers=auth,params={'target':'todo','expected_count':1})
    assert result.status_code == 204
    after=client.get(f"/api/v1/items/{task['ref']}",headers=auth).json()
    assert (after['id'],after['title'],after['state']) == (task['id'],'A task','todo')
    assert client.get(f"/api/v1/items/{task['ref']}/plan",headers=auth).json()['plan_md']=='Keep the plan'
    assert 'Review' not in [s['name'] for s in client.get(f'/api/v1/projects/{project}/states',headers=auth).json()]
    events=client.get(f"/api/v1/items/{task['ref']}/activity",headers=auth).json()
    update=next(e for e in events if e['type']=='item.updated')
    assert update['payload']['state']=={'from':'Review','to':'todo'}


@pytest.mark.parametrize('target',['Review','missing'])
def test_invalid_destination_leaves_tickets_and_column_unchanged(client,auth,project,target):
    url=source(client,auth,project)
    task=_create(client,auth,project,title='Keep it',state='Review').json()
    assert client.delete(url,headers=auth,params={'target':target}).status_code==422
    assert client.get(f"/api/v1/items/{task['ref']}",headers=auth).json()['state']=='Review'


def test_changed_count_requires_new_confirmation(client,auth,project):
    url=source(client,auth,project)
    _create(client,auth,project,title='New arrival',state='Review')
    response=client.delete(url,headers=auth,params={'target':'todo','expected_count':0})
    assert response.status_code==409 and response.json()['error_code']=='column_count_changed'
    assert any(s['name']=='Review' for s in client.get(f'/api/v1/projects/{project}/states',headers=auth).json())


def test_failure_rolls_back_every_ticket_and_event(client,auth,project,monkeypatch):
    url=source(client,auth,project)
    tasks=[_create(client,auth,project,title=f'Task {i}',state='Review').json() for i in range(2)]
    calls=0
    def fail_second(*args,**kwargs):
        nonlocal calls
        calls+=1
        if calls==2:
            raise RuntimeError('fixture rollback')
        return []
    monkeypatch.setattr(webhooks,'fanout',fail_second)
    with pytest.raises(RuntimeError,match='fixture rollback'):
        client.delete(url,headers=auth,params={'target':'todo','expected_count':2})
    for task in tasks:
        assert client.get(f"/api/v1/items/{task['ref']}",headers=auth).json()['state']=='Review'
        events=client.get(f"/api/v1/items/{task['ref']}/activity",headers=auth).json()
        assert not any(e['type']=='item.updated' for e in events)


def test_retargets_deferred_return_path(client,auth,project):
    url=source(client,auth,project)
    task=_create(client,auth,project,title='Deferred task',state='Review').json()
    assert client.patch(f"/api/v1/items/{task['ref']}",headers=auth,json={'deferred_until':'2099-01-01'}).status_code==200
    assert client.delete(url,headers=auth).status_code==409
    assert client.delete(url,headers=auth,params={'target':'todo','expected_count':0}).status_code==204
    restored=client.patch(f"/api/v1/items/{task['ref']}",headers=auth,json={'deferred_until':None})
    assert restored.status_code==200 and restored.json()['state']=='todo'


def test_preserves_archived_tickets_and_transfers_default(client,auth,project):
    task=_create(client,auth,project,title='Archived task',state='backlog').json()
    assert client.delete(f"/api/v1/items/{task['ref']}",headers=auth).status_code==204
    assert client.delete(f'/api/v1/projects/{project}/states/backlog',headers=auth,params={'target':'todo','expected_count':1}).status_code==204
    after=client.get(f"/api/v1/items/{task['ref']}",headers=auth).json()
    assert after['archived_at'] and after['state']=='todo'
    assert _create(client,auth,project,title='New default').json()['state']=='todo'


def test_agent_cannot_use_column_removal_to_bypass_item_gates(client,auth,project,conn):
    url=source(client,auth,project)
    _create(client,auth,project,title='Keep task',state='Review')
    _,key=users.create(conn,handle='worker',display_name='Worker',kind='agent')
    response=client.delete(url,headers={'Authorization':f'Bearer {key}'},params={'target':'todo'})
    assert response.status_code==403
