"""Globale instellingen (BETON-476): ``/settings/model-classes``.

Welk model hoort bij welke werkklasse (routine/standaard/complex) per harnas.
Alleen namen van modellen — geen secrets. Lezen mag iedereen, schrijven alleen
een mens.
"""

from __future__ import annotations

import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from .. import db as dbm
from ..deps import current_human, current_user, get_db
from ..repo import model_classes as mc
from ..repo import project_template
from ..models import StateCreate

router = APIRouter(tags=["settings"])


class ModelClassesUpdate(BaseModel):
    mapping: dict[str, dict[str, str]]


@router.get("/settings/model-classes")
def get_model_classes(
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    return {"classes": list(mc.CLASSES), "mapping": mc.get_all(conn)}


@router.put("/settings/model-classes")
def put_model_classes(
    body: ModelClassesUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    clean: dict[str, dict[str, str]] = {}
    for harness, classes in body.mapping.items():
        h = harness.strip().lower()
        if not h:
            raise HTTPException(422, "Leeg harnas")
        for cls, model in classes.items():
            if cls not in mc.CLASSES:
                raise HTTPException(422, f"Onbekende klasse: {cls}")
            m = model.strip()
            if not m or len(m) > 100:
                raise HTTPException(422, f"Ongeldig model voor {h}/{cls}")
            clean.setdefault(h, {})[cls] = m
    with dbm.transaction(conn):
        mc.replace_all(conn, clean)
    return {"classes": list(mc.CLASSES), "mapping": mc.get_all(conn)}


class ProjectTemplateUpdate(BaseModel):
    states: list[StateCreate] = Field(min_length=1, max_length=30)

    @field_validator("states")
    @classmethod
    def valid_states(cls, states: list[StateCreate]) -> list[StateCreate]:
        """Kolomnamen zijn uniek en exact één kolom is de standaard."""
        names = [s.name.strip() for s in states]
        if any(not name for name in names) or len(set(names)) != len(names):
            raise ValueError("Kolomnamen moeten gevuld en uniek zijn")
        if sum(s.is_default for s in states) != 1:
            raise ValueError("Kies precies één standaardkolom")
        for state, name in zip(states, names):
            if len(name) > 100 or not re.fullmatch(r"#[0-9a-fA-F]{6}", state.color):
                raise ValueError("Ongeldige kolomnaam of kleur")
            state.name = name
        return states


@router.get("/settings/project-template")
def get_project_template(
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    return {"states": project_template.get(conn)}


@router.put("/settings/project-template")
def put_project_template(
    body: ProjectTemplateUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    with dbm.transaction(conn):
        project_template.replace(
            conn, [s.model_dump(exclude={"sort_order"}) for s in body.states]
        )
    return {"states": project_template.get(conn)}


@router.get("/security-status")
def security_status(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    """Alleen geaggregeerde metingen; geen sleutels of webhookinhoud."""
    metrics = getattr(request.app.state, "resource_metrics", None)
    return {
        "active_writes": sum(metrics.writes.values()) if metrics else 0,
        "active_uploads": sum(metrics.uploads.values()) if metrics else 0,
        "active_streams": sum(metrics.streams.values()) if metrics else 0,
        "rejected_requests": dict(metrics.denied) if metrics else {},
        "attachment_bytes": conn.execute(
            "SELECT COALESCE(SUM(size),0) FROM attachments"
        ).fetchone()[0],
        "pending_webhooks": conn.execute(
            "SELECT COUNT(*) FROM webhook_deliveries WHERE status='pending'"
        ).fetchone()[0],
        "pending_wiki_proposals": conn.execute(
            "SELECT COUNT(*) FROM wiki_proposals WHERE status='pending'"
        ).fetchone()[0],
        "write_usage": [
            dict(row)
            for row in conn.execute(
                "SELECT u.handle,w.total_bytes,w.day,w.day_bytes FROM api_write_usage w JOIN users u ON u.id=w.user_id"
            )
        ],
        "llm_usage_today": [
            dict(row)
            for row in conn.execute(
                "SELECT category,spent FROM llm_daily_usage WHERE day=date('now')"
            )
        ],
    }


@router.post("/security-usage/{handle}/reset")
def reset_usage(
    handle: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_human),
) -> dict:
    """Een mens kan na onderzoek een verbruikte applicatiequota herstellen."""
    from ..repo import users, events

    target = users.get_by_handle(conn, handle)
    if target is None:
        raise HTTPException(404, "Onbekende gebruiker")
    with dbm.transaction(conn):
        conn.execute("DELETE FROM api_write_usage WHERE user_id=?", (target["id"],))
        events.record(
            conn,
            type="security.quota_reset",
            actor_id=user["id"],
            payload={"handle": handle},
        )
    metrics = getattr(request.app.state, "resource_metrics", None)
    if metrics:
        metrics.rate.clear_prefix(f"{target['id']}:")
    return {"status": "ok"}
