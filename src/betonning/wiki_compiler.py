"""Wiki-compiler: de zelf-onderhoudende ingestion-loop van de LLM-wiki (BETON-24).

Karpathy's LLM-wiki compileert kennis continu uit ruwe bronnen i.p.v. per query
her-op te halen. Hier is de ruwe bron een **afgerond ticket** (closed-state) plus
z'n comments: wanneer een ticket klaar is, laat een LLM de duurzame lessen
(conventies, valkuilen, genomen keuzes, how-to's) compileren naar de projectwiki —
bestaande pagina's bijwerken i.p.v. dupliceren, of skippen als er niets
wiki-waardigs is. Autonoom, per-project opt-in, standaard uit.

Gemodelleerd naar de triage-bot: achtergrond-loop in de lifespan, marker-kolom
(`items.wiki_compiled_at`) tegen dubbel werk, debounce, `triage`-user als actor.
Pure delen (prompt-bouw/parsing) los testbaar met een FakeLLM.
"""

from __future__ import annotations

from .config import env

import asyncio
import logging
import sqlite3

from pydantic import BaseModel, Field

from . import db as db_module
from .llm import localized_system_prompt, parse_json_result, fenced, clamp, UNTRUSTED_INPUT_RULE
from .repo import llm_usage
from .repo import comments as comments_repo
from .repo import events as events_repo
from .repo import items as items_repo
from .repo import states as states_repo
from .repo import users as users_repo
from .repo import wiki as wiki_repo
from .repo import wiki_review

logger = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_SECONDS = 300
DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_BATCH = 3

# Na dit aantal mislukte compile-pogingen komt een item in quarantaine, zodat één
# poison-item de wiki-compile-loop niet eeuwig bezighoudt (BETON-41).
MAX_ATTEMPTS = 3


class WikiPageEdit(BaseModel):
    slug: str = Field(max_length=100)
    title: str = Field(max_length=300)
    body_md: str = Field(default="", max_length=12000)


class CompileResult(BaseModel):
    skip: bool = False
    pages: list[WikiPageEdit] = Field(default_factory=list, max_length=5)


COMPILE_SYSTEM_PROMPT = """Je bent de wiki-compiler van Betonning: je onderhoudt de \
project-kennisbank (een LLM-wiki). Er is zojuist een ticket afgerond. Je taak: haal \
de DUURZAME, HERBRUIKBARE kennis uit dit ticket + z'n comments en leg die vast in de \
projectwiki. Antwoord met JSON.

Wat WÉL compileren: conventies, architectuurkeuzes, valkuilen/gotchas, how-to's, \
beslissingen-met-motivatie — dingen die een volgende agent bij later werk helpen.
Wat NIET: ticket-specifieke status, eenmalige details, "gefixt in commit X", chit-chat.

Regels:
- Werk bij voorkeur een BESTAANDE pagina bij (zelfde slug) i.p.v. een bijna-duplicaat \
te maken. De bestaande pagina's staan hieronder.
- Bij het bijwerken: geef de VOLLEDIGE nieuwe inhoud van de pagina terug (je output \
vervangt de body), dus behoud wat nog klopt en voeg het nieuwe toe.
- Slugs zijn kort en kebab-case (a-z, 0-9, koppeltekens), bv. "deploy-gotchas".
- Schrijf beknopt en declaratief. Link verwante pagina's met [[slug]].
- Als er niets duurzaam-wiki-waardigs in zit: geef {"skip": true, "pages": []}.

JSON-vorm: {"skip": false, "pages": [{"slug": "...", "title": "...", "body_md": "..."}]}
Antwoord ALLEEN met valide JSON, zonder codeblokken of uitleg eromheen.""" + UNTRUSTED_INPUT_RULE


def _comments_text(comments: list[dict]) -> str:
    if not comments:
        return "(geen comments)"
    return "\n".join(
        f"- @{c.get('author') or '?'}: {(c.get('body_md') or '').strip()}" for c in comments
    )


def build_compile_messages(
    item: dict, comments: list[dict], wiki_context: str, existing_slugs: list[str]
) -> list[dict]:
    """Bouw de chat-messages voor de wiki-compilatie (pure functie, testbaar)."""
    existing = ", ".join(existing_slugs[:200]) or "(nog geen pagina's)"
    user = (
        fenced("bestaande-paginas", clamp(existing, 3000)) + "\n"
        + fenced("wiki-context", clamp(wiki_context or "(leeg)", 20000)) + "\n"
        + fenced("ticket", clamp(
            f"Ref: {item.get('ref')}\nTitel: {item.get('title')}\n"
            f"State: {item.get('state')}\nBeschrijving: {item.get('description_md') or '(geen)'}", 10000)) + "\n"
        + fenced("comments", clamp(_comments_text(comments[-30:]), 12000))
    )
    return [
        {"role": "system", "content": localized_system_prompt(COMPILE_SYSTEM_PROMPT)},
        {"role": "user", "content": user},
    ]


def parse_compile(text: str) -> CompileResult:
    """Parse de LLM-output; val terug op skip bij invalide JSON."""
    return parse_json_result(
        text,
        CompileResult,
        context="Wiki-compile-output",
        fallback=lambda raw, exc: CompileResult(skip=True),
        log=logger,
    )


def apply_compile(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    result: CompileResult,
    actor_id: int,
) -> list[str]:
    """Pas een CompileResult toe: upsert de wiki-pagina's (projectscope) en
    markeer het item als gecompileerd. Eén transactie. Geeft de geraakte slugs."""
    project_id = item["project_id"]
    touched: list[str] = []
    with db_module.transaction(conn):
        if not result.skip:
            for page in result.pages:
                slug = wiki_repo.slugify(page.slug)
                if not slug or not page.title.strip():
                    continue
                existing = wiki_repo.get_by_slug(conn, project_id, slug)
                if wiki_review.needs_review(conn, project_id, slug, actor_id):
                    wiki_review.submit(conn, project_id, slug, page.title, page.body_md, actor_id)
                    touched.append(slug)
                    continue
                if existing is not None:
                    # BETON-209: de compiler-bot is de auteur van deze revisie.
                    wiki_repo.update(
                        conn, existing["id"],
                        {"title": page.title, "body_md": page.body_md},
                        author_id=actor_id,
                    )
                else:
                    wiki_repo.create(
                        conn,
                        project_id=project_id,
                        slug=slug,
                        title=page.title,
                        body_md=page.body_md,
                        author_id=actor_id,
                    )
                touched.append(slug)
        # Spoor in de activity-feed (ook bij skip → observeerbaar dat het draaide).
        events_repo.record(
            conn,
            type="wiki.compiled",
            item_id=item["id"],
            actor_id=actor_id,
            payload={"skipped": result.skip, "pages": touched},
        )
        conn.execute(
            "UPDATE items SET wiki_compiled_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE id = ?",
            (item["id"],),
        )
    return touched


# --- Worker ----------------------------------------------------------------


def find_uncompiled(
    conn: sqlite3.Connection,
    *,
    debounce_seconds: int,
    limit: int,
    max_attempts: int = MAX_ATTEMPTS,
) -> list[int]:
    """Id's van afgeronde (groep completed/cancelled) items in opt-in-projecten die nog niet
    gecompileerd zijn en minstens `debounce_seconds` met rust zijn gelaten (zodat
    late edits eerst bezinken). Items in quarantaine
    (wiki_compile_attempts >= max_attempts) worden overgeslagen."""
    rows = conn.execute(
        f"""SELECT i.id FROM items i
           JOIN projects p ON p.id = i.project_id
           JOIN states s ON s.id = i.state_id
           WHERE i.wiki_compiled_at IS NULL AND i.archived_at IS NULL
             AND p.wiki_compile_enabled = 1
             AND {states_repo.state_closed_sql('s')}
             AND i.wiki_compile_attempts < ?
             AND i.updated_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)
           ORDER BY i.id LIMIT ?""",
        (int(max_attempts), f"-{int(debounce_seconds)} seconds", limit),
    ).fetchall()
    return [r["id"] for r in rows]


def compile_once(
    conn: sqlite3.Connection, item_id: int, llm, *, actor_id: int
) -> bool | None:
    """Compileer één afgerond ticket → projectwiki."""
    item = items_repo.get(conn, item_id)
    if item is None or item["wiki_compiled_at"] is not None:
        return None
    limit = int(env("BETONNING_WIKI_DAILY_BUDGET", "100"))
    if not llm_usage.claim(conn, "wiki-compiler", limit):
        logger.info("Wiki-compiler wacht: dagbudget bereikt")
        return False
    data = items_repo.serialize(conn, item)
    comments = [
        comments_repo.serialize(conn, c)
        for c in comments_repo.list_for_item(conn, item["id"])
    ]
    # Volledige projectpagina's: apply_compile vervangt hun body, dus de
    # compiler moet zien wat er staat (BETON-352).
    wiki_context = wiki_repo.compile_context(conn, item["project_id"])
    existing_slugs = [p["slug"] for p in wiki_repo.list_pages(conn, item["project_id"])]
    messages = build_compile_messages(data, comments, wiki_context, existing_slugs)
    result = parse_compile(llm.complete(messages))
    touched = apply_compile(conn, item, result, actor_id)
    logger.info(
        "Wiki-compile %s → %s", data["ref"], "skip" if result.skip else ", ".join(touched)
    )
    return None


def _compiler_user_id(db_path: str) -> int | None:
    conn = db_module.connect(db_path)
    try:
        u = users_repo.get_by_handle(conn, "triage")
        return u["id"] if u else None
    finally:
        conn.close()


def _record_failure(conn: sqlite3.Connection, item_id: int) -> int:
    """Boek een mislukte compile-poging (teller + error-timestamp). Geeft het
    nieuwe pogingsaantal terug."""
    row = conn.execute(
        "UPDATE items SET wiki_compile_attempts = wiki_compile_attempts + 1, "
        "wiki_compile_error_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ? "
        "RETURNING wiki_compile_attempts",
        (item_id,),
    ).fetchone()
    conn.commit()
    return row[0] if row else 0


def _run_batch(db_path: str, llm, actor_id: int, debounce_seconds: int, batch: int) -> None:
    conn = db_module.connect(db_path)
    try:
        for item_id in find_uncompiled(conn, debounce_seconds=debounce_seconds, limit=batch):
            # Circuit-breaker: één providerfout per ronde, daarna pauze tot de
            # volgende interval; het duurzame dagbudget begrenst herstarts.
            # Per-item exception-handling + quarantaine na MAX_ATTEMPTS (BETON-41):
            # één poison-item mag de batch niet stoppen of de loop eeuwig bezighouden.
            try:
                if compile_once(conn, item_id, llm, actor_id=actor_id) is False:
                    break
            except Exception:  # noqa: BLE001 — één item mag de batch niet slopen
                attempts = _record_failure(conn, item_id)
                if attempts >= MAX_ATTEMPTS:
                    logger.exception(
                        "Wiki-compile van item %s mislukte (%d×) → quarantaine",
                        item_id, attempts,
                    )
                else:
                    logger.exception(
                        "Wiki-compile van item %s mislukte (poging %d)", item_id, attempts
                    )
                break
    finally:
        conn.close()


async def wiki_compile_loop(
    db_path: str,
    stop_event: asyncio.Event,
    llm,
    *,
    debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    batch: int = DEFAULT_BATCH,
) -> None:
    """Achtergrond-loop: compileert periodiek een batch afgeronde tickets."""
    actor_id = _compiler_user_id(db_path)
    if actor_id is None:
        logger.warning("Geen 'triage'-user; wiki-compile-loop stopt.")
        return
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(
                _run_batch, db_path, llm, actor_id, debounce_seconds, batch
            )
        except Exception:  # noqa: BLE001 — loop mag nooit sneuvelen
            logger.exception("Wiki-compile-batch mislukte")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass
