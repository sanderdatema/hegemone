"""Toewijzing rond de vraagmodule (BETON-431).

Eis: staat er een open vraag voor een mens op een ticket, dan is dat ticket aan
die mens toegewezen. Twee kanten:

- :func:`assign_for_question` verhuist de toewijzing bij het plaatsen van een
  vraag, en onthoudt de vorige assignee op de vraag (`comments.prior_assignee_id`).
- :func:`blocks_reassign` is de poort die voorkomt dat een agent die toewijzing
  weer wegzet zolang de vraag openstaat.

De toewijzing schrijft een event zónder fanout (`events_repo.record`), net als
de BETON-285-teruggave in `api/items.py:answer_question`: met fanout kreeg de
vorige assignee een `stand_down` (BETON-293) voor een ticket dat na het
antwoord weer bij hem terugkomt.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from . import mentions as mentions_mod
from .repo import comments as comments_repo
from .repo import events as events_repo
from .repo import items as items_repo
from .repo import users as users_repo


def _active_human(conn: sqlite3.Connection, user_id: int | None) -> sqlite3.Row | None:
    if user_id is None:
        return None
    u = users_repo.get(conn, user_id)
    if u is not None and u["kind"] == "human" and u["active"]:
        return u
    return None


def is_active_human(conn: sqlite3.Connection, user_id: int | None) -> bool:
    return _active_human(conn, user_id) is not None


def reassign_silently(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    assignee_id: int | None,
    *,
    actor_id: int | None,
) -> None:
    """Zet de assignee en schrijf het `item.updated`-event ZONDER fanout.

    Gedeeld door de toewijzing bij een vraag (hieronder), de teruggave na een
    antwoord en die na een intrekking (`api/items.py`). Alle drie willen het
    event voor SSE en activiteit, maar geen notificatie: die is er al (het
    antwoord) of zou een onterechte `stand_down` geven (BETON-293). De caller
    beheert de transactie."""
    items_repo.update(conn, item["id"], {"assignee_id": assignee_id})
    events_repo.record(
        conn,
        type="item.updated",
        item_id=item["id"],
        actor_id=actor_id,
        payload={
            "assignee": {
                "from": users_repo.handle_of(conn, item["assignee_id"]),
                "to": users_repo.handle_of(conn, assignee_id),
            }
        },
    )


def resolve_human_addressee(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    body_md: str,
    addressed_to: Iterable[str] = (),
) -> sqlite3.Row | None:
    """Wie is de mens aan wie deze vraag gericht is? `None` = geen mens.

    Volgorde: de eerste gementionde mens (body, dan `addressed_to`); zijn er
    mentions maar is er geen mens bij, dan is de vraag niet aan een mens gericht.
    Zonder mentions: de huidige assignee als die een mens is (die blijft staan),
    anders de maker van het item als die een mens is, anders de eerste mens."""
    handles: list[str] = []
    for h in [*mentions_mod.parse(body_md), *addressed_to]:
        if h not in handles:
            handles.append(h)
    if handles:
        for h in handles:
            # Handles zijn lowercase; agents schrijven soms `@Person`.
            u = users_repo.get_by_handle(conn, h.lower())
            if u is not None and (human := _active_human(conn, u["id"])):
                return human
        return None
    return (
        _active_human(conn, item["assignee_id"])
        or _active_human(conn, item["created_by"])
        or users_repo.first_human(conn)
    )


def _human_chose_assignee(conn: sqlite3.Connection, item: sqlite3.Row) -> bool:
    """Heeft een mens de huidige assignee zelf gekozen? (BETON-478)

    Waar als er een assignee is die niet `triage` is en het laatste
    toewijzings-event van het item een mens als actor heeft. Beide payload-
    vormen tellen (`{from,to}` van de API, plat `handle` van triage/fanout)."""
    current = item["assignee_id"]
    if current is None:
        return False
    triage = users_repo.get_by_handle(conn, "triage")
    if triage is not None and triage["id"] == current:
        return False
    row = conn.execute(
        """SELECT u.kind FROM events e LEFT JOIN users u ON u.id = e.actor_id
           WHERE e.item_id = ? AND e.type = 'item.updated'
             AND json_type(e.payload, '$.assignee') IN ('object', 'text')
           ORDER BY e.id DESC LIMIT 1""",
        (item["id"],),
    ).fetchone()
    return row is not None and row["kind"] == "human"


def assign_for_question(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    question_id: int,
    body_md: str,
    actor_id: int | None,
    addressed_to: Iterable[str] = (),
    keep_human_choice: bool = False,
) -> None:
    """Wijs het item toe aan de aangesproken mens en onthoud de vorige assignee.

    Doet niets als de vraag niet aan een mens gericht is, als die mens al de
    assignee is, of als een mens de huidige assignee zelf koos (BETON-478). De caller beheert de transactie."""
    item = items_repo.get(conn, item_id)
    if item is None:
        return
    target = resolve_human_addressee(conn, item, body_md, addressed_to)
    if target is None or target["id"] == item["assignee_id"]:
        return
    # BETON-478: een toewijzing die een mens net zelf deed laat triage staan
    # (alleen als de aanroeper dat vraagt: de vervolgvraag uit een evaluatie.
    # Een stale-/guardrail-vraag en een agent die op zijn eigen toegewezen
    # ticket vraagt volgen gewoon BETON-431) —
    # de vraag wordt wel gesteld, het ticket gaat er niet voor weg bij de
    # gekozen assignee (de expliciete keuze voor de coding-queue blijft leidend).
    if keep_human_choice and _human_chose_assignee(conn, item):
        return
    conn.execute(
        "UPDATE comments SET prior_assignee_id = ? WHERE id = ?",
        (item["assignee_id"], question_id),
    )
    reassign_silently(conn, item, target["id"], actor_id=actor_id)


def blocks_reassign(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    actor: sqlite3.Row | None,
    new_assignee_id: int | None,
) -> bool:
    """Zou deze herassignatie een open vraag aan een mens ontkoppelen?

    Waar als een niet-mens de assignee weghaalt bij een mens terwijl er een
    onbeantwoorde, door een niet-mens gestelde vraag op het item staat. Mensen
    mogen altijd. `actor=None` telt als niet-mens."""
    if actor is not None and actor["kind"] == "human":
        return False
    if new_assignee_id == item["assignee_id"] or item["assignee_id"] is None:
        return False
    if _active_human(conn, item["assignee_id"]) is None:
        return False
    return (
        conn.execute(
            "SELECT 1 FROM comments c LEFT JOIN users a ON a.id = c.author_id "
            f"WHERE c.item_id = ? AND {comments_repo.question_open_sql('c')} "
            "AND (a.kind IS NULL OR a.kind != 'human') LIMIT 1",
            (item["id"],),
        ).fetchone()
        is not None
    )
