"""Wiki-repository: markdown-kennispagina's, globaal of per project (BETON-24).

De wiki is Betonnings memory-provider voor (coding-)agents: pagina's worden als
context ingeladen i.p.v. per query her-opgehaald (Karpathy's LLM-wiki-patroon).
`project_id IS NULL` = globaal (voor alle projecten/agents); anders projectspecifiek.
Pure sqlite3, connectie als eerste arg, geen ORM — conform de andere repos.
"""

from __future__ import annotations

from ..config import env

import re
import sqlite3

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Char-cap op de samengevoegde memory-context (BETON-42). Voorkomt dat het
# agent-geheugen onbegrensd groeit en elke trigger/context-load zwaarder maakt.
# 0 of negatief = geen limiet. Override via BETONNING_WIKI_CONTEXT_BUDGET.
DEFAULT_CONTEXT_BUDGET = 12000


def slugify(text: str) -> str:
    """Normaliseer naar een kebab-case slug (a-z0-9 met koppeltekens)."""
    s = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return s


def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug))


def serialize(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "slug": row["slug"],
        "title": row["title"],
        "body_md": row["body_md"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "protected": bool(row["protected"]),
        "source_kind": row["source_kind"],
        "source_author_id": row["source_author_id"],
    }


def get_by_slug(
    conn: sqlite3.Connection, project_id: int | None, slug: str
) -> sqlite3.Row | None:
    if project_id is None:
        return conn.execute(
            "SELECT * FROM wiki_pages WHERE project_id IS NULL AND slug = ?", (slug,)
        ).fetchone()
    return conn.execute(
        "SELECT * FROM wiki_pages WHERE project_id = ? AND slug = ?", (project_id, slug)
    ).fetchone()


def list_index(conn: sqlite3.Connection) -> list[dict]:
    """Alle (scope, slug)-paren over álle scopes (BETON-306).

    ``scope`` = ``"global"`` voor globale pagina's, anders de project-key
    (bv. ``"BETON"``). Alleen slugs, geen bodies — dit draait bij elke
    wiki-render voor de levend/dood-markering van gekwalificeerde interlinks
    (``[[BETON:slug]]``). De slug is per scope uniek, maar dezelfde slug mág in
    meerdere scopes bestaan, dus een kale slug is inherent ambigu — vandaar dat
    de index de scope expliciet meedraagt."""
    rows = conn.execute(
        "SELECT w.slug AS slug, p.key AS pkey FROM wiki_pages w "
        "LEFT JOIN projects p ON p.id = w.project_id "
        "ORDER BY p.key, w.slug"
    ).fetchall()
    return [{"scope": r["pkey"] or "global", "slug": r["slug"]} for r in rows]


def list_pages(conn: sqlite3.Connection, project_id: int | None) -> list[sqlite3.Row]:
    if project_id is None:
        rows = conn.execute(
            "SELECT * FROM wiki_pages WHERE project_id IS NULL ORDER BY slug LIMIT 1000"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM wiki_pages WHERE project_id = ? ORDER BY slug LIMIT 1000", (project_id,)
        ).fetchall()
    return rows


def _source_kind(conn, author_id):
    row = conn.execute("SELECT kind FROM users WHERE id=?", (author_id,)).fetchone()
    return row["kind"] if row else "legacy"


def create(
    conn: sqlite3.Connection,
    *,
    project_id: int | None,
    slug: str,
    title: str,
    body_md: str = "",
    author_id: int | None = None,
) -> sqlite3.Row:
    cur = conn.execute(
        "INSERT INTO wiki_pages (project_id,slug,title,body_md,protected,source_kind,source_author_id) VALUES(?,?,?,?,?,?,?)",
        (project_id, slug, title, body_md, int(project_id is None), _source_kind(conn, author_id), author_id),
    )
    # BETON-209: een nieuwe pagina start meteen met een begin-revisie.
    assert cur.lastrowid is not None
    record_revision(conn, cur.lastrowid, title=title, body_md=body_md, author_id=author_id)
    return conn.execute(
        "SELECT * FROM wiki_pages WHERE id = ?", (cur.lastrowid,)
    ).fetchone()


def update(
    conn: sqlite3.Connection,
    page_id: int,
    fields: dict,
    author_id: int | None = None,
) -> sqlite3.Row:
    # BETON-209: leg een revisie vast zodra de inhoud daadwerkelijk wijzigt (geen
    # revisie op een no-op-PATCH). Vergelijk met de huidige rij vóór de update.
    before = conn.execute(
        "SELECT title, body_md FROM wiki_pages WHERE id = ?", (page_id,)
    ).fetchone()
    allowed = {k: v for k, v in fields.items() if k in ("title", "body_md")}
    if allowed:
        sets = ", ".join(f"{k} = ?" for k in allowed)
        conn.execute(
            f"UPDATE wiki_pages SET {sets}, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (*allowed.values(), page_id),
        )
    conn.execute("UPDATE wiki_pages SET source_kind=?,source_author_id=? WHERE id=?",
                 (_source_kind(conn, author_id), author_id, page_id))
    row = conn.execute("SELECT * FROM wiki_pages WHERE id = ?", (page_id,)).fetchone()
    if row is not None and (
        before is None
        or before["title"] != row["title"]
        or before["body_md"] != row["body_md"]
    ):
        record_revision(
            conn, page_id, title=row["title"], body_md=row["body_md"], author_id=author_id
        )
    return row


def record_revision(
    conn: sqlite3.Connection,
    page_id: int,
    *,
    title: str,
    body_md: str,
    author_id: int | None,
    created_at: str | None = None,
) -> sqlite3.Row:
    """Leg een onveranderlijke snapshot van een wiki-pagina vast (BETON-209)."""
    if created_at is None:
        cur = conn.execute(
            "INSERT INTO wiki_revisions (page_id, title, body_md, author_id) "
            "VALUES (?, ?, ?, ?)",
            (page_id, title, body_md, author_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO wiki_revisions (page_id, title, body_md, author_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (page_id, title, body_md, author_id, created_at),
        )
    return conn.execute(
        "SELECT * FROM wiki_revisions WHERE id = ?", (cur.lastrowid,)
    ).fetchone()


def serialize_revision(row: sqlite3.Row, *, include_body: bool = False) -> dict:
    """Revisie-metadata voor de timeline. `include_body` voegt de volledige
    snapshot toe (voor de diff-/preview-weergave)."""
    out = {
        "id": row["id"],
        "page_id": row["page_id"],
        "title": row["title"],
        "author": row["author_handle"] if "author_handle" in row.keys() else None,
        "created_at": row["created_at"],
    }
    if include_body:
        out["body_md"] = row["body_md"]
    return out


def list_revisions(conn: sqlite3.Connection, page_id: int) -> list[sqlite3.Row]:
    """Revisies van een pagina, nieuwste eerst, met de auteur-handle erbij
    (LEFT JOIN — een backfill-/soft-deleted auteur geeft NULL)."""
    return conn.execute(
        "SELECT r.*, u.handle AS author_handle "
        "FROM wiki_revisions r LEFT JOIN users u ON u.id = r.author_id "
        "WHERE r.page_id = ? ORDER BY r.created_at DESC, r.id DESC",
        (page_id,),
    ).fetchall()


def get_revision(conn: sqlite3.Connection, revision_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT r.*, u.handle AS author_handle "
        "FROM wiki_revisions r LEFT JOIN users u ON u.id = r.author_id "
        "WHERE r.id = ?",
        (revision_id,),
    ).fetchone()


def predecessor_revision(
    conn: sqlite3.Connection, page_id: int, created_at: str, revision_id: int
) -> sqlite3.Row | None:
    """De revisie direct vóór de gegeven revisie (voor de diff). None voor de
    allereerste revisie van een pagina."""
    return conn.execute(
        "SELECT r.*, u.handle AS author_handle "
        "FROM wiki_revisions r LEFT JOIN users u ON u.id = r.author_id "
        "WHERE r.page_id = ? AND (r.created_at, r.id) < (?, ?) "
        "ORDER BY r.created_at DESC, r.id DESC LIMIT 1",
        (page_id, created_at, revision_id),
    ).fetchone()


def delete(conn: sqlite3.Connection, page_id: int) -> None:
    conn.execute("DELETE FROM wiki_pages WHERE id = ?", (page_id,))


def context_budget() -> int:
    """Het char-budget voor `context_markdown` (env `BETONNING_WIKI_CONTEXT_BUDGET`).

    Default `DEFAULT_CONTEXT_BUDGET`; 0 of negatief = geen limiet.
    """
    raw = env("BETONNING_WIKI_CONTEXT_BUDGET")
    if raw is None:
        return DEFAULT_CONTEXT_BUDGET
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_CONTEXT_BUDGET


def _blurb(body_md: str, *, limit: int = 140) -> str:
    """Eén regel samenvatting voor de index: de eerste alinea die géén kop is.

    Veel pagina's beginnen met een H1 die de titel herhaalt; die slaan we over,
    anders levert de index alleen echo op (BETON-352).
    """
    title_free = [
        block.strip()
        for block in body_md.strip().split("\n\n")
        if block.strip() and not block.strip().startswith("#")
    ]
    if not title_free:
        return ""
    line = " ".join(title_free[0].split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _render_page(page: sqlite3.Row) -> str:
    kind = page["source_kind"]
    author = page["source_author_id"]
    status = "beschermd" if page["protected"] else "gewone kennis"
    body = page["body_md"]
    if kind == "agent":
        body = "<agent-kennis>\n" + body.replace("</agent-kennis>", "") + "\n</agent-kennis>"
    return (f"## {page['title']}\n\n"
            f"Bron: {kind} (auteur-ID {author}); {status}.\n\n"
            f"{body}").rstrip()


def _index_line(page: sqlite3.Row, *, blurb_enabled: bool = True) -> str:
    blurb = _blurb(page["body_md"]) if blurb_enabled else ""
    line = f"- `{page['slug']}` — {page['title']}"
    return f"{line} — {blurb}" if blurb else line


TRUNCATION_NOTE = (
    "_Niet alle pagina's passen in het context-budget: hieronder staan de meest "
    "recente volledig, de rest als index. Haal die op met `get_memory_page`._"
)

INDEX_HEADING = "# Niet geladen (index)"


def _assemble(
    conn: sqlite3.Connection,
    project_id: int | None,
    *,
    full_ids: set[int] | None = None,
    blurbs: bool = True,
    cached_pages: tuple[list, list] | None = None,
) -> str:
    """Bouw de contextblob. ``full_ids`` = de pagina's die volledig meegaan;
    ``None`` betekent alles volledig. De rest komt als index onderaan, met
    (``blurbs``) of zonder een eenregelige samenvatting per pagina."""
    scopes: list[tuple[str, list[sqlite3.Row]]] = [
        ("# Globale memory", cached_pages[0] if cached_pages else list_pages(conn, None))
    ]
    if project_id is not None:
        scopes.append(("# Projectmemory", cached_pages[1] if cached_pages else list_pages(conn, project_id)))

    parts: list[str] = []
    index: list[str] = []
    if full_ids is not None:
        parts.append(TRUNCATION_NOTE)
    for heading, pages in scopes:
        chosen_ids = {
            p["id"] for p in pages if full_ids is None or p["id"] in full_ids
        }
        chosen = [p for p in pages if p["id"] in chosen_ids]
        if chosen:
            parts.append(heading)
            parts.extend(_render_page(p) for p in chosen)
        index.extend(
            _index_line(p, blurb_enabled=blurbs)
            for p in pages
            if p["id"] not in chosen_ids
        )
    if index:
        parts.append(INDEX_HEADING)
        parts.append("\n".join(index))
    return "\n\n".join(parts)


def _fill_to_budget(
    conn: sqlite3.Connection, project_id: int | None, budget: int
) -> str:
    """Vul het budget met volledige pagina's, meest recent bijgewerkt eerst.

    Greedy: een pagina gaat er volledig in zolang de héle blob (inclusief de
    index van wat overblijft) binnen het budget past; past hij niet, dan slaan
    we hem over en proberen we de volgende — een kleine pagina kan er dus nog
    wél bij. Zo krijgt een agent bruikbare inhoud i.p.v. 41 stubs (BETON-352).
    """
    global_pages = list(list_pages(conn, None))
    project_pages = list(list_pages(conn, project_id)) if project_id is not None else []
    pages = global_pages + project_pages
    cached_pages = (global_pages, project_pages)
    ranked = sorted(pages, key=lambda p: (p["updated_at"] or "", p["slug"]), reverse=True)

    # De index van álle pagina's is de bodem: die gaat altijd mee, anders weet
    # de agent niet wat er nog meer is. Past die bodem mét blurbs niet, dan
    # vallen de blurbs weg voordat we aan volledige pagina's beginnen.
    blurbs = len(_assemble(conn, project_id, cached_pages=cached_pages, full_ids=set())) <= budget

    full_ids: set[int] = set()
    best = _assemble(conn, project_id, cached_pages=cached_pages, full_ids=full_ids, blurbs=blurbs)
    for page in ranked:
        candidate = full_ids | {page["id"]}
        rendered = _assemble(conn, project_id, cached_pages=cached_pages, full_ids=candidate, blurbs=blurbs)
        if len(rendered) <= budget:
            full_ids = candidate
            best = rendered
    if not full_ids and blurbs:
        # Volledige kennis gaat vóór samenvattingen van de index.
        best = _assemble(conn, project_id, cached_pages=cached_pages, full_ids=set(), blurbs=False)
        for page in ranked:
            candidate = full_ids | {page["id"]}
            rendered = _assemble(conn, project_id, cached_pages=cached_pages, full_ids=candidate, blurbs=False)
            if len(rendered) <= budget:
                full_ids = candidate
                best = rendered
    if len(best) > budget and budget > 0:
        # Bij piepkleine budgetten blijft een bruikbare, begrensde titelindex over.
        lines = ["# Index"]
        for page in ranked:
            line = _index_line(page, blurb_enabled=False)
            if len("\n".join(lines + [line])) > budget:
                break
            lines.append(line)
        best = "\n".join(lines)[:budget]
    return best


# De compiler herschrijft de body van een projectpagina volledig ("behoud wat
# nog klopt"), dus die pagina's moeten VOLLEDIG in zijn context staan — een
# index-regel zou hem uit het niets laten herschrijven (BETON-352). Ruimer
# budget dan de agent-context; globale pagina's raakt hij niet aan.
DEFAULT_COMPILE_BUDGET = 60000


def compile_context(
    conn: sqlite3.Connection, project_id: int | None, *, budget: int | None = None
) -> str:
    """Wiki-context voor de wiki-compiler: eigen projectpagina's volledig,
    globale pagina's alleen als index.

    Boven ``budget`` vallen de minst recent bijgewerkte projectpagina's terug
    naar een index-regel — die kan de compiler dan niet bijwerken, maar hij
    overschrijft ze ook niet blind.
    """
    if budget is None:
        budget = DEFAULT_COMPILE_BUDGET
    parts: list[str] = []
    globals_ = list_pages(conn, None)
    if globals_:
        parts.append("# Globale memory (index — niet bijwerken)")
        parts.append("\n".join(_index_line(p) for p in globals_))
    pages = list(list_pages(conn, project_id)) if project_id is not None else []
    if pages:
        ranked = sorted(
            pages, key=lambda p: (p["updated_at"] or "", p["slug"]), reverse=True
        )
        head = len(("\n\n".join(parts)))
        full_ids: set[int] = set()
        if budget <= 0:
            full_ids = {p["id"] for p in pages}
        else:
            for page in ranked:
                candidate = full_ids | {page["id"]}
                size = head + sum(
                    len(_render_page(p)) + 2 if p["id"] in candidate
                    else len(_index_line(p)) + 1
                    for p in pages
                )
                if size <= budget:
                    full_ids = candidate
        body = [_render_page(p) for p in pages if p["id"] in full_ids]
        index = [_index_line(p) for p in pages if p["id"] not in full_ids]
        parts.append("# Projectmemory (volledig — dit werk je bij)")
        parts.extend(body)
        if index:
            parts.append("## Niet geladen (index)")
            parts.append("\n".join(index))
    return "\n\n".join(parts)


GUARDRAIL_HEADING = "# Guardrails (projectbreed — lees dit eerst)"


def guardrail_block(conn: sqlite3.Connection, project_id: int | None) -> str:
    """Markdown-blok met de actieve projectbrede guardrails van dit project
    (BETON-420).

    Staat BUITEN de budgetverdeling van `_fill_to_budget`: een guardrail mag niet
    verdrongen worden door wiki-pagina's, en andersom mag hij de wiki niet
    opeten. Het blok is per constructie begrensd (max
    GUARDRAIL_PROJECT_WIDE_MAX × GUARDRAIL_MAX_CHARS ≈ 5.000 tekens tegen een
    budget van 12.000). Geen project_id of geen guardrails → lege string.
    """
    if project_id is None:
        return ""
    from . import guardrails as guardrails_repo  # laat import: items ↔ guardrails

    rows = guardrails_repo.project_wide(conn, project_id)
    if not rows:
        return ""
    parts = [
        GUARDRAIL_HEADING,
        "",
        "Deze regels zijn BINDEND: lees ze vóór je aan een ticket in dit "
        "project werkt.",
    ]
    for row in rows:
        parts.append("")
        parts.append(f"## {row['ref']} — {row['title']}")
        parts.append("")
        parts.append(row["guardrail_md"])
        parts.append("")
        parts.append(f"_Reviewdatum: {row['review_by']}._")
    return "\n".join(parts)


def context_markdown(
    conn: sqlite3.Connection, project_id: int | None, *, budget: int | None = None
) -> str:
    """De samengevoegde wiki-markdown die een agent als memory inlaadt.

    Altijd de globale pagina's; bij een project ook de projectpagina's eronder.
    Gescheiden met koppen zodat de herkomst (globaal/project) duidelijk blijft.

    Past alles binnen het char-budget (BETON-42), dan gaat alles volledig mee.
    Anders vullen we het budget met volledige pagina's (meest recent bijgewerkt
    eerst) en komt de rest als index onderaan (BETON-352) — inkorten tot losse
    eerste alinea's leverde een blob op waarin vrijwel elke pagina alleen zijn
    eigen titel herhaalde. ``budget`` default naar `context_budget()`; 0 of
    negatief = geen limiet.
    """
    if budget is None:
        budget = context_budget()
    full = _assemble(conn, project_id)
    if budget <= 0 or len(full) <= budget:
        body = full
    else:
        body = _fill_to_budget(conn, project_id, budget)
    # BETON-420: het guardrail-blok komt ERVOOR en telt niet mee in de
    # budgetvergelijking hierboven — anders zou een guardrail wiki-pagina's
    # verdringen (of zelf verdrongen worden). Zijn omvang is per constructie
    # begrensd door het plafond op het aantal projectbrede guardrails.
    block = guardrail_block(conn, project_id)
    return f"{block}\n\n{body}".strip() if block else body
