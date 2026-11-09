"""Items-endpoints: detail (GET) en partiële update (PATCH) op ref."""

from __future__ import annotations

from ..outbound import outbound

import json
import re
import sqlite3

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from ..deps import (
    current_human,
    current_user,
    get_db,
    llm_errors_as_502,
    llm_rate_limited,
    require_item as _require_item,
    require_llm_client,
)
from .. import models
from ..models import (
    AnswerCreate,
    QuestionWithdraw,
    CommentCreate,
    CommentUpdate,
    GuardrailIn,
    GuardrailProposalIn,
    ItemMove,
    ItemUpdate,
    RelationCreate,
    UnlockIn,
)
from ..repo import comments as comments_repo
from ..repo import events as events_repo
from ..repo import guardrails as guardrails_repo
from ..repo import held_comments as held_repo
from ..repo import item_reads as item_reads_repo
from ..repo import items as items_repo
from ..repo import labels as labels_repo
from ..repo import milestones
from ..repo import follows as follows_repo
from ..repo import mutes as mutes_repo
from ..repo import projects as projects_repo
from ..repo import execution as execution_repo
from ..repo import relations as relations_repo
from ..repo import states as states_repo
from ..repo import users as users_repo
from .. import db as db_module
from .. import decompose as decompose_mod
from .. import llm as llm_module
from .. import mentions as mentions_mod
from .. import question_assign
from .. import triage as triage_mod
from .. import triage_worker as triage_worker_mod
from .. import webhooks

router = APIRouter(tags=["items"])


def _resolve_state_id(conn: sqlite3.Connection, project: sqlite3.Row, name: str) -> int:
    state = states_repo.get_by_name(conn, project["id"], name)
    if state is None:
        raise HTTPException(status_code=400, detail=f"Onbekende state: {name}")
    return state["id"]


def _resolve_assignee_id(conn: sqlite3.Connection, handle: str) -> int:
    user = users_repo.get_by_handle(conn, handle)
    if user is None:
        raise HTTPException(status_code=400, detail=f"Onbekende user: {handle}")
    return user["id"]


def _resolve_parent_id(
    conn: sqlite3.Connection,
    ref: str,
    *,
    project_id: int,
    child_id: int | None = None,
) -> int:
    try:
        parent = items_repo.get_by_ref(conn, ref)
    except ValueError:
        parent = None
    if parent is None:
        raise HTTPException(status_code=400, detail=f"Onbekend parent-item: {ref}")
    if parent["project_id"] != project_id:
        raise HTTPException(
            status_code=400, detail=f"Parent {ref} hoort bij een ander project"
        )
    # Cycle-check: het item mag niet in zijn eigen parent-keten voorkomen.
    if child_id is not None:
        node: sqlite3.Row | None = parent
        while node is not None:
            if node["id"] == child_id:
                raise HTTPException(
                    status_code=400, detail="Parent zou een cyclus vormen"
                )
            node = (
                items_repo.get(conn, node["parent_id"])
                if node["parent_id"] is not None
                else None
            )
    return parent["id"]


def _resolve_milestone_id(
    conn: sqlite3.Connection, project: sqlite3.Row, name: str
) -> int:
    ms = milestones.get_by_name(conn, project["id"], name)
    if ms is None:
        raise HTTPException(status_code=400, detail=f"Onbekende milestone: {name}")
    return ms["id"]


def _resolve_label_id(conn: sqlite3.Connection, project: sqlite3.Row, name: str) -> int:
    label = labels_repo.get_by_name(conn, project["id"], name)
    if label is None:
        raise HTTPException(status_code=400, detail=f"Onbekend label: {name}")
    return label["id"]


def resolve_item_fields(
    conn: sqlite3.Connection,
    project: sqlite3.Row,
    *,
    state: str | None = None,
    assignee: str | None = None,
    parent: str | None = None,
    milestone: str | None = None,
) -> dict:
    """Zet namen/refs om naar id's. Alleen niet-lege waarden worden opgenomen.

    Een lege string betekent "niet gezet" (spiegelt het PATCH-pad, waar "" juist
    "wissen" betekent — op create is er nog niets om te wissen)."""
    resolved: dict = {}
    if state:
        resolved["state_id"] = _resolve_state_id(conn, project, state)
    if assignee:
        resolved["assignee_id"] = _resolve_assignee_id(conn, assignee)
    if parent:
        resolved["parent_id"] = _resolve_parent_id(
            conn, parent, project_id=project["id"]
        )
    if milestone:
        resolved["milestone_id"] = _resolve_milestone_id(conn, project, milestone)
    return resolved


# Vraagmodule (BETON-219): een redelijk maximum aan meerkeuze-opties.
_MAX_QUESTION_OPTIONS = 6

# BETON-304: vangnet tegen meerdere vragen in één vraagmodule. Alleen relevant
# als er OOK options zijn — die horen bij precies één vraag, dus opties die
# over meerdere vragen door elkaar lopen zijn de eigenlijke klacht (zie
# BETON-302: triage propte 3 vragen + gemengde opties in één comment). Een
# vrije-tekstvraag zonder opties heeft dat probleem niet en wordt niet geraakt.
_MAX_QUESTION_MARKS_WITH_OPTIONS = 2  # "Moet ik X? Zo ja, ook Y?" mag nog net

_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
# Een run moet minstens één `?` bevatten om als vraag te tellen — een reeks
# uitroeptekens ("Doe dit nu!!") is geen vraag en mag niet meetellen.
_QUESTION_RUN_RE = re.compile(r"[?!]*\?[?!]*")


def _count_questions(body_md: str) -> int:
    """Tel vraagzinnen in een vraagtekst (pure, los testbaar).

    Code-fences en inline-backticks tellen niet mee (een `?` in een ternary/
    regex/query-string is geen vraag). Een reeks `?`/`!` rond minstens één `?`
    (bv. `??`, `?!`) telt als één vraagteken — retorische interpunctie, geen
    aparte vraag. Een reeks van uitsluitend `!` telt niet mee."""
    text = _CODE_FENCE_RE.sub("", body_md)
    text = _INLINE_CODE_RE.sub("", text)
    return len(_QUESTION_RUN_RE.findall(text))


def _validate_question(
    kind: str, options: list[str] | None, body_md: str = ""
) -> list[str] | None:
    """Valideer/normaliseer meerkeuze-opties bij het aanmaken van een comment.

    Opties horen alleen bij ``kind='question'``. Lege/whitespace-only opties en
    duplicaten zijn misbruik → 422. Retourneert de getrimde optielijst (of None
    als er geen opties zijn)."""
    if options is None:
        return None  # geen opties: gewone comment óf vrije-tekst-vraag
    if kind != "question":
        raise HTTPException(
            status_code=422, detail="options zijn alleen toegestaan bij kind='question'"
        )
    trimmed = [o.strip() for o in options]
    if any(not o for o in trimmed):
        raise HTTPException(status_code=422, detail="lege optie is niet toegestaan")
    if len(trimmed) != len(set(trimmed)):
        raise HTTPException(status_code=422, detail="dubbele optie is niet toegestaan")
    if len(trimmed) > _MAX_QUESTION_OPTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"maximaal {_MAX_QUESTION_OPTIONS} opties toegestaan",
        )
    if _count_questions(body_md) > _MAX_QUESTION_MARKS_WITH_OPTIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                "Eén vraag per vraagmodule — de meerkeuze-opties horen bij "
                "precies één vraag. Stel de tweede vraag met een aparte "
                "ask_question-aanroep."
            ),
        )
    return trimmed


def _require_human_addressee(
    conn: sqlite3.Connection, item: sqlite3.Row, body_md: str
) -> None:
    """De vraagmodule is alleen voor vragen aan een MENS (BETON-307).

    Alleen relevant als de CALLER een agent is (de aanroeper filtert dat al);
    een mens die vraagt blijft altijd ongemoeid. Adressering: een @mention in
    de body, of anders de assignee van het item (dezelfde bron als de fanout,
    `webhooks.fanout` hieronder).

    Weiger alléén als de adressering AANTOONBAAR uitsluitend agents oplevert
    (BRAND-257: een agent mentiont een andere agent, of het item is aan een
    agent toegewezen). Een vraag zónder enige bepaalbare geadresseerde (geen
    mention, geen assignee) blijft toegestaan — dat is de gangbare vrije-
    tekstvraag, niet het gerapporteerde misbruik, en veel bestaande vragen
    hebben nu eenmaal geen assignee."""
    mentioned = mentions_mod.parse(body_md)
    if mentioned:
        addressees = [users_repo.get_by_handle(conn, h) for h in mentioned]
        resolved = [u for u in addressees if u is not None]
        if not resolved or any(u["kind"] == "human" for u in resolved):
            return
    else:
        assignee = (
            users_repo.get(conn, item["assignee_id"])
            if item["assignee_id"] is not None
            else None
        )
        if assignee is None or assignee["kind"] == "human":
            return
    raise HTTPException(
        status_code=422,
        detail=(
            "De vraagmodule is alleen voor vragen aan een mens. Voor een "
            "vraag aan een andere agent: gebruik een gewone comment met "
            "`@handle`."
        ),
    )


@router.get("/items/{ref}")
def get_item(
    ref: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    _reactivate_due(conn)
    item = _require_item(conn, ref)
    observed_event_id = item_reads_repo.last_event_id(conn, item["id"])
    # BETON-294: has_unread is per user — serialiseer t.o.v. de aanroeper. Het
    # ophalen markeert bewust niets als gelezen; dat doet POST /items/{ref}/read.
    data = items_repo.serialize(conn, item, user["id"])
    data["last_event_id"] = observed_event_id
    execution_request = execution_repo.latest(conn, item["id"])
    if execution_request is not None:
        data["execution"] = execution_repo.serialize(conn, execution_request)
    child_rows = [
        items_repo.serialize(conn, c, user["id"])
        for c in items_repo.children(conn, item["id"])
    ]
    data["children"] = [c["ref"] for c in child_rows]
    # BETON-203: de subtakenlijst kleurt naar status — de UI heeft daarvoor de
    # state van elk kind nodig, niet alleen de ref (`children` blijft
    # ongewijzigd voor bestaande consumers).
    data["children_detail"] = [
        {"ref": c["ref"], "title": c["title"], "state": c["state"]}
        for c in child_rows
    ]
    data["comments"] = [
        comments_repo.serialize(conn, c)
        for c in comments_repo.list_for_item(conn, item["id"])
    ]
    # BETON-471: dezelfde groepen als `relations`, maar per item {ref, title,
    # state} voor de UI-lijst (`relations` blijft ongewijzigd voor MCP/agents).
    data["relations_detail"] = relations_repo.for_item_detail(conn, item["id"])
    data["relations"] = {
        g: [d["ref"] for d in items] for g, items in data["relations_detail"].items()
    }
    # BETON-420: gescopede guardrails van ANDERE tickets in dit project waarvan
    # de scope-labels snijden met de labels van dit ticket. Projectbrede
    # guardrails zitten hier bewust niet in — die krijgt de agent al via de
    # wiki-context (`load_memory`), en twee keer leveren is twee keer betalen.
    # De eigen guardrail van dit ticket zit al in `serialize`.
    data["applicable_guardrails"] = guardrails_repo.applicable_for_item(
        conn, item["id"]
    )
    from ..credential_policy import projects as credential_projects
    allowed = credential_projects(user)
    if allowed is not None:
        for group, related in data["relations_detail"].items():
            data["relations_detail"][group] = [r for r in related if r["ref"].rsplit("-", 1)[0] in allowed]
        data["relations"] = {group: [r["ref"] for r in rows] for group, rows in data["relations_detail"].items()}
    return data


@router.get("/items/{ref}/plan")
def get_plan(
    ref: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    """Het plan/handover-veld van een item (BETON-218), on-demand.

    Bewust een apart endpoint: het plan kan groot zijn en zit daarom niet in de
    item-serialisatie (die adverteert alleen ``has_plan``). Zetten/wissen gaat
    via ``PATCH /items/{ref}`` met ``plan_md``."""
    item = _require_item(conn, ref)
    return {"plan_md": item["plan_md"]}


@router.get("/items/{ref}/subscribers")
def list_subscribers(
    ref: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    """De volgers van een item (BETON-245): assignee + eerdere participants +
    subscribe_all-users + expliciete volgers (BETON-369), elk met een
    ``muted``-vlag en een ``following``-vlag.

    De doelgroep is grotendeels afgeleid; alleen ``following`` komt uit een
    tabel (``item_follows``). Een mute (``item_mutes``) haalt een user uit de
    fanout, maar hij blijft in dit overzicht staan (met ``muted: true``) zodat je
    hem weer kunt ontmuten."""
    item = _require_item(conn, ref)
    muted = mutes_repo.muted_user_ids(conn, item["id"])
    following = follows_repo.follower_ids(conn, item["id"])
    subscribers = []
    # Een mute op een user die geen participant/volger is hoort er ook in te
    # staan, anders ziet hij zijn eigen demping niet terug (BETON-459).
    derived = webhooks.derived_subscribers(conn, item["id"])
    extra = [
        uid
        for uid in sorted(muted)
        if uid not in derived
        and (u := users_repo.get(conn, uid)) is not None
        and u["active"]
    ]
    for uid in [*derived, *extra]:
        user = users_repo.get_required(conn, uid)
        subscribers.append(
            {
                "handle": user["handle"],
                "muted": uid in muted,
                "following": uid in following,
            }
        )
    return {"subscribers": subscribers}


@router.post("/items/{ref}/follow", status_code=204)
def follow_item(
    ref: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_human),
) -> None:
    """Volg dit item (BETON-369): je komt in de fanout en krijgt de inbox-reden
    ``following`` bij comments/wijzigingen.

    Mens-only (``current_human`` → 403 voor agents): een agent hoort via mention
    of toewijzing binnen te komen, niet door zichzelf op tickets te abonneren —
    dat is precies de ongevraagde-notificatie-route die BETON-201 dichtzette.
    Idempotent."""
    item = _require_item(conn, ref)
    with db_module.transaction(conn):
        follows_repo.follow(conn, item["id"], user["id"])


@router.delete("/items/{ref}/follow", status_code=204)
def unfollow_item(
    ref: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_human),
) -> None:
    """Stop met volgen (BETON-369). Idempotent; haalt je niet uit de áfgeleide
    doelgroep (daarvoor is de mute)."""
    item = _require_item(conn, ref)
    with db_module.transaction(conn):
        follows_repo.unfollow(conn, item["id"], user["id"])


def _require_mute_target(
    conn: sqlite3.Connection, user: sqlite3.Row, handle: str
) -> sqlite3.Row:
    """De te (ont)dempen user. Een mens mag iedereen dempen (Volgers-rail); een
    agent alleen zichzelf (MCP `mute_item`), anders haalt hij een ander stil uit
    de fanout."""
    if user["kind"] != "human" and handle != user["handle"]:
        raise HTTPException(status_code=403, detail="Een agent dempt alleen zichzelf")
    target = users_repo.get_by_handle(conn, handle)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Onbekende user: {handle}")
    return target


@router.post("/items/{ref}/subscribers/{handle}/mute", status_code=204)
def mute_subscriber(
    ref: str,
    handle: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> None:
    """Mute een user voor dit item (BETON-245): hij krijgt geen fanout meer."""
    item = _require_item(conn, ref)
    target = _require_mute_target(conn, user, handle)
    with db_module.transaction(conn):
        mutes_repo.mute(conn, item["id"], target["id"])


@router.delete("/items/{ref}/subscribers/{handle}/mute", status_code=204)
def unmute_subscriber(
    ref: str,
    handle: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> None:
    """Hef de mute op (BETON-245): de user zit weer in de fanout."""
    item = _require_item(conn, ref)
    target = _require_mute_target(conn, user, handle)
    with db_module.transaction(conn):
        mutes_repo.unmute(conn, item["id"], target["id"])


@router.post("/items/{ref}/read")
def mark_item_read(
    ref: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    """Markeer alle activiteit op dit item als gezien voor de aanroepende user
    (BETON-294).

    Per user en per item: dit raakt de globale inbox-watermark
    (`users.last_seen_event_id`) niet, dus één ticket lezen markeert nooit de rest.
    De watermark gaat alleen omhoog, en het markeren schrijft zelf géén event —
    lezen is geen activiteit (anders zou het item voor anderen ongelezen worden).
    """
    item = _require_item(conn, ref)
    with db_module.transaction(conn):
        marker = item_reads_repo.mark_read(
            conn, item["id"], user["id"], item_reads_repo.last_event_id(conn, item["id"])
        )
    return {"ref": ref, "last_seen_event_id": marker, "has_unread": False}


@router.post("/items/{ref}/lock")
def lock_item(
    ref: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_human),
) -> dict:
    """Zet de noodstop op een ticket: agents reageren er niet meer op (BETON-302).

    Mens-only (`current_human` → 403 voor agents): dit is het middel om agents
    stil te leggen, dus een agent mag het niet zelf bedienen — hij zou zichzelf
    (of een collega) kunnen muilkorven.

    Idempotent: een al gelockt item blijft gelockt, zonder tweede event."""
    item = _require_item(conn, ref)
    if item["locked_at"] is not None:
        return items_repo.serialize(conn, item, viewer_id=user["id"])
    with db_module.transaction(conn):
        _lock_item(conn, item, user["id"], reason="manual")
    return items_repo.serialize(conn, items_repo.get_required(conn, item["id"]), viewer_id=user["id"])


@router.post("/items/{ref}/unlock")
def unlock_item(
    ref: str,
    body: UnlockIn | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_human),
) -> dict:
    """Haal de noodstop van een ticket (BETON-302). Mens-only.

    Geeft het gesprek weer `headroom` comments ruimte (5/10/20, default 5),
    geteld vanaf de huidige stand — daarna klapt het opnieuw dicht. Zo blijft
    een ticket dat in een lus zit onder controle, ook als het een keer
    ontgrendeld is.

    **Wachtende comment (BETON-338)**: stond er een comment in de wacht, dan
    wordt die hier alsnog geplaatst — op naam van de oorspronkelijke auteur, met
    een gewone `comment.created`-fanout, "alsof het normaal was". Dat gebeurt
    vóór het zetten van de nieuwe drempel: de vrijgegeven comment is inhaalwerk
    van vóór het slot en mag de gekozen ruimte niet opeten.

    Idempotent: een niet-gelockt item blijft ongemoeid (en de drempel wordt níet
    opgehoogd — dat zou een noodstop weg-klikken die nooit geklapt heeft)."""
    item = _require_item(conn, ref)
    if item["locked_at"] is None:
        return items_repo.serialize(conn, item, viewer_id=user["id"])
    headroom = body.headroom if body is not None else items_repo.UNLOCK_HEADROOM
    with db_module.transaction(conn):
        released = held_repo.release(conn, item["id"])
        if released is not None:
            row = comments_repo.create(
                conn,
                item_id=item["id"],
                author_id=released["author_id"],
                body_md=released["body_md"],
                kind="comment",
            )
            held_event = events_repo.record(
                conn,
                type="comment.created",
                item_id=item["id"],
                actor_id=released["author_id"],
                payload={"comment_id": row["id"], "held_since": released["created_at"]},
            )
            mentioned = mentions_mod.parse(released["body_md"])
            webhooks.fanout(
                conn,
                event=held_event,
                mentions=mentioned,
                directed=bool(mentioned),
            )
        # Ná het plaatsen tellen: zo valt de vrijgegeven comment buiten de
        # nieuwe ruimte (BETON-338) en krijgt het gesprek een volle `headroom`.
        fresh = items_repo.unlock(
            conn,
            item["id"],
            comments_repo.count_chatter(conn, item["id"]),
            headroom=headroom,
        )
        assert fresh is not None
        event = events_repo.record(
            conn,
            type="item.unlocked",
            item_id=item["id"],
            actor_id=user["id"],
            payload={"comment_limit": fresh["comment_limit"], "headroom": headroom},
        )
        # Ongericht: dit is het legitieme "je mag weer"-sein aan de assignee —
        # het tegenovergestelde van het slot, dus hier hoort de agent hem juist
        # wél te krijgen.
        webhooks.fanout(conn, event=event)
    return items_repo.serialize(conn, fresh, viewer_id=user["id"])


# --- Guardrails (BETON-420) ------------------------------------------------
#
# Mens-only, net als lock/unlock: een guardrail bindt élke agent, dus een agent
# mag hem niet zelf zetten of opheffen (voorstellen doet hij via de vraagmodule).
# `guardrail_md` staat daarom bewust NIET in `items_repo._PATCHABLE` — anders
# zette elke `current_user` hem alsnog via PATCH en was de mens-poort er niet.

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _default_review_by(conn: sqlite3.Connection) -> str:
    """Vandaag + `GUARDRAIL_DEFAULT_REVIEW_DAYS`, in de klok van de database.

    Nodig waar er geen mens een datum meegaf (activeren via een vraagmodule-
    antwoord, of een verlengde review): de reviewdatum is verplicht zodra een
    guardrail actief is."""
    row = conn.execute(
        "SELECT date('now', ?) AS d",
        (f"+{models.GUARDRAIL_DEFAULT_REVIEW_DAYS} days",),
    ).fetchone()
    return row["d"]


def _validate_guardrail(
    conn: sqlite3.Connection, project_id: int, body: GuardrailIn
) -> tuple[str, list[int]]:
    """Valideer tekst, reviewdatum en scope-labels. Geeft (tekst, label_ids)."""
    text = _validate_guardrail_text(body.guardrail_md)
    _validate_review_by(conn, (body.review_by or "").strip())
    return text, _resolve_scope_labels(conn, project_id, body.scope_labels)


def _validate_guardrail_text(raw: str | None) -> str:
    """Guardrail-tekst gestript; leeg of boven de cap = 422."""
    text = (raw or "").strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail="Een guardrail moet uitleggen wat en waarom — lege tekst kan niet.",
        )
    if len(text) > models.GUARDRAIL_MAX_CHARS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Guardrail is {len(text)} tekens; maximaal "
                f"{models.GUARDRAIL_MAX_CHARS}. De cap is de drempel: leg in drie "
                "zinnen uit wat, waarom en wat er gedaan of gelaten moet worden."
            ),
        )
    return text


def _validate_review_by(conn: sqlite3.Connection, review_by: str) -> None:
    """ISO-datum, niet in het verleden (klok van de database) — anders 422."""
    if not _ISO_DATE_RE.match(review_by):
        raise HTTPException(
            status_code=422,
            detail="review_by moet een ISO-datum zijn (YYYY-MM-DD).",
        )
    if review_by < db_module.today(conn):
        raise HTTPException(
            status_code=422, detail="review_by mag niet in het verleden liggen."
        )


def _require_project_wide_room(
    conn: sqlite3.Connection, item: sqlite3.Row, label_ids: list[int]
) -> None:
    """409 als deze guardrail een NIEUWE projectbrede plek zou innemen terwijl
    het plafond vol staat. Een al actieve projectbrede wijzigen telt niet
    dubbel, anders is hij niet meer te corrigeren zodra het plafond vol is."""
    if label_ids:
        return
    already_project_wide = _guardrail_is_active(item) and not (
        guardrails_repo.scope_labels(conn, item["id"])
    )
    if (
        not already_project_wide
        and guardrails_repo.project_wide_count(conn, item["project_id"])
        >= models.GUARDRAIL_PROJECT_WIDE_MAX
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Plafond bereikt ({models.GUARDRAIL_PROJECT_WIDE_MAX} "
                "projectbrede guardrails): hef er eerst een op."
            ),
        )


def _resolve_scope_labels(
    conn: sqlite3.Connection, project_id: int, names: list[str]
) -> list[int]:
    """Scope-labelnamen → label-ids. Onbekend label = 422.

    Bewust niet `_resolve_label_id`: die geeft 400, en voor de guardrail-bodies
    is een onbekend label een validatiefout zoals de rest. Gedeeld door het
    mens-endpoint en het voorstel-endpoint, zodat de melding op één plek staat.
    """
    label_ids: list[int] = []
    for name in names:
        label = labels_repo.get_by_name(conn, project_id, name)
        if label is None:
            raise HTTPException(
                status_code=422, detail=f"Onbekend label op dit project: {name}"
            )
        label_ids.append(label["id"])
    return label_ids


def _guardrail_is_active(item: sqlite3.Row) -> bool:
    """De Python-kant van `items_repo.GUARDRAIL_ACTIVE` op één itemrij."""
    return (
        item["guardrail_md"] is not None
        and item["guardrail_lifted_at"] is None
        and item["archived_at"] is None
    )


@router.post("/items/{ref}/guardrail")
def set_guardrail(
    ref: str,
    body: GuardrailIn,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_human),
) -> dict:
    """Zet (of wijzig) de guardrail van een ticket. Mens-only (403 voor agents).

    Zonder scope-labels is de guardrail projectbreed en telt hij mee in het
    plafond van `GUARDRAIL_PROJECT_WIDE_MAX`; een bestaande projectbrede
    guardrail wijzigen mag altijd, anders is hij niet meer te corrigeren zodra
    het plafond vol is.

    Alles in één transactie — velden, scope en event. Het event draagt een
    marker-payload zonder de tekst (de Hermes-gateway knipt payloads op 4000
    tekens) en gaat bewust ZONDER fanout: de guardrail bereikt de agent al via
    de wiki-context en `get_item`."""
    item = _require_item(conn, ref)
    text, label_ids = _validate_guardrail(conn, item["project_id"], body)
    _require_project_wide_room(conn, item, label_ids)

    with db_module.transaction(conn):
        guardrails_repo.set_guardrail(
            conn, item["id"], text=text, review_by=body.review_by, set_by=user["id"]
        )
        guardrails_repo.set_scope(conn, item["id"], label_ids)
        # BETON-422: "goedkeuren met wijzigingen" loopt hier langs — de mens
        # bewerkt het concept in de Drawer en slaat op. Deze route is dus zelf
        # de beslissing, dus het concept mag daarna niet blijven hangen (het zou
        # anders het conceptblok én de inbox-entry laten staan voor een voorstel
        # dat net verwerkt is).
        guardrails_repo.delete_proposal(conn, item["id"])
        events_repo.record(
            conn,
            type="item.guardrail_set",
            item_id=item["id"],
            actor_id=user["id"],
            payload={
                "guardrail": {
                    "active": True,
                    "review_by": body.review_by,
                    "scoped": bool(label_ids),
                }
            },
        )
    return items_repo.serialize(
        conn, items_repo.get_required(conn, item["id"]), viewer_id=user["id"]
    )


@router.post("/items/{ref}/guardrail/propose")
def propose_guardrail(
    ref: str,
    body: GuardrailProposalIn,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    """Stel een guardrail-wijziging voor als CONCEPT (BETON-422). Dit mag een agent.

    Het concept staat NAAST de actieve versie en bindt niets: zolang een mens het
    niet goedkeurt blijft de actieve guardrail onverkort gelden, wordt het
    concept nergens geleverd (wiki-context, `applicable_guardrails`) en telt het
    niet mee in het plafond. Dat is de reden dat er hier geen plafondpoort staat:
    die hoort bij goedkeuren, want een voorstel mag juist kunnen als het plafond
    vol staat — dát is het moment waarop de mens moet kunnen kiezen.

    Eén concept-slot per ticket: een nieuw voorstel (van welke agent ook)
    overschrijft het openstaande. Onschadelijk, want de actieve versie blijft
    gelden; `proposed_by` en het event leggen vast wie het laatst voorstelde.

    Het event gaat via `events_repo.record`, nooit via `record_and_fanout`, en
    draagt een marker-payload zonder de tekst (de Hermes-gateway knipt payloads
    op 4000 tekens) — net als de andere guardrail-events.
    """
    item = _require_item(conn, ref)
    # Het slot expliciet hier: `_require_unlocked` laat vragen sinds BETON-339
    # altijd door (de vraagmodule is de nooduitgang waarmee een agent om
    # ingrijpen vraagt). Een guardrail-voorstel is dat niet — het is werk dat kan
    # wachten tot de noodstop eraf is.
    _require_unlocked(item, user)

    kind = (body.kind or "").strip()
    if kind not in models.GUARDRAIL_PROPOSAL_KINDS:
        raise HTTPException(
            status_code=422,
            detail="kind moet 'set' (voorstellen/wijzigen) of 'lift' (opheffen) zijn.",
        )

    text: str | None = None
    reason: str | None = None
    review_by: str | None = None
    label_ids: list[int] = []

    if kind == "lift":
        reason = (body.reason or "").strip()
        if not reason:
            raise HTTPException(
                status_code=422,
                detail="Een opheffingsvoorstel moet uitleggen waarom — lege reden kan niet.",
            )
        if len(reason) > models.GUARDRAIL_MAX_CHARS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Reden is {len(reason)} tekens; maximaal "
                    f"{models.GUARDRAIL_MAX_CHARS}."
                ),
            )
        if not _guardrail_is_active(item):
            raise HTTPException(
                status_code=409,
                detail="Er staat geen actieve guardrail op dit ticket om op te heffen.",
            )
    else:
        text = _validate_guardrail_text(body.guardrail_md)
        label_ids = _resolve_scope_labels(conn, item["project_id"], body.scope_labels)
        review_by = (body.review_by or "").strip() or None
        if review_by is not None:
            _validate_review_by(conn, review_by)

    with db_module.transaction(conn):
        guardrails_repo.propose(
            conn,
            item["id"],
            kind=kind,
            text=text,
            review_by=review_by,
            reason=reason,
            proposed_by=user["id"],
            label_ids=label_ids,
        )
        events_repo.record(
            conn,
            type="item.guardrail_proposed",
            item_id=item["id"],
            actor_id=user["id"],
            payload={
                "guardrail": {
                    "proposal": kind,
                    "scoped": bool(label_ids),
                    "review_by": review_by,
                }
            },
        )
    return items_repo.serialize(
        conn, items_repo.get_required(conn, item["id"]), viewer_id=user["id"]
    )


_NO_PROPOSAL = "Er staat geen guardrail-concept op dit ticket."


@router.post("/items/{ref}/guardrail/approve")
def approve_guardrail(
    ref: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_human),
) -> dict:
    """Keur het openstaande concept goed. Mens-only (403 voor agents).

    Bij `kind="set"` vervangt het concept de actieve inhoud (tekst, scope,
    reviewdatum) en wordt de guardrail actief; bij `kind="lift"` wordt hij
    opgeheven. In beide gevallen verdwijnt het concept.

    Het plafond wordt op de UITKOMST getoetst: een concept dat een al actieve
    PROJECTBREDE guardrail wijzigt telt niet dubbel (anders is hij niet meer te
    corrigeren zodra het plafond vol staat), maar een concept dat een nieuwe
    projectbrede guardrail activeert — of een gescopede projectbreed maakt —
    kan 409 geven.

    Het event is bewust het bestaande `item.guardrail_set` resp.
    `item.guardrail_lifted`: het feit is identiek aan wat die types al betekenen,
    dus de activiteitenweergave en de SSE-consumers hoeven er niets voor te
    leren.

    De noodstop (BETON-302) gaat hier bewust NIET voor: dat slot legt agents
    stil, en dit is precies de menselijke beslissing die zo'n stilgelegd ticket
    weer vlot moet trekken — net als `lock_item`/`unlock_item` zelf. Bij
    `propose` staat de poort er wél: dat is agentwerk dat kan wachten."""
    item = _require_item(conn, ref)
    proposal = guardrails_repo.proposal(conn, item["id"])
    if proposal is None:
        raise HTTPException(status_code=409, detail=_NO_PROPOSAL)

    if proposal["kind"] == "lift":
        if not _guardrail_is_active(item):
            raise HTTPException(
                status_code=409,
                detail="Er staat geen actieve guardrail op dit ticket om op te heffen.",
            )
        with db_module.transaction(conn):
            guardrails_repo.lift(conn, item["id"])
            guardrails_repo.delete_proposal(conn, item["id"])
            events_repo.record(
                conn,
                type="item.guardrail_lifted",
                item_id=item["id"],
                actor_id=user["id"],
                payload={"guardrail": {"active": False}},
            )
        return items_repo.serialize(
            conn, items_repo.get_required(conn, item["id"]), viewer_id=user["id"]
        )

    label_ids = guardrails_repo.proposal_scope_label_ids(conn, item["id"])
    _require_project_wide_room(conn, item, label_ids)

    # Een concept kan lang blijven liggen: een voorgestelde datum die intussen
    # verstreken is zou de guardrail meteen door de review-finder laten oppakken.
    review_by = proposal["review_by"]
    if not review_by or review_by < db_module.today(conn):
        review_by = _default_review_by(conn)

    with db_module.transaction(conn):
        guardrails_repo.set_guardrail(
            conn,
            item["id"],
            text=proposal["guardrail_md"] or "",
            review_by=review_by,
            set_by=user["id"],
        )
        guardrails_repo.set_scope(conn, item["id"], label_ids)
        guardrails_repo.delete_proposal(conn, item["id"])
        events_repo.record(
            conn,
            type="item.guardrail_set",
            item_id=item["id"],
            actor_id=user["id"],
            payload={
                "guardrail": {
                    "active": True,
                    "review_by": review_by,
                    "scoped": bool(label_ids),
                }
            },
        )
    return items_repo.serialize(
        conn, items_repo.get_required(conn, item["id"]), viewer_id=user["id"]
    )


@router.post("/items/{ref}/guardrail/reject")
def reject_guardrail(
    ref: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_human),
) -> dict:
    """Wijs het openstaande concept af. Mens-only.

    Het concept verdwijnt, de actieve versie blijft exact zoals hij was en het
    event blijft in de activiteit staan — dus de historie is leesbaar.
    Idempotentie hoeft niet apart: een tweede afwijzing vindt geen concept meer
    en geeft 409."""
    item = _require_item(conn, ref)
    proposal = guardrails_repo.proposal(conn, item["id"])
    if proposal is None:
        raise HTTPException(status_code=409, detail=_NO_PROPOSAL)
    with db_module.transaction(conn):
        guardrails_repo.delete_proposal(conn, item["id"])
        events_repo.record(
            conn,
            type="item.guardrail_rejected",
            item_id=item["id"],
            actor_id=user["id"],
            payload={"guardrail": {"proposal": proposal["kind"]}},
        )
    return items_repo.serialize(
        conn, items_repo.get_required(conn, item["id"]), viewer_id=user["id"]
    )


@router.post("/items/{ref}/guardrail/lift")
def lift_guardrail(
    ref: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_human),
) -> dict:
    """Hef de guardrail op. Mens-only. De tekst blijft staan voor de historie;
    bezorging en markering stoppen meteen. Idempotent: een al opgeheven (of
    nooit gezette) guardrail levert geen tweede event op — net als `lock_item`."""
    item = _require_item(conn, ref)
    if item["guardrail_md"] is None or item["guardrail_lifted_at"] is not None:
        return items_repo.serialize(conn, item, viewer_id=user["id"])
    with db_module.transaction(conn):
        guardrails_repo.lift(conn, item["id"])
        # BETON-422: idem als bij `set_guardrail` — de mens heft hier zelf op,
        # dus een openstaand concept (van welke soort ook) is daarmee afgedaan.
        guardrails_repo.delete_proposal(conn, item["id"])
        events_repo.record(
            conn,
            type="item.guardrail_lifted",
            item_id=item["id"],
            actor_id=user["id"],
            payload={"guardrail": {"active": False}},
        )
    return items_repo.serialize(
        conn, items_repo.get_required(conn, item["id"]), viewer_id=user["id"]
    )


@router.post("/items/{ref}/relations", status_code=201)
def add_relation(
    ref: str,
    body: RelationCreate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    item = _require_item(conn, ref)
    target = _require_item(conn, body.target)
    if target["id"] == item["id"]:
        raise HTTPException(
            status_code=400, detail="Item kan niet naar zichzelf verwijzen"
        )

    stored_type, reversed_ = relations_repo.NORMALIZE[body.type]
    if reversed_:
        src, dst = target["id"], item["id"]
    else:
        src, dst = item["id"], target["id"]

    if relations_repo.reverse_exists(
        conn, item_id=src, related_item_id=dst, stored_type=stored_type
    ):
        raise HTTPException(
            status_code=409,
            detail="Tegenstrijdige relatie: de omgekeerde richting bestaat al",
        )

    with db_module.transaction(conn):
        relations_repo.create(
            conn, item_id=src, related_item_id=dst, stored_type=stored_type
        )
        event = events_repo.record(
            conn,
            type="relation.created",
            item_id=item["id"],
            actor_id=user["id"],
            payload={"type": body.type, "target": body.target},
        )
        webhooks.fanout(conn, event=event)
        # BETON-138: relates_to is symmetrisch, dus het doel-ticket hoort óók
        # een relation.created-event te zien (live-activity + UI-tweeweg).
        # Gerichte types (blocks, duplicate_of) niet: daar is de richting juist
        # het punt (alleen de bron "blokkeert iets", niet het doel).
        if stored_type == "relates_to":
            mirror = events_repo.record(
                conn,
                type="relation.created",
                item_id=target["id"],
                actor_id=user["id"],
                payload={"type": body.type, "target": ref},
            )
            webhooks.fanout(conn, event=mirror)
    return relations_repo.for_item(conn, item["id"])


def _item_is_closed(conn: sqlite3.Connection, item: sqlite3.Row) -> bool:
    """Is dit item "niet meer actief" (BETON-305)?

    De state-groep `completed`/`cancelled` dekt done/cancelled (BETON-483); een deferred-item met een nog niet
    verstreken `deferred_until` telt ook mee. Bewust NIET op `blocks_work` —
    dat vlagt óók backlog/triage/blocked, waar commenten juist wél mag
    (`webhooks.py`: `allowed_actions` bevat daar nog `comment`). Bewust NIET op
    statenaam — gemigreerde projecten heten anders. Een verstreken
    `deferred_until` blokkeert niet (zelfs als de state zelf nog niet is
    teruggevlipt door `_reactivate_due`)."""
    row = conn.execute(
        "SELECT s.grp AS grp, "
        "(i.deferred_until IS NOT NULL "
        " AND i.deferred_until > strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) AS deferred_active "
        "FROM items i LEFT JOIN states s ON s.id = i.state_id WHERE i.id = ?",
        (item["id"],),
    ).fetchone()
    if row is None:
        return False
    return states_repo.is_closed_group(row["grp"]) or bool(row["deferred_active"])


def _require_unlocked(
    item: sqlite3.Row,
    user: sqlite3.Row,
    conn: sqlite3.Connection | None = None,
    body_md: str | None = None,
    kind: str = "comment",
) -> None:
    """Noodstop (BETON-302): op een gelockt item zwijgen agents. Mensen niet.

    Los gehouden van de gesloten-guard (BETON-305) met een eigen foutmelding: een
    agent moet weten of hij tegen een slot aanloopt of tegen een gesloten ticket
    — dat vraagt om een andere actie (respectievelijk: wachten op een mens, versus
    het ticket heropenen).

    **Bewaren (BETON-338)**: met `conn`+`body_md` gaat de geweigerde tekst in de
    wachtrij, zodat hij bij het ontgrendelen alsnog geplaatst wordt. Eén plek per
    item — de tweede die aanklopt krijgt een ander bericht en wordt niet bewaard.
    Het edit-pad geeft die twee argumenten bewust niet mee: een bewerking van een
    bestaande comment is geen nieuw bericht.

    De opslag krijgt een **eigen** transactie. Nu staat deze guard vóór de
    `db.transaction()` van de comment-handler, dus dat is technisch niet nodig —
    maar zou hij ooit naar binnen schuiven, dan draait de `raise` hieronder de
    INSERT terug en verdwijnt de bewaarde comment stilzwijgend. Nooit een write
    bolt-on aan een guard die raist.

    **Vragen gaan er altijd door (BETON-339)**: de vraagmodule staat lós van de
    noodstop. Het slot legt agent-geklets stil, maar een vraag aan een mens is
    juist de nooduitgang waarmee een agent om ingrijpen vraagt — dat kanaal
    dichtzetten smoort het enige legitieme signaal dat er nog uit kan. Vragen
    tellen daarom ook niet mee voor de drempel (`comments.count_chatter`), en
    komen dus nooit in de wachtrij terecht: de stille kind-downgrade uit de
    aanleiding van dit ticket bestaat daarmee niet meer."""
    if user["kind"] != "agent" or item["locked_at"] is None or kind == "question":
        return
    queued = False
    if conn is not None and body_md is not None:
        with db_module.transaction(conn):
            queued = held_repo.hold(conn, item["id"], user["id"], body_md) is not None
    raise HTTPException(
        status_code=409,
        detail={
            "message": (
                "Dit ticket is op slot (noodstop): er wordt niet meer op "
                "gereageerd. Alleen een mens kan hem ontgrendelen. Plaats geen "
                "comment en onderneem hier verder niets."
                + (
                    " Je bericht is bewaard en wordt geplaatst zodra een mens "
                    "het slot eraf haalt — stuur het niet opnieuw."
                    if queued
                    else " Er staat al een bericht van vóór jou in de wacht; "
                    "het jouwe is niet bewaard."
                )
            ),
        },
    )


def _triage_actor_id(conn: sqlite3.Connection) -> int | None:
    """De `triage`-user als afzender van een automatisch slot (BETON-338).

    `None` als triage niet bestaat (bv. een test-db zonder seed) — dan valt het
    terug op het BETON-302-gedrag (geen actor) i.p.v. te crashen."""
    row = users_repo.get_by_handle(conn, "triage")
    return row["id"] if row else None


def _lock_notify_handles(conn: sqlite3.Connection) -> list[str]:
    """Wie moet een slot zien? De mensen — zij alleen kunnen ontgrendelen.

    Bewust niet de assignee/maker van het item: in de lus die dit moet stoppen
    (BRAND-222) zijn dat allebei agents, en juist zíj zijn stilgelegd. En bewust
    álle mensen i.p.v. een vaste persoonsnaam: het slot is een rol-eigenschap
    (mag ontgrendelen), geen persoon."""
    rows = conn.execute("SELECT handle FROM users WHERE kind = 'human' AND active = 1")
    return [r["handle"] for r in rows.fetchall()]


def _lock_item(
    conn: sqlite3.Connection, item: sqlite3.Row, actor_id: int | None, *, reason: str
) -> None:
    """Zet het slot erop + notificeer de mensen (BETON-302).

    Bij de automatische drempel is de actor `triage` (BETON-338): niet de agent
    die toevallig de tiende comment plaatste zette het slot — triage is de
    hoeder van Betonning en dus de juiste afzender. Vóór BETON-338 stond hier
    `None`, wat in de tijdlijn als `@?` verscheen.

    Het oorspronkelijke bezwaar tegen een actor vervalt bij triage: `fanout`
    slaat de actor over, dus een *agent* als actor zou zichzelf uit zijn eigen
    stop-notificatie filteren — maar triage staat sowieso niet in
    `_lock_notify_handles` (dat zijn alleen mensen), dus er wordt niemand
    weggefilterd die de notificatie nodig heeft. Valt triage weg (niet-geseede
    db), dan blijft het `None` en werkt alles zoals voorheen.

    `directed=True`: dit event is uitsluitend voor de mensen. Zonder die vlag
    valt de assignee-agent er automatisch bij in en leest die er een opdracht in
    (BETON-282) — precies de reactie die de noodstop moet voorkomen."""
    items_repo.lock(conn, item["id"])
    event = events_repo.record(
        conn,
        type="item.locked",
        item_id=item["id"],
        actor_id=actor_id,
        payload={"reason": reason},
    )
    webhooks.fanout(
        conn, event=event, mentions=_lock_notify_handles(conn), directed=True
    )


def _may_still_close_comment(conn: sqlite3.Connection, item_id: int, user_id: int) -> bool:
    """Mag `user_id` (een agent) nog commenten op dit gesloten item? (BETON-305)

    Uitzondering: wie het item zélf zojuist sloot mag zijn afsluit-comment nog
    plaatsen — dat is de gedocumenteerde `set_state(done)` → afsluit-comment-
    workflow. Bepaald via het event-log (niet een tijdvenster): de laatste
    `item.updated` met een state-wijziging wijst de sluiter aan. Maar alleen
    de éérste comment ná dat sluitmoment — geen eindeloos napraten."""
    closing_event = conn.execute(
        "SELECT actor_id, created_at FROM events WHERE item_id = ? "
        "AND type = 'item.updated' AND json_extract(payload, '$.state') IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (item_id,),
    ).fetchone()
    if closing_event is None or closing_event["actor_id"] != user_id:
        return False
    already_commented = conn.execute(
        "SELECT 1 FROM comments WHERE item_id = ? AND author_id = ? AND created_at > ? "
        "LIMIT 1",
        (item_id, user_id, closing_event["created_at"]),
    ).fetchone()
    return already_commented is None


@router.post("/items/{ref}/comments", status_code=201)
def add_comment(
    ref: str,
    body: CommentCreate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    item = _require_item(conn, ref)
    # BETON-305: agents reageren niet meer op een gesloten item — behalve wie
    # het zojuist zelf sloot (afsluit-comment). Mensen mogen altijd.
    if (
        user["kind"] == "agent"
        and _item_is_closed(conn, item)
        and not _may_still_close_comment(conn, item["id"], user["id"])
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Dit ticket is gesloten; agents reageren er niet meer op. "
                    "Ben je het er niet mee eens? Zet hem terug op `todo` en "
                    "plaats dán een comment met de reden."
                ),
            },
        )
    # BETON-302: noodstop — op een gelockt item zwijgen agents volledig. Ná de
    # gesloten-guard, want die is specifieker (een gesloten ticket kan een agent
    # zelf heropenen; een slot niet).
    _require_unlocked(item, user, conn, body.body_md, body.kind)
    # Vraagmodule (BETON-219): opties horen alleen bij een 'question'; een lege
    # of dubbele optie is misbruik → 422. Iedereen mag een vraag STELLEN, maar
    # een AGENT mag hem alleen aan een mens RICHTEN (BETON-307, BRAND-257) —
    # een mens die vraagt blijft ongemoeid, ook zonder mention/human-assignee.
    options = _validate_question(body.kind, body.options, body.body_md)
    if body.kind == "question" and user["kind"] == "agent":
        _require_human_addressee(conn, item, body.body_md)
    # Idempotency-vangnet (BETON-217): een double-submit (key-repeat op
    # Cmd+Enter, client-retry) plaatste dezelfde comment 4× binnen 12ms — elke
    # kopie fant uit naar agents, die dan dubbel antwoorden. Exact dezelfde
    # tekst van dezelfde auteur binnen ~10s → geef de bestaande comment terug,
    # zonder nieuwe row/event/fanout. Vragen slaan we niet dedup — een vraag is
    # bewust, en een tweede identieke vraag kan een echte heropening zijn.
    if body.kind == "comment":
        dup = comments_repo.recent_duplicate(
            conn, item_id=item["id"], author_id=user["id"], body_md=body.body_md
        )
        if dup is not None:
            return comments_repo.serialize(conn, dup)
    with db_module.transaction(conn):
        row = comments_repo.create(
            conn,
            item_id=item["id"],
            author_id=user["id"],
            body_md=body.body_md,
            kind=body.kind,
            question_options=options,
        )
        if body.kind == "question" and user["kind"] == "agent":
            # BETON-431: een open vraag aan een mens hoort bij die mens op het
            # bord. Menselijke vragers wijzen niets toe.
            question_assign.assign_for_question(
                conn,
                item_id=item["id"],
                question_id=row["id"],
                body_md=body.body_md,
                actor_id=user["id"],
            )
        event = events_repo.record(
            conn,
            type="comment.created",
            item_id=item["id"],
            actor_id=user["id"],
            payload={"comment_id": row["id"]},
        )
        # BETON-211/216: een comment mét @mentions is gericht — alleen de
        # gementionden (+ subscribe_all) krijgen hem, de assignee alleen als
        # hij zelf gementiond is. Zonder mentions is de comment ongericht en
        # blijft de assignee de ontvanger. Eerdere participants tellen niet
        # meer mee. Anders praten agents mee op vragen die niet aan hen
        # gericht waren (BRAND-150: Joop antwoordde op een vraag aan Lobke).
        mentioned = mentions_mod.parse(body.body_md)
        webhooks.fanout(conn, event=event, mentions=mentioned, directed=bool(mentioned))
        # BETON-302: de comment die de drempel raakt gaat er nog in — dán klapt
        # het dicht. In dezelfde transactie als de comment: een slot dat niet
        # samen met zijn aanleiding wordt vastgelegd, klopt niet.
        if comments_repo.count_chatter(conn, item["id"]) >= item["comment_limit"]:
            _lock_item(conn, item, _triage_actor_id(conn), reason="comment_limit")
    return comments_repo.serialize(conn, row)


@router.get("/items/{ref}/activity")
def item_activity(
    ref: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    item = _require_item(conn, ref)
    return [
        events_repo.serialize(conn, e)
        for e in events_repo.list_for_item(conn, item["id"])
    ]


# Verzoekveld → sleutel in de geserialiseerde item-representatie.
_UPDATE_TO_SERIALIZED = {
    "title": "title",
    "description_md": "description_md",
    "state": "state",
    "priority": "priority",
    "workload": "workload",
    "assignee": "assignee",
    "parent": "parent",
    "milestone": "milestone",
    "labels": "labels",
    "deferred_until": "deferred_until",
    "due_date": "due_date",
}
# Velden waar een lege waarde ("" of null) "wissen" betekent (→ serialize None).
# BETON-311: workload wissen ("" → NULL) betekent "weer als niet-geschat".
_CLEARABLE = ("state", "assignee", "parent", "milestone", "due_date", "workload")

# Suggestie-comment als alle subtaken afgerond zijn (BETON-50). De marker maakt
# het idempotent: is hij er al, dan wordt niet opnieuw gepost.
_SUBTASKS_DONE_MARKER = "[Subtaken]"


def _parent_addressed_to(conn: sqlite3.Connection, parent: sqlite3.Row) -> list[str]:
    """Wie moet de parent-close-suggestie/auto-close-melding zien? (BETON-303)

    De assignee van de ouder (of anders diens maker) — niet de agent die
    toevallig de laatste subtaak sloot, want die schreef het bericht niet."""
    handle_id = parent["assignee_id"] or parent["created_by"]
    if handle_id is None:
        return []
    user = users_repo.get(conn, handle_id)
    return [user["handle"]] if user is not None else []


def _maybe_suggest_close_parent(
    conn: sqlite3.Connection, child: sqlite3.Row, actor_id: int
) -> None:
    """Reageer op het afronden van de láátste levende subtaak van een ouder.

    Twee smaken (BETON-50 + BETON-215):
    - **Agent-umbrella** (Hermes-maker + container-signaal, zie
      ``triage.agent_umbrella_reason``): sluit de umbrella automatisch — het is
      een intern container-ticket (bv. een deliberatie-overleg), de mens hoeft
      er niet over te beslissen. Idempotent: een al-gesloten ouder blijft dicht.
    - **Gewone ouder**: één suggestie-comment ("kan dit item dicht?") — géén
      auto-close, de mens beslist. Idempotent via de comment-marker.

    Beide comments komen op naam van `triage` (BETON-303, niet op naam van
    `actor_id`, de agent die toevallig de laatste subtaak sloot — die heeft het
    bericht nooit geschreven). `actor_id` blijft de actor van de state-wijziging
    zelf (het item.updated-event bij de umbrella-auto-close)."""
    parent_id = child["parent_id"]
    if parent_id is None:
        return
    done, total = items_repo.children_counts(conn, parent_id)
    if total == 0 or done < total:
        return

    parent = items_repo.get(conn, parent_id)
    if parent is None:
        return
    triage_user = users_repo.get_by_handle(conn, "triage")
    triage_actor_id = triage_user["id"] if triage_user is not None else None
    addressed_to = _parent_addressed_to(conn, parent)

    # BETON-215: agent-interne umbrella's automatisch sluiten.
    if triage_mod.agent_umbrella_reason(conn, parent) is not None:
        cur_state = conn.execute(
            "SELECT s.grp AS grp FROM items i JOIN states s ON s.id = i.state_id "
            "WHERE i.id = ?",
            (parent_id,),
        ).fetchone()
        if cur_state is not None and states_repo.is_closed_group(cur_state["grp"]):
            return  # al gesloten — niets te doen
        done_state = conn.execute(
            "SELECT id, name FROM states WHERE project_id = ? AND grp = 'completed' "
            "ORDER BY sort_order LIMIT 1",
            (parent["project_id"],),
        ).fetchone()
        if done_state is not None:
            old_state = items_repo.serialize(conn, parent)["state"]
            items_repo.update(conn, parent_id, {"state_id": done_state["id"]})
            event = events_repo.record(
                conn,
                type="item.updated",
                item_id=parent_id,
                actor_id=actor_id,
                payload={"state": {"from": old_state, "to": done_state["name"]}},
            )
            webhooks.fanout(conn, event=event)
            if triage_actor_id is not None:
                # Geen addressed_to: de comment werd hiervóór ook al niet
                # gefanout (alleen het item.updated-event) — de umbrella-maker
                # kreeg dus nooit een tweede ping voor de close-comment zelf.
                # Dat blijft zo; anders voegt deze fix juist ruis toe.
                triage_mod.post_triage_comment(
                    conn,
                    parent,
                    outbound("parent.auto_close"),
                    triage_actor_id,
                )
            return
        # Geen completed-state in dit project → val terug op de suggestie.

    existing = comments_repo.list_for_item(conn, parent_id)
    if any(_SUBTASKS_DONE_MARKER in c["body_md"] for c in existing):
        return
    if triage_actor_id is None:
        return  # geen triage-user in dit systeem → geen suggestie plaatsen
    body = outbound("parent.suggest_close")
    triage_mod.post_triage_comment(
        conn, parent, body, triage_actor_id, addressed_to=addressed_to
    )


def _reactivate_due(conn: sqlite3.Connection) -> None:
    """Lichte self-heal (BETON-39): zet verlopen deferred-items terug naar actief.

    Alleen een write-transactie als er echt iets verlopen is, zodat een gewone
    read niet onnodig het schrijfslot pakt. Een echte periodieke lus in de
    lifespan zou netter zijn, maar server.py valt buiten deze stream; daarom
    haakt de sweep opportunistisch aan de item-detail-read."""
    due = conn.execute(
        "SELECT 1 FROM items WHERE deferred_until IS NOT NULL AND archived_at IS NULL "
        "AND deferred_until <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now') LIMIT 1"
    ).fetchone()
    if due is None:
        return
    with db_module.transaction(conn):
        affected = items_repo.reactivate_deferred(conn)
        webhooks.notify_reactivations(conn, affected)


def _normalize_requested(key: str, value):
    """Zet een verzoekwaarde om naar de vorm die serialize zou teruggeven."""
    if key in _CLEARABLE and not value:
        return None
    if key == "labels":
        return sorted(value or [])
    return value


def _changed_keys(data: dict, old: dict) -> list[str]:
    """De verzoekvelden die de itemwaarde echt wijzigen (geen no-ops)."""
    changed = []
    for key in data:
        current = sorted(old["labels"]) if key == "labels" else old[key]
        if _normalize_requested(key, data[key]) != current:
            changed.append(key)
    return changed


@router.patch("/items/{ref}")
def update_item(
    ref: str,
    body: ItemUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict:
    item = _require_item(conn, ref)
    project = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (item["project_id"],)
    ).fetchone()

    data = body.model_dump(exclude_unset=True)
    handover = data.pop("handover_md", None)
    old = items_repo.serialize(conn, item)

    # Optimistic concurrency (BETON-44): de If-Match-header wint van het body-veld.
    # Zonder precondition blijft het gedrag last-writer-wins (backwards compatible).
    body_expected = data.pop("expected_updated_at", None)
    expected = if_match if if_match is not None else body_expected
    if expected is not None and expected != old["updated_at"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Item is intussen gewijzigd (updated_at komt niet overeen)",
                "item": old,
            },
        )

    # deferred_until (BETON-39) apart afhandelen: zetten verplaatst het item naar
    # de `deferred`-state; wissen terwijl de state nog deferred is, verplaatst het
    # terug naar de actieve default-state (BETON-165) — zonder deze flip bleef een
    # item in Deferred hangen en werd het nooit meer door de reactivate-loop
    # opgepikt (die filtert juist op `deferred_until IS NOT NULL`).
    deferred_provided = "deferred_until" in data
    deferred_val = data.pop("deferred_until", None) or None
    deferred_changed = deferred_provided and deferred_val != old["deferred_until"]
    # Impliciete state-flips alleen als de caller niet zelf een state meegeeft
    # (expliciete state in dezelfde PATCH wint altijd).
    implicit_defer_state = (
        deferred_changed and deferred_val is not None and not data.get("state")
    )
    implicit_undefer_state = (
        deferred_changed
        and deferred_val is None
        and old["state"] == "deferred"
        and not data.get("state")
    )

    # plan_md (BETON-218) apart afhandelen: het plan zit bewust niet in de
    # serialisatie (te groot voor elk get_item/list), dus de generieke
    # _changed_keys-vergelijking tegen `old` kan er niet bij. Vergelijk direct
    # met de kolomwaarde; "" of null wist (zelfde idioom als due_date).
    plan_provided = "plan_md" in data
    plan_val = data.pop("plan_md", None) or None
    plan_changed = plan_provided and plan_val != (item["plan_md"] or None)

    changed = _changed_keys(data, old)
    if not changed and not deferred_changed and not plan_changed:
        # Niets wijzigt echt → geen write, geen event, geen fanout.
        return old

    # BETON-469: een mens hoeft geen thread terug te lezen om te weten wat nodig is.
    handover_body = None
    if user["kind"] == "agent" and "assignee" in changed and data.get("assignee"):
        target = users_repo.get_by_handle(conn, data["assignee"])
        if target is not None and target["kind"] == "human":
            own_question = any(
                q["author_id"] == user["id"]
                for q in comments_repo.open_questions_for_item(conn, item["id"])
            )
            if not own_question and not handover:
                raise HTTPException(
                    status_code=422,
                    detail=("Wijs je een ticket aan een mens toe, zeg dan in "
                            "`handover_md` (max 300 tekens) wat je van die persoon "
                            "nodig hebt, of stel een vraag met `ask_question`."),
                )
            if handover:
                _require_unlocked(item, user)
                if _item_is_closed(conn, item) and not _may_still_close_comment(
                    conn, item["id"], user["id"]
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Heropen het ticket voordat je een overdrachtsnotitie plaatst",
                    )
                handover_body = outbound("handover.note", handle=target["handle"], body=handover)

    # BETON-431: staat er een open vraag voor een mens, dan blijft het ticket
    # bij die mens. Een agent mag de toewijzing niet wegzetten; het antwoord
    # geeft het ticket vanzelf terug. Mensen mogen altijd.
    if "assignee" in changed and question_assign.blocks_reassign(
        conn,
        item,
        user,
        _resolve_assignee_id(conn, data["assignee"]) if data["assignee"] else None,
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Er staat een open vraag voor een mens op dit ticket, dus het "
                    "blijft aan die mens toegewezen tot de vraag beantwoord is. "
                    "Het ticket komt na het antwoord vanzelf terug; zet de "
                    "toewijzing niet zelf terug."
                ),
            },
        )

    # BETON-454: een agent sluit een ticket niet af terwijl er een open vraag
    # staat — trek hem eerst in (`withdraw_question`) of laat de mens antwoorden.
    # Mensen mogen altijd. Triage en het deferred-mechanisme lopen niet langs
    # deze route (in-process resp. geen completed/cancelled-groep).
    if user["kind"] != "human" and data.get("state"):
        target = states_repo.get_by_name(conn, item["project_id"], data["state"])
        if target is not None and target["grp"] in ("completed", "cancelled"):
            open_qs = comments_repo.open_questions_for_item(conn, item["id"])
            if open_qs:
                first = (open_qs[0]["body_md"] or "").strip().splitlines()
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": (
                            f"Er staat nog een open vraag op dit ticket "
                            f"(comment {open_qs[0]['id']}: "
                            f"{(first[0] if first else '')[:120]}). Is het "
                            "antwoord elders gekomen, trek hem dan in met "
                            "`withdraw_question`; anders wacht op het antwoord."
                        ),
                    },
                )

    # BETON-301: zodra een ticket comments heeft, liggen omschrijving en plan
    # vast — daarna gaat alles via comments. Alleen relevant bij een échte
    # wijziging (na de no-op-return hierboven), en alleen voor agents; een mens
    # moet een ticket kunnen blijven corrigeren.
    if (
        user["kind"] == "agent"
        and ("description_md" in changed or plan_changed)
        and comments_repo.count_for_item(conn, item["id"]) > 0
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Dit ticket heeft al comments; omschrijving en plan liggen "
                    "vast. Zet aanvullingen in een comment."
                ),
            },
        )

    # BETON-191/194: als iemand het item aan een ander (mens of agent) overdraagt
    # terwijl het in-progress (grp='started') staat, hoort het niet in de "wordt
    # actief aan gewerkt"-kolom te blijven hangen — een nieuwe assignee begint
    # immers vers, niet halverwege. Zet het dan terug naar de actieve default-state
    # (todo), tenzij de caller in dezelfde PATCH zelf een state (of deferred)
    # meegeeft. De actor≠assignee-poort voorkomt dat iemand die het werk zélf
    # oppakt (zichzelf toewijst) meteen naar todo teruggetrokken wordt; alleen een
    # échte overdracht telt. Backlog en gesloten states (done/cancelled) blijven
    # ongemoeid — de flip geldt uitsluitend vanuit 'started'.
    implicit_handoff_to_todo = False
    if (
        "assignee" in changed
        and data.get("assignee")
        and not data.get("state")
        and not deferred_changed
    ):
        new_assignee = users_repo.get_by_handle(conn, data["assignee"])
        cur_state = conn.execute(
            "SELECT grp FROM states WHERE id = ?", (item["state_id"],)
        ).fetchone()
        implicit_handoff_to_todo = (
            new_assignee is not None
            and new_assignee["id"] != user["id"]
            and cur_state is not None
            and cur_state["grp"] == "started"
        )

    fields: dict = {}
    for plain in ("title", "description_md", "priority", "workload"):
        if plain in changed:
            fields[plain] = data[plain]
    if "state" in changed:
        fields["state_id"] = (
            _resolve_state_id(conn, project, data["state"]) if data["state"] else None
        )
    if "assignee" in changed:
        fields["assignee_id"] = (
            _resolve_assignee_id(conn, data["assignee"]) if data["assignee"] else None
        )
    if "parent" in changed:
        fields["parent_id"] = (
            _resolve_parent_id(
                conn, data["parent"], project_id=item["project_id"], child_id=item["id"]
            )
            if data["parent"]
            else None
        )
    if "milestone" in changed:
        fields["milestone_id"] = (
            _resolve_milestone_id(conn, project, data["milestone"])
            if data["milestone"]
            else None
        )
    if "due_date" in changed:
        # Puur informatief/filterbaar; "" of null wist de datum (BETON-53).
        fields["due_date"] = data["due_date"] or None

    if deferred_changed:
        fields["deferred_until"] = deferred_val
    if plan_changed:
        fields["plan_md"] = plan_val
    if implicit_defer_state:
        fields["state_id"] = _resolve_state_id(conn, project, "deferred")
    if implicit_undefer_state:
        # BETON-199: terug naar waar het item vandaan kwam vóór het uitstellen,
        # niet blind naar todo/default (tenzij dat niet bekend is, bv. rechtstreeks
        # in deferred aangemaakt).
        fields["state_id"] = items_repo.restore_state_id(
            conn, project["id"], item["deferred_from_state_id"]
        )
    if implicit_handoff_to_todo:
        # Alleen als er echt een actieve state is om naar terug te vallen; anders
        # de state ongemoeid laten (nooit per ongeluk naar NULL wissen).
        todo_id = items_repo.default_active_state_id(conn, project["id"])
        if todo_id is not None:
            fields["state_id"] = todo_id
        else:
            implicit_handoff_to_todo = False

    # BETON-199: onthoud/wis waar het item vandaan kwam zodra de (nieuwe) state
    # het item in/uit deferred beweegt, ongeacht of dat impliciet (bovenstaand)
    # of expliciet (caller geeft zelf `state` mee) gebeurt — zo blijft de reactivatie
    # (`reactivate_deferred`) ook kloppen na een handmatige state-wijziging.
    if "state_id" in fields:
        new_state_id = fields["state_id"]
        new_state_row = (
            conn.execute(
                "SELECT name FROM states WHERE id = ?", (new_state_id,)
            ).fetchone()
            if new_state_id is not None
            else None
        )
        entering_deferred = (
            new_state_row is not None and new_state_row["name"] == "deferred"
        )
        if entering_deferred:
            if old["state"] != "deferred":
                fields["deferred_from_state_id"] = item["state_id"]
        elif old["state"] == "deferred":
            fields["deferred_from_state_id"] = None

    labels_changed = "labels" in changed
    if labels_changed:
        label_ids = [
            _resolve_label_id(conn, project, name) for name in (data["labels"] or [])
        ]

    # Welke geserialiseerde velden in het event-payload komen (incl. deferred +
    # een impliciete state-flip naar Deferred).
    payload_keys = list(changed)
    if deferred_changed:
        payload_keys.append("deferred_until")
    implicit_state_flip = (
        implicit_defer_state or implicit_undefer_state or implicit_handoff_to_todo
    )
    if implicit_state_flip and "state" not in payload_keys:
        payload_keys.append("state")

    with db_module.transaction(conn):
        updated = items_repo.update(conn, item["id"], fields)
        assert updated is not None
        if labels_changed:
            labels_repo.set_for_item(conn, item["id"], label_ids)
        new = items_repo.serialize(conn, updated)

        payload = {
            key: {
                "from": old[_UPDATE_TO_SERIALIZED[key]],
                "to": new[_UPDATE_TO_SERIALIZED[key]],
            }
            for key in payload_keys
        }
        # BETON-218: het plan kan groot zijn — het event markeert alléén dat het
        # wijzigde (geen from/to-inhoud), anders blaast elke plan-edit het
        # event-log en de webhook-payloads op.
        if plan_changed:
            payload["plan_md"] = {"changed": True, "cleared": plan_val is None}
        if handover_body:
            note = comments_repo.create(
                conn, item_id=item["id"], author_id=user["id"], body_md=handover_body
            )
            note_event = events_repo.record(
                conn, type="comment.created", item_id=item["id"],
                actor_id=user["id"], payload={"comment_id": note["id"]},
            )
            webhooks.fanout(
                conn, event=note_event,
                mentions=mentions_mod.parse(handover_body), directed=True,
            )
            payload["handover_md"] = handover
            payload["handover_comment_id"] = note["id"]
            if comments_repo.count_chatter(conn, item["id"]) >= item["comment_limit"]:
                _lock_item(conn, item, _triage_actor_id(conn), reason="comment_limit")
        event = events_repo.record(
            conn,
            type="item.updated",
            item_id=item["id"],
            actor_id=user["id"],
            payload=payload,
        )
        # De detailvorm werd vóór het nieuwe event opgebouwd (BETON-470).
        if "assignee" in changed:
            new["previous_assignee"] = old["assignee"] if new["assignee"] else None
        # Alleen níeuw toegevoegde description-mentions notificeren (geen spam).
        added_mentions = set(mentions_mod.parse(new["description_md"])) - set(
            mentions_mod.parse(old["description_md"])
        )
        work_unblocked = "state" in changed and webhooks.work_was_unblocked(
            conn, item["state_id"], updated["state_id"]
        )
        webhooks.fanout(
            conn,
            event=event,
            mentions=added_mentions,
            include_prior_participants=work_unblocked,
        )
        # Alle subtaken van de ouder afgerond? → één suggestie-comment (BETON-50).
        if "state" in changed:
            _maybe_suggest_close_parent(conn, item, user["id"])
    if handover_body:
        # De notitie kan de commentdrempel raken: geef ook het nieuwe slot terug.
        return items_repo.serialize(conn, items_repo.get_required(conn, item["id"]), viewer_id=user["id"])
    return new


@router.delete("/items/{ref}/relations")
def delete_relation(
    ref: str,
    body: RelationCreate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    item = _require_item(conn, ref)
    target = _require_item(conn, body.target)
    stored_type, reversed_ = relations_repo.NORMALIZE[body.type]
    if reversed_:
        src, dst = target["id"], item["id"]
    else:
        src, dst = item["id"], target["id"]

    with db_module.transaction(conn):
        removed = relations_repo.delete(
            conn, item_id=src, related_item_id=dst, stored_type=stored_type
        )
        if removed == 0:
            raise HTTPException(status_code=404, detail="Relatie bestaat niet")
        event = events_repo.record(
            conn,
            type="relation.deleted",
            item_id=item["id"],
            actor_id=user["id"],
            payload={"type": body.type, "target": body.target},
        )
        webhooks.fanout(conn, event=event)
        # BETON-138: relates_to is symmetrisch → mirror-event op het doel-ticket
        # (zie add_relation voor dezelfde afweging).
        if stored_type == "relates_to":
            mirror = events_repo.record(
                conn,
                type="relation.deleted",
                item_id=target["id"],
                actor_id=user["id"],
                payload={"type": body.type, "target": ref},
            )
            webhooks.fanout(conn, event=mirror)
    return relations_repo.for_item(conn, item["id"])


def _require_comment(
    conn: sqlite3.Connection, item: sqlite3.Row, comment_id: int
) -> sqlite3.Row:
    comment = comments_repo.get(conn, comment_id)
    if comment is None or comment["item_id"] != item["id"]:
        raise HTTPException(status_code=404, detail=f"Onbekende comment: {comment_id}")
    return comment


@router.patch("/items/{ref}/comments/{comment_id}")
def update_comment(
    ref: str,
    comment_id: int,
    body: CommentUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    item = _require_item(conn, ref)
    comment = _require_comment(conn, item, comment_id)
    if comment["author_id"] != user["id"]:
        raise HTTPException(
            status_code=403, detail="Alleen de auteur mag deze comment wijzigen"
        )
    # BETON-305: een bewerking kan nieuwe mentions toevoegen en dus opnieuw
    # fanouten — dat is dezelfde ruis als een nieuwe comment. Geen
    # sluiter-uitzondering hier: die geldt voor de afsluit-comment zelf
    # (add_comment), niet voor het wijzigen van een oude comment.
    if user["kind"] == "agent" and _item_is_closed(conn, item):
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Dit ticket is gesloten; agents wijzigen hun comments er "
                    "niet meer op. Zet het ticket terug op `todo` als een "
                    "correctie echt nodig is."
                ),
            },
        )
    # BETON-302: idem voor de noodstop — een edit fant opnieuw uit, dus een
    # gelockt ticket zou via de achterdeur alsnog agents wakker maken.
    # BETON-339: een vráág mag wél bijgewerkt worden op een gelockt ticket —
    # zelfde redenering als bij het plaatsen (de nooduitgang blijft open).
    # Géén `body_md` meegeven: een edit is geen nieuw bericht en hoort niet in
    # de wachtrij.
    _require_unlocked(item, user, kind=comment["kind"])

    with db_module.transaction(conn):
        row = comments_repo.update(conn, comment_id, body.body_md)
        event = events_repo.record(
            conn,
            type="comment.updated",
            item_id=item["id"],
            actor_id=user["id"],
            payload={"comment_id": comment_id},
        )
        # Alleen níeuwe mentions in de bewerkte comment notificeren. `directed`
        # kijkt naar de héle nieuwe body (BETON-216): bevat de comment nu
        # mentions, dan is hij gericht en wordt de assignee niet nogmaals
        # getriggerd door de bewerking.
        new_mentions = set(mentions_mod.parse(body.body_md))
        added = new_mentions - set(mentions_mod.parse(comment["body_md"]))
        webhooks.fanout(conn, event=event, mentions=added, directed=bool(new_mentions))
    return comments_repo.serialize(conn, row)


@router.delete("/items/{ref}/comments/{comment_id}", status_code=204)
def delete_comment(
    ref: str,
    comment_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> None:
    item = _require_item(conn, ref)
    comment = _require_comment(conn, item, comment_id)
    if comment["author_id"] != user["id"]:
        raise HTTPException(
            status_code=403, detail="Alleen de auteur mag deze comment verwijderen"
        )

    with db_module.transaction(conn):
        comments_repo.delete(conn, comment_id)
        events_repo.record(
            conn,
            type="comment.deleted",
            item_id=item["id"],
            actor_id=user["id"],
            payload={"comment_id": comment_id},
        )


def _resolve_answer(
    question: sqlite3.Row, body: AnswerCreate
) -> tuple[str, int | None]:
    """Leid (antwoordtekst, optie-index) af uit een vraag + antwoord-body.

    Precies één van ``text``/``option_index`` (anders 422); bij een keuze moet de
    index binnen de opties vallen. Bij een keuze wordt de optietekst de
    antwoordtekst, zodat het inline te tonen is."""
    has_text = body.text is not None
    has_index = body.option_index is not None
    if has_text == has_index:
        raise HTTPException(
            status_code=422, detail="Geef precies één van 'text' of 'option_index'"
        )
    if body.option_index is not None:
        options = question["question_options"]
        opts = json.loads(options) if options else []
        if body.option_index < 0 or body.option_index >= len(opts):
            raise HTTPException(status_code=422, detail="option_index buiten bereik")
        return opts[body.option_index], body.option_index
    assert body.text is not None
    return body.text, None


@router.post("/comments/{comment_id}/answer")
def answer_question(
    comment_id: int,
    body: AnswerCreate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    """Beantwoord een vraag-comment (BETON-219/265/262).

    Het antwoord staat inline op de vraag zelf (``answer_text``/
    ``answer_option_index``) — géén los comment meer (BETON-265). Body: precies één
    van ``text`` (vrije tekst) of ``option_index`` (keuze uit de opties).
    Idempotent: een al beantwoorde vraag → 409. De vragensteller wordt pas
    genotificeerd zodra álle vragen op het item beantwoord zijn, na een
    grace-venster (BETON-262)."""
    question = comments_repo.get(conn, comment_id)
    if question is None:
        raise HTTPException(status_code=404, detail=f"Onbekende comment: {comment_id}")
    if question["kind"] != "question":
        raise HTTPException(status_code=422, detail="Deze comment is geen vraag")
    if question["answered_at"] is not None:
        raise HTTPException(status_code=409, detail="Vraag is al beantwoord")
    if question["withdrawn_at"] is not None:
        raise HTTPException(status_code=409, detail="Vraag is ingetrokken")

    answer_text, answer_index = _resolve_answer(question, body)

    with db_module.transaction(conn):
        comments_repo.mark_answered(
            conn,
            comment_id,
            answered_by=user["id"],
            answer_text=answer_text,
            answer_option_index=answer_index,
        )
        # Het event legt vast wie de vraag stelde; de fanout wordt uitgesteld tot
        # release (BETON-262). De actor (antwoorder) krijgt nooit zijn eigen event.
        events_repo.record(
            conn,
            type="question.answered",
            item_id=question["item_id"],
            actor_id=user["id"],
            payload={"comment_id": comment_id},
        )
        # BETON-375: een stale-vraag heeft een vast, deterministisch gevolg —
        # geen LLM-ronde. Handel hem hier af, vóór de release/reassign-logica
        # hieronder, zodat het antwoord meteen zichtbaar is in de state.
        _apply_stale_answer_if_any(conn, question, answer_index, user)
        # BETON-420: idem voor de reviewvraag op een verlopen guardrail.
        _apply_guardrail_review_answer_if_any(conn, question, answer_index, user)
        # Geef de ingehouden antwoord-notificaties vrij zodra er geen open vragen
        # meer op het item zijn.
        webhooks.release_answer_notifications(conn, question["item_id"])
        # BETON-285: als alle vragen op het item beantwoord zijn en de huidige
        # assignee is de mens die zojuist antwoordde, gaat de toewijzing terug
        # naar de auteur van de laatst gestelde vraag — die kan dan weer verder.
        # Alléén als de assignee nu precies de antwoorder is (de expliciete overdrachtsregel):
        # een toewijzing die iemand bewust ergens anders neerzette, overschrijven
        # we nooit.
        if not comments_repo.open_questions_for_item(conn, question["item_id"]):
            current_item = items_repo.get(conn, question["item_id"])
            if (
                current_item is not None
                and user["kind"] == "human"
                and current_item["assignee_id"] == user["id"]
            ):
                answered = comments_repo.answered_questions_for_item(
                    conn, question["item_id"]
                )
                last_question = answered[-1] if answered else None
                asker_id = last_question["author_id"] if last_question else None
                asker = users_repo.get(conn, asker_id) if asker_id is not None else None
                # BETON-431: een vraag van triage onthoudt wie het ticket vóór
                # de vraag had (`prior_assignee_id`). Daar gaat het naartoe —
                # triage stelde de vraag alleen, hij werkt er niet aan, dus
                # teruggeven aan de vraagsteller zou het ticket bij de bot
                # parkeren. Dit vervangt voor nieuwe vragen de stale/review-
                # uitzondering hieronder.
                prior_id = (
                    last_question["prior_assignee_id"]
                    if last_question is not None
                    else None
                )
                from_triage = asker is not None and asker["handle"] == "triage"
                if from_triage and prior_id is not None:
                    asker = users_repo.get(conn, prior_id)
                    asker_id = prior_id
                    stale = False
                else:
                    # BETON-375: een stale-vraag is de uitzondering (historische
                    # vragen zonder prior). Triage stelde hem, maar hij "wacht"
                    # er niet op om verder te kunnen — het item teruggeven aan
                    # triage zou een lopend ticket bij de bot parkeren in plaats
                    # van bij wie eraan werkt.
                    # BETON-420: een guardrail-REVIEWvraag valt onder dezelfde
                    # uitzondering — triage stelde hem, maar wacht er niet op.
                    stale = last_question is not None and (
                        triage_mod.is_stale_question(last_question["body_md"])
                        or triage_mod.is_guardrail_review_question(
                            last_question["body_md"]
                        )
                    )
                if asker is not None and asker["id"] != user["id"] and not stale:
                    # Géén fanout: release_answer_notifications hierboven heeft
                    # de vraagsteller al gericht genotificeerd over ditzelfde
                    # feit, dus een fanout hier zou een dubbele notificatie zijn.
                    question_assign.reassign_silently(
                        conn, current_item, asker_id, actor_id=user["id"]
                    )
    return comments_repo.serialize(conn, comments_repo.get_required(conn, comment_id))


@router.post("/comments/{comment_id}/withdraw")
def withdraw_question(
    comment_id: int,
    body: QuestionWithdraw,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    """Trek een open vraag in (BETON-454), bv. omdat het antwoord elders kwam.

    Iedereen mag dat, ook een agent die de vraag niet zelf stelde: wie merkt
    dat een vraag achterhaald is, sluit hem (BETON-481; daarvoor bleven zulke
    vragen open). De reden is verplicht en staat op de vraag. 409 als de vraag
    al beantwoord of ingetrokken is. Een ingetrokken vraag is niet meer open.
    Was het de laatste open vraag, dan gaat het ticket terug naar
    `prior_assignee_id` (BETON-431) en komen ingehouden antwoord-notificaties
    vrij. Event `question.withdrawn` zonder fanout."""
    question = comments_repo.get(conn, comment_id)
    if question is None:
        raise HTTPException(status_code=404, detail=f"Onbekende comment: {comment_id}")
    if question["kind"] != "question":
        raise HTTPException(status_code=422, detail="Deze comment is geen vraag")
    if question["answered_at"] is not None:
        raise HTTPException(status_code=409, detail="Vraag is al beantwoord")
    if question["withdrawn_at"] is not None:
        raise HTTPException(status_code=409, detail="Vraag is al ingetrokken")

    with db_module.transaction(conn):
        # Her-check binnen de schrijf-lock: een gelijktijdig antwoord of
        # intrekking mag niet beide slagen.
        fresh = comments_repo.get(conn, comment_id)
        assert fresh is not None
        if fresh["answered_at"] is not None or fresh["withdrawn_at"] is not None:
            raise HTTPException(status_code=409, detail="Vraag is al afgehandeld")
        comments_repo.mark_withdrawn(conn, comment_id, reason=body.reason.strip())
        events_repo.record(
            conn,
            type="question.withdrawn",
            item_id=question["item_id"],
            actor_id=user["id"],
            payload={"comment_id": comment_id},
        )
        webhooks.release_answer_notifications(conn, question["item_id"])
        prior_id = question["prior_assignee_id"]
        item = items_repo.get(conn, question["item_id"])
        if (
            prior_id is not None
            and item is not None
            and item["assignee_id"] != prior_id
            and not comments_repo.open_questions_for_item(conn, item["id"])
            and question_assign.is_active_human(conn, item["assignee_id"])
        ):
            question_assign.reassign_silently(
                conn, item, prior_id, actor_id=user["id"]
            )
    return comments_repo.serialize(conn, comments_repo.get_required(conn, comment_id))


@router.patch("/comments/{comment_id}/answer")
def update_answer(
    comment_id: int,
    body: AnswerCreate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    """Wijzig het antwoord op een vraag zolang de notificatie nog niet verstuurd is
    (BETON-263).

    422 als de comment geen (beantwoorde) vraag is; 409 als het antwoord al
    verstuurd (en dus gelockt) is. Een wijziging binnen het grace-venster reset de
    wachttijd, zodat de vragensteller pas de definitieve versie ziet."""
    question = comments_repo.get(conn, comment_id)
    if question is None:
        raise HTTPException(status_code=404, detail=f"Onbekende comment: {comment_id}")
    if question["kind"] != "question":
        raise HTTPException(status_code=422, detail="Deze comment is geen vraag")
    if question["answered_at"] is None:
        raise HTTPException(status_code=422, detail="Vraag is nog niet beantwoord")
    if user["kind"] != "human" and question["answered_by"] != user["id"]:
        raise HTTPException(
            status_code=403, detail="Alleen de antwoorder of een mens wijzigt het antwoord"
        )
    if webhooks.answer_locked(conn, question):
        raise HTTPException(
            status_code=409, detail="Antwoord is al verstuurd en niet meer te wijzigen"
        )

    answer_text, answer_index = _resolve_answer(question, body)

    with db_module.transaction(conn):
        comments_repo.update_answer(
            conn,
            comment_id,
            answer_text=answer_text,
            answer_option_index=answer_index,
        )
        # Verschuif een eventueel al vrijgegeven (maar nog niet afgeleverde) grace.
        webhooks.reset_answer_grace(conn, comment_id)
    return comments_repo.serialize(conn, comments_repo.get_required(conn, comment_id))


def _apply_stale_answer_if_any(
    conn: sqlite3.Connection,
    question: sqlite3.Row,
    answer_index: int | None,
    user: sqlite3.Row,
) -> None:
    """Verwerk het antwoord op een stale-vraag van triage (BETON-375).

    De drie opties hebben een vast gevolg (niets / terug naar todo / vrijgeven aan
    de coding-queue), dus dit is deterministisch — geen LLM-ronde. Een vrij
    tekstantwoord (`answer_index is None`) verandert niets: het antwoord zélf is
    activiteit, en dat zet de her-vraag-klok al opnieuw.

    Zet daarnaast `evaluated_at` vooruit zodat `find_answered_questions`
    (BETON-389) deze vraag NIET ook nog eens aan de LLM voorlegt — hij is hier al
    afgehandeld. Draait binnen de transactie van het answer-endpoint."""
    if not triage_mod.is_stale_question(question["body_md"]):
        return
    item = items_repo.get(conn, question["item_id"])
    if item is None:
        return
    before = items_repo.serialize(conn, item)
    fields = triage_mod.apply_stale_answer(conn, item, answer_index)
    conn.execute(
        f"UPDATE comments SET evaluated_at = {events_repo.NOW_SQL} WHERE id = ?",
        (question["id"],),
    )
    if not fields:
        return
    after = items_repo.serialize(conn, items_repo.get_required(conn, item["id"]))
    payload: dict = {}
    if "state_id" in fields:
        payload["state"] = {"from": before["state"], "to": after["state"]}
    if "assignee_id" in fields:
        payload["assignee"] = {"from": before["assignee"], "to": after["assignee"]}
    webhooks.record_and_fanout(
        conn,
        type="item.updated",
        item_id=item["id"],
        actor_id=user["id"],
        payload=payload,
    )


def _apply_guardrail_review_answer_if_any(
    conn: sqlite3.Connection,
    question: sqlite3.Row,
    answer_index: int | None,
    user: sqlite3.Row,
) -> None:
    """Verwerk het antwoord op een guardrail-reviewvraag (BETON-420).

    Drie opties met een vast gevolg, dus deterministisch — geen LLM-ronde. Zet
    `evaluated_at` vooruit (anders legt BETON-389 er alsnog een LLM-ronde
    overheen) en schrijft het bijbehorende event met marker-payload, zonder
    fanout — net als het zetten/opheffen zelf."""
    if not triage_mod.is_guardrail_review_question(question["body_md"]):
        return
    if user["kind"] != "human":
        raise HTTPException(
            status_code=403,
            detail=(
                "Of een guardrail nog geldt is een menselijk oordeel; een agent "
                "beantwoordt deze vraag niet."
            ),
        )
    conn.execute(
        f"UPDATE comments SET evaluated_at = {events_repo.NOW_SQL} WHERE id = ?",
        (question["id"],),
    )
    item = items_repo.get(conn, question["item_id"])
    if item is None:
        return
    fields = triage_mod.apply_guardrail_review_answer(conn, item, answer_index)
    if not fields:
        return
    if "guardrail_review_by" in fields:
        events_repo.record(
            conn,
            type="item.guardrail_set",
            item_id=item["id"],
            actor_id=user["id"],
            payload={
                "guardrail": {
                    "active": True,
                    "review_by": fields["guardrail_review_by"],
                    "scoped": bool(guardrails_repo.scope_labels(conn, item["id"])),
                }
            },
        )
    else:
        events_repo.record(
            conn,
            type="item.guardrail_lifted",
            item_id=item["id"],
            actor_id=user["id"],
            payload={"guardrail": {"active": False}},
        )


@router.get("/questions")
def list_questions(
    open: bool = True,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    """Open (onbeantwoorde) vragen die aan de aanroepende user gericht zijn.

    "Gericht" = de user is assignee of maker van het item, óf in de vraagtekst
    @gementiond. Levert per vraag de comment-serialisatie plus de item-ref/-titel
    zodat een UI-badge of agent er context bij heeft (BETON-219)."""
    result: list[dict] = []
    rows = comments_repo.open_questions(conn) if open else []
    for q in rows:
        directed = (
            q["item_assignee_id"] == user["id"]
            or q["item_created_by"] == user["id"]
            or user["handle"] in mentions_mod.parse(q["body_md"])
        )
        if not directed:
            continue
        entry = comments_repo.serialize(conn, q)
        entry["item"] = {
            "ref": q["item_ref"],
            "title": q["item_title"],
            "state": q["item_state"],
        }
        result.append(entry)
    return result


def _emit_label_change(
    conn: sqlite3.Connection, item: sqlite3.Row, user: sqlite3.Row, before: list[str]
) -> dict:
    """Schrijf een item.updated-event voor een labelwijziging (labels from→to)."""
    fresh = items_repo.serialize(conn, items_repo.get_required(conn, item["id"]))
    after = fresh["labels"]
    if before != after:
        event = events_repo.record(
            conn,
            type="item.updated",
            item_id=item["id"],
            actor_id=user["id"],
            payload={"labels": {"from": before, "to": after}},
        )
        webhooks.fanout(conn, event=event)
    return fresh


# `:path` — labelnamen mogen een `/` bevatten (BETON-449).
@router.post("/items/{ref}/labels/{name:path}", status_code=201)
def add_label(
    ref: str,
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    item = _require_item(conn, ref)
    project = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (item["project_id"],)
    ).fetchone()
    label_id = _resolve_label_id(conn, project, name)
    before = items_repo.serialize(conn, item)["labels"]
    with db_module.transaction(conn):
        labels_repo.add_to_item(conn, item["id"], label_id)
        fresh = _emit_label_change(conn, item, user, before)
    return fresh


@router.delete("/items/{ref}/labels/{name:path}")
def remove_label(
    ref: str,
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    item = _require_item(conn, ref)
    project = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (item["project_id"],)
    ).fetchone()
    label_id = _resolve_label_id(conn, project, name)
    before = items_repo.serialize(conn, item)["labels"]
    with db_module.transaction(conn):
        labels_repo.remove_from_item(conn, item["id"], label_id)
        fresh = _emit_label_change(conn, item, user, before)
    return fresh


@router.delete("/items/{ref}", status_code=204)
def archive_item(
    ref: str,
    hard: bool = False,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> None:
    """Archiveer een item, of verwijder het onherroepelijk met ``?hard=true``.

    Archiveren (default) haalt het item uit board/list/search maar bewaart het.
    Hard verwijderen wist het item plus alles wat eraan hangt; subtaken worden
    losgekoppeld (BETON-19). Een hard-delete triggert geen agent-fanout — het is
    een handmatige opruimactie — maar laat wél een spoor in de activity-feed
    (event met item_id=NULL, want het item bestaat dan niet meer). Onherroepelijk
    verwijderen is mens-only (BETON-377): agents mogen archiveren maar niet
    hard-deleten."""
    item = _require_item(conn, ref)
    if hard:
        if user["kind"] != "human":
            raise HTTPException(
                status_code=403, detail="Onherroepelijk verwijderen is alleen voor mensen"
            )
        with db_module.transaction(conn):
            events_repo.record(
                conn,
                type="item.deleted",
                item_id=None,
                actor_id=user["id"],
                payload={"ref": ref, "title": item["title"]},
            )
            items_repo.hard_delete(conn, item["id"])
        return
    with db_module.transaction(conn):
        items_repo.archive(conn, item["id"])
        event = events_repo.record(
            conn,
            type="item.archived",
            item_id=item["id"],
            actor_id=user["id"],
            payload={},
        )
        webhooks.fanout(conn, event=event)


@router.post("/items/{ref}/move")
def move_item(
    ref: str,
    body: ItemMove,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    """Verplaats een item **in-place** naar een ander project (BETON-95/244).

    Het item behoudt zijn ``id`` en krijgt alleen een nieuw ``project_id`` + ``seq``
    (dus een nieuwe ref ``KEY-seq``). Omdat comments, relaties, attachments en
    subtaken naar het ongewijzigde item-``id`` verwijzen, verhuizen die
    automatisch mee — "eigenlijk verandert alleen de ``<slug>-<id>``". De
    project-gescopete labels worden geremapt naar het doelproject (aanmaken als ze
    daar nog niet bestaan); de milestone wordt gewist (die hoort bij de
    release-cadans van het bronproject). Het item krijgt de default-state van het
    doelproject.

    Subtaken verhuizen NIET fysiek mee: een verplaatste parent laat zijn children
    in het bronproject achter (ze blijven wél gelinkt via ``parent_id``), en een
    verplaatste subtaak houdt zijn parent in het bronproject. Zo'n cross-project
    parent/child-link zou de API bij een verse create/update weigeren
    (``_resolve_parent_id``), maar de move zelf loopt niet via die guard en schendt
    geen invariant (``serialize``/``children_counts`` resolven puur op id).

    404 bij onbekend item/project, 400 als het item al in het doelproject staat."""
    item = _require_item(conn, ref)
    target = projects_repo.get_by_key(conn, body.project.strip().upper())
    if target is None:
        raise HTTPException(status_code=404, detail=f"Onbekend project: {body.project}")
    if target["id"] == item["project_id"]:
        raise HTTPException(status_code=400, detail="Item staat al in dit project")

    old_ref = ref
    label_names = items_repo.serialize(conn, item)["labels"]
    with db_module.transaction(conn):
        moved = items_repo.move_to_project(conn, item["id"], target["id"])
        assert moved is not None
        # Labels remappen: de item_labels van het bronproject wijzen naar
        # bron-gescopete labels; die naar het doelproject omzetten (aanmaken waar
        # nodig) zodat de labelnamen behouden blijven.
        for name in label_names:
            label = labels_repo.get_by_name(conn, target["id"], name)
            label_id = (label["id"] if label is not None else
                        labels_repo.create(conn, project_id=target["id"], name=name)["id"])
            src = labels_repo.get_by_name(conn, item["project_id"], name)
            if src is not None:
                labels_repo.remove_from_item(conn, item["id"], src["id"])
            labels_repo.add_to_item(conn, item["id"], label_id)
        new_ref = f"{target['key']}-{moved['seq']}"
        moved_event = events_repo.record(
            conn,
            type="item.moved",
            item_id=item["id"],
            actor_id=user["id"],
            payload={"from": old_ref, "to": new_ref},
        )
        # BETON-166: een verplaatst item moet in het doelproject fanout naar de
        # assignee/subscribe_all triggeren — anders blijft het onopgemerkt tot
        # iemand het toevallig opent.
        webhooks.fanout(conn, event=moved_event)
    return items_repo.serialize(conn, moved)


@router.post("/items/{ref}/restore")
def restore_item(
    ref: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    """Herstel een gearchiveerd item terug naar het board (BETON-59).

    Idempotent: een niet-gearchiveerd item blijft ongemoeid (geen event)."""
    item = _require_item(conn, ref)
    if item["archived_at"] is None:
        return items_repo.serialize(conn, item)
    with db_module.transaction(conn):
        items_repo.unarchive(conn, item["id"])
        event = events_repo.record(
            conn,
            type="item.restored",
            item_id=item["id"],
            actor_id=user["id"],
            payload={},
        )
        webhooks.fanout(conn, event=event)
    return items_repo.serialize(conn, items_repo.get_required(conn, item["id"]))


@router.post("/items/{ref}/enrich")
def enrich_item(
    ref: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(llm_rate_limited),
    llm=Depends(require_llm_client),
) -> dict:
    """Genereer een verrijkings-voorstel — of stel vragen bij te magere input.

    Voorstellen-en-bevestigen (BETON-13/163): bij voldoende input geeft het
    endpoint een ``proposal`` terug (de UI toont een diff; pas na bevestiging
    PATCH't de client de omschrijving — hier wordt niets opgeslagen). Bij te
    magere input schrijft de bot GEEN pseudo-omschrijving maar plaatst zijn
    vragen als comment onder `triage`; de response bevat dan ``questions`` +
    ``comment_posted`` zodat de UI een melding toont i.p.v. een lege diff. Een
    menselijk antwoord op die vragen laat de triage-worker de verrijking opnieuw
    proberen (re-enrich). 503 zonder LLM (BETONNING_LLM_*), 502 bij upstream-fout.

    Werkt ook op projecten zónder triage: daar draait de worker-re-trigger niet,
    maar `build_enrich_messages` voedt de comment-thread mee, dus een mens die na
    het beantwoorden opnieuw op Verrijk klikt krijgt alsnog een proposal.
    """
    item = _require_item(conn, ref)
    data = items_repo.serialize(conn, item)
    comments = [
        comments_repo.serialize(conn, c)
        for c in comments_repo.list_for_item(conn, item["id"])
    ]
    project_labels = [
        label["name"] for label in labels_repo.list_for_project(conn, item["project_id"])
    ]
    messages = llm_module.build_enrich_messages(
        data["title"],
        data["description_md"],
        comments,
        project_labels=project_labels,
        item_labels=data["labels"],
    )
    with llm_errors_as_502():
        output = llm.complete(messages)
    result = llm_module.parse_enrich(output)
    if result.kind == "questions":
        # Vragen als comment onder triage — de omschrijving blijft ongemoeid.
        triage_user = users_repo.get_by_handle(conn, "triage")
        comment_posted = False
        if triage_user is not None:
            body = triage_mod.format_enrich_questions(result.questions)
            with db_module.transaction(conn):
                triage_mod.post_triage_comment(conn, item, body, triage_user["id"])
            comment_posted = True
        return {
            "kind": "questions",
            "questions": result.questions,
            "comment_posted": comment_posted,
        }
    return {
        "kind": "proposal",
        "current": data["description_md"],
        "proposal": result.description,
        # BETON-355: het voorstel draagt ook labels. Alleen labels die op het
        # project bestaan en er nog niet op staan — aanvullen, niet vervangen
        # (BETON-65). Er wordt hier niets opgeslagen: de UI toont het voorstel en
        # de mens bevestigt, net als bij de omschrijving.
        "current_labels": data["labels"],
        "labels": llm_module.resolve_label_suggestions(
            result.labels, project_labels, data["labels"]
        ),
    }


def _has_living_children(conn: sqlite3.Connection, item: sqlite3.Row) -> bool:
    """Heeft het item nog LEVENDE (niet-gearchiveerde) subtaken? (BETON-51)

    De decompose-marker (`decomposed_at`) is permanent, maar her-opknippen mag
    zodra alle eerdere subtaken gearchiveerd zijn. De guard kijkt daarom naar
    levende children i.p.v. puur naar de marker."""
    _, total = items_repo.children_counts(conn, item["id"])
    return total > 0


def _project_name(conn: sqlite3.Connection, project_id: int) -> str:
    row = conn.execute(
        "SELECT name FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    return row["name"] if row else "?"


@router.post("/items/{ref}/decompose")
def decompose_item(
    ref: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(llm_rate_limited),
    llm=Depends(require_llm_client),
) -> dict:
    """Stel een decompositie voor (subtaken + volgorde) — slaat NIET op (BETON-31).

    Voorstellen-en-bevestigen: de UI toont het voorstel; pas na bevestiging maakt de
    client de subtaken aan via /decompose/apply. 503 zonder LLM, 409 als het item al
    is opgeknipt (decomposed_at)."""
    item = _require_item(conn, ref)
    if _has_living_children(conn, item):
        raise HTTPException(status_code=409, detail="Item is al opgeknipt")
    data = items_repo.serialize(conn, item)
    images = triage_worker_mod.gather_images(
        conn, item, base=request.app.state.attachments_dir
    )
    messages = decompose_mod.build_decompose_messages(
        {
            "ref": data["ref"],
            "title": data["title"],
            "description_md": data["description_md"],
        },
        {
            "project_name": _project_name(conn, item["project_id"]),
            # BETON-67: agent-roster mee zodat de LLM per subtaak op expertise routeert.
            # BETON-123: gefilterd op per-project toegang (geen 'none'/'respond'-agents).
            "agents": users_repo.assignable_agents(conn, item["project_id"]),
        },
        images=images,
    )
    with llm_errors_as_502():
        raw = llm.complete(messages)
    return decompose_mod.parse_decompose(raw).model_dump()


@router.post("/items/{ref}/decompose/apply", status_code=201)
def apply_decompose_item(
    ref: str,
    body: decompose_mod.DecomposeResult,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    """Maak de (bevestigde/bewerkte) subtaken + blocks-keten aan (BETON-31).

    409 als het item al is opgeknipt; 422 bij een nee-voorstel
    (should_decompose=false) of zonder subtaken."""
    item = _require_item(conn, ref)
    if _has_living_children(conn, item):
        raise HTTPException(status_code=409, detail="Item is al opgeknipt")
    if not body.should_decompose:
        raise HTTPException(
            status_code=422,
            detail="Voorstel zegt niet opknippen (should_decompose=false)",
        )
    if not body.subtasks:
        raise HTTPException(status_code=422, detail="Geen subtaken om aan te maken")
    refs = decompose_mod.apply_decompose(conn, item, body, user["id"])
    return {"created": refs}
