"""Relations-repository: gericht opgeslagen, in beide richtingen opvraagbaar.

Opslag is canoniek in drie types (kolom `type`):
  - 'blocks'        → item_id blokkeert related_item_id
  - 'duplicate_of'  → item_id is duplicaat van related_item_id
  - 'relates_to'    → symmetrisch

De API accepteert de user-gerichte verba (blocks, blocked_by, duplicate_of,
duplicated_by, relates_to) en normaliseert die naar opslag; bij het opvragen
worden beide richtingen weer uit elkaar getrokken naar dezelfde verba.
"""

from __future__ import annotations

import sqlite3
from typing import TypedDict

# User-facing type → (canoniek opslag-type, of de opgegeven target de bron is).
# reversed=True betekent: sla op als (target, item, type) i.p.v. (item, target, type).
NORMALIZE = {
    "blocks": ("blocks", False),
    "blocked_by": ("blocks", True),
    "duplicate_of": ("duplicate_of", False),
    "duplicated_by": ("duplicate_of", True),
    "relates_to": ("relates_to", False),
}


# Gerichte types waarvoor de omgekeerde richting een contradictie is
# (A blokkeert B én B blokkeert A; A duplicaat-van B én B duplicaat-van A).
# 'relates_to' is symmetrisch en kent geen contradictie.
_DIRECTED = ("blocks", "duplicate_of")

# Symmetrische types: (A,B) en (B,A) betekenen hetzelfde. Die slaan we canoniek
# op met item_id < related_item_id, zodat de UNIQUE-constraint een dubbele
# relatie (in welke richting dan ook) weert (BETON-20).
_SYMMETRIC = ("relates_to",)


def _canonical(item_id: int, related_item_id: int, stored_type: str) -> tuple[int, int]:
    """Orden een symmetrisch paar deterministisch; gerichte paren blijven intact."""
    if stored_type in _SYMMETRIC and item_id > related_item_id:
        return related_item_id, item_id
    return item_id, related_item_id


def reverse_exists(
    conn: sqlite3.Connection, *, item_id: int, related_item_id: int, stored_type: str
) -> bool:
    """True als de tegengestelde gerichte relatie al bestaat (contradictie)."""
    if stored_type not in _DIRECTED:
        return False
    row = conn.execute(
        "SELECT 1 FROM relations WHERE item_id = ? AND related_item_id = ? AND type = ?",
        (related_item_id, item_id, stored_type),
    ).fetchone()
    return row is not None


def exists(
    conn: sqlite3.Connection, *, item_id: int, related_item_id: int, stored_type: str
) -> bool:
    item_id, related_item_id = _canonical(item_id, related_item_id, stored_type)
    row = conn.execute(
        "SELECT 1 FROM relations WHERE item_id = ? AND related_item_id = ? AND type = ?",
        (item_id, related_item_id, stored_type),
    ).fetchone()
    return row is not None


def delete(
    conn: sqlite3.Connection, *, item_id: int, related_item_id: int, stored_type: str
) -> int:
    """Verwijder een relatie. Geeft het aantal verwijderde rijen terug.

    Symmetrische relaties worden canoniek opgeslagen, dus verwijderen mag met de
    paar-leden in willekeurige volgorde."""
    item_id, related_item_id = _canonical(item_id, related_item_id, stored_type)
    cur = conn.execute(
        "DELETE FROM relations WHERE item_id = ? AND related_item_id = ? AND type = ?",
        (item_id, related_item_id, stored_type),
    )
    return cur.rowcount


def create(
    conn: sqlite3.Connection, *, item_id: int, related_item_id: int, stored_type: str
) -> sqlite3.Row:
    item_id, related_item_id = _canonical(item_id, related_item_id, stored_type)
    conn.execute(
        """INSERT OR IGNORE INTO relations (item_id, related_item_id, type)
           VALUES (?, ?, ?)""",
        (item_id, related_item_id, stored_type),
    )
    return conn.execute(
        "SELECT * FROM relations WHERE item_id = ? AND related_item_id = ? AND type = ?",
        (item_id, related_item_id, stored_type),
    ).fetchone()


_GROUPS = ("blocks", "blocked_by", "duplicate_of", "duplicated_by", "relates_to")

# Eén query voor alle relaties van een item, mét ref/titel/state van de andere
# kant (BETON-471): geen lookup per rij. `outgoing` = dit item is de bron.
_DETAIL_SQL = """
    SELECT 1 AS outgoing, r.type AS type, p.key AS key, o.seq AS seq,
           o.title AS title, st.name AS state
      FROM relations r
      JOIN items o ON o.id = r.related_item_id
      JOIN projects p ON p.id = o.project_id
      LEFT JOIN states st ON st.id = o.state_id
     WHERE r.item_id = ?
    UNION ALL
    SELECT 0, r.type, p.key, o.seq, o.title, st.name
      FROM relations r
      JOIN items o ON o.id = r.item_id
      JOIN projects p ON p.id = o.project_id
      LEFT JOIN states st ON st.id = o.state_id
     WHERE r.related_item_id = ?
"""


def _group_of(outgoing: int, type_: str) -> str:
    if type_ == "blocks":
        return "blocks" if outgoing else "blocked_by"
    if type_ == "duplicate_of":
        return "duplicate_of" if outgoing else "duplicated_by"
    return "relates_to"


class RelationDetail(TypedDict):
    ref: str
    title: str
    state: str | None


def for_item_detail(
    conn: sqlite3.Connection, item_id: int
) -> dict[str, list[RelationDetail]]:
    """Als `for_item`, maar per relatie `{ref, title, state}` (BETON-471).

    Dedupe en sortering op ref, identiek aan `for_item`."""
    result: dict[str, dict[str, RelationDetail]] = {g: {} for g in _GROUPS}
    for row in conn.execute(_DETAIL_SQL, (item_id, item_id)).fetchall():
        ref = f"{row['key']}-{row['seq']}"
        group = _group_of(row["outgoing"], row["type"])
        result[group].setdefault(
            ref, {"ref": ref, "title": row["title"], "state": row["state"]}
        )
    return {g: [result[g][r] for r in sorted(result[g])] for g in _GROUPS}


def for_item(conn: sqlite3.Connection, item_id: int) -> dict[str, list[str]]:
    """Alle relaties van een item, gegroepeerd naar user-facing verba (refs).

    Gebatcht (BETON-471): het aantal query's groeit niet met het aantal
    relaties. Dedupe (legacy-data vóór migratie 009 kan een symmetrisch paar in
    beide richtingen bevatten) en stabiele sortering zitten in `for_item_detail`."""
    detail = for_item_detail(conn, item_id)
    return {g: [d["ref"] for d in detail[g]] for g in _GROUPS}
