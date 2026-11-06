"""Inbox-repository: welke events raken een user (BETON-55).

De inbox is een afgeleide view op de bestaande events-tabel plus een
read-marker (`users.last_seen_event_id`, migratie 019). Een event "raakt" een
user als:

- het een `@mention` van de user bevat (in een comment, of in de
  item-omschrijving bij aanmaken/wijzigen),
- de user aan het item werd toegewezen (`item.updated` met assignee → user), of
- het een comment/wijziging is op een item dat aan de user toegewezen is, of
- het een comment/wijziging is op een item dat de user expliciet volgt
  (`item_follows`, BETON-369 — de zwakste reden: een specifiekere reden wint).

De actor krijgt nooit zijn eigen events in de inbox. Alles met een event-id
groter dan de read-marker is ongelezen.

Sinds BETON-286 telt daarnaast de per-item-watermark uit `item_reads`
(BETON-294, `POST /items/{ref}/read`) mee: een event is gelezen zodra het
onder de globale watermark **of** de per-item-watermark van dát item ligt.
Zo blijft het bestaande (globale) inbox-gedrag intact en komt "dit ticket heb
ik geopend" er per item bovenop — zonder notificaties van andere tickets
mee te markeren.

**Deadlines** (BETON-367): naast de event-gedreven notificaties draagt de
inbox afgeleide *deadline*-entries (`reason="due"`) voor items die aan de user
toegewezen zijn óf die hij zelf maakte, en waarvan de einddatum vandaag is of
al verstreken. Die worden **bij het opvragen berekend**, niet door een sweep
die events wegschrijft. Motivatie: er ís geen event als een datum verstrijkt,
en een sweep zou er per overdue item per dag één moeten schrijven — die
stapelen zich op in exact het venster (`_SCAN_LIMIT`) waaruit deze inbox leest,
dus de sweep zou de inbox opeten die hij moet voeden. Afleiden is bovendien
zelf-corrigerend: verschuift de einddatum of gaat het item dicht, dan verdwijnt
de entry vanzelf en blijft er geen dode notificatie achter.

Een deadline-entry heeft geen event, dus geen `event_id` (0) en geen actor. Of
hij *gelezen* is volgt uit `item_reads.updated_at` (BETON-294): heeft de user
dit item geopend op of ná de einddatum, dan heeft hij de deadline gezien. Zo is
er geen extra read-state nodig en klaart het signaal vanzelf op zodra hij kijkt.

**Guardrail-concepten** (BETON-422): op dezelfde manier afgeleid draagt de
inbox een entry (`reason="guardrail"`) voor elk openstaand guardrail-voorstel —
nieuw, wijziging of opheffing. Alleen voor mensen: alleen een mens keurt goed.
Zie `concept_entries` voor waarom ook dit afgeleid is en niet uit een event komt.

**Opdrachtvelden** (BETON-296): een agent die pollt in plaats van (of naast)
de webhook kreeg tot dusver een event zónder `instructions`/`expected_action`/
`do`/`do_not`/`read`/`reply` — precies wat BETON-246 op het push-pad wilde
voorkomen. `list_for_user(..., include_instructions=True)` levert die velden nu
ook, via `webhooks.build_agent_instructions` — dezelfde functie die
`_send_webhook` gebruikt, dus push en pull kunnen nooit meer uit de pas lopen.
Bewust **opt-in** (query-param `?instructions=true`): elke instructie kost een
extra `events`-lookup (`build_trigger` doet zelf ook `items_repo.get` +
mogelijk `prior_participants`), en de inbox is ook een menselijke UI-inbox waar
niemand op deze velden wacht. De kosten zijn bovendien begrensd tot de
`limit` (max 200) — nooit tot de volle `_SCAN_LIMIT`-scan.
"""

from __future__ import annotations

from ..config import env

import json
import sqlite3

from .. import mentions as mentions_mod
from ..db import today as db_today
from .. import webhooks as webhooks_mod
from . import follows as follows_repo
from . import item_reads as item_reads_repo
from . import states as states_repo
from .items import LIVE_PROJECT
from .users import handle_of

# Hoeveel recente events we maximaal aftasten voor relevantie. Ruim boven de
# lijst-limiet zodat de ongelezen-teller ook events buiten de eerste pagina telt.
_SCAN_LIMIT = 500

# Hoeveel deadline-entries we maximaal meesturen. Ruim boven een realistisch
# aantal openstaande deadlines per user, maar begrensd zodat een user die honderd
# tickets over de datum heeft de inbox niet dichtzet.
_DUE_LIMIT = 50

# Idem voor guardrail-concepten (BETON-422): ruim boven een realistisch aantal
# openstaande voorstellen, en begrensd zodat ze de inbox nooit dichtzetten.
_CONCEPT_LIMIT = 50

# Een agent is onbereikbaar na zoveel terminaal mislukte webhook-deliveries
# sinds zijn laatste geslaagde (BETON-457). Env: BETONNING_WEBHOOK_ALERT_AFTER.
_ALERT_AFTER_DEFAULT = 3


def _to_val(v):
    """Nieuwe waarde uit een {from,to}-veld óf een kale waarde."""
    return v["to"] if isinstance(v, dict) and "to" in v else v


def _comment_mentions_user(conn: sqlite3.Connection, comment_id: int, handle: str) -> bool:
    row = conn.execute(
        "SELECT body_md FROM comments WHERE id = ?", (comment_id,)
    ).fetchone()
    if row is None:
        return False
    lowered = {h.lower() for h in mentions_mod.parse(row["body_md"])}
    return handle.lower() in lowered


def _reason(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    uid: int,
    handle: str,
    user_kind: str,
    followed: frozenset[int] | set[int] = frozenset(),
) -> str | None:
    """Bepaal waaróm een event de user raakt, of None als het hem niet raakt.

    Volgorde van sterkte: noodstop > mention > toewijzing > activiteit op eigen
    item > gevolgd item (BETON-369).

    ``followed`` zijn de item-id's die deze user expliciet volgt — gebatcht
    aangeleverd (één query per inbox-opvraag, geen N+1). Bewust de zwákste
    reden: wie het item volgt én tegelijk de assignee is, hoort de specifiekere
    ``comment``/``update`` te zien.
    """
    typ = row["type"]
    payload = json.loads(row["payload"] or "{}")

    # 0. Noodstop (BETON-302): een slot raakt élke mens, ongeacht betrokkenheid
    #    bij het item. Alleen mensen kunnen ontgrendelen, dus zij zijn per
    #    definitie de doelgroep — en de andere reden-regels hieronder zouden hem
    #    juist missen: in de lus die dit moet stoppen (BRAND-222) zijn zowel de
    #    assignee als de maker een agent, dus er is geen mention, geen
    #    toewijzing en geen "eigen item". Zonder deze regel zou de gebruiker de
    #    notificatie die hij vroeg nooit zien: hij heeft geen webhook_url en geen
    #    telegram_chat_id, dus de UI-inbox is zijn enige kanaal.
    if typ == "item.locked" and user_kind == "human":
        return "locked"

    # 1. Mention in een comment.
    if typ in ("comment.created", "comment.updated"):
        cid = payload.get("comment_id")
        if cid is not None and _comment_mentions_user(conn, cid, handle):
            return "mention"

    # 2. Mention in een item-omschrijving (bij aanmaken/wijzigen).
    if typ in ("item.created", "item.updated"):
        desc = _to_val(payload.get("description_md")) if "description_md" in payload else None
        if desc is None and typ == "item.created":
            item = conn.execute(
                "SELECT description_md FROM items WHERE id = ?", (row["item_id"],)
            ).fetchone()
            desc = item["description_md"] if item else None
        if desc and handle.lower() in {h.lower() for h in mentions_mod.parse(desc)}:
            return "mention"

    # 3. Toewijzing aan de user.
    if typ == "item.updated" and "assignee" in payload:
        if _to_val(payload["assignee"]) == handle:
            return "assigned"

    # 4. Activiteit op een item dat aan de user toegewezen is.
    if row["item_assignee_id"] == uid:
        if typ in ("comment.created", "comment.updated"):
            return "comment"
        if typ == "item.updated":
            return "update"

    # 5. Activiteit op een item dat de user expliciet volgt (BETON-369). Zelfde
    #    event-whitelist als regel 4 — volgen is "hou me op de hoogte van wat er
    #    gebeurt", geen abonnement op elk technisch event.
    if row["item_id"] in followed and typ in (
        "comment.created",
        "comment.updated",
        "item.updated",
    ):
        return "following"

    return None


# --- Deadlines (BETON-367) -------------------------------------------------


def due_entries(
    conn: sqlite3.Connection, user: sqlite3.Row, *, today: str | None = None
) -> list[dict]:
    """Afgeleide deadline-notificaties voor deze user (BETON-367).

    Levert één entry per open item dat aan de user toegewezen is óf dat hij zelf
    maakte, en waarvan de einddatum vandaag is of al verstreken. Er wordt niets
    weggeschreven: de reden volgt uit de datum, niet uit een event (zie de
    module-docstring voor waarom een sweep hier de verkeerde vorm is).

    Eén begrensde query (geen N+1): de ``item_reads``-join levert meteen de
    gelezen-afleiding mee. ``read`` is waar zodra de user dit item op of ná de
    einddatum geopend heeft (`POST /items/{ref}/read` bumpt ``updated_at``) — de
    deadline is dan gezien, en het signaal klaart vanzelf op.

    Afgeronde/geannuleerde en gearchiveerde items vallen af: daar valt geen
    deadline meer te halen, en met BETON-413 ook items in een gearchiveerd
    project (``LIVE_PROJECT``).
    """
    today = today or db_today(conn)
    uid = user["id"]
    rows = conn.execute(
        f"""SELECT i.id AS item_id, i.title AS title, i.seq AS seq,
                  i.due_date AS due_date, p.key AS pkey,
                  r.updated_at AS read_at
           FROM items i
           JOIN projects p ON p.id = i.project_id
           JOIN states s ON s.id = i.state_id
           LEFT JOIN item_reads r ON r.item_id = i.id AND r.user_id = ?
           WHERE i.archived_at IS NULL AND {LIVE_PROJECT}
             AND i.due_date IS NOT NULL
             AND i.due_date <= ?
             AND {states_repo.state_open_sql('s')}
             AND (i.assignee_id = ? OR i.created_by = ?)
           ORDER BY i.due_date ASC, i.id ASC
           LIMIT ?""",
        (uid, today, uid, uid, _DUE_LIMIT),
    ).fetchall()

    entries: list[dict] = []
    for r in rows:
        due = r["due_date"][:10]
        read_at = r["read_at"]
        entries.append(
            {
                # Geen event → geen event-id. 0 is veilig voor de UI-watermark
                # (`Math.max`) en botst nooit met een echt event-id.
                "event_id": 0,
                "type": "item.due",
                "reason": "due",
                "actor": None,
                "ref": f"{r['pkey']}-{r['seq']}",
                "title": r["title"],
                # Het moment waarop de deadline ging gelden — geen verzonnen "nu".
                "created_at": f"{due}T00:00:00.000Z",
                "read": bool(read_at) and read_at[:10] >= due,
                "due_date": due,
                "overdue": due < today,
            }
        )
    return entries


# --- Guardrail-concepten (BETON-422) ---------------------------------------


def concept_entries(conn: sqlite3.Connection, user: sqlite3.Row) -> list[dict]:
    """Afgeleide notificaties voor guardrail-concepten die op een mens wachten.

    Zelfde vorm en zelfde motivatie als `due_entries`: afgeleid bij het opvragen
    in plaats van uit een event. Een event-regel in `_reason` leest uit het
    scan-venster (`_SCAN_LIMIT`), dus een voorstel van een paar honderd events
    geleden zou eruit vallen terwijl het concept nog steeds op een beslissing
    wacht — en de entry zou ná goedkeuren blijven staan, want een event is
    historie en corrigeert zichzelf niet. Afleiden is zelfcorrigerend: de entry
    verdwijnt zodra het concept goedgekeurd of afgewezen is.

    Alleen voor MENSEN: alleen een mens keurt goed. Géén assignee/maker-filter —
    een concept wacht op een menselijke beslissing, niet op de toevallige
    assignee (die vaak een agent of de virtuele `coding-agent`-rij is).

    Eén begrensde query (geen N+1), inclusief de gelezen-afleiding uit
    `item_reads` (BETON-294): heeft de user het ticket geopend ná het voorstel,
    dan heeft hij het gezien. Beide kanten zijn ISO-timestamps, dus de
    stringvergelijking klopt.
    """
    if user["kind"] != "human":
        return []
    uid = user["id"]
    rows = conn.execute(
        f"""SELECT i.id AS item_id, i.title AS title, i.seq AS seq, p.key AS pkey,
                  gp.kind AS kind, gp.proposed_at AS proposed_at,
                  u.handle AS actor, r.updated_at AS read_at
           FROM item_guardrail_proposals gp
           JOIN items i ON i.id = gp.item_id
           JOIN projects p ON p.id = i.project_id
           LEFT JOIN users u ON u.id = gp.proposed_by
           LEFT JOIN item_reads r ON r.item_id = i.id AND r.user_id = ?
           WHERE i.archived_at IS NULL AND {LIVE_PROJECT}
           ORDER BY gp.proposed_at ASC, i.id ASC
           LIMIT ?""",
        (uid, _CONCEPT_LIMIT),
    ).fetchall()
    entries: list[dict] = []
    for r in rows:
        read_at = r["read_at"]
        entries.append(
            {
                # Geen event → geen event-id; 0 is veilig voor de UI-watermark
                # (`Math.max`). Bekende kosten, net als bij `due`: een groep met
                # alléén guardrail-entries landt onderaan in `groupNotifications`.
                "event_id": 0,
                "type": "item.guardrail_proposed",
                "reason": "guardrail",
                # De actor mag hier wél: anders weet de mens niet wie het
                # voorstelde, en dat bepaalt mede of hij het serieus neemt.
                "actor": r["actor"],
                "ref": f"{r['pkey']}-{r['seq']}",
                "title": r["title"],
                "created_at": r["proposed_at"],
                "read": bool(read_at) and read_at >= r["proposed_at"],
                "proposal_kind": r["kind"],
            }
        )
    return entries


# --- Onbereikbare agents (BETON-457) ---------------------------------------


def _alert_after() -> int:
    try:
        return max(1, int(env("BETONNING_WEBHOOK_ALERT_AFTER", "")))
    except ValueError:
        return _ALERT_AFTER_DEFAULT


def webhook_health(conn: sqlite3.Connection) -> list[dict]:
    """Per agent met een webhook: laatste geslaagde levering en het aantal
    terminaal mislukte sinds die (BETON-457).

    Eén begrensde query (geen N+1; begrensd door het aantal agents). Alleen
    kanaal ``webhook``, alleen actieve niet-virtuele agents mét ``webhook_url``.
    ``pending``/``cancelled`` tellen niet mee: ze zijn geen uitkomst. Een enkele
    ``delivered`` nult de teller, dus herstel is zelfcorrigerend.
    """
    after = _alert_after()
    rows = conn.execute(
        """WITH ok AS (
               SELECT user_id, MAX(id) AS ok_id, MAX(created_at) AS ok_at
               FROM webhook_deliveries
               WHERE channel = 'webhook' AND status = 'delivered'
               GROUP BY user_id
           ), g AS (
               SELECT u.handle AS handle, u.display_name AS display_name,
                      ok.ok_at AS last_delivered_at,
                      COUNT(f.id) AS failed, MIN(f.created_at) AS first_failed_at,
                      MAX(f.id) AS last_fail_id
               FROM users u
               LEFT JOIN ok ON ok.user_id = u.id
               LEFT JOIN webhook_deliveries f
                      ON f.user_id = u.id AND f.channel = 'webhook'
                     AND f.status = 'failed' AND f.id > COALESCE(ok.ok_id, 0)
               WHERE u.kind = 'agent' AND u.webhook_url IS NOT NULL
                 AND COALESCE(u.is_virtual, 0) = 0 AND u.active = 1
               GROUP BY u.id
           )
           SELECT g.*, d.last_error AS last_error
           FROM g LEFT JOIN webhook_deliveries d ON d.id = g.last_fail_id
           ORDER BY g.handle"""
    ).fetchall()
    return [
        {
            "handle": r["handle"],
            "display_name": r["display_name"],
            "last_delivered_at": r["last_delivered_at"],
            "failed_count": r["failed"],
            "first_failed_at": r["first_failed_at"],
            "last_error": r["last_error"],
            "unreachable": r["failed"] >= after,
        }
        for r in rows
    ]


def delivery_health_entries(conn: sqlite3.Connection, user: sqlite3.Row) -> list[dict]:
    """Afgeleide inbox-entry per onbereikbare agent (BETON-457).

    Zelfde motivatie als `due_entries`/`concept_entries`: afgeleid bij het
    opvragen, geen event en geen sweep — een event valt uit `_SCAN_LIMIT` en
    blijft staan na herstel. Alleen voor MENSEN (alleen zij kunnen ingrijpen).
    Geen ``ref``: het gaat om een agent, niet om een ticket; de UI toont ze
    apart. Altijd ongelezen zolang het probleem duurt.
    """
    if user["kind"] != "human":
        return []
    entries = []
    for h in webhook_health(conn):
        if not h["unreachable"]:
            continue
        entries.append(
            {
                "event_id": 0,
                "type": "agent.unreachable",
                "reason": "agent_unreachable",
                "actor": None,
                "ref": None,
                "title": f"@{h['handle']}",
                "handle": h["handle"],
                "created_at": h["first_failed_at"],
                "read": False,
                "failed_count": h["failed_count"],
                "last_error": h["last_error"],
                "last_delivered_at": h["last_delivered_at"],
            }
        )
    return entries


def list_for_user(
    conn: sqlite3.Connection,
    user: sqlite3.Row,
    *,
    limit: int = 50,
    include_instructions: bool = False,
) -> dict:
    """Inbox voor een user: relevante events (nieuwste eerst) + ongelezen-teller.

    ``unread_count`` telt alle relevante ongelezen events binnen het scan-venster,
    ook die buiten de eerste ``limit``.

    ``include_instructions`` (BETON-296, default False): voeg per teruggegeven
    entry (dus begrensd tot ``limit``, nooit tot de volle scan) het opdrachtblok
    toe — dezelfde velden als een webhook-delivery krijgt
    (`webhooks.build_agent_instructions`). ``None`` als er voor dat event geen
    opdracht is (bv. een event zonder item, of een deadline-entry: die heeft
    per constructie geen event om een opdracht uit af te leiden).

    Daarnaast staan er afgeleide deadline-entries in ``items`` (BETON-367,
    ``reason="due"``) — zie de module-docstring. Die tellen mee in
    ``unread_count``: een deadline die de user nog niet gezien heeft is precies
    het signaal waar de teller voor bestaat, en hij klaart vanzelf op zodra hij
    het ticket opent.

    BETON-413: events van een gearchiveerd project vallen af (``LIVE_PROJECT``).
    De poort staat in de SQL en niet in de Python-lus hieronder, want anders eet
    een gearchiveerd project nog steeds het scan-venster (``_SCAN_LIMIT``) op en
    verdringt het de echte events.
    """
    uid = user["id"]
    handle = user["handle"]
    last_seen = user["last_seen_event_id"] or 0
    rows = conn.execute(
        f"""SELECT e.id AS eid, e.type AS type, e.payload AS payload,
                  e.actor_id AS actor_id, e.created_at AS created_at,
                  i.id AS item_id, i.assignee_id AS item_assignee_id,
                  i.title AS title, i.seq AS seq, p.key AS pkey
           FROM events e
           JOIN items i ON i.id = e.item_id
           JOIN projects p ON p.id = i.project_id
           WHERE (e.actor_id IS NULL OR e.actor_id != ?)
             AND i.archived_at IS NULL AND {LIVE_PROJECT}
           ORDER BY e.id DESC LIMIT ?""",
        (uid, _SCAN_LIMIT),
    ).fetchall()

    # Gebatcht (één query) i.p.v. per rij — spiegelt item_reads.unread_bulk.
    item_ids = {r["item_id"] for r in rows}
    per_item_watermarks = item_reads_repo.watermarks_bulk(conn, list(item_ids), uid)
    # BETON-369: één query voor alle gevolgde items van deze user (geen N+1).
    followed = follows_repo.followed_item_ids(conn, uid)

    items: list[dict] = []
    unread = 0
    for r in rows:
        reason = _reason(conn, r, uid, handle, user["kind"], followed)
        if reason is None:
            continue
        item_watermark = per_item_watermarks.get(r["item_id"], 0)
        read = r["eid"] <= last_seen or r["eid"] <= item_watermark
        if not read:
            unread += 1
        if len(items) < limit:
            # BETON-296: `r` draagt zelf al de kolommen die `build_agent_instructions`
            # als "event" nodig heeft (type/payload/actor_id/item_id) — geen extra
            # events-lookup nodig. Alleen voor entries die we ook echt teruggeven
            # (dus begrensd tot `limit`, nooit de volle `_SCAN_LIMIT`-scan).
            instructions = (
                webhooks_mod.build_agent_instructions(conn, r, user)
                if include_instructions
                else None
            )
            entry = {
                "event_id": r["eid"],
                "type": r["type"],
                "reason": reason,
                "actor": handle_of(conn, r["actor_id"]),
                "ref": f"{r['pkey']}-{r['seq']}",
                "title": r["title"],
                "created_at": r["created_at"],
                "read": read,
            }
            if reason == "assigned":
                handover = json.loads(r["payload"]).get("handover_md")
                if handover:
                    entry["handover_md"] = handover
            if include_instructions:
                # Zelfde opdrachtvelden als een webhook-delivery (BETON-296),
                # genest onder `instruction` — een platte `read`-sleutel zou
                # botsen met de bestaande gelezen/ongelezen-vlag hierboven
                # (`entry["read"]`, een bool). `None` als er voor dit event
                # geen opdracht is (bv. een event zonder item).
                entry["instruction"] = instructions
            items.append(entry)
    # Deadlines (BETON-367): afgeleid uit de datum, dus buiten de event-scan om.
    # Vóór de event-entries zodat ze niet achter een volle `limit` verdwijnen.
    due = due_entries(conn, user)
    # Guardrail-concepten (BETON-422): idem afgeleid, idem vóór de event-entries.
    concepts = concept_entries(conn, user)
    # Onbereikbare agents (BETON-457): idem afgeleid, alleen voor mensen.
    unreachable = delivery_health_entries(conn, user)
    for entry in due + concepts + unreachable:
        if not entry["read"]:
            unread += 1
        if include_instructions:
            entry["instruction"] = None

    return {
        "items": unreachable + due + concepts + items,
        "unread_count": unread,
        "last_seen_event_id": last_seen,
    }


def mark_seen(conn: sqlite3.Connection, user_id: int, event_id: int) -> int:
    """Verhoog de read-marker naar ``event_id`` (nooit omlaag). Geeft de nieuwe
    markerwaarde terug."""
    conn.execute(
        "UPDATE users SET last_seen_event_id = MAX(last_seen_event_id, ?) WHERE id = ?",
        (event_id, user_id),
    )
    row = conn.execute(
        "SELECT last_seen_event_id FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return row["last_seen_event_id"] if row else event_id
