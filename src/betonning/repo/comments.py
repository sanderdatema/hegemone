"""Comments-repository: reacties op items."""

from __future__ import annotations

import json
import sqlite3

from .users import handle_of as _handle


# BETON-454: wat een OPEN vraag is, op één plek. Onbeantwoord én niet ingetrokken;
# elke query die "open vragen" bedoelt gebruikt `question_open_sql` (zoals
# `items.GUARDRAIL_ACTIVE`). Een ingetrokken vraag heeft géén `answered_at`.
def question_open_sql(alias: str = "") -> str:
    a = f"{alias}." if alias else ""
    return (
        f"{a}kind = 'question' AND {a}answered_at IS NULL "
        f"AND {a}withdrawn_at IS NULL"
    )




def _answer_locked(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
    """Is het antwoord op deze vraag al verstuurd (BETON-263)? Historische
    antwoorden (met answer_comment_id) zijn onveranderlijk; nieuwe antwoorden zijn
    'locked' zodra hun notificatie is afgeleverd. Inline-SQL i.p.v. een import van
    ``webhooks`` (dat importeert deze repo al)."""
    if row["kind"] != "question" or row["answered_at"] is None:
        return False
    if row["answer_comment_id"] is not None:
        return True
    return (
        conn.execute(
            "SELECT 1 FROM webhook_deliveries d JOIN events e ON e.id = d.event_id "
            "WHERE e.type = 'question.answered' "
            "AND json_extract(e.payload, '$.comment_id') = ? AND d.status = 'delivered' "
            "LIMIT 1",
            (row["id"],),
        ).fetchone()
        is not None
    )


def serialize(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    options = row["question_options"]
    return {
        "id": row["id"],
        "author": _handle(conn, row["author_id"]),
        "body_md": row["body_md"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        # Vraagmodule (BETON-219): een 'question'-comment draagt opties + de
        # antwoord-metadata. Bij een gewone comment zijn deze null/'comment'.
        "kind": row["kind"],
        "question_options": json.loads(options) if options else None,
        "answered_at": row["answered_at"],
        "answered_by": _handle(conn, row["answered_by"]),
        # BETON-265/263: het antwoord staat inline op de vraag (answer_text/
        # answer_option_index) i.p.v. als los comment. answer_comment_id blijft
        # alleen voor historische antwoorden gevuld (backwards-compat).
        "answer_text": row["answer_text"],
        "answer_option_index": row["answer_option_index"],
        "answer_comment_id": row["answer_comment_id"],
        # BETON-263: het antwoord is wijzigbaar zolang het niet 'locked' is
        # (notificatie nog niet verstuurd). De UI toont dan een wijzig-affordance.
        "answer_locked": _answer_locked(conn, row),
        # BETON-454: ingetrokken door de vraagsteller (antwoord kwam elders).
        "withdrawn_at": row["withdrawn_at"],
        "withdrawn_reason": row["withdrawn_reason"],
    }


def create(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    author_id: int | None,
    body_md: str,
    kind: str = "comment",
    question_options: list[str] | None = None,
) -> sqlite3.Row:
    cur = conn.execute(
        "INSERT INTO comments (item_id, author_id, body_md, kind, question_options) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            item_id,
            author_id,
            body_md,
            kind,
            json.dumps(question_options) if question_options is not None else None,
        ),
    )
    return conn.execute(
        "SELECT * FROM comments WHERE id = ?", (cur.lastrowid,)
    ).fetchone()


def mark_answered(
    conn: sqlite3.Connection,
    question_id: int,
    *,
    answered_by: int | None,
    answer_text: str,
    answer_option_index: int | None = None,
) -> sqlite3.Row:
    """Zet het antwoord inline op een vraag-comment (BETON-265/263).

    Het antwoord is géén los comment meer; de tekst (en bij een keuze de
    optie-index) staan direct op de vraag. ``answer_comment_id`` blijft NULL voor
    nieuwe antwoorden (alleen historische antwoorden hebben er nog een)."""
    conn.execute(
        "UPDATE comments SET answered_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
        "answered_by = ?, answer_text = ?, answer_option_index = ? WHERE id = ?",
        (answered_by, answer_text, answer_option_index, question_id),
    )
    return conn.execute(
        "SELECT * FROM comments WHERE id = ?", (question_id,)
    ).fetchone()


def mark_withdrawn(
    conn: sqlite3.Connection, question_id: int, *, reason: str
) -> sqlite3.Row:
    """Trek een vraag in (BETON-454). Raakt `answered_at` niet aan."""
    conn.execute(
        "UPDATE comments SET withdrawn_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
        "withdrawn_reason = ? WHERE id = ?",
        (reason, question_id),
    )
    return conn.execute(
        "SELECT * FROM comments WHERE id = ?", (question_id,)
    ).fetchone()


def update_answer(
    conn: sqlite3.Connection,
    question_id: int,
    *,
    answer_text: str,
    answer_option_index: int | None = None,
) -> sqlite3.Row:
    """Wijzig het inline-antwoord van een al beantwoorde vraag (BETON-263).

    Muteert ``updated_at`` maar niet ``answered_at``/``answered_by`` — het blijft
    hetzelfde antwoord, alleen bijgesteld. Toegestaan zolang de notificatie nog
    niet verstuurd is (de API-laag bewaakt dat)."""
    conn.execute(
        "UPDATE comments SET answer_text = ?, answer_option_index = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
        (answer_text, answer_option_index, question_id),
    )
    return conn.execute(
        "SELECT * FROM comments WHERE id = ?", (question_id,)
    ).fetchone()


def open_questions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Alle onbeantwoorde vraag-comments (over alle projecten heen).

    De rol-/gerichtheidsfilter (assignee/creator/mentioned) draait in de
    API-laag, die de item-context en @mentions kent.

    BETON-413: vragen op een gearchiveerd item of in een gearchiveerd project
    vallen af. Deze query had helemaal geen archief-poort, ook niet op
    item-niveau, dus een afgesloten project bleef om antwoord vragen. Vandaar de
    join op items/projects; ``open_questions_for_item`` en
    ``answered_questions_for_item`` blijven ongefilterd — die zijn item-gescoped
    en voeden de BETON-262-vrijgave, en een poort daar zou de ingehouden
    antwoord-notificaties laten hangen.

    Elke rij draagt naast ``c.*`` de item-context die de API-laag nodig heeft
    (``item_assignee_id``, ``item_created_by``, ``item_ref``, ``item_title``,
    ``item_state``), zodat die niet per vraag het item ophaalt."""
    return conn.execute(
        "SELECT c.*, i.assignee_id AS item_assignee_id, "
        "i.created_by AS item_created_by, p.key || '-' || i.seq AS item_ref, "
        "i.title AS item_title, s.name AS item_state "
        "FROM comments c "
        "JOIN items i ON i.id = c.item_id "
        "JOIN projects p ON p.id = i.project_id "
        "LEFT JOIN states s ON s.id = i.state_id "
        f"WHERE {question_open_sql('c')} "
        # Zelfde regel als items.LIVE_PROJECT; letterlijk hier omdat repo/items
        # deze module importeert (een import terug zou een cyclus geven).
        "AND i.archived_at IS NULL AND p.archived_at IS NULL "
        "ORDER BY c.id"
    ).fetchall()


def open_questions_for_item(
    conn: sqlite3.Connection, item_id: int
) -> list[sqlite3.Row]:
    """Onbeantwoorde vraag-comments op één item (BETON-262).

    Nodig om te bepalen of álle vragen op een item beantwoord zijn voordat de
    antwoord-notificaties worden vrijgegeven."""
    return conn.execute(
        f"SELECT * FROM comments WHERE item_id = ? AND {question_open_sql()} "
        "ORDER BY id",
        (item_id,),
    ).fetchall()


def answered_questions_for_item(
    conn: sqlite3.Connection, item_id: int
) -> list[sqlite3.Row]:
    """Beantwoorde vraag-comments op één item (BETON-262).

    Gebruikt bij het vrijgeven van de ingehouden antwoord-notificaties zodra het
    item geen open vragen meer heeft."""
    return conn.execute(
        "SELECT * FROM comments WHERE item_id = ? AND kind = 'question' "
        "AND answered_at IS NOT NULL ORDER BY id",
        (item_id,),
    ).fetchall()


def list_for_item(conn: sqlite3.Connection, item_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM comments WHERE item_id = ? ORDER BY id", (item_id,)
    ).fetchall()


def count_for_item(conn: sqlite3.Connection, item_id: int) -> int:
    """Aantal comments op één item (BETON-301/302), voor de omschrijving/plan-
    lock en de noodstop-drempel.

    Telt ALLE comments mee, ook vragen (`kind='question'`) — zodra er íets van
    een gesprek is, is de omschrijving publiek geworden en is een stille
    herschrijving even verwarrend als bij een gewone comment.

    **Uitzondering: comments van de `triage`-user tellen niet mee.** Triage
    plaatst vaak al binnen seconden na aanmaken een automatische classificatie-
    comment (BETON-189) — dat is geen discussie, en zou anders de BETON-218-
    planworkflow (plan_md zetten ná aanmaken) op zowat elk getriaged item
    blokkeren nog vóórdat er ooit een plan geschreven is. Een echte reactie
    van een mens of een andere agent bevriest wél."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM comments c "
        "LEFT JOIN users u ON u.id = c.author_id "
        "WHERE c.item_id = ? AND (u.handle IS NULL OR u.handle != 'triage')",
        (item_id,),
    ).fetchone()
    return row["n"]


def count_chatter(conn: sqlite3.Connection, item_id: int) -> int:
    """Aantal comments dat meetelt voor de **noodstop** (BETON-302/339).

    Bewust géén hergebruik van `count_for_item`: die telt voor de BETON-301-
    bevriezing van omschrijving/plan, en dáár tellen vragen wél mee (zie de
    docstring hierboven — zodra er iets van een gesprek is, is de omschrijving
    publiek geworden). Eén functie voor beide zou betekenen dat een wijziging
    aan de ene poort de andere stilzwijgend meeverzet.

    De noodstop telt alleen **geklets**: comments waarmee agents elkaar aan de
    praat houden. Uitgesloten:

    - `triage` (al in `count_for_item`) — automatische classificatie, geen
      discussie.
    - `kind='question'` (de expliciete vraagmodule) — de vraagmodule staat
      lós van de noodstop. Een vraag aan een mens is juist de nooduitgang
      waarmee een agent om ingrijpen vraagt; die mag de drempel niet naar het
      slot toe duwen. Antwoorden staan sinds BETON-265 inline op de vraag, dus
      die vormen geen eigen comment-rij en hoeven hier niet apart uitgesloten.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM comments c "
        "LEFT JOIN users u ON u.id = c.author_id "
        "WHERE c.item_id = ? AND (u.handle IS NULL OR u.handle != 'triage') "
        "AND c.kind != 'question'",
        (item_id,),
    ).fetchone()
    return row["n"]


def recent_duplicate(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    author_id: int | None,
    body_md: str,
    within_seconds: int = 10,
) -> sqlite3.Row | None:
    """De meest recente identieke comment van dezelfde auteur binnen het venster.

    Idempotency-vangnet (BETON-217): een double-submit (bv. key-repeat op
    Cmd+Enter, of een client-retry) plaatste dezelfde comment meermaals binnen
    milliseconden — elke kopie triggerde webhook-fanout en dus dubbele
    agent-antwoorden. Een bewuste herhaling van exact dezelfde tekst binnen
    ~10s is praktisch altijd een duplicaat, geen intentie."""
    return conn.execute(
        "SELECT * FROM comments WHERE item_id = ? AND author_id IS ? "
        "AND body_md = ? AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?) "
        "ORDER BY id DESC LIMIT 1",
        (item_id, author_id, body_md, f"-{within_seconds} seconds"),
    ).fetchone()


def get(conn: sqlite3.Connection, comment_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()


def update(conn: sqlite3.Connection, comment_id: int, body_md: str) -> sqlite3.Row:
    conn.execute(
        "UPDATE comments SET body_md = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
        (body_md, comment_id),
    )
    return conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()


def delete(conn: sqlite3.Connection, comment_id: int) -> None:
    conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))


def get_required(conn: sqlite3.Connection, comment_id: int) -> sqlite3.Row:
    """Lees een comment die door de caller als bestaande rij wordt verwacht."""
    row = get(conn, comment_id)
    if row is None:
        raise LookupError("Verwachte comment ontbreekt")
    return row
