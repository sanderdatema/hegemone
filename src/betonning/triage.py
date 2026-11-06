"""Triage: prompt-bouw, LLM-output-parsing en toepassen op een item (BETON-22).

De ingebouwde triage-bot classificeert een nieuw item (type/model/priority/
assignee/state), detecteert duplicaten/relaties en plaatst een triage-comment —
alles via de bestaande repos, als user `triage`. Hergebruikt de OpenAI-compatibele
llm-client (llm.py). Pure delen (prompt-bouw, parsing) zijn los testbaar.
"""

from __future__ import annotations

from .outbound import outbound

import logging
import re
import sqlite3
from collections.abc import Iterable

from pydantic import BaseModel, field_validator

from . import db as db_module
from . import llm as llm_mod
from . import mentions
from . import models
from . import question_assign
from . import webhooks
from .repo import comments as comments_repo
from .repo import events as events_repo
from .repo import items as items_repo
from .repo import labels as labels_repo
from .repo import model_classes as model_classes_repo
from .repo import relations as relations_repo
from .repo import states as states_repo
from .repo import users as users_repo

logger = logging.getLogger(__name__)


# Gedeelde coercion/normalisatie-helpers wonen nu in llm.py (BETON-323); hier
# als module-lokale naam behouden zodat bestaande gebruikers (o.a. decompose)
# blijven werken zonder duplicatie — spiegelt het bestaande _extract_json-patroon.
_coerce_scalar = llm_mod.coerce_scalar


def clean_question_options(v) -> list[str] | None:
    """Opties opschonen (spiegelt de vraagmodule-validatie, BETON-219): trim,
    lege/dubbele eruit, max 6, en None bij niets bruikbaars.

    Module-functie i.p.v. een validator-methode omdat twee resultaatmodellen hem
    delen: `TriageResult` (BETON-268) en `CommentEvalResult` (BETON-389). De
    vraagmodule-validatie in de API weigert lege/dubbele opties met een 422; hier
    schoont het op, want een LLM-slordigheid mag de triage-ronde niet laten
    stuklopen."""
    if not isinstance(v, list):
        return None
    seen: set[str] = set()
    out: list[str] = []
    for item in v:
        s = _coerce_scalar(item)
        if not isinstance(s, str):
            continue
        s = s.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out[:6] or None


class TriageResult(BaseModel):
    type_label: str
    model_label: str = "standaard"
    priority: str = "none"
    # BETON-311: geschatte werklast (tokenkosten) light/medium/heavy, of "" als
    # de LLM het niet inschat. Backstop bij aanmaken als de maker het leeg liet.
    workload: str = ""
    # BETON-207: default is de virtuele "coding-agent" (gedeelde coding-queue),
    # geen vaste agent- of persoonsnaam — toewijzen aan de mens is de
    # uitzondering (een blokkerende vraag/beslissing), niet de default voor
    # gewoon uitvoerbaar werk. Bij een fallback (invalide LLM-output) is er geen
    # signaal van een blokkerende vraag, dus blijft de veilige default de queue.
    assignee: str = "coding-agent"
    assignee_reason: str = ""
    duplicate_of: str | None = None
    related_to: list[str] = []
    state: str | None = None
    comment: str = ""
    # BETON-37 (fase 4 van decompose): triage vlagt een groot/samengesteld item als
    # kandidaat om op te knippen — conservatief, alleen een suggestie in de comment.
    decompose_suggestion: bool = False
    decompose_reason: str = ""
    # BETON-268: als triage aan de mens toewijst (een blokkerende beslissing), is
    # de comment een echte vraag. Bij een discrete keuze levert de LLM hier de
    # antwoordopties, zodat apply_triage de comment als vraagmodule-vraag
    # (kind='question') met opties kan plaatsen i.p.v. een platte comment.
    question_options: list[str] | None = None

    @field_validator("question_options", mode="before")
    @classmethod
    def _clean_options(cls, v):
        return clean_question_options(v)

    @field_validator("type_label", "model_label", "priority", "workload", "assignee", mode="before")
    @classmethod
    def _norm(cls, v):
        return llm_mod.norm_str(v)

    @field_validator("model_label", mode="after")
    @classmethod
    def _map_model_label(cls, v):
        """Defensief (BETON-476): een oude modelnaam wordt de bijbehorende klasse."""
        mapped = _LEGACY_MODEL_LABELS.get(v, v)
        return mapped if mapped in MODEL_CLASSES else "standaard"

    @field_validator("workload", mode="after")
    @classmethod
    def _map_workload(cls, v):
        """Defensief: de triage-prompt is NL, dus de LLM kan met de NL-labels
        antwoorden (licht/middel/zwaar) i.p.v. de interne Engelse waarden. Zonder
        deze mapping zou dat stil door de `in (...)`-gate in apply_triage vallen —
        geen workload, geen fout (BETON-311)."""
        return {"licht": "light", "middel": "medium", "zwaar": "heavy"}.get(v, v)

    @field_validator(
        "assignee_reason",
        "comment",
        "duplicate_of",
        "state",
        "decompose_reason",
        mode="before",
    )
    @classmethod
    def _coerce_str_fields(cls, v):
        return _coerce_scalar(v)


# Werkklassen zijn onafhankelijk van de gekozen agentnaam of het model.
MODEL_CLASSES: set[str] = set(model_classes_repo.CLASSES)

# Oude modelnamen die een LLM uit gewoonte nog kan teruggeven -> klasse.
_LEGACY_MODEL_LABELS = model_classes_repo.LEGACY_LABELS


def _uses_work_class(conn: sqlite3.Connection, user: sqlite3.Row | None) -> bool:
    """Coding-agents op type; oude agents zonder type via hun modelconfiguratie."""
    if user is None or user["kind"] != "agent" or not user["active"]:
        return False
    if user["agent_type"] == "coding":
        return True
    if user["agent_type"] is not None:
        return False
    return conn.execute(
        "SELECT 1 FROM model_classes WHERE harness = ? LIMIT 1", (user["handle"],)
    ).fetchone() is not None


# BETON-257: één gedeelde rubriek voor "moet dit item opgeknipt worden in subtaken?".
# Zowel het opknip-ADVIES van triage (`decompose_suggestion`) als het opknip-PROCES
# (decompose.DECOMPOSE_SYSTEM_PROMPT) embedden exact deze tekst, zodat ze dezelfde lat
# hanteren. Vroeger adviseerde triage al bij "meerdere zelfstandige stappen" terwijl
# decompose ≥3 zelfstandige stappen + te-groot-voor-één-sessie eist en "nee bij twijfel"
# zegt — triage beloofde dan een opknipsel dat decompose vervolgens weigerde. Deze
# constante woont in triage.py (niet in decompose.py) om de bestaande
# decompose→triage-import acyclisch te houden.
DECOMPOSE_CRITERIA = """Opknippen is de uitzondering, niet de regel; het \
standaardantwoord is NIET opknippen. Adviseer/knip alleen op als ALLE onderstaande \
criteria kloppen:
- De taak bestaat uit minstens 3 werkelijk zelfstandige stappen die los van elkaar \
opgepakt en afgerond kunnen worden.
- Die stappen zijn concreet genoeg om elk als eigen taak te bestaan (geen vage of \
kunstmatig opgesplitste flarden).
- De taak is te groot om in één werksessie af te ronden.
Zeg NEE bij twijfel: een taak die heel blijft is bijna altijd de juiste keuze. Kleine, \
enkelvoudige of in één werksessie afrondbare taken knip je NIET op — dat levert alleen \
administratieve ruis op."""


TRIAGE_SYSTEM_PROMPT = (
    """Je bent de triage-bot voor Betonning, een work-item-tracker \
met meerdere projecten. Je classificeert één nieuw item en antwoordt met JSON.

Velden:
- type_label: één van bug, feature, question, refactor, research, chore, docs, perf.
- model_label: de werkklasse van de taak, voor elke assignee hetzelfde: \
"routine" (afgebakend, voorspelbaar werk: enkel-bestand, simpele fix, tests, \
config, docs), "standaard" (gewoon feature- en bugwerk) of "complex" (multi-file \
refactor, nieuw ontwerp, lastige debugging, architectuur). Het model dat daarbij \
hoort staat in de instellingen per agent; noem zelf nooit een modelnaam. Twijfel \
je tussen twee klassen, kies de lichtere.
- priority: urgent | high | medium | low | none (voor niet-bugs meestal none).
- workload: geschatte hoeveelheid werk als light | medium | heavy. Dit is een \
inschatting van de TOKENkosten van het uitvoeren van dit item, NIET van hoeveel \
tijd een mens eraan zou besteden — denk niet in "een uur"/"een dag". light = kleine \
afgebakende taak (één bestand, typefout, config-tweak); medium = meerdere bestanden \
of een feature met tests, enig uitzoekwerk; heavy = groot samenhangend werk over veel \
bestanden, een migratie, een nieuw (sub)systeem of diep debuggen. Antwoord met \
exact "light", "medium" of "heavy" (niet de Nederlandse woorden).
- assignee: kies ACTIEF de best passende assignee. Voor gewoon codewerk kies je \
"coding-agent" — de gedeelde coding-queue die door Claude, Codex, zcode en andere \
coding-agents opgepakt mag worden. Wijs coding-werk NOOIT direct toe aan een \
individuele coding-agent (claude/codex/zcode). Kijk voor Hermes-taken naar de lijst \
"Beschikbare agents (met expertise)" hierboven en match op de omschrijving van de \
agent, niet op de naam: kies een specifieke Hermes-agent alleen bij een DUIDELIJKE \
specialist-match, en anders de virtuele "hermes-agent" (het Hermes-team beslist zelf wie \
oppakt). Kies een handle uit "Beschikbare mensen" ALLEEN als het item een blokkerende vraag of \
beslissing bevat/oproept die de mens moet beantwoorden vóórdat er gebouwd kan worden \
(bv. een productkeuze, iets dat expliciet menselijke input vraagt). Kies een mens \
dus terughoudend: niet omdat iets groot/onduidelijk/risicovol is, maar alleen omdat \
een mens iets moet BESLISSEN voordat een agent kan starten. Gebruik altijd een handle \
die in de agentlijst of de lijst met beschikbare mensen staat. Verzin geen handles.
- assignee_reason: één zin (in de ingestelde uitvoertaal).
- duplicate_of: ref (bv. "SOS-42") als dit een duplicaat is van een OPEN kandidaat, \
anders null. Staat de kandidaat op Done/Cancelled, dan geen duplicaat maar related_to.
- related_to: lijst van refs die gerelateerd zijn (geen strikte duplicaten).
- state: exacte state-naam als het item direct in een andere kolom hoort, anders null.
- comment: triage-samenvatting in de ingestelde uitvoertaal (2-3 zinnen) — ALLEEN als die \
inhoudelijk iets toevoegt: een onduidelijkheid verduidelijken of een concrete \
vervolgvraag stellen over ontbrekende informatie. Is de bestaande omschrijving al \
duidelijk genoeg om mee te starten, laat comment dan leeg (""). Herhaal nooit \
gewoon wat de omschrijving al zegt. LET OP: kies je een menselijke assignee, dan wijs \
je toe omdat de mens iets moet BESLISSEN — formuleer de comment dan als een \
directe, beknopte vraag aan hem (de vraag wordt als vraagmodule-vraag geplaatst).
- question_options: ALLEEN invullen als je aan een mens toewijst én de beslissing \
een discrete keuze is — een lijst korte antwoordopties (max 6) waaruit hij met één \
klik kan kiezen. Is het een open vraag (vrij tekstantwoord), laat dit null. Bij een \
niet-menselijke assignee altijd null.
- decompose_suggestion: true ALLEEN als deze taak volgens de opknip-criteria \
hieronder opgeknipt hoort te worden in subtaken; anders false. Hanteer exact dezelfde \
lat als het opknip-proces zelf — beloof geen opknipsel dat vervolgens geweigerd wordt.
- decompose_reason: bij decompose_suggestion één korte zin waarom (in de ingestelde uitvoertaal).

## Opknip-criteria (identiek aan het opknip-proces)
"""
    + DECOMPOSE_CRITERIA
    + """

Schrijf de comment overzichtelijk, niet als één blok tekst: gebruik witregels \
tussen losse gedachten en een opsomming als je meerdere punten noemt. Geen wall \
of text.

Antwoord ALLEEN met valide JSON, zonder codeblokken of uitleg eromheen."""
    + llm_mod.UNTRUSTED_INPUT_RULE
)


def _context_text(context: dict) -> str:
    lines = [f"# Project: {context.get('project_name', '?')}"]
    if context.get("states"):
        names = ", ".join(
            f"{s['name']} ({s.get('group', '?')})" for s in context["states"]
        )
        lines.append(f"States: {names}")
    if context.get("labels"):
        lines.append(f"Bestaande labels: {', '.join(context['labels'])}")
    if context.get("users"):
        lines.append(f"Handles: {', '.join('@' + u for u in context['users'])}")
    if context.get("humans"):
        lines.append("Beschikbare mensen: " + ", ".join("@" + handle for handle in context["humans"]))
    # BETON-67: de agent-roster met expertise, zodat de LLM op de best passende
    # agent kan routeren i.p.v. vaste agent- of persoonsnamen.
    if context.get("agents"):
        lines.append("")
        lines.append("Beschikbare agents (met expertise):")
        for a in context["agents"]:
            desc = (a.get("description") or "").strip() or "(geen omschrijving)"
            lines.append(f"- @{a['handle']}: {desc}")
    return "\n".join(lines)


def _candidates_text(candidates: list[dict]) -> str:
    if not candidates:
        return "(geen gelijkende items)"
    out = []
    for c in candidates:
        labels = ", ".join(c.get("labels") or []) or "-"
        out.append(
            f"- {c['ref']}: {c['title']} [state={c.get('state')}, "
            f"priority={c.get('priority')}, labels={labels}]"
        )
        desc = (c.get("description_md") or "").strip()
        if desc:
            out.append(f"  {desc[:200]}")
    return "\n".join(out)


def build_triage_messages(
    item: dict,
    context: dict,
    candidates: list[dict],
    *,
    images: list[dict] | None = None,
) -> list[dict]:
    """Bouw de chat-messages voor triage (pure functie, testbaar).

    Zonder ``images`` is de user-content een string (backward-compat). Met
    ``images`` (OpenAI-vision content-blocks, zie llm.build_image_block) wordt
    de user-content een lijst ``[text-block, *image-blocks]`` (BETON-130)."""
    user = (
        f"{_context_text(context)}\n\n"
        "## Gelijkende bestaande items (voor duplicaat-detectie)\n"
        f"{llm_mod.fenced('kandidaten', _candidates_text(candidates))}\n\n"
        "## Nieuw item om te triagen\n"
        f"{llm_mod.item_block(item)}"
    )
    return [
        {"role": "system", "content": llm_mod.localized_system_prompt(TRIAGE_SYSTEM_PROMPT)},
        {"role": "user", "content": llm_mod.user_content(user, images)},
    ]


# Gedeelde tolerante JSON-extractie woont nu in llm.py (BETON-163); hier als
# module-lokale naam behouden zodat bestaande importeurs (decompose) blijven
# werken zonder duplicatie.
_extract_json = llm_mod.extract_json


def _safe_str(v, default: str) -> str:
    v = _coerce_scalar(v)
    return v if isinstance(v, str) and v.strip() else default


def parse_triage(text: str) -> TriageResult:
    """Parse de LLM-output; val terug op veilige defaults bij invalide JSON/velden.

    Vangt zowel ValidationError (ongeldige velden) als ValueError (geen/kapotte
    JSON in de output) — spiegelt de sibling-parsers (parse_comment_eval etc.).
    Zonder deze ValueError-vangst zou output zonder '{' triage_once laten crashen
    en het item eeuwig ongemarkeerd achterlaten (BETON-40)."""

    def _fallback(raw: dict, exc: Exception) -> TriageResult:
        # Partial-salvage: put wat wél bruikbaar was uit de ruwe dict, i.p.v.
        # de hele output weg te gooien (BETON-40).
        safe = {
            "type_label": _safe_str(raw.get("type_label"), "chore"),
            # Geen tekstvulling meer (BETON-189): een lege comment is een
            # geldige uitkomst, apply_triage beslist zelf of stilte terecht is.
            "comment": _safe_str(raw.get("comment"), ""),
            "assignee_reason": _safe_str(raw.get("assignee_reason"), ""),
        }
        return TriageResult(type_label=safe["type_label"], comment=safe["comment"], assignee_reason=safe["assignee_reason"])

    return llm_mod.parse_json_result(
        text, TriageResult, context="Triage-output", fallback=_fallback, log=logger
    )


# --- Comment-evaluatie (fase 2: mens ↔ agent) ---------------------------


class CommentEvalResult(BaseModel):
    # assign_claude: het ticket is nu duidelijk genoeg → toewijzen aan claude.
    # clarify: nog onvoldoende → een vervolgvraag plaatsen (assignee blijft).
    # answer: een directe vraag aan @triage → inhoudelijk beantwoorden als comment
    #   (assignee blijft; BETON-178).
    # noop: geen actie nodig.
    action: str = "noop"
    comment: str = ""
    # BETON-389: is de vervolgvraag (clarify) aan een MENS gericht, dan wordt hij
    # als vraagmodule-vraag geplaatst (kind='question', BETON-219) i.p.v. een
    # platte comment die wegzakt. Bij een discrete keuze levert de LLM hier de
    # antwoordopties. Zelfde veld en zelfde opschoning als `TriageResult`.
    question_options: list[str] | None = None

    @field_validator("question_options", mode="before")
    @classmethod
    def _clean_options(cls, v):
        return clean_question_options(v)

    @field_validator("action", mode="before")
    @classmethod
    def _norm_action(cls, v):
        v = _coerce_scalar(v)
        v = v.strip().lower() if isinstance(v, str) else v
        return v if v in ("assign_claude", "clarify", "answer", "noop") else "noop"

    @field_validator("comment", mode="before")
    @classmethod
    def _coerce_comment(cls, v):
        return _coerce_scalar(v)


COMMENT_EVAL_SYSTEM_PROMPT = (
    """Je bent de triage-bot voor Betonning. Er is een \
nieuwe reactie geplaatst op een work item. Beoordeel of het item nu duidelijk \
genoeg is om door de AI-coder @claude opgepakt te worden, of dat er nog een \
vervolgvraag nodig is, óf dat er een directe vraag aan jou (de triage-bot) \
openstaat die je moet beantwoorden. Antwoord met JSON.

Wees TERUGHOUDEND: "noop" is de default. Reageer alleen (action != "noop") als \
er een concrete vraag aan de bot/het team openstaat, een echte blokkade is, of \
iets dat daadwerkelijk actie vergt (bv. het item is nu duidelijk genoeg om op te \
pakken, of er ontbreekt info om verder te kunnen). Reageer NIET op bevestigingen \
("oke", "dank je", "duidelijk"), bedankjes, of losse/terloopse opmerkingen die \
geen vervolgactie vragen — daar is "noop" het juiste antwoord.

Velden:
- action: "assign_claude" als de reactie het item duidelijk genoeg maakt om te \
bouwen; "clarify" als er nog een concrete vervolgvraag nodig is; "answer" als de \
reactie een DIRECTE vraag aan jou (de triage-bot) bevat — een mention van @triage \
mét een vraagintentie — die je inhoudelijk kunt beantwoorden op basis van de \
item-context (state, assignee, historie, thread); "noop" (default) als er niets \
hoeft te gebeuren. Gebruik "answer" ALLEEN bij een echte, directe vraag aan de \
bot; bij bevestigingen of terloopse opmerkingen blijft "noop" het antwoord.
- comment: bij assign_claude een korte toelichting waarom het nu opgepakt kan \
worden; bij clarify de concrete vervolgvraag; bij answer het inhoudelijke \
antwoord op de gestelde vraag (in de ingestelde uitvoertaal, op basis van de item-context); bij \
noop leeg.
- question_options: ALLEEN bij action="clarify" en alleen als je vervolgvraag \
een discrete keuze is (bv. "welke van deze twee?"). Geef dan de \
antwoordmogelijkheden als korte lijst strings (max 6). Bij een open vraag laat \
je dit veld weg (null). Vraag je iets aan een mens, dan wordt de vraag met deze \
opties als klikbare keuze voorgelegd i.p.v. als losse reactie.

Schrijf de comment overzichtelijk met witregels tussen losse gedachten; geen \
wall of text. Verwijs naar personen/agents zonder letterlijke @ (dus "claude", \
niet "@claude") om onbedoelde mention-notificaties te voorkomen.

Antwoord ALLEEN met valide JSON, zonder codeblokken of uitleg eromheen."""
    + llm_mod.UNTRUSTED_INPUT_RULE
)


def _thread_text(comments: list[dict]) -> str:
    """De reactie-thread als tekst, per comment én in totaal begrensd (BETON-387)."""
    if not comments:
        return "(geen eerdere reacties)"
    return llm_mod.clamp(
        "\n".join(
            f"- @{c.get('author') or '?'}: "
            f"{llm_mod.clamp((c.get('body_md') or '').strip(), llm_mod.MAX_COMMENT)}"
            for c in comments
        ),
        llm_mod.MAX_THREAD,
    )


def build_comment_eval_messages(
    item: dict,
    context: dict,
    comments: list[dict],
    new_comment: dict,
    images: list[dict] | None = None,
) -> list[dict]:
    """Bouw de chat-messages voor comment-evaluatie (pure functie, testbaar).

    Met ``images`` (vision-blocks, zie triage_worker.gather_images) wordt de
    user-content een lijst ``[text, *images]`` (BETON-477)."""
    # BETON-178: als de nieuwe reactie @triage expliciet mentiont, geef die hint
    # mee zodat het model weet dat de bot direct aangesproken wordt (en dus mag
    # antwoorden i.p.v. terughoudend noop'en). Case-insensitive.
    handles = [h.lower() for h in mentions.parse(new_comment.get("body_md"))]
    directed = "triage" in handles
    hint = (
        "\n\n(De reactie hierboven spreekt @triage direct aan — beantwoord een "
        'eventuele vraag met action="answer".)'
        if directed
        else ""
    )
    nieuw = (
        f"@{new_comment.get('author') or '?'}: "
        f"{llm_mod.clamp(new_comment.get('body_md'), llm_mod.MAX_COMMENT)}"
    )
    user = (
        f"{_context_text(context)}\n\n"
        "## Item\n"
        f"{llm_mod.item_block(item)}\n"
        f"Huidige assignee: @{item.get('assignee') or 'niemand'}\n\n"
        "## Reactie-thread\n"
        f"{llm_mod.fenced('reacties', _thread_text(comments))}\n\n"
        "## Nieuwe reactie om op te beoordelen\n"
        f"{llm_mod.fenced('reactie', nieuw)}"
        f"{hint}"
    )
    return [
        {"role": "system", "content": llm_mod.localized_system_prompt(COMMENT_EVAL_SYSTEM_PROMPT)},
        {"role": "user", "content": llm_mod.user_content(user, images)},
    ]


def parse_comment_eval(text: str) -> CommentEvalResult:
    """Parse de LLM-output; val terug op noop bij invalide JSON."""
    return llm_mod.parse_json_result(
        text,
        CommentEvalResult,
        context="Comment-eval-output",
        fallback=lambda raw, exc: CommentEvalResult(),
        log=logger,
    )


def apply_comment_eval(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    comment_id: int,
    result: CommentEvalResult,
    actor_id: int,
) -> None:
    """Pas een CommentEvalResult toe (reassign/vervolgvraag/antwoord) en markeer
    de beoordeelde comment. Eén transactie."""
    with db_module.transaction(conn):
        # BETON-282: een reactie op één specifieke comment is gericht aan de
        # auteur daarvan — niet aan de assignee (die kreeg 'm hiervoor blind, en
        # las er "reageer" in). De auteur is per definitie een prior participant,
        # dus `build_trigger` typeert hem als 'participant'/'assigned' → `respond`.
        _apply_eval_result(
            conn,
            item,
            result,
            actor_id,
            addressed_to=_comment_author_handles(conn, comment_id, actor_id),
        )
        # Marker: beoordeeld (ongeacht de uitkomst → niet opnieuw beoordelen).
        events_repo._touch(conn, "comments", "evaluated_at", comment_id)


def _apply_eval_result(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    result: CommentEvalResult,
    actor_id: int,
    *,
    addressed_to: Iterable[str] = (),
) -> None:
    """De reactie zelf van een CommentEvalResult (reassign/comment) — zónder
    marker. Gedeeld door de comment-evaluatie (BETON-178) en de reactie op een
    toewijzing aan triage (BETON-287); de aanroeper zet zijn eigen marker en
    opent de transactie, zodat reactie + marker altijd samen committen.

    ``addressed_to`` is wie triage aanspreekt bij een clarify/answer — de fanout is
    gericht (BETON-282). Bij `assign_claude` blijft de comment bewust ongeadresseerd:
    het "pak dit op"-sein is daar de `item.updated`-fanout naar de coding-queue, niet
    de toelichtende comment. `assign_claude` doet NIETS (stille no-op) als het item
    al bij IEMAND ANDERS ligt dan triage zelf (BETON-410) — niet alleen een mens:
    een Hermes-agent die het al onder zich heeft telt net zo goed."""
    if result.action == "assign_claude":
        # BETON-410: staat het item al bij iemand anders dan triage zelf? (een
        # mens die het net zelf toewees voor review, óf een andere agent die er
        # al mee bezig is — niet specifiek een mens: elke bestaande, bewuste
        # toewijzing telt.) Dan mag een oudere, nog niet beoordeelde reactie die
        # toewijzing niet alsnog overschrijven naar de coding-queue. `actor_id`
        # is hier altijd de triage-bot zelf (elke aanroeper geeft `triage_user_id`
        # door) — assignee_id == actor_id is dus precies het legitieme geval uit
        # BETON-287: iemand wees het item BEWUST aan triage toe, dat mag wél
        # doorgaan naar de coding-queue.
        # BETON-431: dit is ook de poort voor een open vraag aan een mens — die
        # staat dan op de mens (assignee != triage), dus triage zet hem niet weg.
        current_id = item["assignee_id"]
        if current_id is not None and current_id != actor_id:
            return
        agent = users_repo.get_by_handle(conn, users_repo.VIRTUAL_CODING)
        if agent is not None:
            items_repo.update(conn, item["id"], {"assignee_id": agent["id"]})
            webhooks.record_and_fanout(
                conn,
                type="item.updated",
                item_id=item["id"],
                actor_id=actor_id,
                payload={"assignee": users_repo.VIRTUAL_CODING},
            )
        # BETON-89: geen letterlijke @handle in de comment-body (voorkomt
        # mention-spam/webhook-fanout op de triage-comment zelf).
        body = result.comment or outbound('apply_eval_result.1')
        _post_triage_comment(conn, item, body, actor_id)
    # clarify (eigen vervolgvraag) én answer (direct antwoord op een @triage-
    # vraag, BETON-178) plaatsen beide alleen een comment — géén assignee-
    # wijziging. Zelfde pad, zodat het antwoord nooit per ongeluk reassignt.
    elif result.action in ("clarify", "answer") and result.comment:
        # BETON-389: een `clarify` is per definitie een vraag om input. Is de
        # aangesprokene een mens, dan hoort die vraag in de vraagmodule
        # (kind='question', BETON-219) — hij komt dan in `get_open_questions`, is
        # met één klik te beantwoorden en zakt niet weg tussen de reacties. Een
        # `answer` is géén vraag en blijft altijd een gewone comment.
        human = _first_human_handle(conn, addressed_to)
        as_question = result.action == "clarify" and human is not None
        _post_triage_comment(
            conn,
            item,
            result.comment,
            actor_id,
            addressed_to=addressed_to,
            kind="question" if as_question else "comment",
            options=result.question_options if as_question else None,
            # BETON-478: een vervolgvraag uit een evaluatie zet geen ticket om
            # dat een mens zelf bij iemand legde.
            keep_human_choice=True,
        )


# --- Reactie op een toewijzing aan triage (BETON-287) -----------------------
#
# `triaged_at` haalt een item permanent uit `find_untriaged`, dus een látere
# toewijzing aan triage triggerde niets. De worker pollt daarom apart op items die
# aan triage zijn toegewezen (`triage_worker.find_assigned_to_triage`); dit is de
# prompt/apply-kant daarvan. Hergebruikt bewust het CommentEvalResult-vocabulaire
# (assign_claude/clarify/answer/noop): "iemand legt dit bij triage neer" vraagt om
# precies dezelfde vier uitkomsten als een reactie op een comment.

ASSIGN_EVAL_SYSTEM_PROMPT = (
    """Je bent de triage-bot voor Betonning. Een work item \
is zojuist aan JOU (de triage-bot) toegewezen — iemand legt dit item dus bewust bij \
jou neer en verwacht een reactie. Beoordeel wat er moet gebeuren en antwoord met JSON.

Anders dan bij een losse reactie is "noop" hier NIET de default: de toewijzing is een \
expliciet verzoek om actie. Kies "noop" alleen als er echt niets zinnigs te doen of te \
zeggen valt.

Velden:
- action: "assign_claude" als het item duidelijk genoeg is om gebouwd te worden \
(dan gaat het naar de coding-queue); "clarify" als je concrete informatie mist en \
een vervolgvraag moet stellen; "answer" als je op basis van de item-context \
(titel, beschrijving, state, thread) inhoudelijk kunt reageren op waarvoor het bij \
jou is neergelegd; "noop" als er niets hoeft te gebeuren.
- comment: bij assign_claude een korte toelichting; bij clarify de concrete \
vervolgvraag; bij answer je inhoudelijke reactie (in de ingestelde uitvoertaal); bij noop leeg.
- question_options: ALLEEN bij action="clarify" en alleen bij een discrete \
keuze — korte lijst antwoordmogelijkheden (max 6), anders null.

Schrijf de comment overzichtelijk met witregels tussen losse gedachten; geen \
wall of text. Verwijs naar personen/agents zonder letterlijke @ (dus "claude", \
niet "@claude") om onbedoelde mention-notificaties te voorkomen.

Antwoord ALLEEN met valide JSON, zonder codeblokken of uitleg eromheen."""
    + llm_mod.UNTRUSTED_INPUT_RULE
)


def build_assign_eval_messages(
    item: dict,
    context: dict,
    comments: list[dict],
    assigned_by: str | None = None,
    images: list[dict] | None = None,
    answers: list[dict] | None = None,
) -> list[dict]:
    """Bouw de chat-messages voor een toewijzing aan triage (pure functie).
    ``images``: vision-blocks, zoals bij de comment-eval (BETON-477).
    ``answers``: pseudo-comments (`format_answered_question`) van antwoorden op
    triage-vragen die bij dezelfde menselijke actie hoorden (BETON-478)."""
    by = f"@{assigned_by}" if assigned_by else "iemand"
    answered_text = ""
    if answers:
        lines = "\n\n".join(f"@{a['author'] or 'iemand'}: {a['body_md']}" for a in answers)
        answered_text = (
            "\n\nDaarbij kwam ook een antwoord op je eigen vraag binnen:\n"
            f"{llm_mod.fenced('antwoorden', lines)}"
        )
    user = (
        f"{_context_text(context)}\n\n"
        "## Item\n"
        f"{llm_mod.item_block(item)}\n"
        f"Huidige state: {item.get('state') or '(geen)'}\n\n"
        "## Reactie-thread\n"
        f"{llm_mod.fenced('reacties', _thread_text(comments))}\n\n"
        f"## Wat er gebeurde\n{by} heeft dit item aan jou (@triage) toegewezen.{answered_text}"
    )
    return [
        {"role": "system", "content": llm_mod.localized_system_prompt(ASSIGN_EVAL_SYSTEM_PROMPT)},
        {"role": "user", "content": llm_mod.user_content(user, images)},
    ]


def apply_assign_eval(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    result: CommentEvalResult,
    actor_id: int,
    *,
    assign_event_id: int,
    addressed_to: Iterable[str] = (),
    answered_question_ids: Iterable[int] = (),
) -> None:
    """Pas de reactie op een toewijzing toe én zet de idempotentie-marker.

    De marker (`items.triage_assign_event_id`) draagt het id van het assignment-event
    dat hiermee is afgehandeld, en wordt — net als `comments.evaluated_at` — gezet
    ONGEACHT de uitkomst: ook een noop is een afgehandelde toewijzing. Zonder dat zou
    een stille beoordeling elke ronde terugkomen (precies de lus die BETON-282 voedt).
    Reactie + marker zitten in één transactie: een crash ertussen kan de marker niet
    zetten zónder de reactie (en andersom)."""
    with db_module.transaction(conn):
        _apply_eval_result(conn, item, result, actor_id, addressed_to=addressed_to)
        conn.execute(
            "UPDATE items SET triage_assign_event_id = ? WHERE id = ?",
            (assign_event_id, item["id"]),
        )
        # BETON-478: antwoorden die als context meegingen zijn hiermee afgehandeld.
        for qid in answered_question_ids:
            conn.execute(
                f"UPDATE comments SET evaluated_at = {events_repo.NOW_SQL} WHERE id = ?",
                (qid,),
            )


def _first_human_handle(
    conn: sqlite3.Connection, handles: Iterable[str]
) -> str | None:
    """De eerste handle uit `handles` die bij een MENS hoort, of None (BETON-389).

    Bepaalt of een vervolgvraag van triage in de vraagmodule thuishoort: alleen
    een mens kan een vraag in de UI beantwoorden. Agents lezen hun vraag gewoon
    als comment (hun kanaal is de webhook-trigger, niet `get_open_questions`)."""
    for handle in handles:
        if not handle:
            continue
        user = users_repo.get_by_handle(conn, handle)
        if user is not None and user["kind"] == "human":
            return user["handle"]
    return None


# --- Terugkoppeling op een beantwoorde triage-vraag (BETON-389) -------------
#
# Een `clarify` als vraagmodule-vraag stellen is alleen een verbetering als het
# antwoord óók bij triage terugkomt. Het antwoord staat sinds BETON-265 inline op
# de vraag — er is dus géén antwoord-comment die `find_unevaluated_comments` kan
# oppikken, en `question.answered` wekt niets. Zonder deze route zou de vraag een
# doodlopende straat zijn: mens antwoordt, triage merkt het nooit.
#
# Idempotentie zonder migratie: `_post_triage_comment` zet `evaluated_at` op de
# vraag bij het plaatsen. "Nog te verwerken" = `answered_at > evaluated_at`; na
# afhandeling schuift `evaluated_at` er weer overheen. Een bewerkt antwoord
# (BETON-263) verzet `updated_at`, niet `answered_at`, dus dat triggert geen
# tweede ronde.


def format_answered_question(question: dict) -> dict:
    """Zet een beantwoorde vraag-comment om in een pseudo-comment die als "nieuwe
    reactie" door de comment-evaluatie kan (pure functie, testbaar).

    De auteur is de béantwoorder — de LLM beoordeelt het antwoord, niet de vraag
    die hij zelf stelde. De vraagtekst gaat als context mee zodat een kaal "ja"
    of een gekozen optie interpreteerbaar blijft."""
    options = question.get("question_options") or []
    idx = question.get("answer_option_index")
    chosen = options[idx] if idx is not None and 0 <= idx < len(options) else None
    answer = (chosen or question.get("answer_text") or "").strip()
    vraag = (question.get("body_md") or "").strip()
    return {
        "author": question.get("answered_by"),
        "body_md": outbound('format_answered_question.1', p0=(vraag), p1=(answer)),
    }


def apply_answer_eval(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    question_id: int,
    result: CommentEvalResult,
    actor_id: int,
    *,
    addressed_to: Iterable[str] = (),
) -> None:
    """Pas de reactie op een beantwoorde triage-vraag toe én schuif de marker op.

    Spiegelt `apply_comment_eval`: reactie + marker in één transactie, marker
    gezet ongeacht de uitkomst (ook een noop is afgehandeld — anders komt deze
    vraag elke ronde terug).

    Bewust géén `events_repo._touch`: die schrijft alleen als de kolom nog NULL
    is, en op een vraag stáát `evaluated_at` al (gezet bij het plaatsen). De
    marker moet hier vóórbij `answered_at` schuiven, dus hij wordt onvoorwaardelijk
    opnieuw gezet."""
    with db_module.transaction(conn):
        _apply_eval_result(conn, item, result, actor_id, addressed_to=addressed_to)
        conn.execute(
            f"UPDATE comments SET evaluated_at = {events_repo.NOW_SQL} WHERE id = ?",
            (question_id,),
        )


def _comment_author_handles(
    conn: sqlite3.Connection, comment_id: int, actor_id: int
) -> list[str]:
    """De handle van de auteur van `comment_id` — de aangesprokene van een
    triage-reactie (BETON-282). Leeg als de auteur onvindbaar is of triage zelf
    is (`fanout` skipt de actor toch al; dit houdt de intentie expliciet)."""
    row = comments_repo.get(conn, comment_id)
    if row is None or row["author_id"] == actor_id:
        return []
    author = users_repo.get(conn, row["author_id"])
    return [author["handle"]] if author is not None else []


def _post_triage_comment(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    body: str,
    actor_id: int,
    addressed_to: Iterable[str] = (),
    *,
    kind: str = "comment",
    options: list[str] | None = None,
    keep_human_choice: bool = False,
) -> None:
    """Plaats een triage-comment en notificeer alléén wie hij aanspreekt (BETON-282).

    ``kind='question'`` (+ optionele ``options``) plaatst hem als vraagmodule-vraag
    (BETON-219/389) i.p.v. een platte comment: hij verschijnt dan in
    `get_open_questions`, is met één klik te beantwoorden en zakt niet weg in de
    thread. Alleen zinvol als de aangesprokene een mens is — de aanroeper beslist
    dat, deze functie voert alleen uit.

    De fanout is **gericht** (`directed=True`): een triage-comment is geen
    "pak dit op"-sein voor de assignee. Zonder dat vlaggetje voegt `fanout` de
    assignee automatisch toe (`webhooks.py`: `if assignee_id is not None and not
    directed`) en maakt `build_instructions` daar `respond` van — dát is hoe Lies
    een ping kreeg op een comment die niet aan haar gericht was.

    De ironie die dit veroorzaakte: triage zet bewust géén letterlijke `@handle`
    in de body (BETON-89, tegen mention-spam), dus `build_trigger.addressed_to`
    blijft leeg en `only_reading` wordt nooit waar — de body-parse kan de
    adressering hier dus niet redden. Vandaar dat de aanroeper de aangesprokene
    expliciet via ``addressed_to`` meegeeft; dat is los van de body-parse de
    enige bron van adressering op dit pad. (Niet ``mentions`` genoemd: deze
    module importeert een gelijknamige module — en de handles gaan hier
    bewust níet de body in.)
    """
    row = comments_repo.create(
        conn,
        item_id=item["id"],
        author_id=actor_id,
        body_md=body,
        kind=kind,
        question_options=options if kind == "question" else None,
    )
    if kind == "question":
        # BETON-431: een open vraag aan een mens hoort bij die mens op het bord.
        question_assign.assign_for_question(
            conn,
            item_id=item["id"],
            question_id=row["id"],
            body_md=body,
            actor_id=actor_id,
            addressed_to=addressed_to,
            keep_human_choice=keep_human_choice,
        )
    # De net-geplaatste triage-comment is al 'beoordeeld' (voorkomt zelf-lus).
    # Bij een vraag is deze marker tegelijk het nulpunt voor de terugkoppeling
    # (BETON-389): pas een `answered_at` NÁ dit moment maakt de vraag weer vers.
    events_repo._touch(conn, "comments", "evaluated_at", row["id"])
    webhooks.record_and_fanout(
        conn,
        type="comment.created",
        item_id=item["id"],
        actor_id=actor_id,
        payload={"comment_id": row["id"]},
        mentions=addressed_to,
        directed=True,
    )


# --- Verrijking via comments (BETON-163) -----------------------------------
#
# Enrich stelt bij te magere input vragen als comment onder `triage` i.p.v. een
# pseudo-omschrijving. Een menselijke reactie op zulke vragen laat de bot de
# verrijking opnieuw proberen (re-enrich in de worker). De markers maken de
# thread-staat deterministisch afleesbaar: staat de LAATSTE enrich-comment van
# triage nog op "vraag", dan is er een openstaande vraag (en triggert een mens-
# reactie een nieuwe poging); staat hij op "voorstel", dan is de ronde klaar.

ENRICH_QUESTION_MARKER = "[Verrijking: vraag]"
ENRICH_PROPOSAL_MARKER = "[Verrijking: voorstel]"


def format_enrich_questions(questions: list[str]) -> str:
    """Bouw de comment-body met openstaande verrijkingsvragen (pure, testbaar).

    BETON-89: geen letterlijke @handles in de body (voorkomt mention-fanout op
    de triage-comment zelf)."""
    lines = [
        ENRICH_QUESTION_MARKER,
        "",
        outbound('format_enrich_questions.1'),
        "",
    ]
    lines.extend(f"- {q}" for q in questions)
    return "\n".join(lines)


def format_enrich_proposal(proposal: str) -> str:
    """Bouw de comment-body met een verrijkings-VOORSTEL (pure, testbaar).

    Het voorstel wordt NOOIT automatisch in de omschrijving gezet — dat blijft
    voorstellen-en-bevestigen. De comment nodigt de mens uit het via de
    Verrijk-knop te bekijken en te bevestigen."""
    return "\n".join(
        [
            ENRICH_PROPOSAL_MARKER,
            "",
            outbound('format_enrich_proposal.1'),
            "",
            "---",
            "",
            proposal,
        ]
    )


def has_outstanding_enrich_questions(comments: list[dict]) -> bool:
    """Staat er een onbeantwoorde verrijkingsvraag van triage open? (BETON-163)

    Deterministisch: kijk naar de LAATSTE enrich-comment van `triage` in de
    thread. Is dat een vraag → open (een mens-reactie hoort een nieuwe poging te
    triggeren). Is het een voorstel (of geen enrich-comment) → niet open. Zo
    termineert de lus: na een voorstel triggert een verdere reactie geen re-enrich."""
    latest_is_question = False
    for c in comments:
        if (c.get("author") or "") != "triage":
            continue
        body = (c.get("body_md") or "").lstrip()
        if body.startswith(ENRICH_QUESTION_MARKER):
            latest_is_question = True
        elif body.startswith(ENRICH_PROPOSAL_MARKER):
            latest_is_question = False
    return latest_is_question


def post_triage_comment(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    body: str,
    actor_id: int,
    addressed_to: Iterable[str] = (),
    *,
    kind: str = "comment",
    options: list[str] | None = None,
) -> None:
    """Publiek alias voor het plaatsen van een triage-comment (BETON-163).

    Gebruikt door het enrich-endpoint, de re-enrich in de worker, de
    parent-close-suggestie (BETON-303) en de stale-vraag (BETON-375). Beheert
    GEEN transactie — de caller wrapt zelf (mirror van apply_comment_eval)."""
    _post_triage_comment(
        conn, item, body, actor_id, addressed_to=addressed_to, kind=kind, options=options
    )


def apply_re_enrich(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    trigger_comment_id: int,
    result: "llm_mod.EnrichResult",
    actor_id: int,
) -> None:
    """Plaats de uitkomst van een nieuwe verrijkingspoging als comment (BETON-163).

    ``result.kind == "questions"`` → nieuwe vervolgvragen; ``"proposal"`` → het
    voorstel (nooit auto-opgeslagen: voorstellen-en-bevestigen blijft). Markeert
    de triggerende (menselijke) comment als beoordeeld zodat een volgende
    worker-sweep hem niet opnieuw oppakt. Eén transactie (mirror
    apply_comment_eval)."""
    if result.kind == "questions" and result.questions:
        body = format_enrich_questions(result.questions)
    else:
        body = format_enrich_proposal(result.description)
    with db_module.transaction(conn):
        _post_triage_comment(conn, item, body, actor_id)
        events_repo._touch(conn, "comments", "evaluated_at", trigger_comment_id)


# --- Stale-detectie (BETON-375) --------------------------------------------
#
# Een item in een `started`-state zonder activiteit hangt: niemand ziet het, en
# het bord liegt over wat er loopt. Triage vraagt de toegewezene dan wat de
# bedoeling is — via de vraagmodule (BETON-219), want de drie antwoorden zijn een
# discrete keuze en het antwoord moet een deterministische actie opleveren.
#
# Géén LLM: de vraag is elke keer dezelfde en de opties zijn vast. De marker in de
# body maakt de vraag herkenbaar bij het beantwoorden (spiegelt de ENRICH-markers
# hierboven); er is geen `meta`-kolom op comments om dat elders te zetten.

STALE_QUESTION_MARKER = "[Stil sinds]"

# Volgorde is contract: `apply_stale_answer` schakelt op de index.
STALE_OPTIONS = [
    "Nog mee bezig — laat staan",
    "Terug naar todo",
    "Vrijgeven aan de coding-queue",
]


def format_stale_question(days: int, mention: str | None = None) -> str:
    """Bouw de body van de stale-vraag (pure functie, testbaar).

    ``mention`` zet er een letterlijke `@handle` in. Dat is de uitzondering op
    BETON-89 (geen @handles in triage-bodies): `GET /questions?open=true` richt
    op assignee/maker/mention, dus voor iemand die géén assignee is, is de
    mention de énige manier waarop de vraag hem bereikt. Is de aangesprokene wél
    de assignee, dan is de mention overbodig en blijft hij weg."""
    wie = f"@{mention} " if mention else ""
    return "\n".join(
        [
            STALE_QUESTION_MARKER,
            "",
            outbound('format_stale_question.1', p0=(wie), p1=(days)),
        ]
    )


def is_stale_question(body: str | None) -> bool:
    """Is dit een stale-vraag van triage? (BETON-375)"""
    return (body or "").lstrip().startswith(STALE_QUESTION_MARKER)


def apply_stale_answer(
    conn: sqlite3.Connection, item: sqlite3.Row, option_index: int | None
) -> dict:
    """Zet het antwoord op een stale-vraag om in de bijbehorende mutatie.

    Deterministisch, geen LLM. Geeft de toegepaste velden terug (leeg bij optie 0
    of een vrij-tekstantwoord — dan is er niets te doen; het antwoord zelf is al
    activiteit en zet de her-vraag-klok opnieuw). De caller beheert de transactie
    en schrijft het event.

    - 0 "Nog mee bezig"        → niets; het item blijft staan waar het staat.
    - 1 "Terug naar todo"      → state naar de todo/default-state van het project.
    - 2 "Vrijgeven"            → todo-state én toewijzing aan de coding-queue.
    """
    fields: dict = {}
    if option_index == 1 or option_index == 2:
        state_id = items_repo.default_active_state_id(conn, item["project_id"])
        if state_id is not None and state_id != item["state_id"]:
            fields["state_id"] = state_id
    if option_index == 2:
        queue = users_repo.get_by_handle(conn, users_repo.VIRTUAL_CODING)
        if queue is not None and queue["id"] != item["assignee_id"]:
            fields["assignee_id"] = queue["id"]
    if fields:
        items_repo.update(conn, item["id"], fields)
    return fields


# --- Guardrail-review (BETON-420) ------------------------------------------
#
# Een guardrail kost elke agent tokens, elke ronde, dus de vraag "geldt dit
# nog?" moet vanzelf terugkomen. Verstreken reviewdatum → vaste vraag via de
# vraagmodule, gespiegeld op het stale-blok hierboven. Géén LLM: vraag en opties
# liggen vast.

GUARDRAIL_REVIEW_MARKER = "[Guardrail-review]"

# Volgorde is contract: `apply_guardrail_review_answer` schakelt op de index.
GUARDRAIL_REVIEW_OPTIONS = [
    "Blijft geldig — verleng de reviewdatum",
    "Vervalt — hef de guardrail op",
    "Aanpassen — ik pas de tekst zelf aan",
]


def format_guardrail_review_question(
    text: str, review_by: str, mention: str | None = None
) -> str:
    """Bouw de body van de reviewvraag (pure functie, testbaar).

    ``mention`` zet er een letterlijke `@handle` in — zelfde uitzondering op
    BETON-89 als `format_stale_question`: of een guardrail nog geldt is een
    menselijk oordeel, en de mens is hier zelden de assignee."""
    wie = f"@{mention} " if mention else ""
    return "\n".join(
        [
            GUARDRAIL_REVIEW_MARKER,
            "",
            outbound('format_guardrail_review_question.1', p0=(wie), p1=(review_by)),
            "",
            "> " + text.replace("\n", "\n> "),
        ]
    )


def is_guardrail_review_question(body: str | None) -> bool:
    """Is dit een guardrail-reviewvraag van triage? (BETON-420)"""
    return (body or "").lstrip().startswith(GUARDRAIL_REVIEW_MARKER)


def apply_guardrail_review_answer(
    conn: sqlite3.Connection, item: sqlite3.Row, option_index: int | None
) -> dict:
    """Zet het antwoord op een reviewvraag om in de bijbehorende mutatie.

    Deterministisch, geen LLM. Geeft de toegepaste velden terug; de caller
    beheert de transactie en schrijft het event.

    - 0 "Blijft geldig" → nieuwe reviewdatum (vandaag + de default-horizon) én
      `guardrail_review_asked_at` terug op NULL. Die marker is de énige
      her-vraag-poort: hem vergelijken met `guardrail_review_by` kan niet, want
      dat is een datum (`YYYY-MM-DD`) en de marker een timestamp — als string is
      `"2026-09-23" > "2026-09-23T10:00:00.000Z"` onwaar, waardoor een
      same-day-verlenging stilzwijgend nooit meer een vraag zou opleveren.
    - 1 "Vervalt"       → opheffen; de tekst blijft staan.
    - 2 / vrije tekst   → niets; de mens past hem zelf in de Drawer aan.
    """
    from .repo import guardrails as guardrails_repo

    if option_index == 0:
        row = conn.execute(
            "SELECT date('now', ?) AS d",
            (f"+{models.GUARDRAIL_DEFAULT_REVIEW_DAYS} days",),
        ).fetchone()
        conn.execute(
            "UPDATE items SET guardrail_review_by = ?, "
            "guardrail_review_asked_at = NULL WHERE id = ?",
            (row["d"], item["id"]),
        )
        return {"guardrail_review_by": row["d"]}
    if option_index == 1:
        guardrails_repo.lift(conn, item["id"])
        return {"guardrail_lifted_at": True}
    return {}


# --- Toepassen -------------------------------------------------------------


def _ensure_label(conn: sqlite3.Connection, project_id: int, name: str) -> int:
    row = labels_repo.get_by_name(conn, project_id, name)
    if row is not None:
        return row["id"]
    created = labels_repo.create(conn, project_id=project_id, name=name)
    return created["id"]


def _add_relation(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    user_type: str,
    target_ref: str,
    actor_id: int,
) -> None:
    try:
        target = items_repo.get_by_ref(conn, target_ref)
    except ValueError:
        target = None
    if target is None or target["id"] == item["id"]:
        return
    stored_type, reversed_ = relations_repo.NORMALIZE[user_type]
    src, dst = (target["id"], item["id"]) if reversed_ else (item["id"], target["id"])
    if relations_repo.reverse_exists(
        conn, item_id=src, related_item_id=dst, stored_type=stored_type
    ):
        return  # tegenstrijdige richting bestaat al → overslaan
    relations_repo.create(
        conn, item_id=src, related_item_id=dst, stored_type=stored_type
    )
    webhooks.record_and_fanout(
        conn,
        type="relation.created",
        item_id=item["id"],
        actor_id=actor_id,
        payload={"type": user_type, "target": target_ref},
    )


# Titelpatroon van een deliberatie-umbrella: "Overleg <onderwerp> <YYYY-MM-DD>".
_UMBRELLA_TITLE = re.compile(r"^\s*overleg\b.*\d{4}-\d{2}-\d{2}", re.IGNORECASE)


def agent_umbrella_reason(conn: sqlite3.Connection, item: sqlite3.Row) -> str | None:
    """Reden waarom `item` een agent-interne umbrella is, of None (BETON-213).

    Een umbrella is een container-ticket dat een Hermes-agent zelf aanmaakte (bv.
    een deliberatie-overleg): de echte actie zit in de kinderen. Zulke items horen
    niet naar de coding-queue gerouteerd te worden. Naast een Hermes-maker geldt
    minstens één container-signaal: lege/container-omschrijving, het
    "Overleg <x> <datum>"-titelpatroon, of reeds bestaande subtaken. Zonder
    container-signaal (Hermes-maker mét echte omschrijving, geen kinderen) blijft
    het gewone routering — bewust conservatief om niet te veel te blokkeren."""
    creator_id = item["created_by"]
    if creator_id is None:
        return None
    creator = users_repo.get(conn, creator_id)
    if creator is None or not users_repo.is_hermes_agent(creator):
        return None
    if not (item["description_md"] or "").strip():
        return outbound('agent_umbrella_reason.1')
    if _UMBRELLA_TITLE.match(item["title"] or ""):
        return outbound('agent_umbrella_reason.2')
    has_children = (
        conn.execute(
            "SELECT 1 FROM items WHERE parent_id = ? AND archived_at IS NULL LIMIT 1",
            (item["id"],),
        ).fetchone()
        is not None
    )
    if has_children:
        return outbound('agent_umbrella_reason.3')
    return None


def apply_triage(
    conn: sqlite3.Connection, item: sqlite3.Row, result: TriageResult, actor_id: int
) -> None:
    """Pas een TriageResult toe op het item (labels/priority/assignee/state/
    relaties/comment) en markeer het als getriaged. Eén transactie."""
    project_id = item["project_id"]
    with db_module.transaction(conn):
        # Veld-updates (priority/assignee/state) — alleen wat oplosbaar is én nog
        # niet expliciet door de maker is ingevuld. Triage vult AAN, overschrijft
        # niet (BETON-65): een bewust gezette priority/assignee/state blijft staan.
        # Afwijkend advies mag in de comment, maar niet als mutatie.
        fields: dict = {}
        changed: dict = {}
        # Priority: alleen zetten als het nog de default ('none') is én triage
        # een echte prioriteit voorstelt. 'none' is geen wijziging (item staat
        # al op 'none') en zou anders een no-op UPDATE + event + webhook-fanout
        # opleveren (BETON-112).
        if result.priority in ("urgent", "high", "medium", "low") and (
            item["priority"] == "none"
        ):
            fields["priority"] = result.priority
            changed["priority"] = result.priority
        # Assignee: alleen zetten als er nog geen assignee is. BETON-207: een
        # concrete coding-agent (claude/codex/zcode) wordt naar de virtuele
        # `coding-agent`-queue geklapt — de deterministische garantie dat triage
        # nooit direct aan een individuele coding-agent toewijst, ook als de LLM
        # er toch één noemt. Specifieke Hermes-agents en mensen blijven staan.
        umbrella_skip: str | None = None
        if result.assignee and item["assignee_id"] is None:
            handle = users_repo.collapse_to_virtual(conn, result.assignee)
            # BETON-213: agent-interne umbrella's (Hermes-maker + container-signaal)
            # niet naar de coding-queue routeren — ze horen bij hun maker/deliberatie-
            # lane, niet op het bord van de coding-agents. Alleen bij de coding-queue
            # ingrijpen; een expliciete Hermes-specialist blijft ongemoeid.
            if handle == users_repo.VIRTUAL_CODING:
                umbrella_skip = agent_umbrella_reason(conn, item)
            if umbrella_skip is None:
                u = users_repo.get_by_handle(conn, handle) if handle else None
                if u is not None:
                    fields["assignee_id"] = u["id"]
                    changed["assignee"] = handle

        # Effectieve assignee-handle ná de assignee-beslissing hierboven: de
        # bestaande assignee als die er al was, anders de handle die triage
        # zojuist zette (indien van toepassing). Bepaalt of het model_label
        # (routine/standaard/complex) toegepast mag worden.
        if item["assignee_id"] is not None:
            existing = users_repo.get(conn, item["assignee_id"])
            effective_handle = existing["handle"] if existing is not None else None
        else:
            effective_handle = changed.get("assignee")

        effective_user = users_repo.get_by_handle(conn, effective_handle) if effective_handle else None
        assigned_to_human = effective_user is not None and effective_user["kind"] == "human"
        # Tokenkosten horen bij agentwerk, ongeacht de handle van de mens.
        if (
            result.workload in ("light", "medium", "heavy")
            and item["workload"] is None
            and not assigned_to_human
        ):
            fields["workload"] = result.workload
            changed["workload"] = result.workload

        # Behoud de gekozen labels, maar vul een ontbrekende werkklasse aan.
        before_labels = sorted(row["name"] for row in conn.execute(
            "SELECT l.name FROM item_labels il JOIN labels l ON l.id=il.label_id WHERE il.item_id=?",
            (item["id"],),
        ))
        label_names = [result.type_label] if not before_labels else []
        if _uses_work_class(conn, effective_user) and not any(name.lower() in MODEL_CLASSES for name in before_labels):
            label_names.append(result.model_label)
        added_labels = [name for name in label_names if name]
        for name in added_labels:
            labels_repo.add_to_item(conn, item["id"], _ensure_label(conn, project_id, name))
        if added_labels:
            changed["labels"] = {"from": before_labels, "to": sorted(set(before_labels + added_labels))}

        if result.state:
            st = states_repo.get_by_name(conn, project_id, result.state)
            # Triage promoot geen backlog-items (BETON-34: backlog = nog niet
            # oppakken, de mens beslist over todo) en heropent geen gesloten items
            # (BETON-32: backfill mag done/cancelled niet terugzetten). En het
            # overschrijft geen bewust gezette state (BETON-65): alleen als het
            # item nog in z'n default-state (of state-loos) staat mag triage zetten.
            cur_state = conn.execute(
                "SELECT s.grp AS grp, s.is_default AS is_default "
                "FROM items i JOIN states s ON s.id = i.state_id WHERE i.id = ?",
                (item["id"],),
            ).fetchone()
            locked = cur_state is not None and (
                cur_state["grp"] == "backlog"
                or states_repo.is_closed_group(cur_state["grp"])
                or not cur_state["is_default"]
            )
            # BETON-387: de guard hierboven kijkt alleen naar de HUIDIGE state.
            # Het DOEL stond open: een vers item in zijn default-state kon op puur
            # LLM-output naar een gesloten state (done/cancelled). De omschrijving
            # is door mensen én agents geschreven, dus dat is precies de knop die
            # prompt-injectie zoekt. Triage die een net aangemaakt item meteen
            # afsluit is nooit legitiem — deze conditie kan dus geen echt ticket
            # tegenhouden. Spiegelt de bron-kant van BETON-32.
            if st is not None and not locked and not states_repo.is_closed_group(st["grp"]):
                fields["state_id"] = st["id"]
                changed["state"] = result.state
        if fields:
            items_repo.update(conn, item["id"], fields)
        if changed:
            webhooks.record_and_fanout(
                conn,
                type="item.updated",
                item_id=item["id"],
                actor_id=actor_id,
                payload=changed,
            )

        # Relaties.
        if result.duplicate_of:
            _add_relation(conn, item, "duplicate_of", result.duplicate_of, actor_id)
        for ref in result.related_to:
            _add_relation(conn, item, "relates_to", ref, actor_id)

        # Triage-comment (BETON-189): alleen plaatsen als er iets inhoudelijks
        # is — een niet-lege comment, of een decompose-suggestie die op
        # zichzelf al een waardevolle hint is. Bij een duidelijke omschrijving
        # zonder decompose-hint blijft triage stil (geen comment-row); de
        # assignee-toelichting hangt aan de comment-body en verdwijnt dan mee.
        has_decompose_hint = (
            result.decompose_suggestion and item["decomposed_at"] is None
        )
        # BETON-487: staat er al een vraag open (bv. de maker vroeg een mens iets
        # vóór de eerste triage-ronde), dan zwijgt triage. Labels, werklast en
        # state zijn hierboven al gezet; een triage-vraag ernaast herhaalde de
        # openstaande vraag alleen (BETON-481). Spiegelt BETON-442.
        has_open_question = bool(comments_repo.open_questions_for_item(conn, item["id"]))
        if not has_open_question and (
            result.comment.strip() or has_decompose_hint or umbrella_skip
        ):
            body = result.comment
            # BETON-87: alleen claimen dat er toegewezen is als triage de
            # assignee daadwerkelijk gezet heeft (niet louter het LLM-voorstel);
            # verwijs naar de werkelijke assignee, niet naar het LLM-voorstel.
            # BETON-89: geen letterlijke @handle in de comment-body (voorkomt
            # mention-spam/webhook-fanout op de triage-comment zelf).
            if "assignee" in changed and result.assignee_reason:
                body += outbound('apply_triage.1', p0=(changed['assignee']), p1=(result.assignee_reason))
            # BETON-213: laat een spoor achter waarom een agent-umbrella níet naar
            # de coding-queue ging (maakt inzichtelijk waarom het niet op het
            # coding-bord staat). Geen @mention → geen fanout-spam.
            if umbrella_skip:
                sep = "\n\n" if body.strip() else ""
                body += outbound('apply_triage.2', p0=(sep), p1=(umbrella_skip))
            # Conservatieve decompose-suggestie (BETON-37): alleen een hint in de
            # comment, geen automatisch opknippen. Niet voor reeds-opgeknipte items.
            if has_decompose_hint:
                reason = (
                    result.decompose_reason or outbound('apply_triage.3')
                )
                hint = (
                    outbound('apply_triage.4', p0=(reason))
                )
                body = f"{body}\n\n{hint}" if body.strip() else hint
            # BETON-268: wijst triage aan een MENS toe, dan is dit een blokkerende
            # beslissing/vraag — plaats de comment als vraagmodule-vraag
            # (kind='question', BETON-219) zodat de mens hem met één klik kan
            # beantwoorden en hij in `get_open_questions` verschijnt, i.p.v. een
            # platte comment die wegzakt. Opties (bij een discrete keuze) komen uit
            # het LLM-veld. Niet-menselijke assignees blijven een gewone comment.
            assignee_user = (
                users_repo.get_by_handle(conn, effective_handle)
                if effective_handle
                else None
            )
            is_human_question = (
                assignee_user is not None and assignee_user["kind"] == "human"
            )
            row = comments_repo.create(
                conn,
                item_id=item["id"],
                author_id=actor_id,
                body_md=body,
                kind="question" if is_human_question else "comment",
                question_options=result.question_options if is_human_question else None,
            )
            if is_human_question:
                # BETON-431: de vraag aan een mens → het item staat bij die mens.
                question_assign.assign_for_question(
                    conn,
                    item_id=item["id"],
                    question_id=row["id"],
                    body_md=body,
                    actor_id=actor_id,
                    addressed_to=[effective_handle] if effective_handle else [],
                )
            # BETON-282: gericht uitfanoutten. Dit is de tweede helft van "waarom
            # reageerde ze twee keer?": bij een verse toewijzing kreeg de assignee
            # hierboven al de `item.updated`-fanout (→ `pick_up`); deze comment is
            # de toelichting dáárop en gaf blind een tweede sein (→ `respond`).
            # Eén aanleiding hoort één notificatie te geven.
            #
            # Uitzondering: is de comment een vraagmodule-vraag aan een mens
            # (BETON-268), dan is hij wél aan die mens geadresseerd en moet hij
            # hem bereiken — anders zakt een blokkerende vraag stil weg. Alleen
            # dán de assignee expliciet als aangesprokene meegeven.
            webhooks.record_and_fanout(
                conn,
                type="comment.created",
                item_id=item["id"],
                actor_id=actor_id,
                payload={"comment_id": row["id"]},
                mentions=(
                    [effective_handle] if is_human_question and effective_handle else []
                ),
                directed=True,
            )

        # Marker: getriaged.
        events_repo._touch(conn, "items", "triaged_at", item["id"])


def stale_options() -> list[str]:
    """Presentatielabels; de bestaande indexsemantiek blijft onveranderd."""
    return [outbound("options.stale." + str(index)) for index in range(3)]


def guardrail_options() -> list[str]:
    """Presentatielabels; de bestaande indexsemantiek blijft onveranderd."""
    return [outbound("options.guardrail." + str(index)) for index in range(3)]
