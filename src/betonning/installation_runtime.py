"""Appgebonden runtime-snapshots en gecontroleerde wisseling van AI-workers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import threading

from . import config, llm, embeddings, ratelimit
from .installation_config import InstallationSettings, SettingsSecretError, decrypt_key


@dataclass(repr=False)
class Snapshot:
    revision: int
    values: dict = field(repr=False)
    llm: object = field(repr=False)
    embedding: object = field(repr=False)
    triage: bool
    wiki: bool
    status: dict
    overrides: list[str]


def truth(value):
    return str(value).lower() in {'1', 'true', 'yes', 'on'}


def prepare(app, row) -> Snapshot:
    """Bouw clients zonder netwerk; alleen publieke status komt in de API."""
    settings = InstallationSettings.model_validate(row['settings'] if row else {}).model_dump()
    values = {'BETONNING_AI_LANGUAGE': settings['ai_language'],
              'BETONNING_PUBLIC_URL': settings['public_url'], 'BETONNING_LANGUAGE': settings['language']}
    status = {}
    clients = {}
    for name, prefix, column, factory, injection in [
        ('llm', 'LLM', 'llm_key', llm.client_from_env, 'llm_client'),
        ('embedding', 'EMBED', 'embedding_key', embeddings.client_from_env, 'embed_client'),
    ]:
        provider = settings[name]
        base = f'BETONNING_{prefix}_'
        legacy = all(config.raw_env(base + suffix) for suffix in ['BASE_URL', 'API_KEY', 'MODEL'])
        configured_enabled = config.raw_env(base + 'ENABLED')
        enabled = truth(configured_enabled) if configured_enabled is not None else bool(legacy or provider['enabled'])
        overridden = [name for name, suffix in [('base_url', 'BASE_URL'), ('api_key', 'API_KEY'), ('model', 'MODEL'), ('timeout', 'TIMEOUT')]
                      if config.raw_env(base + suffix) is not None]
        if legacy or configured_enabled is not None:
            overridden.append('enabled')
        info = {'enabled': enabled, 'ready': False, 'overrides': overridden, 'error': None}
        values.update({base + 'BASE_URL': provider['base_url'], base + 'MODEL': provider['model'],
                       base + 'TIMEOUT': str(provider['timeout'])})
        if injection in app.state.runtime_overrides:
            clients[name] = app.state.runtime_overrides[injection]
            info.update(enabled=clients[name] is not None, ready=clients[name] is not None, source='injected')
        elif enabled:
            try:
                # Een expliciete envkey, ook leeg, mag geen opgeslagen key ontsleutelen.
                key = config.raw_env(base + 'API_KEY')
                if key is None:
                    key = decrypt_key(row[column] if row else None)
                values[base + 'API_KEY'] = key or ''
                with config.runtime_context(values):
                    clients[name] = factory()
                info.update(ready=clients[name] is not None, source='environment' if overridden else 'stored')
            except SettingsSecretError:
                clients[name] = None
                info.update(error='secret_unavailable', source='stored')
        else:
            clients[name] = None
            info['source'] = 'environment' if overridden else 'stored'
        status[name] = info
    flags = {}
    overrides = [name for name, variable in [("language", "LANGUAGE"), ("ai_language", "AI_LANGUAGE"), ("public_url", "PUBLIC_URL")]
                 if config.raw_env("BETONNING_" + variable) is not None]
    for name, variable, injected in [('triage', 'TRIAGE_ENABLED', 'enable_triage'), ('wiki', 'WIKI_COMPILE_ENABLED', 'enable_wiki_compile')]:
        setting = 'triage_enabled' if name == 'triage' else 'wiki_compile_enabled'
        value = config.raw_env('BETONNING_' + variable)
        flags[name] = app.state.runtime_overrides.get(injected, truth(value) if value is not None else settings[setting])
        if injected in app.state.runtime_overrides or value is not None:
            overrides.append(setting)
    return Snapshot(row['revision'] if row else 0, values, clients['llm'], clients['embedding'],
                    flags['triage'], flags['wiki'], status, overrides)


def publish(app, snapshot):
    with app.state.runtime_lock:
        old = getattr(app.state, 'installation_runtime', None)
        if old is not None and old.revision > snapshot.revision:
            return
        app.state.installation_runtime = snapshot
        app.state.llm_client = snapshot.llm
        app.state.embed_client = snapshot.embedding
        app.state.enable_triage = snapshot.triage
        app.state.enable_wiki_compile = snapshot.wiki
    loop = getattr(app.state, 'runtime_loop', None)
    if loop and loop.is_running():
        loop.call_soon_threadsafe(app.state.runtime_changed.set)


def initialize(app):
    app.state.runtime_lock = threading.RLock()


class RuntimeReconfigured(BaseException):
    """Interne batchonderbreking; telt niet als providerfout of quarantaine."""


class WorkerProvider:
    def __init__(self, app, snapshot, provider):
        self.app, self.snapshot, self.provider = app, snapshot, provider

    def _client(self):
        if self.app.state.installation_runtime is not self.snapshot:
            raise RuntimeReconfigured()
        return getattr(self.snapshot, self.provider)

    def complete(self, messages):
        return self._client().complete(messages)

    def embed(self, text):
        return self._client().embed(text)


async def supervise(app, stop):
    """Maximaal één worker per soort; geen cancel tijdens lopende writes/calls."""
    from . import triage_worker, wiki_compiler
    running: list[asyncio.Task[None]] = []
    local_stop = None
    current = None
    budget = ratelimit.DailyBudget(ratelimit.triage_daily_budget())

    async def guarded(coro, values):
        try:
            with config.runtime_context(values):
                await coro
        except RuntimeReconfigured:
            pass

    try:
        while not stop.is_set():
            snapshot = app.state.installation_runtime
            if snapshot is not current:
                if local_stop is not None:
                    local_stop.set()
                    for task in running:
                        await task
                if stop.is_set():
                    break
                current, running, local_stop = snapshot, [], asyncio.Event()
                provider = WorkerProvider(app, snapshot, 'llm')
                embedder = WorkerProvider(app, snapshot, 'embedding') if snapshot.embedding is not None else None
                if snapshot.llm is not None and snapshot.triage:
                    running.append(asyncio.create_task(guarded(triage_worker.triage_loop(
                        app.state.db_path, local_stop, provider, embedder,
                        debounce_seconds=app.state.triage_debounce,
                        interval_seconds=app.state.triage_interval, budget=budget), snapshot.values)))
                if snapshot.llm is not None and snapshot.wiki:
                    running.append(asyncio.create_task(guarded(wiki_compiler.wiki_compile_loop(
                        app.state.db_path, local_stop, provider,
                        debounce_seconds=app.state.wiki_compile_debounce,
                        interval_seconds=app.state.wiki_compile_interval), snapshot.values)))
            app.state.runtime_changed.clear()
            if app.state.installation_runtime is not current:
                continue
            try:
                await asyncio.wait_for(app.state.runtime_changed.wait(), timeout=0.25)
            except asyncio.TimeoutError:
                pass
    finally:
        if local_stop is not None:
            local_stop.set()
        for task in running:
            await task


class RuntimeContextMiddleware:
    def __init__(self, app, owner):
        self.app, self.owner = app, owner

    async def __call__(self, scope, receive, send):
        snapshot = getattr(self.owner.state, 'installation_runtime', None)
        if scope['type'] != 'http' or snapshot is None:
            return await self.app(scope, receive, send)
        scope.setdefault('state', {})['installation_runtime'] = snapshot
        with config.runtime_context(snapshot.values):
            await self.app(scope, receive, send)
