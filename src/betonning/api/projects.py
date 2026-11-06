"""Projects-endpoints: projecten, states en de gefilterde items-lijst."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import current_human, current_user, get_db, require_project
from ..models import (
    AccessLevelUpdate,
    ItemCreate,
    LabelCreate,
    LabelUpdate,
    MilestoneCreate,
    MilestoneUpdate,
    ProjectCreate,
    ProjectUpdate,
    StateCreate,
    StateUpdate,
    TriageOptIn,
)
from ..repo import access
from ..repo import events as events_repo
from ..repo import items as items_repo
from ..repo import labels as labels_repo
from ..repo import milestones as milestones_repo
from ..repo import overview as overview_repo
from ..repo import projects as projects_repo
from ..repo import states as states_repo
from ..repo import users as users_repo
from .. import credential_policy
from .. import db as db_module
from .. import mentions as mentions_mod
from .. import webhooks
from .items import _resolve_label_id, _resolve_state_id, resolve_item_fields

from ..repo import model_classes as model_classes_repo

router = APIRouter(tags=["projects"])


@router.get("/projects")
def list_projects(
    archived: bool = False,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    rows = projects_repo.list_all(conn, include_archived=archived)
    # Laatste activiteit per project (BETON-475), voor de "Stille projecten" in
    # de kiezer; dezelfde gegroepeerde query als het Overzicht, dus constant in
    # het aantal projecten.
    allowed = credential_policy.projects(user)
    if allowed is not None:
        rows = [row for row in rows if row["key"] in allowed]
    activity = overview_repo.last_activity(conn)
    for r in rows:
        r["last_activity_at"] = activity.get(r["id"])
    return rows


@router.post("/projects", status_code=201)
def create_project(
    body: ProjectCreate,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    if projects_repo.get_by_key(conn, body.key) is not None:
        raise HTTPException(status_code=409, detail=f"Project bestaat al: {body.key}")
    with db_module.transaction(conn):
        return projects_repo.create(
            conn, key=body.key, name=body.name, description=body.description
        )


@router.patch("/projects/{key}")
def update_project(
    key: str,
    body: ProjectUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    """Werk naam/omschrijving van een project bij (BETON-26)."""
    project = require_project(conn, key)
    with db_module.transaction(conn):
        projects_repo.update(conn, project["id"], body.model_dump(exclude_unset=True))
    return projects_repo.serialize(require_project(conn, key))


# BETON-482: archiveren en herstellen zijn mens-only. Archiveren haalt het
# project uit alle sweeps (BETON-413), inclusief triage; dat beslist een mens.
@router.delete("/projects/{key}", status_code=204)
def archive_project(
    key: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> None:
    project = require_project(conn, key)
    with db_module.transaction(conn):
        projects_repo.archive(conn, project["id"])


@router.post("/projects/{key}/restore")
def restore_project(
    key: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    project = require_project(conn, key)
    with db_module.transaction(conn):
        projects_repo.restore(conn, project["id"])
    return projects_repo.serialize(require_project(conn, key))


@router.put("/projects/{key}/triage")
def set_triage_optin(
    key: str,
    body: TriageOptIn,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    """Zet de per-project triage-opt-in aan/uit (fase 3, BETON-22)."""
    project = require_project(conn, key)
    with db_module.transaction(conn):
        projects_repo.set_triage_enabled(conn, project["id"], body.enabled)
    return projects_repo.serialize(require_project(conn, key))


@router.post("/projects/{key}/triage/backfill")
def backfill_triage(
    key: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    """Plan de bestaande items van een (opt-in) project opnieuw voor triage in.

    De triage-loop pikt ze daarna in zijn eigen tempo op (debounce/interval =
    rate-limit). Vereist dat het project opt-in heeft (anders 400)."""
    project = require_project(conn, key)
    if not project["triage_enabled"]:
        raise HTTPException(
            status_code=400,
            detail="Triage staat uit voor dit project; zet eerst opt-in aan.",
        )
    with db_module.transaction(conn):
        queued = projects_repo.backfill_untriage(conn, project["id"])
    return {"queued": queued}


@router.put("/projects/{key}/wiki-compile")
def set_wiki_compile_optin(
    key: str,
    body: TriageOptIn,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    """Zet de per-project wiki-compiler-opt-in aan/uit (BETON-24)."""
    project = require_project(conn, key)
    with db_module.transaction(conn):
        projects_repo.set_wiki_compile_enabled(conn, project["id"], body.enabled)
    return projects_repo.serialize(require_project(conn, key))


@router.post("/projects/{key}/wiki-compile/backfill")
def backfill_wiki_compile(
    key: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    """Plan de afgeronde items van een (opt-in) project opnieuw voor wiki-compilatie
    in. De compile-loop pikt ze in zijn eigen tempo op. Vereist opt-in (anders 400)."""
    project = require_project(conn, key)
    if not project["wiki_compile_enabled"]:
        raise HTTPException(
            status_code=400,
            detail="Wiki-compiler staat uit voor dit project; zet eerst opt-in aan.",
        )
    with db_module.transaction(conn):
        queued = projects_repo.backfill_uncompiled(conn, project["id"])
    return {"queued": queued}


@router.get("/projects/{key}/access")
def get_access(
    key: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    """Per-project agent-toegang: per-type defaults + per-agent overrides met het
    effectieve niveau (BETON-123)."""
    project = require_project(conn, key)
    return access.list_access(conn, project["id"])


@router.put("/projects/{key}/access/type/{agent_type}")
def set_type_access(
    key: str,
    agent_type: str,
    body: AccessLevelUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    """Zet (of wis met level=null) de default voor een agent-type op dit project.
    Mens-only: anders zet een agent zijn eigen grens op `assign`."""
    project = require_project(conn, key)
    if agent_type not in ("coding", "hermes"):
        raise HTTPException(
            status_code=422, detail=f"Onbekend agent-type: {agent_type}"
        )
    with db_module.transaction(conn):
        access.set_type_access(conn, project["id"], agent_type, body.level)
    return access.list_access(conn, project["id"])


@router.put("/projects/{key}/access/agent/{handle}")
def set_agent_access(
    key: str,
    handle: str,
    body: AccessLevelUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    """Zet (of wis met level=null → inherit) de override voor één agent op dit
    project. Mens-only, net als de type-default."""
    project = require_project(conn, key)
    user = users_repo.get_by_handle(conn, handle)
    if user is None or user["kind"] != "agent":
        raise HTTPException(status_code=404, detail=f"Onbekende agent: {handle}")
    with db_module.transaction(conn):
        access.set_agent_access(conn, project["id"], user["id"], body.level)
    return access.list_access(conn, project["id"])


@router.get("/projects/{key}/states")
def list_states(
    key: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    project = require_project(conn, key)
    return states_repo.list_for_project(conn, project["id"])


@router.post("/projects/{key}/states", status_code=201)
def create_state(
    key: str,
    body: StateCreate,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    project = require_project(conn, key)
    if states_repo.get_by_name(conn, project["id"], body.name) is not None:
        raise HTTPException(status_code=409, detail=f"State bestaat al: {body.name}")
    return states_repo.create(
        conn,
        project_id=project["id"],
        name=body.name,
        group=body.group,
        color=body.color,
        sort_order=body.sort_order,
        is_default=body.is_default,
        closed=body.closed,
        blocks_work=body.blocks_work,
    )


@router.patch("/projects/{key}/states/{name}")
def update_state(
    key: str,
    name: str,
    body: StateUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    """Werk metadata (naam/kleur/volgorde/uitvoeringsbeleid) van een bestaande
    state bij (BETON-177). Hernoemen is veilig — items refereren via state_id —
    maar de nieuwe naam moet uniek zijn binnen het project (anders 409)."""
    project = require_project(conn, key)
    state = states_repo.get_by_name(conn, project["id"], name)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Onbekende state: {name}")
    fields = body.model_dump(exclude_unset=True)
    new_name = fields.get("name")
    if new_name is not None and new_name.strip().lower() != state["name"].lower():
        if states_repo.get_by_name(conn, project["id"], new_name) is not None:
            raise HTTPException(status_code=409, detail=f"State bestaat al: {new_name}")
    return states_repo.update(conn, state["id"], fields)


@router.delete("/projects/{key}/states/{name}", status_code=204)
def delete_state(
    key: str,
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> None:
    """Verwijder een state (kolom) uit een project (BETON-351).

    Twee guards vóór de DELETE: de laatste kolom van een project mag niet weg
    (een project zonder states kan geen items plaatsen), en een kolom met nog
    items erin mag niet weg (anders wordt zo'n item onzichtbaar — state_id
    zonder rij). Verplaats de items eerst naar een andere kolom."""
    project = require_project(conn, key)
    state = states_repo.get_by_name(conn, project["id"], name)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Onbekende state: {name}")
    remaining = states_repo.list_for_project(conn, project["id"])
    if len(remaining) <= 1:
        raise HTTPException(
            status_code=409, detail="Laatste kolom van een project kan niet verwijderd worden"
        )
    item_count = states_repo.count_items(conn, state["id"])
    if item_count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Kolom '{name}' bevat nog {item_count} item(s) — "
                "verplaats ze eerst naar een andere kolom"
            ),
        )
    with db_module.transaction(conn):
        states_repo.delete(conn, state["id"])


@router.get("/projects/{key}/labels")
def list_labels(
    key: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    project = require_project(conn, key)
    return labels_repo.list_for_project(conn, project["id"])


@router.post("/projects/{key}/labels", status_code=201)
def create_label(
    key: str,
    body: LabelCreate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    if user["kind"] == "agent" and body.name.strip().lower() in model_classes_repo.LEGACY_LABELS:
        raise HTTPException(422, "Gebruik een werkklasse: routine, standaard of complex; geen modelnaam als label")
    project = require_project(conn, key)
    if labels_repo.get_by_name(conn, project["id"], body.name) is not None:
        raise HTTPException(status_code=409, detail=f"Label bestaat al: {body.name}")
    return labels_repo.create(
        conn, project_id=project["id"], name=body.name, color=body.color
    )


# `:path` — labelnamen mogen een `/` bevatten (`Kind/Bug`, BETON-449).
@router.patch("/projects/{key}/labels/{name:path}")
def update_label(
    key: str,
    name: str,
    body: LabelUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    """Label-kleur wijzigen (BETON-461). Alleen `color`; hernoemen niet."""
    project = require_project(conn, key)
    label = labels_repo.get_by_name(conn, project["id"], name)
    if label is None:
        raise HTTPException(status_code=404, detail=f"Onbekend label: {name}")
    with db_module.transaction(conn):
        return labels_repo.set_color(conn, label["id"], body.color)


@router.delete("/projects/{key}/labels/{name:path}", status_code=204)
def delete_label(
    key: str,
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> None:
    project = require_project(conn, key)
    label = labels_repo.get_by_name(conn, project["id"], name)
    if label is None:
        raise HTTPException(status_code=404, detail=f"Onbekend label: {name}")
    labels_repo.delete(conn, label["id"])


@router.get("/projects/{key}/milestones")
def list_milestones(
    key: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    project = require_project(conn, key)
    return milestones_repo.list_for_project(conn, project["id"])


@router.post("/projects/{key}/milestones", status_code=201)
def create_milestone(
    key: str,
    body: MilestoneCreate,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    project = require_project(conn, key)
    if milestones_repo.get_by_name(conn, project["id"], body.name) is not None:
        raise HTTPException(
            status_code=409, detail=f"Milestone bestaat al: {body.name}"
        )
    return milestones_repo.create(
        conn, project_id=project["id"], name=body.name, due_date=body.due_date
    )


@router.patch("/projects/{key}/milestones/{name}")
def update_milestone(
    key: str,
    name: str,
    body: MilestoneUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    project = require_project(conn, key)
    ms = milestones_repo.get_by_name(conn, project["id"], name)
    if ms is None:
        raise HTTPException(status_code=404, detail=f"Onbekende milestone: {name}")
    return milestones_repo.update(conn, ms["id"], body.model_dump(exclude_unset=True))


@router.delete("/projects/{key}/milestones/{name}", status_code=204)
def delete_milestone(
    key: str,
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> None:
    project = require_project(conn, key)
    ms = milestones_repo.get_by_name(conn, project["id"], name)
    if ms is None:
        raise HTTPException(status_code=404, detail=f"Onbekende milestone: {name}")
    with db_module.transaction(conn):
        milestones_repo.delete(conn, ms["id"])


@router.get("/projects/{key}/items")
def list_items(
    key: str,
    state: str | None = None,
    priority: str | None = None,
    workload: str | None = None,
    label: str | None = None,
    assignee: str | None = None,
    milestone: str | None = None,
    q: str | None = None,
    due_before: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int | None = Query(default=None, ge=0),
    # BETON-359: default None = ongewijzigd gedrag — élke bestaande aanroeper
    # (UI zonder dit query-param, MCP list_items, rechtstreekse REST-clients)
    # krijgt precies wat hij al kreeg. Alleen de UI-board-fetch stuurt dit mee.
    closed_limit: int | None = Query(default=None, ge=1, le=500),
    archived: bool = False,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    project = require_project(conn, key)
    return items_repo.list_items(
        conn,
        project["id"],
        # BETON-294: has_unread is per user; gebatcht in _compact_rows (geen N+1).
        viewer_id=user["id"],
        state=state,
        priority=priority,
        workload=workload,
        label=label,
        assignee=assignee,
        milestone=milestone,
        q=q,
        due_before=due_before,
        limit=limit,
        offset=offset,
        closed_limit=closed_limit,
        include_archived=archived,
    )


@router.get("/projects/{key}/state-counts")
def state_counts(
    key: str,
    archived: bool = False,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict[str, int]:
    """Aantal items per state-naam (BETON-359) — de UI vergelijkt dit met wat
    een begrensde (`closed_limit`) kolom daadwerkelijk ophaalde om te weten of
    er een "toon meer" nodig is."""
    project = require_project(conn, key)
    return items_repo.state_counts(conn, project["id"], include_archived=archived)


@router.post("/projects/{key}/items", status_code=201)
def create_item(
    key: str,
    body: ItemCreate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    project = require_project(conn, key)
    resolved = resolve_item_fields(
        conn,
        project,
        state=body.state,
        assignee=body.assignee,
        parent=body.parent,
        milestone=body.milestone,
    )
    # BETON-212: een uitsteldatum bij aanmaken plaatst het item meteen in de
    # deferred-state (spiegelt de PATCH-flip in api/items.py) — anders staat het
    # met een toekomstige deferred_until nog in de actieve kolom. Een expliciet
    # meegegeven state wint (dan geen impliciete flip).
    if body.deferred_until and not body.state:
        resolved["state_id"] = _resolve_state_id(conn, project, "deferred")
    label_ids = [_resolve_label_id(conn, project, name) for name in body.labels]
    with db_module.transaction(conn):
        row = items_repo.create(
            conn,
            project_id=project["id"],
            title=body.title,
            description_md=body.description_md,
            priority=body.priority,
            workload=body.workload,
            created_by=user["id"],
            due_date=body.due_date or None,
            deferred_until=body.deferred_until or None,
            plan_md=body.plan_md or None,
            **resolved,
        )
        if label_ids:
            labels_repo.set_for_item(conn, row["id"], label_ids)
        data = items_repo.serialize(conn, row)
        payload = {"ref": data["ref"], "title": data["title"]}
        if body.plan_md:
            # BETON-430: net als bij PATCH alleen een marker, nooit de inhoud
            # (het plan kan groot zijn; events/webhooks blijven klein).
            payload["plan_md"] = {"changed": True, "cleared": False}
        event = events_repo.record(
            conn,
            type="item.created",
            item_id=row["id"],
            actor_id=user["id"],
            payload=payload,
        )
        webhooks.fanout(
            conn, event=event, mentions=mentions_mod.parse(body.description_md)
        )
    return data


@router.get("/projects/{key}/activity")
def project_activity(
    key: str,
    since: int | None = None,
    actor: str | None = None,
    type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    """Activiteitenfeed voor één project (BETON-372): events van al zijn items,
    nieuwste eerst. Spiegelt `GET /items/{ref}/activity` (`events_repo.serialize`)
    maar dan gebatcht over meerdere items — vandaar `serialize_bulk` i.p.v. een
    `serialize()`-call per event."""
    project = require_project(conn, key)
    actor_id = None
    if actor is not None:
        actor_row = users_repo.get_by_handle(conn, actor)
        if actor_row is None:
            raise HTTPException(status_code=404, detail=f"Onbekende user: {actor}")
        actor_id = actor_row["id"]
    types = [type] if type else None
    rows = events_repo.list_for_project(
        conn,
        project["id"],
        project["key"],
        since_id=since,
        actor_id=actor_id,
        types=types,
        limit=limit,
    )
    return events_repo.serialize_bulk(conn, rows)
