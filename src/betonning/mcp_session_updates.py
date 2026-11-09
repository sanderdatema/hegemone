"""Session-local reply hints piggyback on successful MCP tool results.

No background task, ticket subscription rows or shared inbox read markers.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import weakref
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

MAX_WATCHED = 32


def _canonical(ref):
    if not isinstance(ref,str) or len(ref)>80:
        return None
    key,separator,seq = ref.strip().rpartition('-')
    return f'{key.upper()}-{int(seq)}' if separator and key and seq.isdecimal() else None


def _tool_data(result):
    if isinstance(result,tuple) and len(result)==2 and isinstance(result[1],dict):
        return result[1]
    content = result.content if isinstance(result,CallToolResult) else result
    if isinstance(content,list):
        for part in content:
            if isinstance(part,TextContent):
                try:
                    value=json.loads(part.text)
                    if isinstance(value,dict):
                        return value
                except ValueError:
                    continue
    return {}


@dataclass
class _Watch:
    cursors: OrderedDict[str, int | None] = field(default_factory=OrderedDict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def remember(self, ref, cursor=None):
        old = self.cursors.pop(ref, None)
        self.cursors[ref] = max(old or 0, cursor) if cursor is not None else old
        while len(self.cursors) > MAX_WATCHED:
            self.cursors.popitem(last=False)


class SessionUpdatesMCP(FastMCP):
    def __init__(self, *args, notification_client, notification_key, **kwargs):
        self._notification_client = notification_client
        self._notification_key = notification_key
        self._watches: weakref.WeakKeyDictionary[Any, tuple[bytes, _Watch]] = weakref.WeakKeyDictionary()
        super().__init__(*args, **kwargs)

    async def _poll(self, watch, key, only=None):
        if not watch.cursors:
            return None
        try:
            async with self._notification_client(key) as client:
                response = await client.get('/api/v1/me/session-updates',
                                            params={'cursors':json.dumps({only:watch.cursors[only]} if only else watch.cursors)})
                response.raise_for_status()
                data = response.json()
            for ref in data['unavailable']:
                watch.cursors.pop(ref,None)
            for ref,cursor in data['cursors'].items():
                if ref in watch.cursors:
                    watch.cursors[ref] = cursor
            return data if data.get('updates') else None
        except Exception:
            # Notification failure must not fail a successful primary operation.
            # Keep cursors so a later successful request can retry the read.
            return None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        ctx = self.get_context()
        try:
            session = ctx.session
        except (ValueError, LookupError):
            return await super().call_tool(name, arguments)
        key = self._notification_key(ctx)
        identity = hashlib.sha256(key.encode()).digest()
        existing = self._watches.get(session)
        if existing is None or existing[0] != identity:
            watch = _Watch()
            self._watches[session] = (identity, watch)
        else:
            watch = existing[1]
        # A first question may be answered before its result reaches the client.
        # Establish its baseline before asking, not after a possible answer.
        if name == 'ask_question' and _canonical(arguments.get('ref')) is not None:
            ref = _canonical(arguments['ref'])
            async with watch.lock:
                if ref not in watch.cursors:
                    watch.remember(ref)
                    await self._poll(watch,key,only=ref)
        result = await super().call_tool(name, arguments)
        if self._notification_key(ctx) != key:
            return result
        async with watch.lock:
            if name == 'get_item':
                item = _tool_data(result)
                if isinstance(item.get('ref'),str):
                    watch.remember(item['ref'], item.get('last_event_id'))
            notice = await self._poll(watch,key)
        if not notice:
            return result
        text = TextContent(type='text',text=notice['notice'])
        if isinstance(result,tuple) and len(result)==2 and isinstance(result[1],dict):
            content, structured = result
            return [*content,text], {**structured,'_session_updates':notice['updates'],'_session_notice':notice['notice']}
        if isinstance(result,CallToolResult):
            return result.model_copy(update={'content':[*result.content,text]})
        if isinstance(result,list):
            return [*result,text]
        return result
