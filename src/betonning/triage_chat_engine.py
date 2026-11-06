"""Chat-motor voor chat-met-triage (BETON-120).

De motor orkestreert één beurt: `gebruikersbericht + (begrensde) historie +
scope-context` → LLM. De LLM antwoordt met JSON in één van drie vormen:

- ``query``    — een gestructureerde leesvraag (filters). Wij draaien 'm
                 deterministisch, voeren het resultaat terug in een begrensde lus
                 (`max_query_rounds`) → LLM antwoordt/stelt voor.
- ``reply``    — een NL-antwoord of vervolgvraag (geen actie).
- ``proposal`` — getypeerde commando's; wij valideren + resolven de concrete
                 doel-items en slaan het voorstel als ``pending``-bericht op. Pas
                 bij ``confirm`` draait de deterministische uitvoerder
                 (`triage_commands.execute`) — als user ``triage``, met de mens als
                 opdrachtgever in de audit-log.

Scope werkt als de wiki: `project_id=None` = de globale thread (project per
commando noemen), anders een projectthread (project impliciet/vast). De historie
naar de LLM is begrensd tot de laatste ``MAX_HISTORY`` beurten van de actieve
sessie; een sessie archiveren reset de context volledig.

Puur waar het kan (prompt-bouw/parsing) zodat het los met een FakeLLM getest kan
worden — het huisidioom.
"""

from __future__ import annotations

from .outbound import outbound

from .config import env

import json
import logging
import sqlite3

from pydantic import BaseModel, ConfigDict, field_validator

from . import triage_commands as tc
from .llm import localized_system_prompt, parse_json_result
from .repo import labels as labels_repo
from .repo import projects as projects_repo
from .repo import states as states_repo
from .repo import triage_chat as chat_repo
from .repo import users as users_repo

logger = logging.getLogger(__name__)


def _int_env(name: str, default: int) -> int:
    try:
        return int(env(name, default))
    except (TypeError, ValueError):
        return default


# Laatste N beurten die naar de LLM gaan (naast het per-scope sessie-model). Zo
# blijft de token-context begrensd ook zonder handmatig een nieuw gesprek te starten.
MAX_HISTORY = _int_env("BETONNING_CHAT_MAX_HISTORY", 20)
# Boven deze drempel vraagt de UI om het aantal te typen (veiligheidsrem).
BULK_CONFIRM_THRESHOLD = _int_env("BETONNING_CHAT_BULK_THRESHOLD", 10)
# Hoeveel items we maximaal terugvoeren naar de LLM per query-ronde.
QUERY_SAMPLE = 20


SYSTEM_PROMPT = """Je bent de triage-bot voor Betonning, een work-item-tracker met \
meerdere projecten. Een mens chat met je: hij stelt vragen of geeft opdrachten. \
Antwoord ALTIJD met één JSON-object, zonder codeblokken of tekst eromheen.

Er zijn drie antwoordvormen (veld "kind"):

1. {"kind": "query", "query": {"filter": {...}}} — als je gegevens nodig hebt om \
een vraag te beantwoorden of een opdracht te concretiseren. Wij draaien de query en \
sturen je het resultaat terug; daarna antwoord je opnieuw. Filtervelden (combineer \
naar wens): "state_open" (open items), "state_closed" (gesloten), "state" (exacte \
statusnaam), "updated_before_days" (N: niet aangeraakt in N dagen), "label", \
"assignee" (handle), "priority" (urgent|high|medium|low|none).

2. {"kind": "reply", "text": "..."} — een gewoon antwoord of een vervolgvraag als \
iets onduidelijk is. In de ingestelde uitvoertaal, bondig.

3. {"kind": "proposal", "summary": "...", "commands": [ ... ]} — als de mens een \
actie wil. Voer NOOIT zelf uit; stel voor. Elk commando: {"verb": ..., "selector": \
{...}, "params": {...}}. Verbs: archive, restore, set_state, set_priority, \
set_assignee, add_label, remove_label, set_milestone, add_relation, create_item. \
Er is GEEN verwijder-verb — archiveren is het maximum (omkeerbaar). "selector" is \
{"refs": ["SOS-1", ...]} of {"filter": {...}} (zelfde filtervelden als query); \
create_item heeft geen selector, wel params.title. params per verb: set_state \
{"state"}, set_priority {"priority"}, set_assignee {"assignee"}, add_label/ \
remove_label {"label"}, set_milestone {"milestone"}, add_relation {"relation_type", \
"target_ref"}, create_item {"title", (optioneel) "description_md"}.

Belangrijke grenzen:
- Eén commando raakt precies ÉÉN project.
- SCOPE: %SCOPE%
- Wees terughoudend: bij twijfel over wat de mens bedoelt, gebruik "reply" met een \
vervolgvraag i.p.v. gokken. Bevestiging vraagt de mens zelf via de UI; jouw \
"proposal" toont eerst een preview.

Antwoord ALTIJD met PRECIES ÉÉN JSON-object — nooit platte tekst, nooit een \
codeblok, nooit uitleg ervoor of erna. De historie hierboven toont statusregels \
zoals "[status] De gebruiker annuleerde het voorstel." — dat zijn feiten over het \
gesprek, GEEN voorbeelden van hoe jij moet antwoorden. Herhaal zulke UI-teksten \
nooit letterlijk in een eigen antwoord. Als een voorstel is geannuleerd of \
verlopen en de mens geeft daarna een correctie of nieuwe instructie, maak dan een \
NIEUW "proposal" met de gecorrigeerde interpretatie — antwoord niet met platte \
tekst en doe niet alsof er al een voorstel loopt."""


def _scope_line(conn: sqlite3.Connection, project_id: int | None) -> str:
    if project_id is None:
        return (
            "Dit is de GLOBALE thread. Noem in elke query/commando het project "
            'expliciet met "project": "KEY" (bv. "SOS").'
        )
    key = conn.execute(
        "SELECT key FROM projects WHERE id = ?", (project_id,)
    ).fetchone()["key"]
    return (
        f"Dit is de thread van project {key}. Alle queries/commando's gelden voor "
        f"{key}; een ander project noemen kan niet — vraag de mens dan van thread te "
        "wisselen."
    )


def _context_text(conn: sqlite3.Connection, project_id: int | None) -> str:
    """Beknopte context voor de LLM: welke projecten/states/labels/agents er zijn."""
    if project_id is None:
        rows = conn.execute(
            "SELECT key, name FROM projects WHERE archived_at IS NULL ORDER BY key"
        ).fetchall()
        listed = ", ".join(f"{r['key']} ({r['name']})" for r in rows) or "(geen)"
        return f"# Projecten: {listed}"

    project = conn.execute(
        "SELECT key, name FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    lines = [f"# Project: {project['key']} — {project['name']}"]
    states = states_repo.list_for_project(conn, project_id)
    if states:
        lines.append(
            "States: "
            + ", ".join(f"{s['name']} ({s.get('group', '?')})" for s in states)
        )
    labels = [lbl["name"] for lbl in labels_repo.list_for_project(conn, project_id)]
    if labels:
        lines.append(f"Labels: {', '.join(labels)}")
    agents = users_repo.assignable_agents(conn, project_id)
    if agents:
        lines.append(
            "Toewijsbare agents: " + ", ".join(f"@{a['handle']}" for a in agents)
        )
    return "\n".join(lines)


# Engine-gegenereerde statusregels (géén LLM-JSON-beurt): teksten die de motor zelf
# als assistant-bericht opslaat bij annuleren/verlopen/uitvoeren (zie `cancel` en
# `confirm`). Als deze ongewijzigd terug de historie in gaan, ziet het model ze als
# platte-tekst-voorbeelden en gaat het ze imiteren (BETON-181) — terwijl het model
# volgens de system-prompt uitsluitend JSON hoort te produceren. Daarom geven we ze
# als neutrale `[status]`-regel op de USER-rol terug: een gespreksfeit, niet
# imiteerbare assistant-output.
_STATUS_NOTE_EXACT = {
    "Voorstel geannuleerd.": "chat.status.cancelled",
    "Proposal cancelled.": "chat.status.cancelled",
}
_STATUS_NOTE_PREFIXES = {
    "Voorstel verlopen: ": "chat.status.expired",
    "Proposal expired: ": "chat.status.expired",
    "Uitgevoerd op ": "chat.status.executed",
    "Executed on ": "chat.status.executed",
}


def _status_note(body_md: str) -> str | None:
    """Geef de neutrale statusbeschrijving terug als `body_md` een door de motor
    gegenereerde statusregel is, anders None (= gewone reply)."""
    if body_md in _STATUS_NOTE_EXACT:
        return outbound(_STATUS_NOTE_EXACT[body_md])
    for prefix, template in _STATUS_NOTE_PREFIXES.items():
        if body_md.startswith(prefix):
            return outbound(template, rest=body_md[len(prefix):])
    return None


def build_chat_messages(
    conn: sqlite3.Connection,
    project_id: int | None,
    history: list[sqlite3.Row],
    scratch: list[dict] | None = None,
) -> list[dict]:
    """Bouw de messages voor één LLM-call: system(+scope+context) → historie
    (die eindigt met het net-opgeslagen huidige bericht) → eventuele
    query-resultaat-rondes (`scratch`).

    Historie-hygiëne (BETON-181): assistant-beurten gaan in protocolvorm terug
    naar het model (JSON-string als content), niet als gerénderde platte tekst
    — anders leert het model van zijn eigen historie om platte tekst te
    antwoorden. Een voorstel-rij wordt `{"kind":"proposal","summary":...}`, een
    gewone reply `{"kind":"reply","text":...}`. Engine-statusregels (annulering/
    verlopen/uitvoering) zijn geen assistant-JSON-beurt en gaan als
    `[status]`-regel op de user-rol mee — een gespreksfeit, geen imiteerbare
    output."""
    system = localized_system_prompt(SYSTEM_PROMPT).replace("%SCOPE%", _scope_line(conn, project_id))
    system = f"{system}\n\n{_context_text(conn, project_id)}"
    messages = [{"role": "system", "content": system}]
    for row in history:
        if row["role"] == "user":
            messages.append({"role": "user", "content": row["body_md"]})
            continue
        note = _status_note(row["body_md"])
        if note is not None:
            messages.append({"role": "user", "content": f"[status] {note}"})
            continue
        if row["proposal"]:
            proposal = json.loads(row["proposal"])
            protocol = {
                "kind": "proposal",
                "summary": proposal.get("summary") or row["body_md"],
            }
        else:
            protocol = {"kind": "reply", "text": row["body_md"]}
        messages.append(
            {"role": "assistant", "content": json.dumps(protocol, ensure_ascii=False)}
        )
    if scratch:
        messages.extend(scratch)
    return messages


class _ChatOutput(BaseModel):
    """Minimale getypeerde schil om het idioom te delen (BETON-322).

    ``extra="allow"`` want de vorm hangt af van `kind` (query/reply/proposal
    dragen elk andere velden) — die blijven ongemoeid staan. De ``kind``-
    whitelist is de enige échte validatie hier; ontbrekend/onbekend/niet-string
    `kind` geeft een ValidationError en dus de reply-fallback."""

    model_config = ConfigDict(extra="allow")

    kind: str

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v):
        if v not in ("query", "reply", "proposal"):
            raise ValueError(f"onbekend kind: {v!r}")
        return v


def parse_chat_output(text: str) -> dict:
    """Parse de LLM-JSON naar een dict met "kind". Valt veilig terug op een
    "reply" met de ruwe tekst als het geen (bruikbare) JSON is — spiegelt de
    fallback in parse_triage, zodat een rare output de beurt nooit laat crashen.
    Gebruikt de gedeelde tolerante `extract_json` (strict=False, via
    `parse_json_result`) zodat letterlijke control characters (bv. newlines) in
    een JSON-stringwaarde niet de hele beurt laten mislukken (BETON-163/179)."""
    stripped = (text or "").strip()
    result = parse_json_result(
        stripped,
        _ChatOutput,
        context="Chat-output",
        fallback=lambda raw, exc: {
            "kind": "reply",
            "text": stripped or outbound('chat.parse_chat_output.1'),
        },
        log=logger,
    )
    return result.model_dump() if isinstance(result, _ChatOutput) else result


def _resolve_scope_project(
    conn: sqlite3.Connection, project_id: int | None, named: str | None
) -> tuple[int | None, str | None]:
    """Bepaal het doel-project van een query/commando. Geeft (project_id, error)."""
    if project_id is not None:
        if named:
            proj = projects_repo.get_by_key(conn, named)
            if proj is not None and proj["id"] != project_id:
                return None, outbound('chat.resolve_scope_project.1', p0=(named))
        return project_id, None
    if not named:
        return None, outbound('chat.resolve_scope_project.2')
    proj = projects_repo.get_by_key(conn, named)
    if proj is None:
        return None, outbound('chat.resolve_scope_project.3', p0=(named))
    return proj["id"], None


def _run_query(conn: sqlite3.Connection, project_id: int | None, query: dict) -> dict:
    """Voer een leesquery uit en geef een compact resultaat terug voor de LLM."""
    pid, error = _resolve_scope_project(conn, project_id, query.get("project"))
    if error:
        return {"error": error}
    assert pid is not None
    selector = {"filter": query.get("filter") or {}}
    try:
        rows = tc.resolve_targets(conn, pid, selector)
    except ValueError as exc:
        return {"error": str(exc)}
    key = conn.execute("SELECT key FROM projects WHERE id = ?", (pid,)).fetchone()["key"]
    sample = []
    for row in rows[:QUERY_SAMPLE]:
        state = None
        if row["state_id"] is not None:
            s = conn.execute(
                "SELECT name FROM states WHERE id = ?", (row["state_id"],)
            ).fetchone()
            state = s["name"] if s else None
        sample.append(
            {"ref": f"{key}-{row['seq']}", "title": row["title"], "state": state,
             "priority": row["priority"]}
        )
    return {"count": len(rows), "items": sample}


def _build_proposal(
    conn: sqlite3.Connection, project_id: int | None, turn: dict
) -> tuple[list[dict], list[str], list[dict], int]:
    """Zet de ruwe LLM-commando's om naar gevalideerde commando-dicts + preview.
    Geeft (commands, errors, preview, total_count)."""
    commands: list[dict] = []
    errors: list[str] = []
    preview: list[dict] = []
    total = 0

    for raw in turn.get("commands") or []:
        verb = raw.get("verb")
        pid, error = _resolve_scope_project(conn, project_id, raw.get("project"))
        if error:
            errors.append(error)
            continue
        assert pid is not None
        cmd = tc.Command(
            verb=verb,
            project_id=pid,
            selector=raw.get("selector"),
            params=raw.get("params") or {},
        )
        cmd_errors = tc.validate(conn, cmd)
        if cmd_errors:
            errors.extend(cmd_errors)
            continue

        key = conn.execute(
            "SELECT key FROM projects WHERE id = ?", (pid,)
        ).fetchone()["key"]
        if verb == "create_item":
            refs: list[str] = []
            count = 1
            detail = cmd.params.get("title")
        else:
            targets = tc.resolve_targets(
                conn, pid, cmd.selector, include_archived=(verb == "restore")
            )
            refs = [f"{key}-{t['seq']}" for t in targets]
            count = len(refs)
            detail = None
        total += count
        preview.append({"verb": verb, "refs": refs, "count": count, "detail": detail})
        # Bevries de concrete refs in het commando. Bij bevestigen voeren we exact
        # deze items uit — niet wat de filter op dát moment matcht — zodat de mens
        # precies de gepreviewde set krijgt (create_item heeft geen doelen).
        frozen_selector = cmd.selector if verb == "create_item" else {"refs": refs}
        commands.append(
            {"verb": verb, "project_id": pid, "selector": frozen_selector,
             "params": cmd.params}
        )

    return commands, errors, preview, total


class LLMError(Exception):
    """De LLM-call zelf faalde (upstream, bv. gateway-429) — het endpoint mapt
    dit naar 502, net als enrich/decompose. Zo blijft een lokale DB-fout een
    echte 500 i.p.v. te worden verpakt als 'LLM-fout'."""


def run_turn(
    conn: sqlite3.Connection,
    llm,
    user_msg: str,
    actor_id: int,
    *,
    project_id: int | None = None,
    max_query_rounds: int = 3,
) -> dict:
    """Verwerk één gebruikersbeurt in de actieve sessie van de scope. Geeft
    ``{"kind": "reply"|"proposal", "message": <serialized>}`` terug. Bij een
    proposal is het bericht ``pending`` en muteert er nog niets."""
    if max_query_rounds < 0:
        raise ValueError("max_query_rounds moet minimaal nul zijn")
    session = chat_repo.active_session(conn, project_id)
    chat_repo.add_message(conn, session["id"], "user", actor_id, user_msg)
    history = chat_repo.list_messages(conn, session["id"], limit=MAX_HISTORY)

    scratch: list[dict] = []
    for round_no in range(max_query_rounds + 1):
        messages = build_chat_messages(conn, project_id, history, scratch)
        try:
            raw = llm.complete(messages)
        except Exception as exc:  # noqa: BLE001 — upstream-fout → 502 met context
            raise LLMError(str(exc)) from exc
        turn = parse_chat_output(raw)
        kind = turn.get("kind")

        if kind == "query" and round_no < max_query_rounds:
            result = _run_query(conn, project_id, turn.get("query") or {})
            scratch.append({"role": "assistant", "content": raw})
            scratch.append(
                {"role": "user", "content": "Query-resultaat:\n"
                 + json.dumps(result, ensure_ascii=False)}
            )
            continue

        if kind == "proposal":
            commands, errors, preview, total = _build_proposal(conn, project_id, turn)
            if errors or not commands:
                text = (turn.get("summary") or outbound('chat.run_turn.1'))
                if errors:
                    text += "\n\n" + "\n".join(f"- {e}" for e in errors)
                msg = chat_repo.add_message(conn, session["id"], "assistant", None, text)
                return {"kind": "reply", "message": chat_repo.serialize_message(msg)}
            proposal: dict = {
                "summary": turn.get("summary") or outbound('chat.run_turn.2'),
                "commands": commands,
                "preview": preview,
                "total_count": total,
                "threshold": BULK_CONFIRM_THRESHOLD,
            }
            msg = chat_repo.add_message(
                conn, session["id"], "assistant", None,
                proposal["summary"], proposal=proposal, status="pending",
            )
            return {"kind": "proposal", "message": chat_repo.serialize_message(msg)}

        # reply (of query voorbij de rondelimiet → val terug op reply)
        text = turn.get("text") or outbound('chat.run_turn.3')
        msg = chat_repo.add_message(conn, session["id"], "assistant", None, text)
        return {"kind": "reply", "message": chat_repo.serialize_message(msg)}

    raise AssertionError("Chatronde eindigde zonder antwoord")


class ConfirmationRequired(Exception):
    """Boven de veiligheidsdrempel moet de mens het aantal typen om te bevestigen."""

    def __init__(self, total: int) -> None:
        super().__init__(outbound('chat.init.1', p0=(total)))
        self.total = total


class ProposalNotPending(Exception):
    """Het bericht draagt geen openstaand (pending) voorstel meer."""



def confirm(
    conn: sqlite3.Connection, message_id: int, actor_id: int, *, typed_count: int | None = None
) -> dict:
    """Voer een bevestigd voorstel uit. Mutaties worden geboekt op naam van de
    triage-bot (events/activity), de mens (`actor_id`) staat als opdrachtgever in
    de audit-log. Bulk (>1 item per commando) onderdrukt de webhook-fanout."""
    msg = chat_repo.get_message(conn, message_id)
    if msg is None or msg["status"] != "pending" or not msg["proposal"]:
        raise ProposalNotPending()
    proposal = json.loads(msg["proposal"])
    total = int(proposal.get("total_count", 0))
    if total > BULK_CONFIRM_THRESHOLD and typed_count != total:
        raise ConfirmationRequired(total)

    triage = users_repo.get_by_handle(conn, "triage")
    triage_id = triage["id"] if triage else actor_id

    # De selectors dragen bevroren refs (zie _build_proposal): validatie/uitvoering
    # raken exact de gepreviewde items. Valideer ALLES eerst — pas als elk commando
    # nog geldig is voeren we uit, zodat een sinds-het-voorstel-veranderde situatie
    # geen halve uitvoering geeft (bv. een verwijderd item, of een assignee die zijn
    # toewijsrecht verloor).
    commands = [
        tc.Command(
            verb=cmd_dict["verb"],
            project_id=cmd_dict["project_id"],
            selector=cmd_dict.get("selector"),
            params=cmd_dict.get("params") or {},
        )
        for cmd_dict in proposal["commands"]
    ]
    all_errors: list[str] = []
    for cmd in commands:
        all_errors.extend(tc.validate(conn, cmd))
    if all_errors:
        chat_repo.set_message_status(conn, message_id, "cancelled")
        note = outbound('chat.confirm.1') + "; ".join(all_errors)
        msg2 = chat_repo.add_message(conn, msg["session_id"], "assistant", None, note)
        return {"kind": "reply", "message": chat_repo.serialize_message(msg2),
                "executed": []}

    executed: list[str] = []
    for cmd in commands:
        if cmd.verb == "create_item":
            fanout = True
        else:
            n = len(
                tc.resolve_targets(
                    conn, cmd.project_id, cmd.selector,
                    include_archived=(cmd.verb == "restore"),
                )
            )
            fanout = n == 1
        refs = tc.execute(conn, cmd, triage_id, fanout=fanout)
        executed.extend(refs)
        chat_repo.record_action(
            conn,
            message_id=message_id,
            commanded_by=actor_id,
            verb=cmd.verb,
            project_id=cmd.project_id,
            params=cmd.params,
            target_refs=refs,
        )

    chat_repo.set_message_status(conn, message_id, "confirmed")
    summary = outbound('chat.confirm.one' if len(executed) == 1 else 'chat.confirm.2', p0=len(executed)) + ", ".join(executed[:10])
    if len(executed) > 10:
        summary += f" … (+{len(executed) - 10})"
    done = chat_repo.add_message(conn, msg["session_id"], "assistant", None, summary)
    return {"kind": "done", "message": chat_repo.serialize_message(done), "executed": executed}


def cancel(conn: sqlite3.Connection, message_id: int) -> dict:
    """Annuleer een openstaand voorstel."""
    msg = chat_repo.get_message(conn, message_id)
    if msg is None or msg["status"] != "pending":
        raise ProposalNotPending()
    chat_repo.set_message_status(conn, message_id, "cancelled")
    note = chat_repo.add_message(
        conn, msg["session_id"], "assistant", None, outbound('chat.cancel.1')
    )
    return {"kind": "reply", "message": chat_repo.serialize_message(note)}
