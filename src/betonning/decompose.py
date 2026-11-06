"""Decompose: een groot item opknippen in subtaken met volgorde-relaties (BETON-31).

Spiegelt het triage/enrich-patroon: pure prompt-bouw + parsing (los testbaar met
FakeLLM) en een apply die subitems + een blocks-keten + een `[Decompose]`-comment
aanmaakt in één transactie. Idempotent via de hidden marker `items.decomposed_at`
(migratie 015): een item wordt nooit twee keer opgeknipt.
"""

from __future__ import annotations

from .outbound import outbound

import logging
import json
import sqlite3

from pydantic import BaseModel, Field, field_validator

from . import db as db_module
from . import llm as llm_mod
from . import webhooks
from .repo import comments as comments_repo
from .repo import events as events_repo
from .repo import items as items_repo
from .repo import relations as relations_repo
from .repo import users as users_repo
from .triage import DECOMPOSE_CRITERIA

logger = logging.getLogger(__name__)

MAX_SUBTASKS = 8


class DecomposeSubtask(BaseModel):
    title: str = Field(max_length=300)
    description_md: str = Field(default="", max_length=60000)
    priority: str = "none"
    # BETON-67: gesuggereerde agent-handle (op expertise). None → val bij het
    # toepassen terug op de parent-assignee of claude.
    assignee: str | None = None

    @field_validator("priority", mode="before")
    @classmethod
    def _norm_priority(cls, v):
        v = llm_mod.norm_str(v)
        return v if v in ("urgent", "high", "medium", "low", "none") else "none"

    @field_validator("assignee", mode="before")
    @classmethod
    def _norm_assignee(cls, v):
        v = llm_mod.norm_str(v)
        if not isinstance(v, str):
            return None
        v = v.lstrip("@")
        return v or None


class DecomposeResult(BaseModel):
    should_decompose: bool = False
    reason: str = ""
    subtasks: list[DecomposeSubtask] = Field(default_factory=list, max_length=MAX_SUBTASKS)
    # 0-based index-paren (a, b): subtasks[a] blokkeert subtasks[b] (volgorde).
    blocks: list[tuple[int, int]] = []


DECOMPOSE_SYSTEM_PROMPT = (
    """Je bent de decompose-orchestrator voor Betonning, een \
work-item-tracker. Je beoordeelt of één taak beter opgeknipt kan worden in meerdere \
kleinere, los uitvoerbare subtaken, en zo ja, in welke volgorde. Antwoord met JSON.

"""
    # BETON-257: exact dezelfde opknip-rubriek als het triage-ADVIES
    # (decompose_suggestion), zodat wat triage aanraadt hier ook echt gebeurt.
    + DECOMPOSE_CRITERIA
    + """

Bij should_decompose = false laat je subtasks en blocks leeg.

Voorbeelden:
- "Typefout in de footer corrigeren" → {"should_decompose": false, "reason": "Eén \
kleine wijziging, in één sessie klaar.", "subtasks": [], "blocks": []}
- "Refactor: hernoem de functie foo naar bar" → {"should_decompose": false, "reason": \
"Enkelvoudige, samenhangende wijziging.", "subtasks": [], "blocks": []}

Velden:
- should_decompose: true alleen als álle criteria hierboven kloppen; anders false.
- reason: één zin (in de ingestelde uitvoertaal) waarom wel/niet.
- subtasks: lijst van {title, description_md, priority, assignee}. Elke subtaak is \
concreet en zelfstandig afrondbaar. Maximaal 8. Schrijf omschrijvingen overzichtelijk \
met witregels, geen wall of text. Leeg als should_decompose = false. Kies per subtaak \
in "assignee" de agent wiens expertise (zie "Beschikbare agents (met expertise)" \
hieronder) het beste bij die subtaak past — match op de omschrijving, niet op naam. \
Zonder duidelijke specialist-match gebruik je "coding-agent" (de gedeelde coding-\
queue). Gebruik alleen handles die in de agentlijst staan.
- blocks: lijst van [a, b] met 0-based indices in subtasks, waarbij subtaak a áf moet \
zijn voordat b kan beginnen (volgorde/afhankelijkheid). Laat leeg als er geen \
strikte volgorde is (of als should_decompose = false).

Antwoord ALLEEN met valide JSON, zonder codeblokken of uitleg eromheen."""
    + llm_mod.UNTRUSTED_INPUT_RULE
)


def _roster_text(context: dict) -> str:
    """Agent-roster (handle + expertise) voor de per-subtaak-routering (BETON-67)."""
    agents = context.get("agents")
    if not agents:
        return ""
    lines = ["", "## Beschikbare agents (met expertise)"]
    for a in agents:
        desc = (a.get("description") or "").strip() or "(geen omschrijving)"
        lines.append(f"- @{a['handle']}: {desc}")
    return "\n".join(lines)


def build_decompose_messages(
    item: dict, context: dict, *, images: list[dict] | None = None
) -> list[dict]:
    """Bouw de chat-messages voor decompose (pure functie, testbaar).

    Zonder ``images`` is de user-content een string (backward-compat). Met
    ``images`` (OpenAI-vision content-blocks, zie llm.build_image_block) wordt
    de user-content een lijst ``[text-block, *image-blocks]`` (BETON-139)."""
    user = (
        f"# Project: {context.get('project_name', '?')}\n\n"
        "## Taak om te beoordelen\n"
        f"{llm_mod.item_block(item)}"
        f"{_roster_text(context)}"
    )
    return [
        {"role": "system", "content": llm_mod.localized_system_prompt(DECOMPOSE_SYSTEM_PROMPT)},
        {"role": "user", "content": llm_mod.user_content(user, images)},
    ]


def parse_decompose(text: str) -> DecomposeResult:
    """Parse de LLM-output; val veilig terug op 'niet opknippen' bij ongeldige JSON."""
    # Modeluitvoer mag worden begrensd; de HTTP-applybody blijft streng gevalideerd.
    try:
        obj = llm_mod.extract_json(text)
        if isinstance(obj.get("subtasks"), list):
            obj["subtasks"] = obj["subtasks"][:MAX_SUBTASKS]
        text = json.dumps(obj)
    except (ValueError, TypeError):
        pass
    result = llm_mod.parse_json_result(
        text,
        DecomposeResult,
        context="Decompose-output",
        fallback=lambda raw, exc: DecomposeResult(),
        log=logger,
    )
    if not result.subtasks:
        result.should_decompose = False
    if not result.should_decompose:
        result.subtasks = []
        result.blocks = []
        return result
    result.subtasks = result.subtasks[:MAX_SUBTASKS]
    result.blocks = [(a, b) for a, b in result.blocks
                     if 0 <= a < len(result.subtasks) and 0 <= b < len(result.subtasks) and a != b]
    return result


def _resolve_assignee(
    conn: sqlite3.Connection, handle: str | None, parent_assignee_id: int | None
) -> int | None:
    """Zet een gesuggereerde agent-handle veilig om naar een user-id (BETON-67).

    Volgorde: geldige (actieve) gesuggereerde handle → de parent-assignee →
    de virtuele coding-queue `coding-agent`. Een onbekende/inactieve handle wordt
    genegeerd (val terug), zodat een hallucinatie de decompose niet laat crashen.

    BETON-207: een concrete coding-agent (claude/codex/zcode) wordt naar de
    virtuele `coding-agent`-queue geklapt — subtaken belanden nooit direct bij
    één individuele coding-agent."""
    if handle:
        u = users_repo.get_by_handle(conn, handle)
        if u is not None and u["active"]:
            target_handle = users_repo.collapse_to_virtual(conn, handle)
            target = users_repo.get_by_handle(conn, target_handle) if target_handle else None
            return target["id"] if target is not None else u["id"]
    if parent_assignee_id is not None:
        return parent_assignee_id
    fallback = users_repo.get_by_handle(conn, users_repo.VIRTUAL_CODING)
    if fallback is None:  # DB zonder migratie 027 — terugval op de oude default.
        fallback = users_repo.get_by_handle(conn, "claude")
    return fallback["id"] if fallback is not None else None


def apply_decompose(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    result: DecomposeResult,
    actor_id: int,
) -> list[str]:
    """Maak de subtaken + blocks-keten + een `[Decompose]`-comment aan en markeer het
    item als opgeknipt (`decomposed_at`). Eén transactie. Geeft de refs van de nieuwe
    subtaken terug.

    Per subtaak wordt óók een ``blocks``-relatie naar de parent aangelegd
    (BETON-137): de subtaak blokkeert de parent, zodat de parent pas "klaar"
    kan zijn als alle subtaken af zijn. Hergebruikt de bestaande
    ``blocks``-relatie; geen nieuw mechanisme.

    Verwacht dat de caller al heeft gecontroleerd dat het item nog niet is opgeknipt
    (idempotentie via decomposed_at) en dat should_decompose waar is met subtaken.
    """
    created: list[sqlite3.Row] = []
    with db_module.transaction(conn):
        for sub in result.subtasks:
            row = items_repo.create(
                conn,
                project_id=item["project_id"],
                title=sub.title,
                description_md=sub.description_md,
                priority=sub.priority,
                assignee_id=_resolve_assignee(conn, sub.assignee, item["assignee_id"]),
                milestone_id=item["milestone_id"],
                parent_id=item["id"],
                created_by=actor_id,
            )
            created.append(row)
            data = items_repo.serialize(conn, row)
            webhooks.record_and_fanout(
                conn,
                type="item.created",
                item_id=row["id"],
                actor_id=actor_id,
                payload={"ref": data["ref"], "title": data["title"], "parent": None},
            )

            # BETON-137: subtaat blokkeert de parent, zodat de parent pas "klaar"
            # kan zijn als alle subtaken af zijn. Hergebruikt de bestaande
            # `blocks`-relatie (geen nieuw mechanisme); het patroon hieronder
            # (reverse_exists-guard + relation.created-event) spiegelt de
            # volgorde-relatie-keten verderop in deze functie.
            if not relations_repo.reverse_exists(
                conn, item_id=row["id"], related_item_id=item["id"],
                stored_type="blocks",
            ):
                relations_repo.create(
                    conn, item_id=row["id"], related_item_id=item["id"],
                    stored_type="blocks",
                )
                parent_ref = items_repo.serialize(conn, item)["ref"]
                webhooks.record_and_fanout(
                    conn,
                    type="relation.created",
                    item_id=row["id"],
                    actor_id=actor_id,
                    payload={"type": "blocks", "target": parent_ref},
                )

        # Volgorde-relaties: subtasks[a] blokkeert subtasks[b].
        n = len(created)
        for a, b in result.blocks:
            if a == b or not (0 <= a < n) or not (0 <= b < n):
                continue
            blocker, blocked = created[a], created[b]
            if relations_repo.reverse_exists(
                conn, item_id=blocker["id"], related_item_id=blocked["id"],
                stored_type="blocks",
            ):
                continue
            relations_repo.create(
                conn, item_id=blocker["id"], related_item_id=blocked["id"],
                stored_type="blocks",
            )
            webhooks.record_and_fanout(
                conn,
                type="relation.created",
                item_id=blocker["id"],
                actor_id=actor_id,
                payload={"type": "blocks", "target": items_repo.serialize(conn, blocked)["ref"]},
            )

        # Samenvattende comment op het ouder-item.
        refs = [items_repo.serialize(conn, r)["ref"] for r in created]
        body = outbound("decompose.summary", refs=", ".join(refs))
        if result.reason:
            body += f"\n\n{result.reason}"
        crow = comments_repo.create(
            conn, item_id=item["id"], author_id=actor_id, body_md=body
        )
        webhooks.record_and_fanout(
            conn, type="comment.created", item_id=item["id"],
            actor_id=actor_id, payload={"comment_id": crow["id"]},
        )

        # Marker: opgeknipt (idempotentie + onderhoud).
        events_repo._touch(conn, "items", "decomposed_at", item["id"])
    return refs
