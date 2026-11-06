"""Deterministische command-uitvoerder voor chat-met-triage (BETON-120).

Een `Command` is een getypeerd, gevalideerd voornemen (verb + params + selector)
— nooit rechtstreeks door de LLM uitgevoerd. `validate` checkt vóór alles;
`resolve_targets` bepaalt de concrete geraakte items (voor de preview);
`execute` voert pas uit ná bevestiging, via de bestaande repo-functies, als user
`triage`, met events + optionele fanout (bulk = geen fanout, voorkomt spam).

Whitelist van verbs — bewust GEEN hard-delete: alles wat hier gebeurt is
omkeerbaar (archiveren kent een restore).
"""

from __future__ import annotations

from .outbound import outbound

import sqlite3
from dataclasses import dataclass, field

from . import db as db_module
from . import webhooks
from .models import PRIORITIES
from .repo import access
from .repo import events as events_repo
from .repo import items as items_repo
from .repo import labels as labels_repo
from .repo import milestones as milestones_repo
from .repo import relations as relations_repo
from .repo import states as states_repo
from .repo import users as users_repo

VERBS = frozenset(
    {
        "archive",
        "restore",
        "set_state",
        "set_priority",
        "set_assignee",
        "add_label",
        "remove_label",
        "set_milestone",
        "add_relation",
        "create_item",
    }
)

_PRIORITIES = frozenset(PRIORITIES)  # BETON-327: uit models.Priority afgeleid

# create_item werkt niet op bestaande items — die heeft geen selector nodig.
_NO_SELECTOR_VERBS = frozenset({"create_item"})


@dataclass(frozen=True)
class Command:
    """Eén voorgesteld commando. `selector` is `{"refs": [...]}` (expliciete
    refs) of `{"filter": {...}}` (bv. `{"state_closed": True,
    "updated_before_days": 30}`); `None` voor `create_item`."""

    verb: str
    project_id: int
    selector: dict | None = None
    params: dict = field(default_factory=dict)


def resolve_targets(
    conn: sqlite3.Connection,
    project_id: int,
    selector: dict | None,
    *,
    include_archived: bool = False,
) -> list[sqlite3.Row]:
    """De concrete items die dit commando raakt — altijd binnen één project.

    Bij `selector["refs"]`: expliciete refs, elk gevalideerd tegen dit project
    (een ref uit een ander project levert een ValueError op — cross-project is
    niet toegestaan). Bij `selector["filter"]`: een combinatie van
    `state_closed` (states.closed=1), `updated_before_days` (updated_at vóór de
    grens), `label`, `assignee`, `priority`.
    """
    if not selector:
        return []

    refs = selector.get("refs")
    if refs is not None:
        rows = []
        for ref in refs:
            try:
                row = items_repo.get_by_ref(conn, ref)
            except ValueError:
                raise ValueError(outbound("commands.invalid_ref", ref=repr(ref))) from None
            if row is None:
                raise ValueError(outbound('commands.resolve_targets.1', p0=(ref)))
            if row["project_id"] != project_id:
                raise ValueError(outbound('commands.resolve_targets.2', p0=(ref)))
            rows.append(row)
        return rows

    filt = selector.get("filter") or {}
    sql = ["SELECT items.* FROM items"]
    where = ["items.project_id = ?"]
    params: list = [project_id]
    needs_states_join = False

    if not include_archived:
        where.append("items.archived_at IS NULL")

    if filt.get("state_closed"):
        needs_states_join = True
        where.append("st.closed = 1")
    if filt.get("state_open"):
        needs_states_join = True
        where.append("st.closed = 0")
    if filt.get("state"):
        needs_states_join = True
        where.append("st.name = ? COLLATE NOCASE")
        params.append(filt["state"])
    if needs_states_join:
        sql.append("JOIN states st ON st.id = items.state_id")
    if filt.get("updated_before_days") is not None:
        where.append("items.updated_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)")
        params.append(f"-{int(filt['updated_before_days'])} days")
    if filt.get("priority"):
        where.append("items.priority = ?")
        params.append(filt["priority"])
    if filt.get("label"):
        where.append(
            "EXISTS (SELECT 1 FROM item_labels il JOIN labels l ON l.id = il.label_id "
            "WHERE il.item_id = items.id AND l.name = ? COLLATE NOCASE)"
        )
        params.append(filt["label"])
    if filt.get("assignee"):
        where.append(
            "EXISTS (SELECT 1 FROM users u WHERE u.id = items.assignee_id "
            "AND u.handle = ? COLLATE NOCASE)"
        )
        params.append(filt["assignee"])

    sql.append("WHERE " + " AND ".join(where))
    sql.append("ORDER BY items.id")
    return conn.execute(" ".join(sql), params).fetchall()


def validate(conn: sqlite3.Connection, command: Command) -> list[str]:
    """Alle fouten die uitvoering zouden laten mislukken of onveilig maken.
    Lege lijst = veilig om te previewen/bevestigen."""
    errors: list[str] = []

    if command.verb not in VERBS:
        return [outbound('commands.validate.1', p0=(command.verb))]

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (command.project_id,)
    ).fetchone()
    if project is None:
        return [outbound('commands.validate.2')]

    if command.verb == "create_item":
        if not command.params.get("title", "").strip():
            errors.append(outbound('commands.validate.3'))
        return errors

    if not command.selector:
        errors.append(outbound('commands.validate.4', p0=(command.verb)))
        return errors

    try:
        targets = resolve_targets(
            conn,
            command.project_id,
            command.selector,
            include_archived=(command.verb == "restore"),
        )
    except ValueError as exc:
        errors.append(str(exc))
        return errors
    if not targets:
        errors.append(outbound('commands.validate.5'))

    if command.verb == "set_state":
        name = command.params.get("state")
        if not name:
            errors.append(outbound('commands.validate.6'))
        elif states_repo.get_by_name(conn, command.project_id, name) is None:
            errors.append(outbound('commands.validate.7', p0=(name)))
    elif command.verb == "set_priority":
        if command.params.get("priority") not in _PRIORITIES:
            errors.append(outbound('commands.validate.8'))
    elif command.verb == "set_assignee":
        handle = command.params.get("assignee")
        if handle:
            user = users_repo.get_by_handle(conn, handle)
            if user is None:
                errors.append(outbound('commands.validate.9', p0=(handle)))
            elif access.effective_level(conn, command.project_id, user) != "assign":
                errors.append(outbound('commands.validate.10', p0=(handle)))
    elif command.verb in ("add_label", "remove_label"):
        if not command.params.get("label"):
            errors.append(outbound('commands.validate.11', p0=(command.verb)))
    elif command.verb == "set_milestone":
        name = command.params.get("milestone")
        if name and milestones_repo.get_by_name(conn, command.project_id, name) is None:
            errors.append(outbound('commands.validate.12', p0=(name)))
    elif command.verb == "add_relation":
        rel_type = command.params.get("relation_type")
        target_ref = command.params.get("target_ref")
        if rel_type not in relations_repo.NORMALIZE:
            errors.append(outbound('commands.validate.13', p0=(rel_type)))
        if not target_ref or items_repo.get_by_ref(conn, target_ref) is None:
            errors.append(outbound('commands.validate.14', p0=(target_ref)))

    return errors


def _project_key(conn: sqlite3.Connection, project_id: int) -> str:
    row = conn.execute("SELECT key FROM projects WHERE id = ?", (project_id,)).fetchone()
    return row["key"]


def _apply_single(
    conn: sqlite3.Connection, command: Command, item: sqlite3.Row, actor_id: int
) -> sqlite3.Row:
    """Muteer één item volgens het commando; geeft het geschreven event terug."""
    verb = command.verb
    if verb == "archive":
        items_repo.archive(conn, item["id"])
        return events_repo.record(
            conn, type="item.archived", item_id=item["id"], actor_id=actor_id, payload={}
        )
    if verb == "restore":
        items_repo.unarchive(conn, item["id"])
        return events_repo.record(
            conn, type="item.restored", item_id=item["id"], actor_id=actor_id, payload={}
        )
    if verb == "set_state":
        state = states_repo.get_by_name(conn, command.project_id, command.params["state"])
        assert state is not None
        items_repo.update(conn, item["id"], {"state_id": state["id"]})
        return events_repo.record(
            conn, type="item.updated", item_id=item["id"], actor_id=actor_id,
            payload={"state": command.params["state"]},
        )
    if verb == "set_priority":
        items_repo.update(conn, item["id"], {"priority": command.params["priority"]})
        return events_repo.record(
            conn, type="item.updated", item_id=item["id"], actor_id=actor_id,
            payload={"priority": command.params["priority"]},
        )
    if verb == "set_assignee":
        handle = command.params.get("assignee")
        user = users_repo.get_by_handle(conn, handle) if handle else None
        items_repo.update(conn, item["id"], {"assignee_id": user["id"] if user else None})
        return events_repo.record(
            conn, type="item.updated", item_id=item["id"], actor_id=actor_id,
            payload={"assignee": handle},
        )
    if verb == "add_label":
        name = command.params["label"]
        label = labels_repo.get_by_name(conn, command.project_id, name)
        label_id = (label["id"] if label is not None else
                    labels_repo.create(conn, project_id=command.project_id, name=name)["id"])
        labels_repo.add_to_item(conn, item["id"], label_id)
        return events_repo.record(
            conn, type="item.updated", item_id=item["id"], actor_id=actor_id,
            payload={"label_added": name},
        )
    if verb == "remove_label":
        name = command.params["label"]
        label = labels_repo.get_by_name(conn, command.project_id, name)
        if label is not None:
            labels_repo.remove_from_item(conn, item["id"], label["id"])
        return events_repo.record(
            conn, type="item.updated", item_id=item["id"], actor_id=actor_id,
            payload={"label_removed": name},
        )
    if verb == "set_milestone":
        name = command.params.get("milestone")
        ms = milestones_repo.get_by_name(conn, command.project_id, name) if name else None
        items_repo.update(conn, item["id"], {"milestone_id": ms["id"] if ms else None})
        return events_repo.record(
            conn, type="item.updated", item_id=item["id"], actor_id=actor_id,
            payload={"milestone": name},
        )
    if verb == "add_relation":
        rel_type = command.params["relation_type"]
        target = items_repo.get_by_ref(conn, command.params["target_ref"])
        assert target is not None
        stored_type, reversed_ = relations_repo.NORMALIZE[rel_type]
        src, dst = (target["id"], item["id"]) if reversed_ else (item["id"], target["id"])
        relations_repo.create(conn, item_id=src, related_item_id=dst, stored_type=stored_type)
        return events_repo.record(
            conn, type="relation.created", item_id=item["id"], actor_id=actor_id,
            payload={"type": rel_type, "target": command.params["target_ref"]},
        )
    raise ValueError(outbound("commands.unknown_guard", verb=verb))  # pragma: no cover — validate() dekt dit af


def execute(
    conn: sqlite3.Connection, command: Command, actor_id: int, *, fanout: bool
) -> list[str]:
    """Voer een gevalideerd commando uit. Geeft de refs van de geraakte items
    terug. `fanout=False` bij bulk (>1 item) onderdrukt webhook-deliveries
    (voorkomt meldingsspam) maar events/audit blijven altijd geschreven."""
    with db_module.transaction(conn):
        key = _project_key(conn, command.project_id)
        if command.verb == "create_item":
            item = items_repo.create(
                conn,
                project_id=command.project_id,
                title=command.params["title"],
                description_md=command.params.get("description_md", ""),
                created_by=actor_id,
            )
            event = events_repo.record(
                conn, type="item.created", item_id=item["id"], actor_id=actor_id, payload={}
            )
            if fanout:
                webhooks.fanout(conn, event=event)
            return [f"{key}-{item['seq']}"]

        targets = resolve_targets(
            conn,
            command.project_id,
            command.selector,
            include_archived=(command.verb == "restore"),
        )
        refs: list[str] = []
        for item in targets:
            refs.append(f"{key}-{item['seq']}")
            event = _apply_single(conn, command, item, actor_id)
            if fanout:
                webhooks.fanout(conn, event=event)
        return refs
