"""Triage-worker: orkestreert de triage van één item + de achtergrond-loop.

De loop draait in de lifespan (net als de webhook-dispatcher) en pollt op
niet-getriagede items die lang genoeg met rust zijn gelaten (debounce), embed +
zoekt gelijkende items, laat de LLM classificeren en past het resultaat toe als
user `triage`. Bestaande items zijn in migratie 008 al gemarkeerd, dus alleen
níeuwe items worden verwerkt.
"""

from __future__ import annotations

from .config import env

import asyncio
import logging
import sqlite3

from . import db as db_module
from . import embeddings as embeddings_mod
from . import llm as llm_mod
from . import mentions
from . import ratelimit
from . import storage
from . import triage as triage_mod
from .repo import attachments as attachments_repo
from .repo import comments as comments_repo
from .repo import events as events_repo
from .repo import items as items_repo
from .repo import labels as labels_repo
from .repo import states as states_repo
from .repo import users as users_repo

logger = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_SECONDS = 120
DEFAULT_INTERVAL_SECONDS = 30
DEFAULT_BATCH = 5
DEFAULT_TOP_K = 8
# BETON-375: na hoeveel dagen zonder activiteit een lopend item "stil" heet.
# 0 (of negatief) zet de detectie uit.
DEFAULT_STALE_DAYS = 3
# BETON-130: max aantal afbeeldingen dat per item meegaat naar de LLM (OpenAI-
# praktijkrichtlijn; meer = trager/duurder zonder meerwaarde). GESORTEERD op
# created_at (oudste eerst — meestal de context die het item opende).
MAX_VISION_IMAGES = 4

# Na dit aantal mislukte LLM-pogingen wordt een item/comment in quarantaine gezet:
# de finders slaan het over zodat één poison-item de loop niet eeuwig bezighoudt
# (BETON-41, gemodelleerd naar webhooks.MAX_ATTEMPTS). Gedefinieerd in de
# repo-laag, want `items_repo.triage_assign_pending` past dezelfde grens toe.
MAX_ATTEMPTS = items_repo.TRIAGE_MAX_ATTEMPTS


# --- Gedeelde eligibility-guard (BETON-325) ---------------------------------
#
# De poll-queries hieronder joinen allemaal `items i ... JOIN projects p`
# en herhaalden verbatim dezelfde drie-conditie-guard: niet gearchiveerd, niet
# gelockt (BETON-302), project doet triage. Eén bron voorkomt dat een latere
# eligibility-wijziging (zoals BETON-302 destijds) in één finder wordt vergeten.
# Geen van de drie condities heeft een bind-parameter, dus de fragmenten kunnen
# vrij in elke query gecomposed worden zonder de bestaande `?`-parametervolgorde
# van die query te verstoren.


def _eligibility_where(alias: str = "i") -> str:
    """SQL-fragment: item niet gearchiveerd/gelockt, project levend en doet triage.
    `alias` is de tabel-alias van `items` in de query (overal `i`).

    BETON-413: een gearchiveerd project valt af. Archiveren raakt
    `triage_enabled` bewust niet (dat zou onomkeerbaar zijn — restore kent de
    oude waarde niet meer), dus zonder deze poort bleven de zes finders draaien
    op een project dat weg is. Dat gebeurde ook: TOR staat sinds 2026-09-02
    gearchiveerd mét `triage_enabled = 1` en kreeg daarna nog zes
    triage-comments plus vragen die een mens beantwoordde. Een vraagmodule-vraag
    passeert het telegram-kanaal (BETON-313), dus dit reikte tot zijn telefoon."""
    return (
        f"{alias}.archived_at IS NULL AND {alias}.locked_at IS NULL "
        f"AND {items_repo.LIVE_PROJECT} AND p.triage_enabled = 1"
    )


def _debounce_clause(column: str) -> str:
    """SQL-fragment voor de debounce-poort op `column` (bv. `i.updated_at`).
    Hoort bij precies één `?`-placeholder: de `-N seconds`-string."""
    return f"{column} < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)"


def find_untriaged(
    conn: sqlite3.Connection,
    *,
    debounce_seconds: int,
    limit: int,
    max_attempts: int = MAX_ATTEMPTS,
) -> list[int]:
    """Id's van niet-gearchiveerde items zonder triaged_at die minstens
    `debounce_seconds` niet zijn bewerkt (zodat lopende edits met rust blijven).
    Items in quarantaine (triage_attempts >= max_attempts) worden overgeslagen.

    Gelockte items vallen af (BETON-302): een noodstop legt álle agents stil, en
    triage is er daar één van. De poort zit hier in de finder en niet pas bij het
    posten van de comment, zodat er ook geen LLM-call op gedaan wordt.

    Afgesloten items (state-groep `completed`/`cancelled`) vallen af (BETON-455):
    een eerste ronde op een dicht ticket zette alsnog labels, toewijzing en een
    opknip-vraag in de inbox van de menselijke ontvanger. `triaged_at` wordt bewust niet
    gezet; een heropend item komt dus gewoon alsnog langs. Zelfde groepnamen als
    `find_stale`; items zonder state blijven meedoen."""
    rows = conn.execute(
        f"""SELECT i.id FROM items i
           JOIN projects p ON p.id = i.project_id
           LEFT JOIN states s ON s.id = i.state_id
           WHERE i.triaged_at IS NULL AND {_eligibility_where()}
             AND {states_repo.state_open_sql('s')}
             AND i.triage_attempts < ?
             AND {_debounce_clause('i.updated_at')}
           ORDER BY i.id LIMIT ?""",
        (int(max_attempts), f"-{int(debounce_seconds)} seconds", limit),
    ).fetchall()
    return [r["id"] for r in rows]


def find_unevaluated_comments(
    conn: sqlite3.Connection,
    *,
    triage_user_id: int,
    debounce_seconds: int,
    limit: int,
    max_attempts: int = MAX_ATTEMPTS,
) -> list[int]:
    """Id's van nog-niet-beoordeelde comments (niet van triage zelf) op niet-
    gearchiveerde items, die minstens `debounce_seconds` met rust zijn gelaten.
    Comments in quarantaine (eval_attempts >= max_attempts) worden overgeslagen.

    BETON-260: alleen echte comments (``kind='comment'``) worden beoordeeld —
    vraag-comments (``kind='question'``) en historische antwoord-comments (die als
    ``answer_comment_id`` aan een vraag hangen) worden overgeslagen, zodat triage
    niet meepraat op de vraagmodule.

    BETON-302: comments op een gelockt item worden niet beoordeeld — dit is de
    route waarlangs triage aan een comment-lus meedoet, en precies die moet de
    noodstop afknijpen.

    BETON-487: na de eerste triage reageert triage alleen nog als iemand hem
    aanspreekt. Alleen comments met `@triage` erin komen langs; de rest blijft
    ongemarkeerd en kost dus ook geen plek in het rondebudget van `_run_batch`.
    `LIKE` is in SQLite hoofdletterongevoelig voor ASCII; `evaluate_comment_once`
    toetst de mention daarna exact."""
    rows = conn.execute(
        f"""SELECT c.id FROM comments c
           JOIN items i ON i.id = c.item_id
           JOIN projects p ON p.id = i.project_id
           WHERE c.evaluated_at IS NULL
             AND {_eligibility_where()}
             AND c.kind = 'comment'
             AND c.body_md LIKE '%@triage%'
             AND c.id NOT IN (
                 SELECT answer_comment_id FROM comments
                 WHERE answer_comment_id IS NOT NULL
             )
             AND c.eval_attempts < ?
             AND (c.author_id IS NULL OR c.author_id != ?)
             AND {_debounce_clause('c.created_at')}
           ORDER BY c.id LIMIT ?""",
        (int(max_attempts), triage_user_id, f"-{int(debounce_seconds)} seconds", limit),
    ).fetchall()
    return [r["id"] for r in rows]


def find_answered_questions(
    conn: sqlite3.Connection,
    *,
    triage_user_id: int,
    debounce_seconds: int,
    limit: int,
    max_attempts: int = MAX_ATTEMPTS,
) -> list[int]:
    """Id's van triage-vragen die inmiddels beantwoord zijn en nog verwerkt moeten
    worden (BETON-389).

    Vierde poll-query, en de tegenhanger van de vraagmodule-vraag die triage nu
    zelf stelt: het antwoord staat sinds BETON-265 INLINE op de vraag, dus er is
    geen antwoord-comment die `find_unevaluated_comments` kan oppikken (die filtert
    bovendien op `kind='comment'`), en `question.answered` wekt geen enkele finder.
    Zonder deze query loopt een gestelde vraag dood.

    Marker zonder migratie: `_post_triage_comment` zet `evaluated_at` bij het
    plaatsen van de vraag, dus "nog te verwerken" = `answered_at` ligt daarná.
    Afhandelen schuift `evaluated_at` er weer overheen → één ronde per antwoord.

    Poorten: alleen vragen van triage zelf, niet gearchiveerd, niet op slot
    (BETON-302 — een noodstop legt ook deze route stil), project doet triage,
    niet in quarantaine, en het antwoord is lang genoeg met rust gelaten
    (debounce, zodat een nog te bewerken antwoord — BETON-263 — met rust blijft).

    BETON-487: alleen een antwoord dat triage aanspreekt (`@triage` in de
    antwoordtekst) komt nog langs. Een gewoon antwoord gaat via de teruggave
    (BETON-431) naar wie het ticket had; triage maakte er een nieuwe vraag of
    ongevraagd advies van (BETON-481/482)."""
    rows = conn.execute(
        f"""SELECT c.id FROM comments c
           JOIN items i ON i.id = c.item_id
           JOIN projects p ON p.id = i.project_id
           WHERE c.kind = 'question'
             AND c.author_id = ?
             AND c.answered_at IS NOT NULL
             AND c.answer_text LIKE '%@triage%'
             AND (c.evaluated_at IS NULL OR c.answered_at > c.evaluated_at)
             AND {_eligibility_where()}
             AND c.eval_attempts < ?
             AND {_debounce_clause('c.answered_at')}
           ORDER BY c.id LIMIT ?""",
        (triage_user_id, int(max_attempts), f"-{int(debounce_seconds)} seconds", limit),
    ).fetchall()
    return [r["id"] for r in rows]


def evaluate_answer_once(
    conn: sqlite3.Connection, question_id: int, llm, *, triage_user_id: int
) -> None:
    """Verwerk het antwoord op één triage-vraag (BETON-389).

    Hergebruikt de comment-evaluatie: het antwoord gaat als "nieuwe reactie" de
    bestaande prompt in, dus dezelfde vier uitkomsten (assign_claude/clarify/
    answer/noop) gelden. Gericht aan wie antwoordde (BETON-282)."""
    question = comments_repo.get(conn, question_id)
    if question is None or question["kind"] != "question":
        return
    if question["author_id"] != triage_user_id or question["answered_at"] is None:
        return
    if (
        question["evaluated_at"] is not None
        and question["answered_at"] <= question["evaluated_at"]
    ):
        return  # al verwerkt
    item = items_repo.get(conn, question["item_id"])
    if item is None:
        return
    # BETON-487: de exacte toets naast de LIKE in de finder. Marker vooruit, zoals
    # `apply_answer_eval` hem zet (`_touch` schrijft alleen als hij NULL is).
    if not _mentions_triage(conn, triage_user_id, question["answer_text"]):
        with db_module.transaction(conn):
            conn.execute(
                f"UPDATE comments SET evaluated_at = {events_repo.NOW_SQL} WHERE id = ?",
                (question_id,),
            )
        return
    # BETON-478: antwoord + toewijzing aan triage is één menselijke actie. Staat
    # de toewijzing nog open, dan neemt de assign-eval het antwoord als context
    # mee en markeert hij de vraag; hier wachten we, zonder marker te zetten.
    if items_repo.triage_assign_pending(conn, item):
        return
    data = _item_context(conn, item)
    context = _project_context(conn, item["project_id"])
    thread = [
        comments_repo.serialize(conn, c)
        for c in comments_repo.list_for_item(conn, item["id"])
    ]
    answered = triage_mod.format_answered_question(
        comments_repo.serialize(conn, question)
    )
    messages = triage_mod.build_comment_eval_messages(
        data, context, thread, answered, images=gather_images(conn, item)
    )
    result = triage_mod.parse_comment_eval(llm.complete(messages))
    triage_mod.apply_answer_eval(
        conn,
        item,
        question_id,
        result,
        triage_user_id,
        addressed_to=[answered["author"]] if answered["author"] else [],
    )
    logger.info(
        "Antwoord op vraag %s (%s) verwerkt → %s", question_id, data["ref"], result.action
    )


# --- Stale-detectie (BETON-375) ---------------------------------------------
#
# `last_activity_at` is een AFGELEIDE waarde (BETON-68): geen kolom, maar het
# maximum van `items.updated_at` en de laatste comment-mutatie. De finder moet
# hem dus zelf uitrekenen — vandaar dit fragment i.p.v. `i.last_activity_at`.

_LAST_ACTIVITY_SQL = (
    "MAX(i.updated_at, COALESCE("
    "(SELECT MAX(c2.updated_at) FROM comments c2 WHERE c2.item_id = i.id), "
    "i.updated_at))"
)


def find_stale(
    conn: sqlite3.Connection,
    *,
    triage_user_id: int,
    days: int,
    limit: int,
    max_attempts: int = MAX_ATTEMPTS,
) -> list[int]:
    """Id's van items die in een lopende status staan maar al `days` dagen stil
    zijn, en waarover nog niet gevraagd is (BETON-375).

    `days <= 0` zet de detectie UIT en geeft altijd een lege lijst terug — dat is
    een expliciete short-circuit, want `'-0 days'` zou de grens op *nu* leggen en
    daarmee élk lopend item als stil aanmerken.

    Idempotentie: `stale_asked_at` is gezet ná het plaatsen van de vraag, dus
    direct erna is `last_activity <= stale_asked_at` en komt het item niet terug.
    Opnieuw vragen mag pas als er echte activiteit ná de vraag was (strikt `>`)
    én het daarna weer `days` stil is. De `NOT EXISTS` sluit bovendien uit dat er
    een tweede vraag komt terwijl de eerste nog open staat.

    Poorten: dezelfde `_eligibility_where` als de andere finders (niet
    gearchiveerd, niet op slot, project doet triage) plus quarantaine."""
    if days <= 0:
        return []
    rows = conn.execute(
        f"""SELECT i.id FROM items i
           JOIN projects p ON p.id = i.project_id
           JOIN states s ON s.id = i.state_id
           WHERE s.grp = 'started'
             AND {_eligibility_where()}
             AND i.triage_attempts < ?
             AND {_LAST_ACTIVITY_SQL}
                 < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)
             AND (i.stale_asked_at IS NULL
                  OR {_LAST_ACTIVITY_SQL} > i.stale_asked_at)
             AND NOT EXISTS (
                 SELECT 1 FROM comments c3
                 WHERE c3.item_id = i.id
                   AND {comments_repo.question_open_sql('c3')}
                   AND c3.author_id = ?
                   AND c3.body_md LIKE ?
             )
           ORDER BY i.id LIMIT ?""",
        (
            int(max_attempts),
            f"-{int(days)} days",
            triage_user_id,
            f"{triage_mod.STALE_QUESTION_MARKER}%",
            limit,
        ),
    ).fetchall()
    return [r["id"] for r in rows]


def _stale_addressee(conn: sqlite3.Connection, item: sqlite3.Row) -> tuple[str, bool]:
    """Wie krijgt de stale-vraag, en moet die met een @mention aangesproken worden?

    De assignee, tenzij die er niet is of virtueel is: de `coding-agent`- en
    `hermes-agent`-rijen authenticeren nooit (migratie 027), dus een vraag die
    alleen dáár terechtkomt bereikt niemand — precies het doodlopende pad dat
    BETON-389 net dichtte. Dan valt hij terug op de eerste actieve mens, en die
    is géén assignee: `GET /questions?open=true` richt op assignee/maker/mention,
    dus alleen een letterlijke mention laat de vraag bij hem aankomen.
    Geeft `(handle, mention_nodig)`; `("", False)` als er niemand is."""
    if item["assignee_id"] is not None:
        assignee = users_repo.get(conn, item["assignee_id"])
        if assignee is not None and not users_repo._row_is_virtual(assignee):
            return assignee["handle"], False
    human = users_repo.first_human(conn)
    return (human["handle"], True) if human is not None else ("", False)


def ask_stale_once(
    conn: sqlite3.Connection, item_id: int, *, triage_user_id: int, days: int
) -> None:
    """Stel de stale-vraag op één item en zet de marker (BETON-375).

    Géén LLM: de vraag is elke ronde dezelfde en de drie antwoorden zijn een vaste,
    discrete keuze. Vraag + marker in één transactie, en de marker NA de vraag —
    de vraag is zelf een comment en telt dus mee in `last_activity_at`; andersom
    zou de her-vraag-conditie meteen weer waar zijn."""
    item = items_repo.get(conn, item_id)
    if item is None:
        return
    handle, needs_mention = _stale_addressee(conn, item)
    if not handle:
        logger.warning("Geen ontvanger voor stale-vraag op item %s", item_id)
        return
    body = triage_mod.format_stale_question(days, mention=handle if needs_mention else None)
    with db_module.transaction(conn):
        triage_mod.post_triage_comment(
            conn,
            item,
            body,
            triage_user_id,
            addressed_to=[handle],
            kind="question",
            options=triage_mod.stale_options(),
        )
        conn.execute(
            "UPDATE items SET stale_asked_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE id = ?",
            (item_id,),
        )
    logger.info("Stale-vraag gesteld op item %s (aan %s)", item_id, handle)


# --- Guardrail-review (BETON-420) ------------------------------------------
#
# Zesde poll-query, gespiegeld op het stale-paar hierboven. Trigger is de
# VERSTREKEN reviewdatum, niet stilte — `_LAST_ACTIVITY_SQL` speelt hier dus
# geen rol. Géén LLM-call (vraag en opties liggen vast), dus deze finder telt
# niet mee tegen `DailyBudget` en valt buiten het rondebudget.


def find_guardrails_due_review(
    conn: sqlite3.Connection,
    *,
    triage_user_id: int,
    limit: int,
    max_attempts: int = MAX_ATTEMPTS,
) -> list[int]:
    """Id's van items met een actieve guardrail waarvan de reviewdatum verstreken
    is en waarover nog niet gevraagd is (BETON-420).

    Géén `s.grp`-filter (anders dan `find_stale`): een guardrail geldt in elke
    state, ook op een afgerond ticket dat de kennis nog draagt.

    Idempotentie hangt volledig aan `guardrail_review_asked_at`: die wordt NA het
    plaatsen van de vraag gezet en gaat weer op NULL zodra er een nieuwe
    reviewdatum staat (`set_guardrail`, en optie 0 van het review-antwoord). De
    marker NOOIT met `guardrail_review_by` vergelijken — dat is een datum en de
    marker een timestamp; als string zou een same-day-verlenging dan stil nooit
    meer een vraag opleveren. De `NOT EXISTS` houdt daarnaast een tweede vraag
    tegen zolang de eerste openstaat.

    BETON-422: een ticket met een openstaand OPHEFFINGS-concept valt er ook uit —
    daar ligt de vraag "geldt hij nog?" al bij de mens."""
    rows = conn.execute(
        f"""SELECT i.id FROM items i
           JOIN projects p ON p.id = i.project_id
           WHERE {_eligibility_where()}
             AND {items_repo.guardrail_active_sql("i")}
             AND i.guardrail_review_by IS NOT NULL
             AND i.guardrail_review_by <= date('now')
             AND i.guardrail_review_asked_at IS NULL
             AND i.triage_attempts < ?
             -- BETON-422: ligt er al een openstaand voorstel om deze guardrail
             -- OP TE HEFFEN, dan ligt "geldt hij nog?" al bij de mens. Een
             -- reviewvraag ernaast zou dezelfde beslissing twee keer stellen,
             -- op twee plekken, met twee verschillende gevolgen. Een `set`-
             -- concept sluit de reviewvraag níet uit: dat is een voorstel voor
             -- andere tekst, geen antwoord op of hij nog moet gelden.
             AND NOT EXISTS (
                 SELECT 1 FROM item_guardrail_proposals gp
                 WHERE gp.item_id = i.id AND gp.kind = 'lift'
             )
             AND NOT EXISTS (
                 SELECT 1 FROM comments c3
                 WHERE c3.item_id = i.id
                   AND {comments_repo.question_open_sql('c3')}
                   AND c3.author_id = ?
                   AND c3.body_md LIKE ?
             )
           ORDER BY i.id LIMIT ?""",
        (
            int(max_attempts),
            triage_user_id,
            f"{triage_mod.GUARDRAIL_REVIEW_MARKER}%",
            limit,
        ),
    ).fetchall()
    return [r["id"] for r in rows]


def ask_guardrail_review_once(
    conn: sqlite3.Connection, item_id: int, *, triage_user_id: int
) -> None:
    """Stel de reviewvraag op één item en zet de marker (BETON-420).

    Ontvanger is ALTIJD de eerste actieve mens, mét een letterlijke `@handle` in
    de body: of een guardrail nog geldt is een menselijk oordeel, en de assignee
    kan een agent zijn (of de virtuele `coding-agent`-rij, die nooit
    authenticeert). Zonder de mention bereikt de vraag hem niet via
    `GET /questions?open=true`.

    Vraag + marker in één transactie, en de marker NÁ de vraag — dezelfde
    valkuil die `039_item_stale.sql` documenteert."""
    item = items_repo.get(conn, item_id)
    if item is None:
        return
    human = users_repo.first_human(conn)
    if human is None:
        logger.warning("Geen mens voor de guardrail-review op item %s", item_id)
        return
    body = triage_mod.format_guardrail_review_question(
        item["guardrail_md"] or "", item["guardrail_review_by"] or "", mention=human["handle"]
    )
    with db_module.transaction(conn):
        triage_mod.post_triage_comment(
            conn,
            item,
            body,
            triage_user_id,
            addressed_to=[human["handle"]],
            kind="question",
            options=triage_mod.guardrail_options(),
        )
        conn.execute(
            "UPDATE items SET guardrail_review_asked_at = "
            "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (item_id,),
        )
    logger.info(
        "Guardrail-review gevraagd op item %s (aan %s)", item_id, human["handle"]
    )


# --- Toewijzing aan triage als trigger (BETON-287) --------------------------
#
# `find_untriaged` pakt alleen items met `triaged_at IS NULL`; zodra dat gezet is,
# is het item daar permanent uit en triggerde een látere toewijzing aan triage
# niets. Die vlag mag ook niet hergebruikt worden (dat sloopt de eerste-triage-
# flow). Vandaar een derde poll-query met een eigen marker die aan DE TOEWIJZING
# hangt: `items.triage_assign_event_id` = het laatste afgehandelde assignment-event.
#
# Idempotentie: reageren = er bestaat een assignment-event dat NIEUWER is dan de
# marker. Een herhaalde ronde vindt niets (marker == laatste event), een NIEUWE
# toewijzing (weg → terug naar triage) wél (nieuw event > marker). Triage's eigen
# acties tellen niet mee als trigger (actor-guard), dus zijn reactie kan zichzelf
# niet opnieuw aanzetten.
#
# NB: mentions hebben dit niet nodig — `find_unevaluated_comments` pakt juist
# alleen comments op die `@triage` noemen (BETON-487).


def latest_assign_event(
    conn: sqlite3.Connection, item_id: int, triage_user_id: int
) -> sqlite3.Row | None:
    """Het jongste event dat dit item aan triage toewees (of None).

    Alleen `item.updated` met een echte `{from,to}`-diff telt: `json_extract` op
    `$.assignee.to` geeft NULL voor de platte `{"assignee": "handle"}`-payload die
    triage zelf schrijft (`apply_comment_eval`), dus die kan hier nooit als trigger
    binnenkomen. De actor-guard sluit triage's eigen toewijzingen expliciet uit."""
    return conn.execute(
        """SELECT e.id, e.actor_id FROM events e
           WHERE e.item_id = ?
             AND e.type = 'item.updated'
             AND json_extract(e.payload, '$.assignee.to') = (
                 SELECT handle FROM users WHERE id = ?
             )
             AND (e.actor_id IS NULL OR e.actor_id != ?)
           ORDER BY e.id DESC LIMIT 1""",
        (item_id, triage_user_id, triage_user_id),
    ).fetchone()


def find_assigned_to_triage(
    conn: sqlite3.Connection,
    *,
    triage_user_id: int,
    debounce_seconds: int,
    limit: int,
    max_attempts: int = MAX_ATTEMPTS,
) -> list[int]:
    """Id's van items die aan triage zijn toegewezen en waarvan die toewijzing nog
    niet is afgehandeld (BETON-287).

    Poorten, in volgorde van de WHERE: nog echt aan triage toegewezen; niet
    gearchiveerd; niet op slot (BETON-302 — een noodstop legt ook triage stil);
    project doet triage; al een keer getriaged (is dat niet zo, dan
    is `find_untriaged` de juiste route — die reageert al op het item, we willen
    er geen twee reacties op); NIET op een afgesloten state-groep (BETON-409: een ticket
    dat al `done`/`cancelled` is loopt niet meer — triage's "leg dit bij mij
    neer"-reactie (opnieuw vragen, heropenen als coding-werk) hoort alleen bij
    tickets die nog lopen, een toewijzing hier is typisch een mens die het
    antwoord al in een comment gaf en triage's eigen vraag daarmee afsluit; dat
    schrijft immers zelf weer een `assignee.to = 'triage'`-event); niet in
    quarantaine; en er is een assignment-event nieuwer dan de marker dat lang
    genoeg met rust is gelaten (debounce)."""
    rows = conn.execute(
        f"""SELECT i.id FROM items i
           JOIN projects p ON p.id = i.project_id
           LEFT JOIN states s ON s.id = i.state_id
           WHERE i.assignee_id = ?
             AND {_eligibility_where()}
             AND {states_repo.state_open_sql('s')}
             AND i.triaged_at IS NOT NULL
             AND i.triage_attempts < ?
             AND EXISTS (
                 SELECT 1 FROM events e
                 WHERE e.item_id = i.id
                   AND e.type = 'item.updated'
                   AND json_extract(e.payload, '$.assignee.to') = (
                       SELECT handle FROM users WHERE id = ?
                   )
                   AND (e.actor_id IS NULL OR e.actor_id != ?)
                   AND (i.triage_assign_event_id IS NULL
                        OR e.id > i.triage_assign_event_id)
                   AND {_debounce_clause('e.created_at')}
             )
           ORDER BY i.id LIMIT ?""",
        (
            triage_user_id,
            int(max_attempts),
            triage_user_id,
            triage_user_id,
            f"-{int(debounce_seconds)} seconds",
            limit,
        ),
    ).fetchall()
    return [r["id"] for r in rows]


def respond_to_assignment_once(
    conn: sqlite3.Connection, item_id: int, llm, *, triage_user_id: int
) -> None:
    """Reageer op één toewijzing aan triage: item + thread → LLM → toepassen.

    De marker wordt door `apply_assign_eval` gezet (samen met de reactie, in één
    transactie) — ook bij een noop, zodat dit item niet elke ronde terugkomt."""
    item = items_repo.get(conn, item_id)
    if item is None or item["assignee_id"] != triage_user_id:
        return
    event = latest_assign_event(conn, item_id, triage_user_id)
    if event is None or (
        item["triage_assign_event_id"] is not None
        and event["id"] <= item["triage_assign_event_id"]
    ):
        return  # niets nieuws sinds de laatste afhandeling
    data = _item_context(conn, item)
    context = _project_context(conn, item["project_id"])
    thread = [
        comments_repo.serialize(conn, c)
        for c in comments_repo.list_for_item(conn, item["id"])
    ]
    assigner = users_repo.get(conn, event["actor_id"]) if event["actor_id"] else None
    assigned_by = assigner["handle"] if assigner is not None else None
    # BETON-478: onverwerkte antwoorden op triage-vragen horen bij dezelfde
    # menselijke actie; ze gaan als context mee en worden hier afgehandeld, zodat
    # de answer-eval er geen tweede reactie op geeft.
    pending_answers = [
        r
        for r in conn.execute(
            """SELECT id FROM comments
               WHERE item_id = ? AND kind = 'question' AND author_id = ?
                 AND answered_at IS NOT NULL
                 AND (evaluated_at IS NULL OR answered_at > evaluated_at)""",
            (item_id, triage_user_id),
        ).fetchall()
    ]
    answers = [
        triage_mod.format_answered_question(
            comments_repo.serialize(conn, comments_repo.get_required(conn, r["id"]))
        )
        for r in pending_answers
    ]
    messages = triage_mod.build_assign_eval_messages(
        data,
        context,
        thread,
        assigned_by=assigned_by,
        images=gather_images(conn, item),
        answers=answers,
    )
    result = triage_mod.parse_comment_eval(llm.complete(messages))
    # BETON-282: gericht aan wie het item bij triage neerlegde — niet aan de
    # assignee (dat is triage zelf).
    triage_mod.apply_assign_eval(
        conn,
        item,
        result,
        triage_user_id,
        assign_event_id=event["id"],
        addressed_to=[assigned_by] if assigned_by else [],
        answered_question_ids=[r["id"] for r in pending_answers],
    )
    logger.info("Reactie op toewijzing %s → %s", data["ref"], result.action)


def evaluate_comment_once(
    conn: sqlite3.Connection, comment_id: int, llm, *, triage_user_id: int
) -> None:
    """Beoordeel één comment: item + thread → LLM → toepassen (reassign/vraag)."""
    comment = comments_repo.get(conn, comment_id)
    if comment is None or comment["evaluated_at"] is not None:
        return
    if comment["author_id"] == triage_user_id:  # eigen comment → nooit beoordelen
        return
    item = items_repo.get(conn, comment["item_id"])
    if item is None:
        return
    # BETON-487: alleen een comment die triage aanspreekt. De finder filtert al
    # met LIKE; dit is de exacte toets (geen `@triage-bot` o.i.d.).
    if not _mentions_triage(conn, triage_user_id, comment["body_md"]):
        with db_module.transaction(conn):
            events_repo._touch(conn, "comments", "evaluated_at", comment_id)
        return
    # BETON-442: staat er al een vraag open, dan ligt het ticket bij een mens en
    # heeft triage niets toe te voegen — een "clarify" herhaalde die vraag
    # alleen. Wel markeren, anders komt deze comment ná het antwoord alsnog langs.
    if comments_repo.open_questions_for_item(conn, item["id"]):
        with db_module.transaction(conn):
            events_repo._touch(conn, "comments", "evaluated_at", comment_id)
        logger.info("Comment %s overgeslagen: open vraag op het item", comment_id)
        return
    context = _project_context(conn, item["project_id"])
    data = _item_context(conn, item)
    thread = [
        comments_repo.serialize(conn, c)
        for c in comments_repo.list_for_item(conn, item["id"])
    ]
    new_comment = comments_repo.serialize(conn, comment)

    # BETON-163: is dit een menselijk antwoord op openstaande verrijkingsvragen
    # van triage? Dan opnieuw verrijken i.p.v. de normale comment-evaluatie —
    # zolang er onvoldoende info is stelt de bot vervolgvragen, anders plaatst
    # hij het voorstel (nooit auto-opgeslagen). Kort-sluiten: geen dubbele comment.
    if _is_human(conn, comment) and triage_mod.has_outstanding_enrich_questions(thread):
        messages = llm_mod.build_enrich_messages(
            data["title"], data["description_md"], thread
        )
        enrich_result = llm_mod.parse_enrich(llm.complete(messages))
        triage_mod.apply_re_enrich(conn, item, comment_id, enrich_result, triage_user_id)
        logger.info("Re-enrich %s → %s", data["ref"], enrich_result.kind)
        return

    messages = triage_mod.build_comment_eval_messages(
        data, context, thread, new_comment, images=gather_images(conn, item)
    )
    result = triage_mod.parse_comment_eval(llm.complete(messages))
    triage_mod.apply_comment_eval(conn, item, comment_id, result, triage_user_id)
    logger.info(
        "Beoordeeld comment %s op %s → %s", comment_id, data["ref"], result.action
    )


def _mentions_triage(
    conn: sqlite3.Connection, triage_user_id: int, text: str | None
) -> bool:
    """Spreekt `text` de triage-user aan met een `@handle`? (BETON-487)"""
    triage_user = users_repo.get(conn, triage_user_id)
    if triage_user is None:
        return False
    handle = triage_user["handle"].lower()
    return any(h.lower() == handle for h in mentions.parse(text))


def _is_human(conn: sqlite3.Connection, comment: sqlite3.Row) -> bool:
    """Is de auteur van deze comment een mens? (BETON-163)

    Re-enrich reageert alleen op een menselijk antwoord op verrijkingsvragen —
    niet op agent-reacties (die zouden een lus kunnen voeden)."""
    if comment["author_id"] is None:
        return False
    author = users_repo.get(conn, comment["author_id"])
    return author is not None and author["kind"] == "human"


def _project_context(conn: sqlite3.Connection, project_id: int) -> dict:
    project = conn.execute(
        "SELECT key, name FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    return {
        "project_name": project["name"] if project else "?",
        "states": states_repo.list_for_project(conn, project_id),
        "labels": [
            lbl["name"] for lbl in labels_repo.list_for_project(conn, project_id)
        ],
        "users": [
            r["handle"]
            for r in conn.execute(
                "SELECT handle FROM users WHERE active = 1"
            ).fetchall()
        ],
        "humans": [
            row["handle"] for row in conn.execute(
                "SELECT handle FROM users WHERE active = 1 AND kind = 'human' ORDER BY id"
            ).fetchall()
        ],
        # BETON-67: agent-roster (handle + expertise) voor expertise-routering.
        # BETON-123: gefilterd op per-project toegang (geen 'none'/'respond'-agents).
        "agents": users_repo.assignable_agents(conn, project_id),
    }


def _candidates(
    conn: sqlite3.Connection, item: sqlite3.Row, embeddings, *, top_k: int
) -> list[dict]:
    """Gelijkende items via embeddings; leeg als embeddings niet beschikbaar zijn.

    Een fout in embeddings.embed (bv. de embed-provider ligt eruit) mag triage niet
    laten crashen — dan blijven de dedup-kandidaten simpelweg leeg (BETON-41)."""
    if embeddings is None:
        return []
    text = f"{item['title']}\n\n{item['description_md'] or ''}"
    try:
        vec = embeddings.embed(text)
        embeddings_mod.upsert(conn, item["id"], getattr(embeddings, "_model", "?"), vec)
        conn.commit()
        similar = embeddings_mod.find_similar(
            conn, item["project_id"], vec, top_k=top_k, exclude_item_id=item["id"]
        )
    except Exception:  # noqa: BLE001 — embeddings-storing → geen kandidaten
        logger.warning(
            "Embeddings mislukten voor item %s; geen dedup-kandidaten", item["id"]
        )
        return []
    out = []
    for other_id, _score in similar:
        row = items_repo.get(conn, other_id)
        if row is not None:
            data = items_repo.serialize(conn, row)
            out.append(
                {
                    "ref": data["ref"],
                    "title": data["title"],
                    "state": data["state"],
                    "priority": data["priority"],
                    "labels": data["labels"],
                    "description_md": data["description_md"],
                }
            )
    return out


def gather_images(
    conn: sqlite3.Connection, item: sqlite3.Row, *, base: str | None = None
) -> list[dict]:
    """Verzamel vision-content-blocks voor de attachments van dit item.

    Gedeelde helper voor triage (BETON-130) en decompose (BETON-139). Leeg
    (geen afbeeldingen) tenzij vision aan staat (llm.vision_enabled()) én het
    item afbeeldings-attachments heeft met een toegestaan mime-type. Bytes
    worden van disk gelezen via storage.read_bytes; een ontbrekend bestand of
    een leesfout slaat die ene afbeelding over (mag de LLM-call niet laten
    crashen). Max MAX_VISION_IMAGES, oudste eerst.

    ``base`` is de attachments-map op disk; default uit
    ``BETONNING_ATTACHMENTS_DIR``. De API geeft ``app.state.attachments_dir``
    door zodat in tests de temp-map wordt gebruikt i.p.v. de env-var."""
    if not llm_mod.vision_enabled():
        return []
    allowed = llm_mod.vision_types()
    base = base or env("BETONNING_ATTACHMENTS_DIR")
    if not base:
        return []
    out: list[dict] = []
    for att in attachments_repo.list_for_item(conn, item["id"]):
        mime = (att.get("content_type") or "").lower()
        if mime not in allowed:
            continue
        data = storage.read_bytes(base, att["sha256"])
        if not data:
            continue
        out.append(llm_mod.build_image_block(data, mime))
        if len(out) >= MAX_VISION_IMAGES:
            break
    return out


def _item_context(conn: sqlite3.Connection, item: sqlite3.Row) -> dict:
    """Interne triagecontext bevat ook het lazy planveld (BETON-506)."""
    data = items_repo.serialize(conn, item)
    data["plan_md"] = item["plan_md"]
    return data


def triage_once(
    conn: sqlite3.Connection,
    item_id: int,
    llm,
    embeddings,
    *,
    triage_user_id: int,
    top_k: int = DEFAULT_TOP_K,
) -> None:
    """Triage één item: context + kandidaten → LLM → toepassen."""
    item = items_repo.get(conn, item_id)
    if item is None or item["triaged_at"] is not None:
        return
    context = _project_context(conn, item["project_id"])
    candidates = _candidates(conn, item, embeddings, top_k=top_k)
    images = gather_images(conn, item)
    data = _item_context(conn, item)
    messages = triage_mod.build_triage_messages(
        {
            "ref": data["ref"],
            "title": data["title"],
            "description_md": data["description_md"],
            "plan_md": data["plan_md"],
        },
        context,
        candidates,
        images=images,
    )
    output = llm.complete(messages)
    result = triage_mod.parse_triage(output)
    triage_mod.apply_triage(conn, item, result, triage_user_id)
    logger.info("Getriaged %s → %s/%s", data["ref"], result.type_label, result.assignee)


async def triage_loop(
    db_path: str,
    stop_event: asyncio.Event,
    llm,
    embeddings,
    *,
    debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    batch: int = DEFAULT_BATCH,
    budget: ratelimit.DailyBudget | None = None,
) -> None:
    """Achtergrond-loop: verwerkt periodiek een batch niet-getriagede items."""
    triage_user_id = _triage_user_id(db_path)
    if triage_user_id is None:
        logger.warning("Geen 'triage'-user; triage-loop stopt.")
        return
    # BETON-387: elke LLM-call van deze loop wordt op het dagbudget afgeschreven;
    # `_run_batch` slaat een ronde over zodra het op is (tot middernacht UTC).
    budget = budget if budget is not None else ratelimit.DailyBudget(ratelimit.triage_daily_budget())
    llm = ratelimit.BudgetedLLM(llm, budget)
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(
                _run_batch,
                db_path,
                llm,
                embeddings,
                triage_user_id,
                debounce_seconds,
                batch,
                budget=budget,
            )
        except Exception:  # noqa: BLE001 — loop mag nooit sneuvelen
            logger.exception("Triage-batch mislukte")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass


def _triage_user_id(db_path: str) -> int | None:
    conn = db_module.connect(db_path)
    try:
        u = users_repo.get_by_handle(conn, "triage")
        return u["id"] if u else None
    finally:
        conn.close()


def _record_failure(
    conn: sqlite3.Connection,
    *,
    table: str,
    attempts_col: str,
    error_col: str,
    row_id: int,
) -> int:
    """Boek een mislukte LLM-poging: verhoog de teller + zet error-timestamp.
    Geeft het nieuwe pogingsaantal terug (voor quarantaine-logging)."""
    row = conn.execute(
        f"UPDATE {table} SET {attempts_col} = {attempts_col} + 1, "
        f"{error_col} = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ? "
        f"RETURNING {attempts_col}",
        (row_id,),
    ).fetchone()
    conn.commit()
    return row[0] if row else 0


def stale_days() -> int:
    """Na hoeveel dagen stilte een lopend item bevraagd wordt (BETON-375).

    `BETONNING_STALE_DAYS`; 0 (of onleesbaar) zet de detectie uit."""
    raw = env("BETONNING_STALE_DAYS")
    if raw is None:
        return DEFAULT_STALE_DAYS
    try:
        return int(raw)
    except ValueError:
        return 0


def _run_batch(
    db_path: str,
    llm,
    embeddings,
    triage_user_id: int,
    debounce_seconds: int,
    batch: int,
    *,
    days_stale: int | None = None,
    llm_call_budget: int | None = None,
    budget: ratelimit.DailyBudget | None = None,
) -> None:
    # Keyword-only met een default: de bestaande (positionele) aanroepen in tests
    # en in de loop blijven zo werken.
    days_stale = stale_days() if days_stale is None else days_stale
    # BETON-387: dagbudget. De per-user token-bucket op de HTTP-endpoints raakt
    # deze worker per constructie niet (hij roept `llm.complete` rechtstreeks
    # aan), en dat moet ook zo blijven — een limiet die de bot stillegt breekt de
    # triage. Dit is zijn eigen, veel ruimere plafond tegen een op hol geslagen
    # lus. De poort staat hier en niet in `BudgetedLLM`: een exception midden in
    # `triage_once` zou als item-fout tellen en het item na drie ronden in
    # quarantaine duwen.
    if budget is not None and budget.exhausted():
        return
    # BETON-392: `find_untriaged`, `find_unevaluated_comments`,
    # `find_assigned_to_triage` en `find_answered_questions` deden elk hun eigen
    # `limit=batch`-poll, dus een drukke ronde kon tot 4× `batch` LLM-calls doen.
    # Ze delen nu één rondebudget dat aftelt met wat er écht verwerkt is (niet met
    # de gevraagde limiet — een lege categorie mag de rest niet leegtrekken).
    # Volgorde bij een opraakend budget: eerste triage (het meest zichtbare gat —
    # een ongetrieerd item mist nog labels/assignee/state) vóór comment-eval vóór
    # assign-eval vóór answer-eval. Overgeslagen items blijven gewoon in de finder
    # staan (geen marker gezet) en komen de volgende ronde terug aan de beurt.
    # `find_stale` doet geen LLM-call (vraag+opties liggen vast, BETON-375) en telt
    # dus niet mee — uit het budget halen zou hem laten wachten op een dure ronde.
    llm_call_budget = batch if llm_call_budget is None else llm_call_budget
    remaining = max(0, llm_call_budget)
    conn = db_module.connect(db_path)
    try:
        if remaining:
            limit = min(batch, remaining)
            item_ids = find_untriaged(
                conn, debounce_seconds=debounce_seconds, limit=limit
            )
            remaining -= len(item_ids)
            for item_id in item_ids:
                # Per-item exception-handling: één poison-item mag de batch niet
                # stoppen en na MAX_ATTEMPTS mislukkingen belandt het in
                # quarantaine (BETON-41).
                try:
                    triage_once(
                        conn, item_id, llm, embeddings, triage_user_id=triage_user_id
                    )
                except Exception:  # noqa: BLE001 — één item mag de batch niet slopen
                    attempts = _record_failure(
                        conn,
                        table="items",
                        attempts_col="triage_attempts",
                        error_col="triage_error_at",
                        row_id=item_id,
                    )
                    if attempts >= MAX_ATTEMPTS:
                        logger.exception(
                            "Triage van item %s mislukte (%d×) → quarantaine",
                            item_id,
                            attempts,
                        )
                    else:
                        logger.exception(
                            "Triage van item %s mislukte (poging %d)",
                            item_id,
                            attempts,
                        )
        # Fase 2: nieuwe comments (niet van triage) beoordelen tussen mens en agent.
        if remaining:
            limit = min(batch, remaining)
            comment_ids = find_unevaluated_comments(
                conn,
                triage_user_id=triage_user_id,
                debounce_seconds=debounce_seconds,
                limit=limit,
            )
            remaining -= len(comment_ids)
            for comment_id in comment_ids:
                try:
                    evaluate_comment_once(
                        conn, comment_id, llm, triage_user_id=triage_user_id
                    )
                except Exception:  # noqa: BLE001 — één comment mag de batch niet slopen
                    attempts = _record_failure(
                        conn,
                        table="comments",
                        attempts_col="eval_attempts",
                        error_col="eval_error_at",
                        row_id=comment_id,
                    )
                    if attempts >= MAX_ATTEMPTS:
                        logger.exception(
                            "Comment-eval %s mislukte (%d×) → quarantaine",
                            comment_id,
                            attempts,
                        )
                    else:
                        logger.exception(
                            "Comment-eval %s mislukte (poging %d)",
                            comment_id,
                            attempts,
                        )
        # BETON-287: items die aan triage zijn toegewezen ná hun eerste triage —
        # `find_untriaged` ziet die niet meer (triaged_at staat), dus dit is de
        # enige route waarlangs een toewijzing triage nog laat afgaan.
        if remaining:
            limit = min(batch, remaining)
            assign_ids = find_assigned_to_triage(
                conn,
                triage_user_id=triage_user_id,
                debounce_seconds=debounce_seconds,
                limit=limit,
            )
            remaining -= len(assign_ids)
            for item_id in assign_ids:
                try:
                    respond_to_assignment_once(
                        conn, item_id, llm, triage_user_id=triage_user_id
                    )
                except Exception:  # noqa: BLE001 — één item mag de batch niet slopen
                    attempts = _record_failure(
                        conn,
                        table="items",
                        attempts_col="triage_attempts",
                        error_col="triage_error_at",
                        row_id=item_id,
                    )
                    if attempts >= MAX_ATTEMPTS:
                        logger.exception(
                            "Reactie op toewijzing %s mislukte (%d×) → quarantaine",
                            item_id,
                            attempts,
                        )
                    else:
                        logger.exception(
                            "Reactie op toewijzing %s mislukte (poging %d)",
                            item_id,
                            attempts,
                        )
        # BETON-389: beantwoorde triage-vragen. Het antwoord staat inline op de
        # vraag, dus geen enkele andere finder ziet het — zonder deze lus loopt
        # elke vraagmodule-vraag van triage dood.
        if remaining:
            limit = min(batch, remaining)
            question_ids = find_answered_questions(
                conn,
                triage_user_id=triage_user_id,
                debounce_seconds=debounce_seconds,
                limit=limit,
            )
            remaining -= len(question_ids)
            for question_id in question_ids:
                try:
                    evaluate_answer_once(
                        conn, question_id, llm, triage_user_id=triage_user_id
                    )
                except Exception:  # noqa: BLE001 — één vraag mag de batch niet slopen
                    attempts = _record_failure(
                        conn,
                        table="comments",
                        attempts_col="eval_attempts",
                        error_col="eval_error_at",
                        row_id=question_id,
                    )
                    if attempts >= MAX_ATTEMPTS:
                        logger.exception(
                            "Antwoord-eval %s mislukte (%d×) → quarantaine",
                            question_id,
                            attempts,
                        )
                    else:
                        logger.exception(
                            "Antwoord-eval %s mislukte (poging %d)",
                            question_id,
                            attempts,
                        )
        # BETON-375: lopende items die al dagen stilliggen. Geen LLM-call — de
        # vraag en de opties liggen vast, dus dit valt buiten het rondebudget.
        for item_id in find_stale(
            conn, triage_user_id=triage_user_id, days=days_stale, limit=batch
        ):
            try:
                ask_stale_once(
                    conn, item_id, triage_user_id=triage_user_id, days=days_stale
                )
            except Exception:  # noqa: BLE001 — één item mag de batch niet slopen
                attempts = _record_failure(
                    conn,
                    table="items",
                    attempts_col="triage_attempts",
                    error_col="triage_error_at",
                    row_id=item_id,
                )
                logger.exception(
                    "Stale-vraag op item %s mislukte (poging %d)", item_id, attempts
                )
        # BETON-420: guardrails waarvan de reviewdatum verstreken is. Ook hier
        # geen LLM-call — vraag en opties liggen vast — dus buiten het
        # rondebudget, net als de stale-lus hierboven.
        for item_id in find_guardrails_due_review(
            conn, triage_user_id=triage_user_id, limit=batch
        ):
            try:
                ask_guardrail_review_once(
                    conn, item_id, triage_user_id=triage_user_id
                )
            except Exception:  # noqa: BLE001 — één item mag de batch niet slopen
                attempts = _record_failure(
                    conn,
                    table="items",
                    attempts_col="triage_attempts",
                    error_col="triage_error_at",
                    row_id=item_id,
                )
                logger.exception(
                    "Guardrail-review op item %s mislukte (poging %d)",
                    item_id,
                    attempts,
                )
    finally:
        conn.close()
