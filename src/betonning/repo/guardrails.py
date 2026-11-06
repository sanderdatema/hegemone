"""Guardrail-repository (BETON-420): zetten/opheffen, scope en plafondtelling.

Een guardrail is kennis die niet in een regressietest past en die elke agent
hierna moet naleven. Hij hangt aan een ticket (`items.guardrail_*`) en heeft
nul of meer projectlabels als scope (`item_guardrail_labels`). Zonder scope is
hij projectbreed; dán telt hij mee in het plafond van
`models.GUARDRAIL_PROJECT_WIDE_MAX`.

Pure sqlite3, connectie als eerste arg, geen ORM — conform de andere repos.

De SQL-fragmenten uit `repo/items.py` (`GUARDRAIL_ACTIVE`, `LIVE_PROJECT`)
worden bewust pas IN de functies gedereferenced en niet in module-constanten:
`items.py` importeert deze module voor `serialize`, dus op importmoment is hij
nog maar half geïnitialiseerd.
"""

from __future__ import annotations

import sqlite3

from . import items as items_repo


def set_guardrail(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    text: str,
    review_by: str,
    set_by: int | None,
) -> None:
    """Zet (of wijzig) de guardrail van een ticket.

    Wist `guardrail_lifted_at` — opnieuw activeren na opheffen moet kunnen — en
    `guardrail_review_asked_at`: een nieuwe reviewdatum is een nieuwe reviewklok,
    en de finder in `triage_worker` gebruikt die marker als enige her-vraag-poort.

    Raakt `items.updated_at` bewust NIET (eigen UPDATE, niet via
    `items_repo.update`): een guardrail is metadata over hóé je met het ticket
    omgaat, geen inhoudelijke wijziging, en zou het ticket anders naar de top van
    "Laatst gewijzigd" duwen. Precedent: `add_label`.
    """
    conn.execute(
        "UPDATE items SET guardrail_md = ?, guardrail_review_by = ?, "
        "guardrail_set_by = ?, "
        "guardrail_set_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
        "guardrail_lifted_at = NULL, guardrail_review_asked_at = NULL "
        "WHERE id = ?",
        (text, review_by, set_by, item_id),
    )


def lift(conn: sqlite3.Connection, item_id: int) -> None:
    """Hef de guardrail op. De tekst blijft staan (historie); bezorging stopt
    meteen, want die hangt aan `GUARDRAIL_ACTIVE`. Idempotent."""
    conn.execute(
        "UPDATE items SET guardrail_lifted_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE id = ? AND guardrail_lifted_at IS NULL",
        (item_id,),
    )


def set_scope(conn: sqlite3.Connection, item_id: int, label_ids: list[int]) -> None:
    """Vervang de scope volledig (spiegelt `labels_repo.set_for_item`, maar op
    `item_guardrail_labels` — de labels van het ticket zélf blijven ongemoeid)."""
    conn.execute("DELETE FROM item_guardrail_labels WHERE item_id = ?", (item_id,))
    for lid in label_ids:
        conn.execute(
            "INSERT INTO item_guardrail_labels (item_id, label_id) VALUES (?, ?)",
            (item_id, lid),
        )


def scope_labels(conn: sqlite3.Connection, item_id: int) -> list[str]:
    """De labelnamen van de scope, gesorteerd. Leeg = projectbreed."""
    rows = conn.execute(
        "SELECT l.name FROM item_guardrail_labels g "
        "JOIN labels l ON l.id = g.label_id "
        "WHERE g.item_id = ? ORDER BY l.name",
        (item_id,),
    ).fetchall()
    return [r["name"] for r in rows]


# --- Concept-voorstellen (BETON-422) ---------------------------------------
#
# Een agent zet nooit rechtstreeks een guardrail. Zijn voorstel — nieuw zetten
# (`kind='set'`) of opheffen (`kind='lift'`) — staat als CONCEPT naast de
# actieve versie in `item_guardrail_proposals`. Tot een mens het goedkeurt
# verandert er niets aan de actieve versie: `GUARDRAIL_ACTIVE` kijkt alleen naar
# de `items.guardrail_*`-kolommen en raakt deze tabel nooit aan.
#
# Eén slot per ticket (`item_id` is PK): een nieuw voorstel overschrijft het
# openstaande. Onschadelijk, want de actieve versie blijft gelden.


def propose(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    kind: str,
    text: str | None = None,
    review_by: str | None = None,
    reason: str | None = None,
    proposed_by: int | None,
    label_ids: list[int] | None = None,
) -> None:
    """Zet (of vervang) het concept van een ticket.

    Eerst DELETE, dan INSERT: de scope-rijen hangen via een cascade aan het
    voorstel, dus zo erft een nieuw concept nooit stil de scope van het vorige.
    Raakt `items` niet aan — dus ook `items.updated_at` niet, net als
    `set_guardrail`.
    """
    delete_proposal(conn, item_id)
    conn.execute(
        "INSERT INTO item_guardrail_proposals "
        "(item_id, kind, guardrail_md, review_by, reason, proposed_by, proposed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
        (item_id, kind, text, review_by, reason, proposed_by),
    )
    for lid in label_ids or []:
        conn.execute(
            "INSERT INTO item_guardrail_proposal_labels (item_id, label_id) "
            "VALUES (?, ?)",
            (item_id, lid),
        )


def proposal(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    """Het openstaande concept van dit ticket, of None."""
    return conn.execute(
        "SELECT * FROM item_guardrail_proposals WHERE item_id = ?", (item_id,)
    ).fetchone()


def proposal_scope_labels(conn: sqlite3.Connection, item_id: int) -> list[str]:
    """De voorgestelde scope (labelnamen, gesorteerd). Leeg = projectbreed."""
    rows = conn.execute(
        "SELECT l.name FROM item_guardrail_proposal_labels g "
        "JOIN labels l ON l.id = g.label_id "
        "WHERE g.item_id = ? ORDER BY l.name",
        (item_id,),
    ).fetchall()
    return [r["name"] for r in rows]


def proposal_scope_label_ids(conn: sqlite3.Connection, item_id: int) -> list[int]:
    """De voorgestelde scope als label-ids — wat `set_scope` bij goedkeuren
    nodig heeft."""
    rows = conn.execute(
        "SELECT label_id FROM item_guardrail_proposal_labels WHERE item_id = ? "
        "ORDER BY label_id",
        (item_id,),
    ).fetchall()
    return [r["label_id"] for r in rows]


def delete_proposal(conn: sqlite3.Connection, item_id: int) -> None:
    """Wis het concept (goedgekeurd of afgewezen). De scope-rijen gaan mee via
    de cascade. Idempotent."""
    conn.execute("DELETE FROM item_guardrail_proposals WHERE item_id = ?", (item_id,))


def _no_scope() -> str:
    return (
        "NOT EXISTS (SELECT 1 FROM item_guardrail_labels g WHERE g.item_id = i.id)"
    )


def project_wide_count(conn: sqlite3.Connection, project_id: int) -> int:
    """Aantal actieve projectbrede (ongescopede) guardrails in dit project.

    Voedt het plafond. Een gearchiveerd ticket telt niet mee — dat zit in
    `GUARDRAIL_ACTIVE` — zodat archiveren de plek vrijgeeft. Een gearchiveerd
    PROJECT valt eveneens af (`LIVE_PROJECT`, BETON-413): daar valt niets meer
    te bewaken, en hetzelfde filter geldt voor de andere drie guardrail-reads."""
    row = conn.execute(
        f"""SELECT COUNT(*) AS n FROM items i
            JOIN projects p ON p.id = i.project_id
            WHERE i.project_id = ?
              AND {items_repo.LIVE_PROJECT}
              AND {items_repo.guardrail_active_sql("i")}
              AND {_no_scope()}""",
        (project_id,),
    ).fetchone()
    return int(row["n"] or 0)


def project_wide(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    """Dezelfde set als `project_wide_count`, met ref/titel/tekst/reviewdatum.

    Voedt het guardrail-blok bovenaan de wiki-context. Oudste eerst (stabiel):
    zo verandert de volgorde van het blok niet bij elke nieuwe guardrail."""
    rows = conn.execute(
        f"""SELECT p.key AS pkey, i.seq AS seq, i.title AS title,
                   i.guardrail_md AS guardrail_md,
                   i.guardrail_review_by AS review_by
            FROM items i
            JOIN projects p ON p.id = i.project_id
            WHERE i.project_id = ?
              AND {items_repo.LIVE_PROJECT}
              AND {items_repo.guardrail_active_sql("i")}
              AND {_no_scope()}
            ORDER BY i.guardrail_set_at, i.id""",
        (project_id,),
    ).fetchall()
    return [
        {
            "ref": f"{r['pkey']}-{r['seq']}",
            "title": r["title"],
            "guardrail_md": r["guardrail_md"],
            "review_by": r["review_by"],
        }
        for r in rows
    ]


def applicable_for_item(conn: sqlite3.Connection, item_id: int) -> list[dict]:
    """Actieve GESCOPEDE guardrails van andere tickets in hetzelfde project
    waarvan de scope-labels snijden met de labels van dít ticket.

    Projectbrede guardrails zitten hier bewust niet in: die krijgt de agent al
    via de wiki-context (`load_memory`), en twee keer leveren is twee keer
    betalen. Het ticket ziet zichzelf niet."""
    rows = conn.execute(
        f"""SELECT DISTINCT p.key AS pkey, i.seq AS seq, i.title AS title,
                   i.guardrail_md AS guardrail_md,
                   i.guardrail_review_by AS review_by
            FROM items i
            JOIN projects p ON p.id = i.project_id
            JOIN item_guardrail_labels g ON g.item_id = i.id
            JOIN item_labels il ON il.label_id = g.label_id
            WHERE il.item_id = ?
              AND i.id != ?
              AND i.project_id = (SELECT project_id FROM items WHERE id = ?)
              AND {items_repo.LIVE_PROJECT}
              AND {items_repo.guardrail_active_sql("i")}
            ORDER BY i.seq""",
        (item_id, item_id, item_id),
    ).fetchall()
    return [
        {
            "ref": f"{r['pkey']}-{r['seq']}",
            "title": r["title"],
            "guardrail_md": r["guardrail_md"],
            "review_by": r["review_by"],
        }
        for r in rows
    ]
