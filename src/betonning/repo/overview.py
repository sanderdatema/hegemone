"""Overzicht over ÁLLE projecten (BETON-371): per project de tellers die je
nodig hebt om te kiezen waar je vandaag heen moet.

Het risico van dit scherm zit niet in de inhoud maar in de vorm: een lus over
projecten die per project telt is O(N) query's en groeit mee met het aantal
projecten. Alles hieronder is daarom **gebatcht** — elke query gaat over álle
levende projecten tegelijk en groepeert op `project_id`; het optellen per
project gebeurt in Python. Zelfde idioom als `items._compact_rows` en
`item_reads.unread_bulk` (BETON-275/294).

Het aantal query's is **constant** in het aantal projecten (bewaakt door
`tests/test_overview.py::test_query_count_is_constant_in_projects`, die telt met
een `set_trace_callback` bij 3 én 7 projecten).

Buiten beeld blijven: gearchiveerde items (`items.archived_at`) en gearchiveerde
projecten (`projects.archived_at`).
"""

from __future__ import annotations

import sqlite3

from .. import mentions as mentions_mod
from . import comments as comments_repo
from . import item_reads as item_reads_repo
from . import states as states_repo

# States zonder `grp` bestaan (items kunnen `state_id IS NULL` hebben — zie
# `projects.backfill_untriage`, die daar expliciet op guard't). Zonder de
# NULL-tak zou `st.grp NOT IN (...)` daar NULL (= niet waar) opleveren en
# vielen die items stilzwijgend uit de "open"-telling.

# Boven dit aantal item-id's knippen we de `IN (?,?,…)`-lijst op: oudere
# SQLite-builds hebben een variabelen-limiet (SQLITE_MAX_VARIABLE_NUMBER, vaak
# 999). Het aantal query's blijft daarmee afhankelijk van het aantal *items*,
# nooit van het aantal projecten.
_CHUNK = 800


def _chunks(ids: list[int]):
    for start in range(0, len(ids), _CHUNK):
        yield ids[start : start + _CHUNK]


def _unread_ids(conn: sqlite3.Connection, ids: list[int], viewer_id: int | None) -> set[int]:
    """Ongelezen item-id's — via `item_reads.unread_bulk`, nooit met een eigen
    query. De regel ("hoogste vreemde event-id boven zowel de globale als de
    per-item-watermark") staat op één plek en moet daar blijven staan."""
    out: set[int] = set()
    for chunk in _chunks(ids):
        out |= item_reads_repo.unread_bulk(conn, chunk, viewer_id)
    return out


def _blocked_ids(conn: sqlite3.Connection) -> set[int]:
    """Item-id's die door een ander (levend) item geblokkeerd worden.

    Richting is alles: `blocked_by` wordt opgeslagen als een omgekeerde `blocks`
    (`relations.NORMALIZE`), dus het geblokkeerde item is de **related_item_id**
    van een `type='blocks'`-rij.

    De blokkeerder moet nog OPEN werk zijn: niet gearchiveerd én niet in een
    afgeronde state. Op een echt bord wordt een blokkeerder veel vaker afgerond
    dan dat iemand de relatie opruimt — zonder die tweede voorwaarde telt de
    teller vooral historie. (BETON-293's `relation.deleted blocked_by` →
    `pick_up` gaat over notificaties, niet over "klemt dit nu".)
    """
    rows = conn.execute(
        f"""SELECT DISTINCT r.related_item_id AS id FROM relations r
            JOIN items b ON b.id = r.item_id
            LEFT JOIN states bst ON bst.id = b.state_id
            WHERE r.type = 'blocks' AND b.archived_at IS NULL
              AND {states_repo.state_open_sql('bst')}""",
    ).fetchall()
    return {r["id"] for r in rows}


def _open_question_counts(
    conn: sqlite3.Connection, viewer_id: int, viewer_handle: str
) -> dict[int, int]:
    """Onbeantwoorde vragen die aan de kijker gericht zijn, per project.

    De gerichtheidsregel is dezelfde als die van `GET /questions?open=true`
    (`api/items.py:list_questions`): assignee óf maker van het item, óf
    @gementiond in de vraagtekst. Die endpoint doet een `get`+`serialize` per
    vraag (N+1) — hier één join over alle projecten, met de predikaat-toets in
    Python omdat de mention-parsing de body nodig heeft.
    """
    rows = conn.execute(
        f"""SELECT i.project_id AS project_id, i.assignee_id AS assignee_id,
                  i.created_by AS created_by, c.body_md AS body_md
           FROM comments c
           JOIN items i ON i.id = c.item_id
           JOIN projects p ON p.id = i.project_id
           WHERE {comments_repo.question_open_sql('c')}
             AND i.archived_at IS NULL AND p.archived_at IS NULL"""
    ).fetchall()
    counts: dict[int, int] = {}
    for r in rows:
        directed = (
            r["assignee_id"] == viewer_id
            or r["created_by"] == viewer_id
            or viewer_handle in set(mentions_mod.parse(r["body_md"] or ""))
        )
        if directed:
            counts[r["project_id"]] = counts.get(r["project_id"], 0) + 1
    return counts


def _next_milestones(conn: sqlite3.Connection) -> dict[int, dict]:
    """De eerstvolgende openstaande milestone per project, met voortgang.

    Twee query's over álle projecten: de openstaande milestones, en de
    (done, total)-telling per (project, milestone). Bewust NIET
    `milestones._progress_bulk` — die neemt één `project_id` en zou hier dus
    de per-project-lus terugbrengen die dit scherm juist moet vermijden.

    "Eerstvolgend" = de vroegste `due_date`; milestones zonder datum komen
    daarna, op naam (deterministisch, anders wisselt de keuze per query-plan).
    """
    progress_rows = conn.execute(
        f"""SELECT i.project_id AS project_id, i.milestone_id AS mid,
                   COUNT(*) AS total,
                   SUM(CASE WHEN {states_repo.state_closed_sql('st')} THEN 1 ELSE 0 END) AS done
            FROM items i
            LEFT JOIN states st ON st.id = i.state_id
            WHERE i.milestone_id IS NOT NULL AND i.archived_at IS NULL
            GROUP BY i.project_id, i.milestone_id""",
    ).fetchall()
    progress = {r["mid"]: (int(r["done"] or 0), int(r["total"] or 0)) for r in progress_rows}

    rows = conn.execute(
        """SELECT m.id AS id, m.project_id AS project_id, m.name AS name,
                  m.due_date AS due_date, m.status AS status
           FROM milestones m
           JOIN projects p ON p.id = m.project_id
           WHERE p.archived_at IS NULL AND m.status != 'completed'
           ORDER BY m.due_date IS NULL, m.due_date, m.name"""
    ).fetchall()
    out: dict[int, dict] = {}
    for r in rows:
        if r["project_id"] in out:
            continue  # de ORDER BY zette de eerstvolgende bovenaan
        done, total = progress.get(r["id"], (0, 0))
        out[r["project_id"]] = {
            "name": r["name"],
            "due_date": r["due_date"],
            "items_done": done,
            "items_total": total,
        }
    return out


def last_activity(conn: sqlite3.Connection) -> dict[int, str]:
    """Laatste activiteit per project (BETON-464): de nieuwste `updated_at` van
    een niet-gearchiveerd item óf van een comment erop. Zelfde definitie als
    `last_activity_at` op een item (BETON-68), maar gegroepeerd: twee query's
    over alle projecten, dus constant in het aantal projecten."""
    out: dict[int, str] = {}
    queries = (
        """SELECT i.project_id AS project_id, MAX(i.updated_at) AS ts
           FROM items i WHERE i.archived_at IS NULL GROUP BY i.project_id""",
        """SELECT i.project_id AS project_id, MAX(c.updated_at) AS ts
           FROM comments c JOIN items i ON i.id = c.item_id
           WHERE i.archived_at IS NULL GROUP BY i.project_id""",
    )
    for q in queries:
        for r in conn.execute(q).fetchall():
            if r["ts"] and r["ts"] > out.get(r["project_id"], ""):
                out[r["project_id"]] = r["ts"]
    return out


def project_overview(
    conn: sqlite3.Connection, viewer_id: int | None = None, viewer_handle: str = ""
) -> list[dict]:
    """Per levend project: open / in-progress / geblokkeerd / niet-toegewezen /
    open vragen voor mij / ongelezen voor mij / eerstvolgende milestone /
    laatste activiteit.

    Zonder kijker (`viewer_id is None`) blijven de persoonlijke tellers 0 —
    net als `has_unread` bij een serialisatie zonder viewer.
    """
    projects = conn.execute(
        "SELECT id, key, name, created_at FROM projects WHERE archived_at IS NULL ORDER BY key"
    ).fetchall()

    open_rows = conn.execute(
        f"""SELECT i.id AS id, i.project_id AS project_id, i.assignee_id AS assignee_id,
                   st.grp AS grp
            FROM items i
            LEFT JOIN states st ON st.id = i.state_id
            JOIN projects p ON p.id = i.project_id
            WHERE i.archived_at IS NULL AND p.archived_at IS NULL
              AND {states_repo.state_open_sql('st')}""",
    ).fetchall()

    blocked = _blocked_ids(conn)
    open_ids = [r["id"] for r in open_rows]
    unread = _unread_ids(conn, open_ids, viewer_id)
    questions = (
        _open_question_counts(conn, viewer_id, viewer_handle) if viewer_id is not None else {}
    )
    milestones = _next_milestones(conn)
    activity = last_activity(conn)

    tally: dict[int, dict] = {
        p["id"]: {
            "open": 0,
            "in_progress": 0,
            "blocked": 0,
            "unassigned": 0,
            "unread": 0,
        }
        for p in projects
    }
    for r in open_rows:
        t = tally.get(r["project_id"])
        if t is None:
            continue
        t["open"] += 1
        if r["grp"] == "started":
            t["in_progress"] += 1
        if r["id"] in blocked:
            t["blocked"] += 1
        if r["assignee_id"] is None:
            t["unassigned"] += 1
        if r["id"] in unread:
            t["unread"] += 1

    return [
        {
            "key": p["key"],
            "name": p["name"],
            "created_at": p["created_at"],
            **tally[p["id"]],
            "open_questions": questions.get(p["id"], 0),
            "next_milestone": milestones.get(p["id"]),
            "last_activity_at": activity.get(p["id"]),
        }
        for p in projects
    ]
