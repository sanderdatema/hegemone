"""Scoped reply hints are independent for MCP sessions and inbox read markers."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx

from betonning import mcp_server
from test_mcp_server import isolated_mcp_configuration as isolated_mcp_configuration


class Session:
    pass


def test_mcp_notices_are_session_local_and_do_not_repeat(client,auth,project,monkeypatch):
    agent=client.post('/api/v1/users',headers=auth,json={'handle':'worker','display_name':'Worker'}).json()
    headers={'Authorization':f"Bearer {agent['api_key']}"}
    monkeypatch.setenv('BETONNING_API_KEY',agent['api_key'])
    monkeypatch.setattr(mcp_server,'_client',lambda key:httpx.AsyncClient(
        transport=httpx.ASGITransport(app=client.app),base_url='http://test',headers=headers))
    first=client.post('/api/v1/projects/SOS/items',headers=auth,json={'title':'First'}).json()['ref']
    second=client.post('/api/v1/projects/SOS/items',headers=auth,json={'title':'Second'}).json()['ref']
    server=mcp_server.build_server()
    contexts=[SimpleNamespace(session=Session()),SimpleNamespace(session=Session())]
    current=contexts[0]
    monkeypatch.setattr(server,'get_context',lambda:current)

    async def scenario():
        nonlocal current
        current=contexts[0]
        await server.call_tool('get_item',{'ref':first})
        current=contexts[1]
        await server.call_tool('get_item',{'ref':second})
        client.post(f'/api/v1/items/{first}/comments',headers=auth,json={'body_md':'Human reply'})
        client.post(f'/api/v1/items/{second}/comments',headers=auth,json={'body_md':'Other human reply'})
        current=contexts[0]
        content,data=await server.call_tool('list_projects',{})
        assert [value['ref'] for value in data['_session_updates']]==[first]
        assert first in content[-1].text and second not in content[-1].text
        assert data['result'][0]['key']=='SOS'
        _,again=await server.call_tool('list_projects',{})
        assert '_session_updates' not in again
        current=contexts[1]
        _,data=await server.call_tool('list_projects',{})
        assert [value['ref'] for value in data['_session_updates']]==[second]
        # Both sessions may watch the same ticket without consuming each other's hints.
        await server.call_tool('get_item',{'ref':first})
        client.post(f'/api/v1/items/{first}/comments',headers=auth,json={'body_md':'Another human reply'})
        for current in contexts:
            _,data=await server.call_tool('list_projects',{})
            assert [value['ref'] for value in data['_session_updates']]==[first]
    asyncio.run(scenario())


def test_reply_api_enforces_scope_ignores_agents_and_does_not_use_inbox_watermarks(client,auth,project):
    agent=client.post('/api/v1/users',headers=auth,json={'handle':'worker','display_name':'Worker'}).json()
    headers={'Authorization':f"Bearer {agent['api_key']}"}
    own=client.post('/api/v1/projects/SOS/items',headers=auth,json={'title':'Own'}).json()['ref']
    client.post('/api/v1/projects',headers=auth,json={'key':'OTHER','name':'Other'})
    other=client.post('/api/v1/projects/OTHER/items',headers=auth,json={'title':'Other'}).json()['ref']
    initial=client.get('/api/v1/me/session-updates',headers=headers,params={'cursors':json.dumps({own:None,other:None})}).json()
    client.post(f'/api/v1/items/{own}/comments',headers=auth,json={'body_md':'Human reply'})
    client.post(f'/api/v1/items/{other}/comments',headers=auth,json={'body_md':'Private other reply'})
    client.post(f'/api/v1/items/{own}/comments',headers=headers,json={'body_md':'Agent chatter'})
    latest=client.get(f'/api/v1/items/{own}',headers=headers).json()['last_event_id']
    client.post('/api/v1/inbox/seen',headers=headers,json={'event_id':latest})
    client.patch('/api/v1/users/worker',headers=auth,json={'api_key_scopes':['read'],'api_key_projects':['SOS']})
    result=client.get('/api/v1/me/session-updates',headers=headers,params={'cursors':json.dumps(initial['cursors'])})
    assert result.status_code==200
    data=result.json()
    assert [value['ref'] for value in data['updates']]==[own]
    assert data['updates'][0]['actor']=='person'
    assert other not in data['cursors'] and data['unavailable']==[other]
    assert client.get('/api/v1/me/session-updates',headers=headers,params={'cursors':json.dumps({own:True})}).status_code==422


def test_answer_to_a_session_question_is_noticed_on_a_later_tool(client,auth,project,monkeypatch):
    agent=client.post('/api/v1/users',headers=auth,json={'handle':'worker','display_name':'Worker'}).json()
    headers={'Authorization':f"Bearer {agent['api_key']}"}
    monkeypatch.setenv('BETONNING_API_KEY',agent['api_key'])
    monkeypatch.setattr(mcp_server,'_client',lambda key:httpx.AsyncClient(
        transport=httpx.ASGITransport(app=client.app),base_url='http://test',headers=headers))
    ref=client.post('/api/v1/projects/SOS/items',headers=auth,json={'title':'Question','assignee':'worker'}).json()['ref']
    server=mcp_server.build_server()
    ctx=SimpleNamespace(session=Session())
    monkeypatch.setattr(server,'get_context',lambda:ctx)

    async def scenario():
        result=await server.call_tool('ask_question',{'ref':ref,'question_md':'Which route, @person?'})
        question=json.loads(result[0].text)
        response=client.post(f"/api/v1/comments/{question['id']}/answer",headers=auth,json={'text':'Left'})
        assert response.status_code==200
        _,data=await server.call_tool('list_projects',{})
        assert data['_session_updates'][0]['ref']==ref
        assert data['_session_updates'][0]['kind']=='answer'
        assert data['_session_updates'][0]['actor']=='person'
    asyncio.run(scenario())
