"""Mensgebonden installatieconfiguratie; credentials komen nooit terug."""
from __future__ import annotations

import sqlite3
import copy
import math
import time
from typing import Literal


from fastapi import APIRouter, Depends, HTTPException, Response, Request
from pydantic import ValidationError

from .. import credential_policy, db, installation_runtime
from ..deps import current_human, get_db, llm_rate_limited
from ..installation_config import (
    InstallationUpdate, SettingsSecretError, merge_patch, public_settings, settings_cipher,
)
from ..repo import events, users
from ..repo import installation_settings as store

router = APIRouter(tags=['settings'])


def installation_admin(user: sqlite3.Row = Depends(current_human)):
    if 'admin' not in credential_policy.scopes(user):
        raise HTTPException(403, 'Deze sleutel mist beheerscope')
    return user


def runtime_view(request, row):
    result = public_settings(row)
    snapshot = getattr(request.app.state, 'installation_runtime', None)
    if snapshot is not None:
        result['runtime'] = {'revision': snapshot.revision, 'providers': snapshot.status, 'overrides': snapshot.overrides,
                             'triage_enabled': snapshot.triage, 'wiki_compile_enabled': snapshot.wiki}
    return result


@router.get('/settings/installation')
def get_installation(request: Request, response: Response, conn=Depends(get_db), _=Depends(installation_admin)):
    response.headers['Cache-Control'] = 'no-store'
    return runtime_view(request, store.get(conn))


@router.patch('/settings/installation')
def update_installation(body: InstallationUpdate, request: Request, response: Response, conn=Depends(get_db), user=Depends(installation_admin)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        with db.transaction(conn):
            old = store.get(conn)
            revision = old['revision'] if old else 0
            if body.expected_revision != revision:
                raise HTTPException(409, 'Installatie-instellingen zijn intussen gewijzigd; laad ze opnieuw')
            settings, key_updates, changed = merge_patch(old['settings'] if old else {}, body.settings)
            keys = {'llm': old['llm_key'] if old else None, 'embedding': old['embedding_key'] if old else None}
            for provider, key in key_updates.items():
                keys[provider] = settings_cipher().encrypt(key.encode()) if key else None
            if not changed:
                return runtime_view(request, old)
            result = store.replace(conn, settings=settings, llm_key=keys['llm'], embedding_key=keys['embedding'],
                                   revision=revision + 1, actor_id=user['id'])
            prepared = installation_runtime.prepare(request.app, result)
            if prepared.llm is not None and (prepared.triage or prepared.wiki):
                actor = users.get_by_handle(conn, 'triage')
                if actor is None:
                    users.create(conn, handle='triage', display_name='Triage', kind='agent')
                elif actor['kind'] != 'agent' or not actor['active']:
                    raise HTTPException(422, 'De interne triage-agent is niet beschikbaar')
            events.record(conn, type='installation.settings.updated', actor_id=user['id'],
                          payload={'schema_version': 1, 'revision': revision + 1, 'fields': changed})
    except SettingsSecretError as exc:
        raise HTTPException(503, str(exc)) from None
    except ValidationError:
        # Een fout in samengevoegde velden mag geen invoerkeys in ctx/input kopiëren.
        raise HTTPException(422, 'Ongeldige installatie-instellingen') from None
    installation_runtime.publish(request.app, prepared)
    response.headers['Cache-Control'] = 'no-store'
    return runtime_view(request, result)


@router.post('/settings/installation/providers/{provider}/test', dependencies=[Depends(llm_rate_limited)])
def test_provider(provider: Literal['llm', 'embedding'], request: Request, response: Response,
                  user=Depends(installation_admin)):
    """Een bewuste, begrensde test met synthetische tekst; geen upstreamdata terug."""
    response.headers['Cache-Control'] = 'no-store'
    if 'llm' not in credential_policy.scopes(user):
        raise HTTPException(403, 'Deze sleutel mist de benodigde scope')
    snapshot = request.app.state.installation_runtime
    client = snapshot.llm if provider == 'llm' else snapshot.embedding
    if client is None:
        raise HTTPException(409, 'Bewaar en activeer eerst een volledige providerconfiguratie')
    client = copy.copy(client)
    if hasattr(client, '_timeout'):
        client._timeout = min(client._timeout, 10)
    if hasattr(client, '_max_output_tokens'):
        client._max_output_tokens = min(client._max_output_tokens, 128)
    started = time.monotonic()
    try:
        if provider == 'llm':
            result = client.complete([{'role': 'user', 'content': 'Hegemone connection test. Reply with OK.'}])
            valid = isinstance(result, str) and bool(result.strip())
        else:
            result = client.embed('Hegemone connection test')
            valid = isinstance(result, list) and bool(result) and all(type(value) in (int, float) and math.isfinite(value) for value in result)
        if not valid:
            raise ValueError('Ongeldig providerantwoord')
    except Exception:
        # Zelfs upstream-errors kunnen credentials of de hele response bevatten.
        raise HTTPException(502, 'Providertest mislukt; controleer endpoint, model en toegang') from None
    return {'provider': provider, 'ok': True, 'duration_ms': round((time.monotonic() - started) * 1000),
            'runtime_revision': snapshot.revision}
