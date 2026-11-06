"""Items-repository: CRUD, ref-resolutie ("SOS-42") en server-side filtering."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable

from . import comments as comments_repo
from . import events as events_repo
from . import follows as follows_repo
from . import guardrails as guardrails_repo
from . import held_comments as held_repo
from . import item_reads as item_reads_repo
from .item_reads import _in_clause
from . import projects as projects_repo
from . import states as states_repo
from .users import handle_of
from .relations import NORMALIZE as _RELATION_NORMALIZE
from ..models import PRIORITIES, WORKLOADS  # noqa: F401 — BETON-327: één bron


def parse_ref(ref: str) -> tuple[str, int]:
    """Splits "SOS-42" in ("SOS", 42). Raise ValueError bij onzin."""
    m = re.fullmatch(r"(.+)-(\d+)", ref.strip())
    if not m:
        raise ValueError(f"Ongeldige ref: {ref!r}")
    return m.group(1), int(m.group(2))


def _last_activity_at(conn: sqlite3.Connection, item_id: int, updated_at: str) -> str:
    """Laatste activiteit op een item: `updated_at`, of een recentere comment-
    mutatie (toevoegen/bewerken telt mee via `comments.updated_at`; BETON-68).

    Bewust géén migratie/kolom: puur afgeleid zodat `items.updated_at` de
    optimistic-concurrency-token blijft (BETON-44) en comment-mutaties die
    NIET aanraken.
    """
    row = conn.execute(
        "SELECT MAX(updated_at) AS last FROM comments WHERE item_id = ?",
        (item_id,),
    ).fetchone()
    last_comment = row["last"] if row else None
    if last_comment is None:
        return updated_at
    return max(updated_at, last_comment)


def _labels_for(conn: sqlite3.Connection, item_id: int) -> list[str]:
    rows = conn.execute(
        """SELECT l.name FROM item_labels il
           JOIN labels l ON l.id = il.label_id
           WHERE il.item_id = ? ORDER BY l.name""",
        (item_id,),
    ).fetchall()
    return [r["name"] for r in rows]


def _guardrail_proposal(conn: sqlite3.Connection, item_id: int, handle) -> dict | None:
    """Het openstaande guardrail-concept (BETON-422), of None.

    Los van de actieve versie: een concept bindt niets tot een mens het
    goedkeurt, dus het mag nergens met de `guardrail_*`-velden samenvallen."""
    p = guardrails_repo.proposal(conn, item_id)
    if p is None:
        return None
    return {
        "kind": p["kind"],
        "guardrail_md": p["guardrail_md"],
        "review_by": p["review_by"],
        "reason": p["reason"],
        "scope": guardrails_repo.proposal_scope_labels(conn, item_id),
        "proposed_by": handle(p["proposed_by"]),
        "proposed_at": p["proposed_at"],
    }


# Quarantainegrens van de triage-bot (BETON-41); `triage_worker.MAX_ATTEMPTS`
# verwijst hierheen (de worker importeert deze module, niet andersom).
TRIAGE_MAX_ATTEMPTS = 3


def triage_assign_pending(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
    """Staat er een toewijzing aan triage die triage nog moet afhandelen? (BETON-478)

    Afgeleid, geen state: het item is nu aan `triage` toegewezen, loopt nog
    (niet gesloten, niet gearchiveerd), is al een keer getriaged (anders is
    `find_untriaged` de route), niet in quarantaine, en er is een toewijzing
    door een ander dan triage die nieuwer is dan `items.triage_assign_event_id`
    (BETON-287). Dezelfde voorwaarden als `triage_worker.find_assigned_to_triage`,
    zonder debounce en zonder de project/slot-poorten: voor de UI-regel en voor
    de answer-eval telt het moment van de menselijke actie, niet de pollronde."""
    triage = conn.execute("SELECT id, handle FROM users WHERE handle = 'triage'").fetchone()
    if (
        triage is None
        or row["assignee_id"] != triage["id"]
        or row["archived_at"] is not None
        or row["triaged_at"] is None
        or row["triage_attempts"] >= TRIAGE_MAX_ATTEMPTS
    ):
        return False
    grp = conn.execute(
        "SELECT grp FROM states WHERE id = ?", (row["state_id"],)
    ).fetchone() if row["state_id"] is not None else None
    if grp is not None and states_repo.is_closed_group(grp["grp"]):
        return False
    return (
        conn.execute(
            """SELECT 1 FROM events e
               WHERE e.item_id = ? AND e.type = 'item.updated'
                 AND json_extract(e.payload, '$.assignee.to') = ?
                 AND (e.actor_id IS NULL OR e.actor_id != ?)
                 AND (? IS NULL OR e.id > ?)
               LIMIT 1""",
            (
                row["id"],
                triage["handle"],
                triage["id"],
                row["triage_assign_event_id"],
                row["triage_assign_event_id"],
            ),
        ).fetchone()
        is not None
    )


def serialize(
    conn: sqlite3.Connection, row: sqlite3.Row, viewer_id: int | None = None
) -> dict:
    """Volledige representatie van een item met opgeloste namen/refs.

    ``viewer_id`` (BETON-294) bepaalt de per-user ``has_unread``-vlag. Zonder
    viewer (serialisatie buiten een request-context) is die altijd False —
    read-state is per user en zonder user niet te bepalen.
    """
    project = conn.execute(
        "SELECT key FROM projects WHERE id = ?", (row["project_id"],)
    ).fetchone()
    ref = f"{project['key']}-{row['seq']}"

    def _handle(uid: int | None) -> str | None:
        return handle_of(conn, uid)

    state = None
    if row["state_id"] is not None:
        r = conn.execute(
            "SELECT name FROM states WHERE id = ?", (row["state_id"],)
        ).fetchone()
        state = r["name"] if r else None

    parent_ref = None
    if row["parent_id"] is not None:
        pr = conn.execute(
            """SELECT p.key AS key, i.seq AS seq FROM items i
               JOIN projects p ON p.id = i.project_id WHERE i.id = ?""",
            (row["parent_id"],),
        ).fetchone()
        if pr:
            parent_ref = f"{pr['key']}-{pr['seq']}"

    milestone = None
    if row["milestone_id"] is not None:
        r = conn.execute(
            "SELECT name FROM milestones WHERE id = ?", (row["milestone_id"],)
        ).fetchone()
        milestone = r["name"] if r else None

    assignee = _handle(row["assignee_id"])
    # Alleen de volledige detailvorm leest de vorige toewijzing (BETON-470).
    previous = conn.execute(
        """SELECT json_extract(payload, '$.assignee.from') AS handle
           FROM events WHERE item_id = ? AND type = 'item.updated'
           AND json_type(payload, '$.assignee') = 'object'
           AND json_extract(payload, '$.assignee.to') = ?
           ORDER BY id DESC LIMIT 1""",
        (row["id"], assignee),
    ).fetchone() if assignee else None

    done, total = children_counts(conn, row["id"])
    return {
        "id": row["id"],
        "ref": ref,
        "project": project["key"],
        "seq": row["seq"],
        "title": row["title"],
        "description_md": row["description_md"],
        "state": state,
        "priority": row["priority"],
        # BETON-311: werklast (hoeveel tokens); leeg = nog niet geschat.
        "workload": row["workload"],
        "assignee": assignee,
        "previous_assignee": previous["handle"] if previous else None,
        "created_by": _handle(row["created_by"]),
        "parent": parent_ref,
        "milestone": milestone,
        "labels": _labels_for(conn, row["id"]),
        "children_done": done,
        "children_total": total,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_activity_at": _last_activity_at(conn, row["id"], row["updated_at"]),
        "completed_at": row["completed_at"],
        "archived_at": row["archived_at"],
        "deferred_until": row["deferred_until"],
        "due_date": row["due_date"],
        # BETON-302: noodstop. `comment_limit` gaat mee zodat een agent (en de
        # UI) kan zien hoeveel ruimte er nog is vóór het dichtklapt — anders is
        # het slot een verrassing.
        "locked_at": row["locked_at"],
        "comment_limit": row["comment_limit"],
        # BETON-338: de comment die op het slot stuitte, nog niet geplaatst.
        # Alleen hier (de drawer), bewust niet in `compact`: de kaartweergave
        # heeft genoeg aan het slotje, en `_compact_rows` is een bulk-pad dat
        # we niet met een extra query per item willen belasten.
        "held_comment": held_repo.serialize(conn, held_repo.get(conn, row["id"])),
        # BETON-218: het plan zelf zit bewust NIET in de serialisatie (kan groot
        # zijn; token-economie voor agents die get_item/list aanroepen). Alleen
        # de advertentie dat er één is; de inhoud komt via GET /items/{ref}/plan.
        "has_plan": bool(row["plan_md"]),
        # BETON-478: triage heeft een toewijzing nog niet afgehandeld ("triage
        # reageert zo"). Afgeleid, alleen in de volledige vorm.
        "triage_pending": triage_assign_pending(conn, row),
        # BETON-275: markering voor de kaart/lijst dat er een open vraag is.
        "has_open_question": conn.execute(
            "SELECT 1 FROM comments WHERE item_id = ? AND "
            + comments_repo.question_open_sql()
            + " LIMIT 1",
            (row["id"],),
        ).fetchone()
        is not None,
        # BETON-294: ongelezen activiteit voor de aanroepende user (eigen
        # activiteit telt niet mee). Bulk-variant: `_unread_bulk`.
        "has_unread": item_reads_repo.has_unread(conn, row["id"], viewer_id),
        # BETON-420: de guardrail van dít ticket. De tekst gaat hier wél
        # volledig mee (max GUARDRAIL_MAX_CHARS) — anders dan `plan_md`, dat
        # onbegrensd is en daarom een eigen endpoint kreeg. `has_guardrail`
        # draagt de drie termen van "actief" (tekst, niet opgeheven, niet
        # gearchiveerd), dus bewust NIET de `bool(row[...])`-vorm van has_plan.
        "guardrail_md": row["guardrail_md"],
        "guardrail_review_by": row["guardrail_review_by"],
        "guardrail_set_by": _handle(row["guardrail_set_by"]),
        "guardrail_set_at": row["guardrail_set_at"],
        "guardrail_lifted_at": row["guardrail_lifted_at"],
        "guardrail_scope": guardrails_repo.scope_labels(conn, row["id"]),
        "has_guardrail": bool(
            row["guardrail_md"]
            and row["guardrail_lifted_at"] is None
            and row["archived_at"] is None
        ),
        # BETON-422: het openstaande CONCEPT, los van de actieve versie — een
        # agent stelt voor, een mens keurt goed, en tot dat moment geldt de
        # actieve versie hierboven onverkort. Daarom een eigen sleutel en géén
        # status op de velden erboven: de UI moet beide tegelijk kunnen tonen.
        "guardrail_proposal": _guardrail_proposal(conn, row["id"], _handle),
        # BETON-369: volgt de aanroepende user dit item expliciet? Alleen in de
        # volledige serialisatie (de drawer heeft het nodig), niet in `compact`:
        # het bord toont geen volg-status en dat zou een query per kaart kosten.
        "is_following": follows_repo.is_following(conn, row["id"], viewer_id),
    }


def _to_compact(m: dict) -> dict:
    """Canonieke compacte projectie (18 card-velden) uit een mapping met
    dezelfde sleutels als `serialize()` — of een minimale rij-mapping met
    identieke sleutels, zoals `_compact_rows` bouwt.

    Gedeeld door `compact()` (single-item pad, o.a. de SSE-snapshot in
    `api/stream.py`) en `_compact_rows` (bulk list-pad) zodat een nieuw
    card-veld nog maar op één plek hoeft — voorheen dreven ze uit elkaar
    (BETON-320, bv. `locked`/`last_activity_at` verschillend berekend).
    """
    return {
        "ref": m["ref"],
        "title": m["title"],
        "state": m["state"],
        "priority": m["priority"],
        "workload": m.get("workload"),
        "assignee": m["assignee"],
        "labels": m["labels"],
        "children_done": m.get("children_done", 0),
        "children_total": m.get("children_total", 0),
        "deferred_until": m.get("deferred_until"),
        "due_date": m.get("due_date"),
        "milestone": m.get("milestone"),
        "archived_at": m.get("archived_at"),
        # BETON-302: in de lijst/op de kaart volstaat "staat 'ie op slot?" — het
        # tijdstip en de drempel zijn detail (die zitten in `serialize`).
        "locked": bool(m.get("locked_at")),
        # BETON-420: alleen de markering, nooit de tekst (die zit in `serialize`).
        "has_guardrail": m.get("has_guardrail", False),
        # BETON-422: ligt er een concept dat op een mens wacht? Alleen de
        # boolean — de inhoud van het voorstel hoort in `serialize`. Twee
        # bronnen, want beide paden voeden deze functie: het lijstpad levert de
        # EXISTS-kolom, het single-item-pad (`compact(serialize(...))`, o.a. de
        # SSE-snapshot) alleen het `guardrail_proposal`-blok. Zonder die tweede
        # term wist een live event de vlag die de lijst net zette.
        "has_guardrail_proposal": bool(
            m.get("has_guardrail_proposal") or m.get("guardrail_proposal")
        ),
        "created_at": m["created_at"],
        "last_activity_at": m.get("last_activity_at", m["created_at"]),
        "has_open_question": m.get("has_open_question", False),
        "has_unread": m.get("has_unread", False),
        # BETON-344: relaties op de kaart, zelfde vorm als de volledige
        # `relations.for_item` (verb → refs). Ontbreekt de sleutel (een
        # aanroeper die geen relaties heeft aangeleverd) → lege set per verb,
        # geen relatierij op de kaart.
        "relations": m.get("relations") or {t: [] for t in RELATION_VERBS},
        # BETON-344 (vervolg): "subtaak van" — zit niet in `relations` (die
        # tabel kent geen parent), komt uit `items.parent_id`. `serialize()`
        # levert dit al als "parent"; `_compact_rows` bouwt 'm zelf op uit de
        # self-join hierboven (`_COMPACT_SELECT`).
        "parent": m.get("parent"),
    }


def compact(item: dict) -> dict:
    """Compacte JSON voor list-endpoints (zoals plane.py DEFAULT_FIELDS)."""
    return _to_compact(item)


def children_counts(conn: sqlite3.Connection, parent_id: int) -> tuple[int, int]:
    """(done, total) van de levende (niet-gearchiveerde) subtaken van een item.

    Een subtaak in een closed-group state (completed/cancelled) telt als done.
    """
    row = conn.execute(
        f"""SELECT COUNT(*) AS total,
                  SUM(CASE WHEN {states_repo.state_closed_sql('st')} THEN 1 ELSE 0 END) AS done
           FROM items i LEFT JOIN states st ON st.id = i.state_id
           WHERE i.parent_id = ? AND i.archived_at IS NULL""",
        (parent_id,),
    ).fetchone()
    return int(row["done"] or 0), int(row["total"] or 0)


def _children_counts_bulk(
    conn: sqlite3.Connection, parent_ids: list[int]
) -> dict[int, tuple[int, int]]:
    """(done, total) per parent voor meerdere items in één query (voorkomt N+1)."""
    if not parent_ids:
        return {}
    placeholders = _in_clause(parent_ids)
    rows = conn.execute(
        f"""SELECT i.parent_id AS pid, COUNT(*) AS total,
                   SUM(CASE WHEN {states_repo.state_closed_sql('st')} THEN 1 ELSE 0 END) AS done
            FROM items i LEFT JOIN states st ON st.id = i.state_id
            WHERE i.parent_id IN ({placeholders}) AND i.archived_at IS NULL
            GROUP BY i.parent_id""",
        parent_ids,
    ).fetchall()
    return {r["pid"]: (int(r["done"] or 0), int(r["total"] or 0)) for r in rows}


def _last_comment_activity_bulk(
    conn: sqlite3.Connection, item_ids: list[int]
) -> dict[int, str]:
    """Laatste comment-mutatie per item (MAX van created_at/updated_at) in één query.

    Onderdeel van `last_activity_at` (BETON-68): de kaart toont de meest recente
    activiteit, óók als die een comment is (toevoegen/bewerken) i.p.v. een
    itemwijziging. Geen N+1: één gebatchte query naast labels/subtaak-counts.
    """
    if not item_ids:
        return {}
    placeholders = _in_clause(item_ids)
    rows = conn.execute(
        f"""SELECT item_id AS item_id, MAX(updated_at) AS last
            FROM comments WHERE item_id IN ({placeholders}) GROUP BY item_id""",
        item_ids,
    ).fetchall()
    return {r["item_id"]: r["last"] for r in rows}


def _open_questions_bulk(conn: sqlite3.Connection, item_ids: list[int]) -> set[int]:
    """Item-id's met minstens één onbeantwoorde vraag-comment (BETON-275).

    Eén gebatchte query zodat de board-/lijstkaart een open-vraag-markering kan
    tonen zonder N+1."""
    if not item_ids:
        return set()
    placeholders = _in_clause(item_ids)
    rows = conn.execute(
        f"""SELECT DISTINCT item_id AS item_id FROM comments
            WHERE {comments_repo.question_open_sql()}
              AND item_id IN ({placeholders})""",
        item_ids,
    ).fetchall()
    return {r["item_id"] for r in rows}


# User-facing verba (RELATION_VERBS) + de twee richtingskaarten, afgeleid van
# relations.NORMALIZE (dezelfde bron als de single-item `for_item`) zodat er
# maar één plek is die weet welke verba er bestaan.
RELATION_VERBS = tuple(_RELATION_NORMALIZE)
_OUTGOING_VERB = {stored: verb for verb, (stored, rev) in _RELATION_NORMALIZE.items() if not rev}
# relates_to is symmetrisch — geen aparte rev-vorm in NORMALIZE, dus zonder de
# expliciete regel hieronder zou een inkomende relates_to-rij geen verb vinden.
_INCOMING_VERB = {stored: verb for verb, (stored, rev) in _RELATION_NORMALIZE.items() if rev}
_INCOMING_VERB["relates_to"] = "relates_to"


def _relations_bulk(conn: sqlite3.Connection, item_ids: list[int]) -> dict[int, dict[str, list[str]]]:
    """Relaties per item voor de kaart (BETON-344), zelfde vorm als
    `relations.for_item` (dict per user-facing verb → refs) maar gebatcht over
    meerdere items in twee query's i.p.v. één `for_item`-call (+ een
    ref-lookup per relatie) per item — voorkomt N+1 op het board/lijst-pad.
    """
    if not item_ids:
        return {}
    placeholders = _in_clause(item_ids)
    out: dict[int, dict[str, list[str]]] = {}
    # Uitgaand: één van de meegegeven items is de bron (r.item_id).
    for r in conn.execute(
        f"""SELECT r.item_id AS src, r.type AS type, p.key AS pkey, i.seq AS seq
            FROM relations r
            JOIN items i ON i.id = r.related_item_id
            JOIN projects p ON p.id = i.project_id
            WHERE r.item_id IN ({placeholders})""",
        item_ids,
    ).fetchall():
        bucket = out.setdefault(r["src"], {t: [] for t in RELATION_VERBS})
        bucket[_OUTGOING_VERB[r["type"]]].append(f"{r['pkey']}-{r['seq']}")
    # Inkomend: één van de meegegeven items is het doel (r.related_item_id).
    for r in conn.execute(
        f"""SELECT r.related_item_id AS src, r.type AS type, p.key AS pkey, i.seq AS seq
            FROM relations r
            JOIN items i ON i.id = r.item_id
            JOIN projects p ON p.id = i.project_id
            WHERE r.related_item_id IN ({placeholders})""",
        item_ids,
    ).fetchall():
        bucket = out.setdefault(r["src"], {t: [] for t in RELATION_VERBS})
        bucket[_INCOMING_VERB[r["type"]]].append(f"{r['pkey']}-{r['seq']}")
    # Dedupe + stabiel sorteren, zelfde defensieve stap als `for_item` (legacy
    # symmetrische paren vóór migratie 009 konden in beide richtingen staan).
    for bucket in out.values():
        for key, refs in bucket.items():
            bucket[key] = sorted(dict.fromkeys(refs))
    return out


def _labels_bulk(conn: sqlite3.Connection, item_ids: list[int]) -> dict[int, list[str]]:
    """Alle labels voor meerdere items in één query (voorkomt N+1)."""
    if not item_ids:
        return {}
    placeholders = _in_clause(item_ids)
    rows = conn.execute(
        f"""SELECT il.item_id AS item_id, l.name AS name FROM item_labels il
            JOIN labels l ON l.id = il.label_id
            WHERE il.item_id IN ({placeholders}) ORDER BY l.name""",
        item_ids,
    ).fetchall()
    out: dict[int, list[str]] = {}
    for r in rows:
        out.setdefault(r["item_id"], []).append(r["name"])
    return out


def _compact_rows(
    conn: sqlite3.Connection, rows: list[sqlite3.Row], viewer_id: int | None = None
) -> list[dict]:
    """Bouw compacte dicts uit rijen met aliassen (pkey/seq/state/assignee).

    Labels worden in één extra query gebatcht i.p.v. per item — dus twee query's
    voor een hele lijst i.p.v. 4–5 per item. `last_activity_at` (BETON-68) idem:
    één gebatchte MAX(comments.updated_at)-query, gecombineerd met de al
    aanwezige `items.updated_at` per rij. `has_unread` (BETON-294) volgt hetzelfde
    patroon: gebatcht per lijst, nooit een query per item. Relaties (BETON-344)
    idem via `_relations_bulk` — twee query's voor de hele lijst i.p.v. een
    `for_item`-call (+ ref-lookup) per item.
    """
    ids = [r["id"] for r in rows]
    labels_by_item = _labels_bulk(conn, ids)
    counts_by_item = _children_counts_bulk(conn, ids)
    last_comment_by_item = _last_comment_activity_bulk(conn, ids)
    open_q_items = _open_questions_bulk(conn, ids)
    unread_items = item_reads_repo.unread_bulk(conn, ids, viewer_id)
    relations_by_item = _relations_bulk(conn, ids)
    return [
        _to_compact(
            {
                "ref": f"{r['pkey']}-{r['seq']}",
                "title": r["title"],
                "state": r["state"],
                "priority": r["priority"],
                "workload": r["workload"],
                "assignee": r["assignee"],
                "labels": labels_by_item.get(r["id"], []),
                "children_done": counts_by_item.get(r["id"], (0, 0))[0],
                "children_total": counts_by_item.get(r["id"], (0, 0))[1],
                "deferred_until": r["deferred_until"],
                "due_date": r["due_date"],
                "milestone": r["milestone"],
                "archived_at": r["archived_at"],
                "locked_at": r["locked_at"],
                "has_guardrail": bool(r["has_guardrail"]),
                "has_guardrail_proposal": bool(r["has_guardrail_proposal"]),
                "created_at": r["created_at"],
                "last_activity_at": max(
                    r["updated_at"], last_comment_by_item.get(r["id"], r["updated_at"])
                ),
                "has_open_question": r["id"] in open_q_items,
                "has_unread": r["id"] in unread_items,
                "relations": relations_by_item.get(r["id"]),
                "parent": f"{r['pkey']}-{r['parent_seq']}" if r["parent_seq"] is not None else None,
            }
        )
        for r in rows
    ]


def list_assigned_open(
    conn: sqlite3.Connection,
    user_ids: int | list[int],
    *,
    viewer_id: int | None = None,
) -> list[dict]:
    """Compacte, cross-project lijst van open items van één of meer assignees
    (BETON-55). Meerdere ids (BETON-207): een coding-agent ziet naast z'n eigen
    tickets ook de gedeelde `coding-agent`-queue (zie ``users.visible_queue_ids``).

    "Open" = niet gearchiveerd en niet in een closed-group state
    (completed/cancelled). Gesorteerd op project-key + seq. Herbruikt
    ``_compact_rows`` (N+1-vrij op labels/subtaken).

    BETON-413: items in een gearchiveerd project vallen af (``LIVE_PROJECT``) —
    dit is de "wat ligt er voor mij"-sweep, en werk in een gearchiveerd project
    ligt er niet meer. Op de draaiende installatie was 97 van de 129 items op
    de claude-key van een gearchiveerd project."""
    ids = [user_ids] if isinstance(user_ids, int) else list(user_ids)
    if not ids:
        return []
    placeholders = _in_clause(ids)
    rows = conn.execute(
        f"""SELECT i.id AS id, i.seq AS seq, i.title AS title, i.priority AS priority,
                  i.workload AS workload,
                  ({guardrail_active_sql("i")}) AS has_guardrail,
                  ({GUARDRAIL_PROPOSAL_EXISTS.format(a="i")}) AS has_guardrail_proposal,
                  i.created_at AS created_at, i.updated_at AS updated_at,
                  i.deferred_until AS deferred_until,
                  i.due_date AS due_date, i.archived_at AS archived_at,
                  i.locked_at AS locked_at,
                  p.key AS pkey, s.name AS state, m.name AS milestone,
                  a.handle AS assignee, parent_i.seq AS parent_seq
           FROM items i
           JOIN projects p ON p.id = i.project_id
           LEFT JOIN states s ON s.id = i.state_id
           LEFT JOIN milestones m ON m.id = i.milestone_id
           LEFT JOIN users a ON a.id = i.assignee_id
           LEFT JOIN items parent_i ON parent_i.id = i.parent_id
           WHERE i.assignee_id IN ({placeholders}) AND i.archived_at IS NULL
             AND {LIVE_PROJECT}
             AND {states_repo.state_open_sql('s')}
           ORDER BY p.key, i.seq""",
        ids,
    ).fetchall()
    return _compact_rows(conn, rows, viewer_id)


def get(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()


def get_by_plane_id(conn: sqlite3.Connection, plane_id: str) -> sqlite3.Row | None:
    """Voor idempotente migratie: zoek een item op zijn Plane-UUID."""
    return conn.execute(
        "SELECT * FROM items WHERE plane_id = ?", (plane_id,)
    ).fetchone()


def get_by_ref(conn: sqlite3.Connection, ref: str) -> sqlite3.Row | None:
    """Zoek item op "KEY-seq". None als project of item niet bestaat."""
    key, seq = parse_ref(ref)
    project = projects_repo.get_by_key(conn, key)
    if project is None:
        return None
    return conn.execute(
        "SELECT * FROM items WHERE project_id = ? AND seq = ?",
        (project["id"], seq),
    ).fetchone()


def create(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    title: str,
    description_md: str = "",
    state_id: int | None = None,
    priority: str = "none",
    workload: str | None = None,
    assignee_id: int | None = None,
    created_by: int | None = None,
    parent_id: int | None = None,
    milestone_id: int | None = None,
    due_date: str | None = None,
    deferred_until: str | None = None,
    plane_id: str | None = None,
    seq: int | None = None,
    plan_md: str | None = None,
) -> sqlite3.Row:
    if seq is None:
        seq = projects_repo.next_seq(conn, project_id)
    if state_id is None:
        default = conn.execute(
            "SELECT id FROM states WHERE project_id = ? ORDER BY is_default DESC, sort_order LIMIT 1",
            (project_id,),
        ).fetchone()
        state_id = default["id"] if default else None
    cur = conn.execute(
        """INSERT INTO items
           (project_id, seq, title, description_md, state_id, priority, workload,
            assignee_id, created_by, parent_id, milestone_id, due_date,
            deferred_until, plane_id, plan_md)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            project_id,
            seq,
            title,
            description_md,
            state_id,
            priority,
            workload,
            assignee_id,
            created_by,
            parent_id,
            milestone_id,
            due_date,
            deferred_until,
            plane_id,
            plan_md,
        ),
    )
    assert cur.lastrowid is not None
    return get_required(conn, cur.lastrowid)


# Kolommen die via PATCH gezet mogen worden (naam → kolom).
#
# `guardrail_md` (en de andere guardrail-kolommen) staan hier BEWUST niet in
# (BETON-420): zetten en opheffen is mens-only via `POST /items/{ref}/guardrail`
# (`current_human`). Zou hij hier "voor de volledigheid" bij komen, dan zet elke
# `current_user` — dus ook een agent — hem alsnog via PATCH en is die poort er
# niet meer. `tests/test_guardrail.py` bewaakt dat.
_PATCHABLE = {
    "title": "title",
    "description_md": "description_md",
    "state_id": "state_id",
    "priority": "priority",
    "workload": "workload",
    "assignee_id": "assignee_id",
    "parent_id": "parent_id",
    "milestone_id": "milestone_id",
    "deferred_until": "deferred_until",
    "due_date": "due_date",
    "deferred_from_state_id": "deferred_from_state_id",
    "plan_md": "plan_md",
}


def update(conn: sqlite3.Connection, item_id: int, fields: dict) -> sqlite3.Row | None:
    """Partiële update. Onbekende velden worden genegeerd. Zet updated_at."""
    sets = []
    values = []
    for name, value in fields.items():
        col = _PATCHABLE.get(name)
        if col is None:
            continue
        sets.append(f"{col} = ?")
        values.append(value)

    # completed_at bijwerken als de state naar een 'completed'-groep gaat.
    if "state_id" in fields and fields["state_id"] is not None:
        grp = conn.execute(
            "SELECT grp FROM states WHERE id = ?", (fields["state_id"],)
        ).fetchone()
        if grp and grp["grp"] == "completed":
            sets.append("completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
        else:
            sets.append("completed_at = NULL")

    if not sets:
        return get(conn, item_id)

    sets.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    values.append(item_id)
    conn.execute(f"UPDATE items SET {', '.join(sets)} WHERE id = ?", values)
    return get(conn, item_id)


def _fts_query(q: str) -> str | None:
    """Bouw een veilige FTS5 prefix-query uit vrije tekst (woorddeel-match)."""
    tokens = re.findall(r"\w+", q)
    if not tokens:
        return None
    return " ".join(f'"{t}"*' for t in tokens)


# Default-cap voor de substring-fallback als de caller geen limit meegeeft.
_SUBSTRING_DEFAULT_LIMIT = 50


def _like_escape(word: str) -> str:
    """Escape LIKE-wildcards (`%`/`_`) zodat een woord-token nooit als patroon
    werkt — een letterlijke substring-match, geen verrassingen bij bv. een
    underscore in de zoekterm."""
    return word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _substring_conditions(q: str) -> tuple[list[str], list[str]] | None:
    """Bouw AND-gecombineerde LIKE-condities voor een echte substring-fallback
    (BETON-230): elk woord-token moet letterlijk voorkomen in titel óf
    omschrijving (case-insensitief). Vervangt de vroegere trigram-fuzzy-fallback
    (BETON-8) — die matchte op gedeelde trigrams, waardoor onzin-zoektermen
    (bv. "poepie") toch treffers gaven omdat vrijwel elk drieletter-fragment
    ergens in een grote itemset voorkomt. Substring-matching blijft wél
    mid-word-zoeken ondersteunen (bv. "onning" in "Betonning"), maar geeft geen
    losse typo-tolerantie meer.
    """
    tokens = re.findall(r"\w+", q.lower())
    if not tokens:
        return None
    conditions = []
    params: list[str] = []
    for token in tokens:
        pattern = f"%{_like_escape(token)}%"
        conditions.append(
            "(LOWER(items.title) LIKE ? ESCAPE '\\' "
            "OR LOWER(items.description_md) LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern])
    return conditions, params


# Cross-project poort (BETON-413): een read die over ÁLLE projecten sweept laat
# gearchiveerde projecten weg — dezelfde regel die `repo/overview.py` al in zijn
# rollups hanteert. Een read die één project expliciet noemt (`get`, de
# project-lijst, `events.list_for_project`) filtert hier NIET op: anders wordt
# archiveren eenrichtingsverkeer en is de historie niet meer te lezen.
# Als constante zodat een volgende cross-project query hem niet stil vergeet;
# de alias `p` is in al die query's al de `projects`-join.
LIVE_PROJECT = "p.archived_at IS NULL"

# Een guardrail (BETON-420) is ACTIEF zolang er tekst staat, hij niet opgeheven
# is en het ticket niet gearchiveerd. Die derde term is bewust: archiveren geeft
# de plek in het plafond van GUARDRAIL_PROJECT_WIDE_MAX vrij in plaats van hem
# door een dood ticket te laten bezetten. Eén definitie, overal hergebruikt —
# repo, endpoints, wiki-contextblok en de review-poll-query.
GUARDRAIL_ACTIVE = (
    "{a}.guardrail_md IS NOT NULL AND {a}.guardrail_lifted_at IS NULL "
    "AND {a}.archived_at IS NULL"
)


# BETON-422: ligt er een openstaand CONCEPT op dit ticket? Bewust een eigen
# fragment naast `GUARDRAIL_ACTIVE` en niet erin verweven: een concept bindt
# niets: het mag bezorging, plafondtelling en de kaartmarkering nooit raken.
GUARDRAIL_PROPOSAL_EXISTS = (
    "EXISTS (SELECT 1 FROM item_guardrail_proposals gp WHERE gp.item_id = {a}.id)"
)


def guardrail_active_sql(alias: str = "items") -> str:
    """Het `GUARDRAIL_ACTIVE`-fragment met de tabel-alias van de aanroeper."""
    return GUARDRAIL_ACTIVE.format(a=alias)

# Selecteert precies de kolommen die _compact_rows nodig heeft, met aliassen
# voor state/assignee/project zodat er geen per-item vervolgquery's nodig zijn.
# `parent_seq` (BETON-344): de parent-relatie zit niet in de `relations`-tabel
# maar in `items.parent_id` zelf — vandaar een losse self-join i.p.v. iets voor
# `_relations_bulk`. Altijd hetzelfde project als het kind (cross-project
# parent is een 400 bij het zetten, api/items.py:_resolve_parent_id), dus geen
# aparte project-key-lookup nodig: `pkey` geldt voor beide.
_COMPACT_SELECT = (
    "SELECT DISTINCT items.id AS id, items.seq AS seq, items.title AS title, "
    # BETON-420: op de kaart alleen de boolean, berekend uit de item-rij zelf —
    # nul extra query's, geen bulk-helper nodig. De tekst hoort niet in het
    # list-pad.
    f"({guardrail_active_sql('items')}) AS has_guardrail, "
    # BETON-422: idem voor het openstaande concept — een EXISTS in dezelfde
    # SELECT, dus nul extra query's per kaart.
    f"({GUARDRAIL_PROPOSAL_EXISTS.format(a='items')}) AS has_guardrail_proposal, "
    "items.priority AS priority, items.workload AS workload, "
    "items.created_at AS created_at, "
    "items.updated_at AS updated_at, "
    "items.archived_at AS archived_at, items.locked_at AS locked_at, "
    "items.deferred_until AS deferred_until, items.due_date AS due_date, "
    "p.key AS pkey, st.name AS state, ms.name AS milestone, "
    "u.handle AS assignee, parent_i.seq AS parent_seq FROM items "
    "JOIN projects p ON p.id = items.project_id "
    "LEFT JOIN states st ON st.id = items.state_id "
    "LEFT JOIN milestones ms ON ms.id = items.milestone_id "
    "LEFT JOIN users u ON u.id = items.assignee_id "
    "LEFT JOIN items parent_i ON parent_i.id = items.parent_id"
)

# Zelfde MAX-expressie als elders (_compact_rows / triage_worker._LAST_ACTIVITY_SQL):
# de laatste comment telt óók mee, niet alleen items.updated_at (comments raken
# die kolom niet aan).
_LAST_ACTIVITY_EXPR = (
    "MAX(items.updated_at, COALESCE("
    "(SELECT MAX(c2.updated_at) FROM comments c2 WHERE c2.item_id = items.id), "
    "items.updated_at))"
)

# Zelfde SELECT als _COMPACT_SELECT, plus de drie kolommen die de
# closed_limit-windowing (BETON-359) nodig heeft: `state_id` (PARTITION BY —
# een state-NAAM is niet uniek genoeg als twee projecten toevallig gelijk
# heten, `state_id` is dat wel), `state_closed` (COALESCE zodat een item
# zonder state — NULL — als "open" telt, niet als gesloten) en
# `last_activity` (de ordening binnen elke partitie).
_CLOSED_LIMIT_SELECT = _COMPACT_SELECT.replace(
    "SELECT DISTINCT items.id AS id,",
    "SELECT DISTINCT items.id AS id, items.state_id AS state_id, "
    f"COALESCE(st.closed, 0) AS state_closed, {_LAST_ACTIVITY_EXPR} AS last_activity,",
    1,
)


def _wrap_closed_limit(select_where_sql: str, params: list, closed_limit: int) -> tuple[str, list]:
    """Wrap een kale ``SELECT ... WHERE ...``-string (gebouwd op
    `_CLOSED_LIMIT_SELECT`) met de closed-state-windowing: per gesloten state
    (`state_closed`) blijven alleen de nieuwste `closed_limit` rijen over (naar
    `last_activity`); open states — en items zonder state — blijven ongemoeid.

    Twee extra lagen: een window-function-alias mag niet in de WHERE van
    dezelfde query staan (SQLite, net als de meeste SQL-dialecten) — de
    binnenste laag berekent `rn`, de buitenste filtert erop. De aanroeper
    plakt zelf nog ORDER BY/LIMIT/OFFSET achter het resultaat (kolomnamen
    overleven `SELECT *` door een subquery, dus `seq`/`id`/… blijven bereikbaar).
    """
    with_rn = (
        "SELECT w1.*, ROW_NUMBER() OVER ("
        "PARTITION BY w1.state_id ORDER BY w1.last_activity DESC"
        f") AS rn FROM ({select_where_sql}) w1"
    )
    filtered = f"SELECT * FROM ({with_rn}) w2 WHERE w2.state_closed = 0 OR w2.rn <= ?"
    return filtered, [*params, closed_limit]


def _exact_then_substring(
    rows: list[sqlite3.Row],
    *,
    try_substring: bool,
    run_substring: Callable[[], list[sqlite3.Row]],
) -> list[sqlite3.Row]:
    """Gedeelde exact-dan-substring-fallback voor `list_items`/`search`.

    Levert de exacte FTS-query (`rows`) niets op, dan pas de substring-LIKE-query
    uitvoeren (`run_substring`, lazy zodat hij niet nodeloos draait). `try_substring`
    laat de aanroeper de voorwaarde bepalen waaronder de fallback zinvol is
    (bv. alleen als er een tekst-query is).
    """
    if not rows and try_substring:
        return run_substring()
    return rows


def _parse_project_ref_or_seq(q: str) -> tuple[str | None, int] | None:
    """ "BETON-187" → ("BETON", 187); "187" → (None, 187); anders None (geen
    ref/seq-achtige query, de FTS-tekstmatch moet 'm oplossen)."""
    qs = q.strip()
    try:
        key, seq = parse_ref(qs)
        return key, seq
    except ValueError:
        if qs.isdigit():
            return None, int(qs)
        return None


def list_items(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    state: str | None = None,
    priority: str | None = None,
    workload: str | None = None,
    label: str | None = None,
    assignee: str | None = None,
    milestone: str | None = None,
    q: str | None = None,
    due_before: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    closed_limit: int | None = None,
    include_archived: bool = False,
    viewer_id: int | None = None,
) -> list[dict]:
    """Server-side gefilterde, compacte lijst. Alle filters zijn AND-gecombineerd.

    Bij een tekst-query (`q`) wordt eerst geprobeerd of het op een ref/ticketnummer
    lijkt ("BETON-187" of enkel "187", BETON-187): bij een match binnen dit project
    gaat die vóór en bypast de tekst-match zelf (een puur nummer staat immers zelden
    letterlijk in titel/omschrijving) — de overige filters (state/label/assignee/
    milestone/priority/due_before) blijven wel gelden. Levert dat niets op, dan valt
    de zoek terug op exact/prefix (items_fts); levert ook dát niets op, dan een
    letterlijke substring-fallback (LIKE op titel/omschrijving, BETON-230) — geen
    losse fuzzy-/typo-matching meer (dat gaf ruis: zie BETON-230).

    `closed_limit` (BETON-359): standaard `None` = ongewijzigd gedrag (élke
    bestaande aanroeper — UI, MCP `list_items`, REST — krijgt zonder dit
    argument exact wat hij al kreeg). Gezet, dan houdt élke state met
    `closed=1` alleen zijn nieuwste `closed_limit` items over (naar
    last-activity); open states en items zonder state blijven volledig.
    Bedoeld voor grote projecten waar een "Done"-kolom met honderden oude
    items het bord vertraagt. `offset` (samen met `limit`) is losse paginering
    ("toon meer" op één kolom) en werkt onafhankelijk van `closed_limit`.
    """

    def base_where() -> tuple[list[str], list[str], list]:
        """JOIN-fragmenten, WHERE-clausules en params voor alle filters behalve
        de tekst/ref-query zelf — gedeeld door het ref-pad en het FTS/substring-pad."""
        sql: list[str] = []
        where = ["items.project_id = ?"]
        params: list = [project_id]

        if not include_archived:
            where.append("items.archived_at IS NULL")
        if state is not None:
            # Case-insensitief filteren (BETON-35): `todo` matcht `Todo`/`TODO`.
            where.append("st.name = ? COLLATE NOCASE")
            params.append(state)
        if assignee is not None:
            where.append("u.handle = ? COLLATE NOCASE")
            params.append(assignee)
        if milestone is not None:
            where.append("ms.name = ? COLLATE NOCASE")
            params.append(milestone)
        if label is not None:
            sql.append("JOIN item_labels il ON il.item_id = items.id")
            sql.append("JOIN labels lbl ON lbl.id = il.label_id")
            where.append("lbl.name = ? COLLATE NOCASE")
            params.append(label)
        if priority is not None:
            where.append("items.priority = ?")
            params.append(priority)
        if workload is not None:
            where.append("items.workload = ?")
            params.append(workload)
        if due_before is not None:
            # ISO-datums vergelijken lexicografisch; <= zodat de grensdatum meetelt.
            where.append("items.due_date IS NOT NULL AND items.due_date <= ?")
            params.append(due_before)
        return sql, where, params

    def finish(select: str, sql: list[str], where: list[str], params: list) -> list[sqlite3.Row]:
        """Plak SELECT+joins+WHERE dicht en voeg de closed_limit-windowing
        (optioneel) + ORDER BY + LIMIT/OFFSET toe. Zonder `closed_limit`
        ongewijzigd: `items.seq DESC` op de rauwe SELECT, exact het oude
        gedrag. Mét `closed_limit`: eerst wrappen (`_wrap_closed_limit`,
        levert kale kolomnamen op — geen `items.`-alias meer bereikbaar),
        dus `ORDER BY seq DESC` zonder prefix."""
        select_where = " ".join([select, *sql, "WHERE " + " AND ".join(where)])
        if closed_limit is not None:
            select_where, params = _wrap_closed_limit(select_where, params, closed_limit)
            final_sql = select_where + " ORDER BY seq DESC"
        else:
            final_sql = select_where + " ORDER BY items.seq DESC"
        if limit is not None:
            final_sql += " LIMIT ?"
            params = [*params, limit]
        if offset is not None:
            if limit is None:
                # SQLite eist een LIMIT vóór OFFSET; -1 = "geen grens".
                final_sql += " LIMIT -1"
            final_sql += " OFFSET ?"
            params = [*params, offset]
        return conn.execute(final_sql, params).fetchall()

    def run(q_table: str, q_match: str | None) -> list[sqlite3.Row]:
        extra_sql, where, params = base_where()
        select = _CLOSED_LIMIT_SELECT if closed_limit is not None else _COMPACT_SELECT
        sql = list(extra_sql)
        if q is not None:
            if q_match is not None:
                sql.append(f"JOIN {q_table} ON {q_table}.rowid = items.id")
                where.append(f"{q_table} MATCH ?")
                params.append(q_match)
            else:
                # Geen bruikbare tokens → geen resultaten.
                where.append("1 = 0")
        return finish(select, sql, where, params)

    def run_substring() -> list[sqlite3.Row]:
        extra_sql, where, params = base_where()
        select = _CLOSED_LIMIT_SELECT if closed_limit is not None else _COMPACT_SELECT
        sql = list(extra_sql)
        cond = _substring_conditions(q) if q is not None else None
        if cond is None:
            where.append("1 = 0")
        else:
            conditions, cparams = cond
            where.extend(conditions)
            params.extend(cparams)
        return finish(select, sql, where, params)

    if q is not None:
        ref_match = _parse_project_ref_or_seq(q)
        if ref_match is not None:
            key, seq = ref_match
            extra_sql, where, params = base_where()
            if key is not None:
                where.append("p.key = ? COLLATE NOCASE")
                params.append(key)
            where.append("items.seq = ?")
            params.append(seq)
            sql = [_COMPACT_SELECT, *extra_sql]
            sql.append("WHERE " + " AND ".join(where))
            sql.append("ORDER BY items.seq DESC")
            if limit is not None:
                sql.append("LIMIT ?")
                params.append(limit)
            ref_rows = conn.execute(" ".join(sql), params).fetchall()
            if ref_rows:
                return _compact_rows(conn, ref_rows, viewer_id)

    rows = run("items_fts", _fts_query(q) if q is not None else None)
    rows = _exact_then_substring(
        rows,
        try_substring=q is not None,
        run_substring=run_substring,
    )
    return _compact_rows(conn, rows, viewer_id)


def state_counts(
    conn: sqlite3.Connection, project_id: int, *, include_archived: bool = False
) -> dict[str, int]:
    """Aantal items per state-naam voor één project (BETON-359) — de UI
    gebruikt dit om te weten of een begrensde (`closed_limit`) kolom méér
    items heeft dan er zijn opgehaald ("toon meer (N)"). Losse, lichte route
    i.p.v. een veld in de items-lijst zelf: makkelijker te cachen en de
    items-call zelf blijft ongewijzigd van vorm. Items zonder state (of in
    een archiefstate zonder naam) tellen niet mee — de UI kent alleen
    kolommen met een echte state-naam."""
    where = ["items.project_id = ?", "items.state_id IS NOT NULL"]
    params: list = [project_id]
    if not include_archived:
        where.append("items.archived_at IS NULL")
    rows = conn.execute(
        "SELECT st.name AS name, COUNT(*) AS n FROM items "
        "JOIN states st ON st.id = items.state_id "
        f"WHERE {' AND '.join(where)} GROUP BY st.name",
        params,
    ).fetchall()
    return {r["name"]: r["n"] for r in rows}


def search(
    conn: sqlite3.Connection,
    q: str,
    *,
    limit: int | None = None,
    include_archived: bool = False,
    viewer_id: int | None = None,
) -> list[dict]:
    """FTS5-zoek over alle projecten (woorddeel-match op titel + description).

    Ref-first: als de query op een ticketnummer lijkt (``"BETON-143"`` of
    enkel ``"143"``) worden de ref-treffers bovenaan gezet (BETON-143). Daarna
    exact-first FTS: prefix-match (items_fts, hoge precisie, op rank). Levert
    dat niets op, dan een letterlijke substring-fallback (LIKE op titel/
    omschrijving, BETON-230) — geen losse fuzzy-/typo-matching meer: die trigram-
    fallback (BETON-8) matchte op gedeelde 3-letter-fragmenten, waardoor ook
    onzin-zoektermen treffers gaven omdat vrijwel elk fragment ergens voorkomt.

    Daarachter komen de comment-treffers (BETON-370, ``comments_fts``): items
    waarvan alleen een reactie de zoekterm bevat, met ``matched_in="comment"``
    en het ``comment_id`` van de best scorende reactie. Item-treffers dragen
    ``matched_in="item"``. De substring-fallback blijft item-only.

    BETON-413: items in een gearchiveerd project vallen af, meelopend met de
    bestaande ``include_archived``-vlag (één schakelaar, geen tweede opt-in) —
    in alle vier takken: FTS, substring-fallback, comment-treffers en de kale
    nummer-vorm van de ref-zoek. De volledige ref ("TOR-42") is de uitzondering:
    die noemt zijn project zelf en is dus een gerichte lookup.
    """

    def run(q_table: str, q_match: str | None, cap: int | None) -> list[sqlite3.Row]:
        if q_match is None:
            return []
        sql = [
            _COMPACT_SELECT,
            f"JOIN {q_table} ON {q_table}.rowid = items.id",
            f"WHERE {q_table} MATCH ?",
        ]
        params: list = [q_match]
        if not include_archived:
            sql.append(f"AND items.archived_at IS NULL AND {LIVE_PROJECT}")
        sql.append("ORDER BY rank")
        if cap is not None:
            sql.append("LIMIT ?")
            params.append(cap)
        return conn.execute(" ".join(sql), params).fetchall()

    def run_substring(cap: int | None) -> list[sqlite3.Row]:
        cond = _substring_conditions(q)
        if cond is None:
            return []
        conditions, substring_params = cond
        params: list[str | int] = list(substring_params)
        sql = [_COMPACT_SELECT, "WHERE", " AND ".join(conditions)]
        if not include_archived:
            sql.append(f"AND items.archived_at IS NULL AND {LIVE_PROJECT}")
        sql.append("ORDER BY items.seq DESC")
        if cap is not None:
            sql.append("LIMIT ?")
            params = [*params, cap]
        return conn.execute(" ".join(sql), params).fetchall()

    # Ref-match (BETON-143): ticketnummer gaat voor op tekst-zoek.
    ref_rows = _ref_search(conn, q, include_archived=include_archived)
    fts_rows = run("items_fts", _fts_query(q), limit)
    # Substring-fallback heeft een langere staart dan de exacte FTS-prefix-match;
    # cap standaard zodat alleen een beperkte set terugkomt.
    fts_rows = _exact_then_substring(
        fts_rows,
        try_substring=True,
        run_substring=lambda: run_substring(limit or _SUBSTRING_DEFAULT_LIMIT),
    )
    item_rows = _dedup_rows(ref_rows + fts_rows)
    results = _compact_rows(conn, item_rows, viewer_id)
    for d in results:
        d["matched_in"] = "item"

    # Comment-treffers (BETON-370) komen ná de item-treffers en alleen voor items
    # die nog niet op titel/omschrijving gevonden zijn — een item-treffer is
    # sterker dan een reactie-treffer. `limit` telt over het samengevoegde
    # resultaat, dus de comment-zoek krijgt het restbudget.
    remaining = None if limit is None else max(0, limit - len(item_rows))
    if remaining != 0:
        seen_ids = {r["id"] for r in item_rows}
        hits = [
            (item_id, comment_id)
            for item_id, comment_id in _comment_search(
                conn, q, include_archived=include_archived, limit=None
            )
            if item_id not in seen_ids
        ]
        if remaining is not None:
            hits = hits[:remaining]
        if hits:
            by_id = {r["id"]: r for r in _rows_by_ids(conn, [i for i, _ in hits])}
            comment_of = dict(hits)
            rows = [by_id[i] for i, _ in hits if i in by_id]
            for d, r in zip(_compact_rows(conn, rows, viewer_id), rows):
                d["matched_in"] = "comment"
                d["comment_id"] = comment_of[r["id"]]
                results.append(d)
    return results


def _rows_by_ids(conn: sqlite3.Connection, ids: list[int]) -> list[sqlite3.Row]:
    """Compacte rijen (``_COMPACT_SELECT``-vorm) voor een lijst item-ids."""
    if not ids:
        return []
    sql = f"{_COMPACT_SELECT} WHERE items.id IN ({_in_clause(ids)})"
    return conn.execute(sql, ids).fetchall()


def _comment_search(
    conn: sqlite3.Connection,
    q: str,
    *,
    include_archived: bool = False,
    limit: int | None = None,
) -> list[tuple[int, int]]:
    """FTS5-zoek over comments (BETON-370) → ``[(item_id, comment_id), …]``.

    Eén rij per item: de best scorende comment wint (``ORDER BY rank`` +
    dedup op item_id). Gearchiveerde items vallen af tenzij gevraagd. Bewust
    een aparte, smalle query: de compacte item-rijen worden daarna in één keer
    opgehaald (``_rows_by_ids``), zodat de rank-volgorde en de bestaande
    ``_COMPACT_SELECT``-vorm los van elkaar blijven.
    """
    match = _fts_query(q)
    if match is None:
        return []
    sql = [
        "SELECT comments.item_id AS item_id, comments.id AS comment_id",
        "FROM comments_fts",
        "JOIN comments ON comments.id = comments_fts.rowid",
        "JOIN items ON items.id = comments.item_id",
        "JOIN projects p ON p.id = items.project_id",
        "WHERE comments_fts MATCH ?",
    ]
    if not include_archived:
        sql.append(f"AND items.archived_at IS NULL AND {LIVE_PROJECT}")
    sql.append("ORDER BY rank")
    out: list[tuple[int, int]] = []
    seen: set[int] = set()
    for r in conn.execute(" ".join(sql), [match]):
        if r["item_id"] in seen:
            continue
        seen.add(r["item_id"])
        out.append((r["item_id"], r["comment_id"]))
        if limit is not None and len(out) >= limit:
            break
    return out


def _ref_search(
    conn: sqlite3.Connection, q: str, *, include_archived: bool = False
) -> list[sqlite3.Row]:
    """Ref-gebaseerd zoeken: ``"BETON-143"`` → exact, ``"143"`` → seq cross-project.

    Geeft compacte rijen terug (zelfde structuur als de FTS-`run()`), of een
    lege lijst als de query niet op een ref/nummer lijkt.
    """
    qs = q.strip()
    rows: list[sqlite3.Row] = []
    sql = [_COMPACT_SELECT, "WHERE"]
    params: list = []
    named_project = False
    try:
        key, seq = parse_ref(qs)  # "BETON-143" → ("BETON", 143)
        sql.append("p.key = ? COLLATE NOCASE AND items.seq = ?")
        params = [key, seq]
        named_project = True
    except ValueError:
        if qs.isdigit():  # "143" → alle items met seq 143, cross-project
            sql.append("items.seq = ?")
            params = [int(qs)]
        else:
            return rows  # geen ref-query → FTS mag 't oplossen
    if not include_archived:
        sql.append("AND items.archived_at IS NULL")
        # BETON-413: de volledige ref ("TOR-42") noemt zijn project zelf en is
        # dus geen cross-project sweep maar een gerichte lookup — zelfde
        # uitzondering als `get`/`get_by_ref`, anders is een ticket in een
        # gearchiveerd project niet meer op te zoeken. Een kaal nummer ("42")
        # matcht wél over alle projecten en valt onder de poort.
        if not named_project:
            sql.append(f"AND {LIVE_PROJECT}")
    sql.append("ORDER BY items.seq DESC")
    return conn.execute(" ".join(sql), params).fetchall()


def parse_hash_query(q: str) -> tuple[str, str]:
    """Splits een #-autocomplete-query in (letters, digits) — spiegelt de
    frontend-parser ``parseHashQuery``.

    Een leidende ``#`` en een koppelteken tussen key en seq worden genegeerd.
    ``"B1"`` → ("B", "1"); ``"42"`` → ("", "42"); ``"SOS"`` → ("SOS", "");
    ``"BETON-143"`` → ("BETON", "143"). Onzin → ("", "").
    """
    qs = q.strip()
    if qs.startswith("#"):
        qs = qs[1:]
    m = re.fullmatch(r"([A-Za-z]*)-?(\d*)", qs)
    if not m:
        return "", ""
    return m.group(1), m.group(2)


def ref_candidates(
    conn: sqlite3.Connection,
    q: str,
    *,
    project_key: str | None = None,
    limit: int = 12,
    include_archived: bool = False,
    viewer_id: int | None = None,
) -> list[dict]:
    """Ticket-ref-autocomplete voor het ``#``-menu (BETON-254).

    Splitst ``q`` in een key-fragment (letters) en een seq-fragment (cijfers) en
    matcht met **substrings** volgens de zoeksemantiek (``#B1`` → project-key bevat
    ``B`` én seq bevat ``1``, cross-project):

    - **letters aanwezig** → cross-project; ``p.key`` bevat de letters
      (case-insensitief). Zijn er ook cijfers, dan moet de seq die cijfers als
      substring bevatten.
    - **alleen cijfers** → beperkt tot ``project_key`` (het huidige project); seq
      bevat de cijfers als substring.
    - **niets bruikbaars** → lege lijst.

    Ref-first ordening zodat de meest voor de hand liggende treffer bovenaan
    staat (``#42`` → ``BETON-42`` bovenaan, niet begraven onder 142/420): exacte
    seq → seq begint met de cijfers → key begint met de letters → rest; daarna
    oplopende seq. Gecapt op ``limit``.
    """
    letters, digits = parse_hash_query(q)
    if not letters and not digits:
        return []

    conditions: list[str] = []
    params: list = []
    if letters:
        conditions.append("p.key LIKE ? ESCAPE '\\' COLLATE NOCASE")
        params.append(f"%{_like_escape(letters)}%")
    elif project_key:
        # Alleen cijfers → scope tot het huidige project (de standaard zoekscope).
        conditions.append("p.key = ? COLLATE NOCASE")
        params.append(project_key)
    if digits:
        conditions.append("CAST(items.seq AS TEXT) LIKE ? ESCAPE '\\'")
        params.append(f"%{_like_escape(digits)}%")
    if not include_archived:
        conditions.append("items.archived_at IS NULL")
        # BETON-413: ook hier geen tickets uit een gearchiveerd project. De
        # letters-tak is cross-project (`#B1` zoekt over alle keys), dus dit is
        # een sweep. Wie een ticket in een gearchiveerd project tóch wil
        # bereiken, typt zijn volledige ref in de zoek — dat blijft een gerichte
        # lookup (zie `_ref_search`).
        conditions.append(LIVE_PROJECT)

    order: list[str] = []
    if digits:
        order.append(
            "CASE WHEN items.seq = ? THEN 0 "
            "WHEN CAST(items.seq AS TEXT) LIKE ? ESCAPE '\\' THEN 1 ELSE 2 END"
        )
        params.append(int(digits))
        params.append(f"{_like_escape(digits)}%")
    if letters:
        order.append(
            "CASE WHEN p.key LIKE ? ESCAPE '\\' COLLATE NOCASE THEN 0 ELSE 1 END"
        )
        params.append(f"{_like_escape(letters)}%")
    order.append("items.seq ASC")

    sql = [
        _COMPACT_SELECT,
        "WHERE",
        " AND ".join(conditions),
        "ORDER BY",
        ", ".join(order),
    ]
    sql.append("LIMIT ?")
    params.append(limit)
    rows = conn.execute(" ".join(sql), params).fetchall()
    return _compact_rows(conn, rows, viewer_id)


def _dedup_rows(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """Verwijder dubbele rijen op ``items.id`` (behoud eerste voorkomen)."""
    seen: set[int] = set()
    out: list[sqlite3.Row] = []
    for r in rows:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return out


def children(conn: sqlite3.Connection, item_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM items WHERE parent_id = ? ORDER BY seq", (item_id,)
    ).fetchall()


def default_active_state_id(conn: sqlite3.Connection, project_id: int) -> int | None:
    """De state waar een item naar terugkeert als het de deferred-state verlaat
    (zetten van de state niet expliciet meegegeven): bij voorkeur de `todo`-state,
    anders de default-state van het project. Gebruikt door zowel
    `reactivate_deferred` (verlopen deferred_until) als de API (BETON-165:
    deferred_until wissen terwijl de state nog deferred is)."""
    row = conn.execute(
        "SELECT id FROM states WHERE project_id = ? AND name = 'todo' COLLATE NOCASE",
        (project_id,),
    ).fetchone()
    if row is not None:
        return row["id"]
    row = conn.execute(
        "SELECT id FROM states WHERE project_id = ? "
        "ORDER BY is_default DESC, sort_order LIMIT 1",
        (project_id,),
    ).fetchone()
    return row["id"] if row else None


def restore_state_id(
    conn: sqlite3.Connection, project_id: int, from_state_id: int | None
) -> int | None:
    """De state waar een item naartoe moet als het de deferred-state verlaat:
    bij voorkeur `from_state_id` (waar het vandaan kwam vóór het uitstellen,
    BETON-199), maar alleen als dat een "werkbare" state is (`unstarted`/`started`
    — todo, in-progress, review, ...). Anders de `todo`/default-fallback
    (`default_active_state_id`): bv. omdat het item rechtstreeks in deferred is
    aangemaakt, vanuit backlog werd uitgesteld, of de oude state inmiddels
    verwijderd is. Een gereactiveerd item hoort nooit onopgemerkt terug in de
    backlog te belanden (BETON-199) of in een gesloten state (done/cancelled)."""
    if from_state_id is not None:
        row = conn.execute(
            "SELECT id FROM states WHERE id = ? AND grp IN ('unstarted', 'started')",
            (from_state_id,),
        ).fetchone()
        if row is not None:
            return row["id"]
    return default_active_state_id(conn, project_id)


def reactivate_deferred(conn: sqlite3.Connection, now: str | None = None) -> list[dict]:
    """Zet items met een verlopen `deferred_until` terug naar waar ze vandaan
    kwamen (`deferred_from_state_id`, BETON-199) — of de `todo`/default-state als
    dat niet bekend is — en wis beide velden. Idempotent; geeft per geraakt item
    een dict terug met de oude/nieuwe state_id en de gewiste `deferred_until`,
    zodat de caller (BETON-164) daar een `item.updated`-event + webhook-fanout
    van kan maken — dat gebeurt hier bewust NIET: `repo/` blijft pure data-access,
    zonder afhankelijkheid van `events`/`webhooks` (die op hun beurt weer
    `repo.items` importeren — een import hier zou circulair zijn).

    Lichte periodieke self-heal (BETON-39): een item dat "tot <datum>" wachtte,
    keert daarna vanzelf terug in de actieve kolommen i.p.v. in Deferred te blijven
    hangen. `now` is optioneel (ISO-string) — handig voor tests; default = nu.
    Datums in de toekomst blijven staan (ISO-strings vergelijken lexicografisch).
    """
    if now is None:
        rows = conn.execute(
            "SELECT id, project_id, state_id, deferred_until, deferred_from_state_id "
            "FROM items WHERE deferred_until IS NOT NULL AND archived_at IS NULL "
            "AND deferred_until <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, project_id, state_id, deferred_until, deferred_from_state_id "
            "FROM items WHERE deferred_until IS NOT NULL AND archived_at IS NULL "
            "AND deferred_until <= ?",
            (now,),
        ).fetchall()
    affected: list[dict] = []
    for r in rows:
        target = restore_state_id(conn, r["project_id"], r["deferred_from_state_id"])
        conn.execute(
            "UPDATE items SET state_id = ?, deferred_until = NULL, "
            "deferred_from_state_id = NULL, completed_at = NULL, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (target, r["id"]),
        )
        affected.append(
            {
                "id": r["id"],
                "from_state_id": r["state_id"],
                "to_state_id": target,
                "from_deferred_until": r["deferred_until"],
            }
        )
    return affected


def move_to_project(
    conn: sqlite3.Connection, item_id: int, target_project_id: int
) -> sqlite3.Row | None:
    """Verplaats een item **in-place** naar een ander project (BETON-244).

    Het item behoudt zijn ``id`` — alleen ``project_id`` + ``seq`` (en dus de ref
    ``KEY-seq``) wijzigen. Omdat comments, relaties, attachments en subtaken naar
    het ongewijzigde item-``id`` verwijzen, volgen ze automatisch mee (de labels
    zijn project-gescopet en worden door de API-laag apart geremapt).

    Wist alle project-gescopete velden die in het doelproject betekenisloos of
    zelfs gevaarlijk zijn: ``milestone_id`` (hoort bij de release-cadans van het
    bronproject) én ``deferred_until``/``deferred_from_state_id``. Dat laatste is
    cruciaal: bleef ``deferred_from_state_id`` naar een *bron*-project-state
    wijzen, dan zou ``reactivate_deferred`` het item later stilletjes naar een
    state van een ánder project zetten (cross-project state-corruptie). Omdat de
    state hier toch al naar de default van het doelproject gaat, is de
    deferred-context sowieso verlopen → wissen is de consistente keuze. De state
    wordt op de default-state van het doelproject gezet via ``update`` (dat regelt
    tegelijk ``completed_at`` en ``updated_at``)."""
    seq = projects_repo.next_seq(conn, target_project_id)
    conn.execute(
        "UPDATE items SET project_id = ?, seq = ?, milestone_id = NULL, "
        "deferred_until = NULL, deferred_from_state_id = NULL WHERE id = ?",
        (target_project_id, seq, item_id),
    )
    default = conn.execute(
        "SELECT id FROM states WHERE project_id = ? "
        "ORDER BY is_default DESC, sort_order LIMIT 1",
        (target_project_id,),
    ).fetchone()
    if default is not None:
        update(conn, item_id, {"state_id": default["id"]})
    return get(conn, item_id)


def archive(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    """Markeer een item als gearchiveerd (idempotent op reeds-gearchiveerd)."""
    events_repo._touch(conn, "items", "archived_at", item_id)
    return get(conn, item_id)


def unarchive(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    """Herstel een gearchiveerd item (archived_at → NULL). Idempotent (BETON-59)."""
    conn.execute(
        "UPDATE items SET archived_at = NULL, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE id = ? AND archived_at IS NOT NULL",
        (item_id,),
    )
    return get(conn, item_id)


# Hoeveel comments ruimte een item krijgt ná ontgrendelen (BETON-302). Bewust
# kleiner dan de eerste drempel (10): een ticket dat al een keer is dichtgeklapt
# is verdacht, dus de tweede ronde is korter.
UNLOCK_HEADROOM = 5


def lock(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    """Zet een item op slot (idempotent op reeds-gelockt; BETON-302).

    Raakt `updated_at` niet: een slot is geen inhoudelijke wijziging van het
    item, en `updated_at` is de optimistic-concurrency-token (BETON-44). Het
    `item.locked`-event is het spoor."""
    events_repo._touch(conn, "items", "locked_at", item_id)
    return get(conn, item_id)


def unlock(
    conn: sqlite3.Connection,
    item_id: int,
    comment_count: int,
    headroom: int = UNLOCK_HEADROOM,
) -> sqlite3.Row | None:
    """Haal een item van het slot en schuif de drempel op (BETON-302).

    De nieuwe drempel is `comment_count + headroom` — dus altijd geteld vanaf
    waar het gesprek NU staat, niet vanaf de oude drempel. Een vaste 10 zou een
    item dat bij 10 ontgrendeld wordt meteen weer dichtklappen.

    `headroom` is sinds BETON-338 kiesbaar (5/10/20); de default houdt het
    BETON-302-gedrag intact voor elke bestaande aanroeper. De validatie van de
    keuze zit in het request-model (`models.UnlockIn.headroom`, een
    `Literal`), niet hier — deze
    functie is het mechaniek, niet het beleid.

    **Telling t.o.v. een wachtende comment (BETON-338)**: de aanroeper plaatst
    een eventuele held comment vóór hij dit aanroept, zodat `comment_count` hem
    al meetelt en de gekozen ruimte er bovenop komt. De vrijgegeven comment is
    inhaalwerk van vóór het slot en mag de nieuwe ronde niet opeten.

    Alleen een écht gelockt item wordt aangeraakt (`locked_at IS NOT NULL`):
    een ontgrendeling van een open item mag de drempel niet stiekem ophogen —
    dat zou een noodstop weg-klikken die nooit heeft geklapt."""
    conn.execute(
        "UPDATE items SET locked_at = NULL, comment_limit = ? "
        "WHERE id = ? AND locked_at IS NOT NULL",
        (comment_count + headroom, item_id),
    )
    return get(conn, item_id)


def hard_delete(conn: sqlite3.Connection, item_id: int) -> None:
    """Verwijder een item onherroepelijk.

    Comments, labels, relaties, events, attachments en embeddings cascaden weg
    (ON DELETE CASCADE) en de FTS-triggers houden de zoekindex bij. Alleen
    `parent_id` staat op RESTRICT, dus subtaken worden eerst losgekoppeld
    (parent_id → NULL) zodat ze top-level worden i.p.v. de delete te blokkeren.
    """
    conn.execute("UPDATE items SET parent_id = NULL WHERE parent_id = ?", (item_id,))
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))


def get_required(conn: sqlite3.Connection, row_id: int) -> sqlite3.Row:
    """Lees een rij die door de caller als write-postconditie wordt verwacht."""
    row = get(conn, row_id)
    if row is None:
        raise LookupError("Item ontbreekt na de verwachte bewerking")
    return row
