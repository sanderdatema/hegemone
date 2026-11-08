"""Wachtrij voor comments die op de noodstop stuitten (BETON-338).

Als een ticket op slot staat (BETON-302) krijgt een agent die wil reageren een
409. Die tekst was daarmee weg — terwijl juist díe comment vaak zegt waaróm de
lus doorging. Deze module bewaart hem tot een mens het slot eraf haalt; dan
wordt hij alsnog als gewone comment geplaatst.

**Eén plek per item.** De limiet is een `UNIQUE`-constraint op `item_id`
(migratie 037), geen applicatielogica: twee gelijktijdige geblokkeerde
verzoeken kunnen niet allebei een rij maken. `hold` geeft `None` terug als er al
iets in de wacht staat — óók wanneer de race in de database wordt beslist — zodat
de aanroeper één pad heeft voor "er ligt al iets" en niet op timing hoeft te
vertrouwen.

Waarom maar één: het slot bestaat om een lus te stóppen. Alles bewaren betekent
dat de lus tijdens het slot doorproduceert en de vloed alleen wordt uitgesteld
tot het ontgrendelen. Eén bewaren houdt de diagnostische waarde zonder het slot
te ondermijnen.

Pure sqlite3-data-access, connectie als eerste arg — geen ORM.
"""

from __future__ import annotations

import sqlite3

from .users import handle_of

NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


def hold(
    conn: sqlite3.Connection, item_id: int, author_id: int, body_md: str
) -> sqlite3.Row | None:
    """Bewaar een geblokkeerde comment. ``None`` als er al iets in de wacht staat.

    De `UNIQUE`-constraint op ``item_id`` is de scheidsrechter: een tweede
    poging — ook een gelijktijdige — botst en levert ``None`` op, geen tweede
    rij en geen 500.
    """
    try:
        cur = conn.execute(
            f"""INSERT INTO held_comments (item_id, author_id, body_md, created_at)
                VALUES (?, ?, ?, {NOW_SQL})""",
            (item_id, author_id, body_md),
        )
    except sqlite3.IntegrityError as exc:
        if str(exc) == "archived_project_readonly":
            raise
        return None
    return get(conn, item_id) if cur.lastrowid else None


def get(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    """De comment die voor dit item in de wacht staat, of ``None``."""
    return conn.execute(
        "SELECT * FROM held_comments WHERE item_id = ?", (item_id,)
    ).fetchone()


def release(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    """Haal de wachtende comment op én verwijder hem uit de wachtrij.

    Retourneert de rij zodat de aanroeper hem als echte comment kan plaatsen.
    De verwijdering hoort in dezelfde transactie als dat plaatsen — anders kan
    een halve uitvoering hem dubbel of nergens opleveren.
    """
    row = get(conn, item_id)
    if row is None:
        return None
    conn.execute("DELETE FROM held_comments WHERE item_id = ?", (item_id,))
    return row


def serialize(conn: sqlite3.Connection, row: sqlite3.Row | None) -> dict | None:
    """API-vorm: auteur-handle i.p.v. id, want de UI toont een naam.

    Bewust alleen gebruikt in `items.serialize` (de drawer), niet in `compact` —
    de kaartweergave heeft genoeg aan het slotje, en `_compact_rows` is een
    bulk-pad dat we niet met een N+1 willen belasten.
    """
    if row is None:
        return None
    return {
        "id": row["id"],
        "author": handle_of(conn, row["author_id"]),
        "body_md": row["body_md"],
        "created_at": row["created_at"],
    }
