"""Portable, niet-geheime configuratie: allowlist, preview en toepassing."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .installation_config import InstallationSettings
from .config import raw_env
from .repo import configuration as repo, installation_settings, model_classes, project_template, projects, users

Text = Annotated[str, Field(min_length=1, max_length=100)]
Level = Literal['none', 'respond', 'assign']
AgentType = Literal['coding', 'hermes']


class Portable(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Agent(Portable):
    handle: str = Field(min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=100)
    agent_type: AgentType | None
    subscribe_all: bool

    @field_validator('handle')
    @classmethod
    def valid_handle(cls, value):
        value = users.validate_handle(value)
        if value == 'triage':
            raise ValueError('Interne agent kan niet worden geïmporteerd')
        return value


class Project(Portable):
    key: str = Field(pattern=r'^[A-Z0-9]{1,20}$')
    name: str = Field(min_length=1, max_length=300)
    triage_enabled: bool
    wiki_compile_enabled: bool
    type_defaults: dict[AgentType, Level]
    agent_overrides: dict[Annotated[str, Field(min_length=1, max_length=32)], Level] = Field(max_length=200)


class Column(Portable):
    name: Text
    group: Literal['backlog', 'unstarted', 'started', 'completed', 'cancelled']
    color: str = Field(pattern=r'^#[0-9a-fA-F]{6}$')
    is_default: bool
    closed: bool
    blocks_work: bool


class Document(Portable):
    format: Literal['hegemone.configuration']
    version: Literal[1]
    installation: InstallationSettings
    model_classes: dict[Text, dict[Literal['routine', 'standaard', 'complex'], Text]] = Field(max_length=200)
    project_template: list[Column] = Field(min_length=1, max_length=30)
    agents: list[Agent] = Field(max_length=200)
    projects: list[Project] = Field(max_length=200)

    @field_validator('version', mode='before')
    @classmethod
    def version_one(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError('Niet-ondersteunde configuratieversie')
        return value

    @model_validator(mode='after')
    def unique_names(self):
        for values in [[a.handle for a in self.agents], [p.key for p in self.projects], [s.name for s in self.project_template]]:
            if len(values) != len(set(values)):
                raise ValueError('Dubbele configuratie-identiteit')
        if sum(s.is_default for s in self.project_template) != 1:
            raise ValueError('Kies precies één standaardkolom')
        return self


def export_document(conn) -> dict:
    row = installation_settings.get(conn)
    project_data = []
    for project in projects.list_all(conn):
        types, agents = repo.project_access(conn, project['id'])
        project_data.append({key: project[key] for key in ['key', 'name', 'triage_enabled', 'wiki_compile_enabled']} | {'type_defaults': types, 'agent_overrides': agents})
    return Document.model_validate({
        'format': 'hegemone.configuration', 'version': 1,
        'installation': row['settings'] if row else {},
        'model_classes': model_classes.get_all(conn), 'project_template': project_template.get(conn),
        'agents': [{**agent, 'subscribe_all': bool(agent['subscribe_all'])} for agent in repo.agents(conn)],
        'projects': project_data,
    }).model_dump()


def plan(conn, document: Document) -> dict:
    current = export_document(conn)
    changes, conflicts, warnings = [], [], []
    def change(resource, identity, before, after):
        if before != after:
            changes.append({'resource': resource, 'identity': identity, 'action': 'create' if before is None else 'update', 'before': before, 'after': after})
    target = document.model_dump()
    for field in ['installation', 'model_classes', 'project_template']:
        change(field, field, current[field], target[field])
    stored = installation_settings.get(conn)
    for provider, column, prefix in [('llm', 'llm_key', 'LLM'), ('embedding', 'embedding_key', 'EMBED')]:
        has_key = bool((stored and stored[column]) or raw_env(f'BETONNING_{prefix}_API_KEY'))
        if has_key and target['installation'][provider]['base_url'] != current['installation'][provider]['base_url']:
            conflicts.append({'code': 'provider_endpoint_has_key', 'target': provider})
    roster = {a['handle']: a for a in current['agents']}
    for agent in document.agents:
        existing = users.get_by_handle(conn, agent.handle)
        if existing is not None and (existing['kind'] != 'agent' or existing['is_virtual']):
            conflicts.append({'code': 'identity_conflict', 'target': agent.handle})
        change('agent', agent.handle, roster.get(agent.handle), agent.model_dump())
        if existing is None:
            warnings.append({'code': 'new_agent_disabled', 'target': agent.handle})
    available = set(roster) | {a.handle for a in document.agents}
    current_projects = {p['key']: p for p in current['projects']}
    for project in document.projects:
        existing = projects.get_by_key(conn, project.key)
        if existing is not None and existing['archived_at']:
            conflicts.append({'code': 'archived_project', 'target': project.key})
        for handle in project.agent_overrides:
            if handle not in available:
                conflicts.append({'code': 'unknown_agent', 'target': handle})
        change('project', project.key, current_projects.get(project.key), project.model_dump())
    return {'can_apply': not conflicts, 'changes': changes, 'conflicts': conflicts, 'warnings': warnings}


def apply_document(conn, document: Document, actor_id: int) -> dict:
    """Alle writes vallen onder de transactie van de bevestigingsroute."""
    old = installation_settings.get(conn)
    result = installation_settings.replace(conn, settings=document.installation.model_dump(),
        llm_key=old['llm_key'] if old else None, embedding_key=old['embedding_key'] if old else None,
        revision=(old['revision'] if old else 0) + 1, actor_id=actor_id)
    model_classes.replace_all(conn, {agent: {str(work_class): model for work_class, model in models.items()}
        for agent, models in document.model_classes.items()})
    project_template.replace(conn, [column.model_dump() for column in document.project_template])
    for agent in document.agents:
        existing = users.get_by_handle(conn, agent.handle)
        if existing is None:
            created, _ = users.create(conn, handle=agent.handle, display_name=agent.display_name,
                kind='agent', agent_type=agent.agent_type, subscribe_all=agent.subscribe_all)
            users.admin_update(conn, created['id'], {'active': False})
        else:
            users.admin_update(conn, existing['id'], {'display_name': agent.display_name, 'agent_type': agent.agent_type})
            users.update_settings(conn, existing['id'], {'subscribe_all': agent.subscribe_all})
    for project in document.projects:
        project_row = projects.get_by_key(conn, project.key)
        if project_row is None:
            project_id = projects.create(conn, key=project.key, name=project.name)['id']
        else:
            project_id = project_row['id']
            projects.update(conn, project_id, {'name': project.name})
        projects.set_triage_enabled(conn, project_id, project.triage_enabled)
        projects.set_wiki_compile_enabled(conn, project_id, project.wiki_compile_enabled)
        repo.replace_access(conn, project_id, project.type_defaults, project.agent_overrides)
    return result
