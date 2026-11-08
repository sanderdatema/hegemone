"""Webhooks: event→delivery-fanout, HMAC-signing en de dispatcher-loop.

Fanout draait synchroon in de request: bij elk event maken we
`webhook_deliveries`-rijen aan voor de betrokken users met een webhook_url
(assignee, @mentioned, of subscribe_all). Comments zijn gericht (BETON-211/216):
mét @mentions gaan ze alleen naar de gementionden (+ subscribe_all), zónder
mentions naar de assignee; eerdere participants worden alleen nog bij een
vrijgave-event meegenomen (include_prior_participants, zie BETON-110/201).
De actor krijgt nooit zijn eigen event; users zónder webhook_url (o.a. de
Claude Code-user) worden nooit getriggerd.

De feitelijke bezorging gebeurt in een asyncio-achtergrondtaak (lifespan):
`deliver_pending` verwerkt de openstaande deliveries één batch, POST met
`X-Betonning-Signature` (HMAC-SHA256 over de body), en herprobeert tot
`MAX_ATTEMPTS` met exponentiële backoff. Daarnaast dragen deliveries Hermes
Agent-compatibele headers (BETON-104): `X-Webhook-Signature-V2` +
`X-Webhook-Timestamp` (Generic V2, replay-veilig) en `X-Webhook-Signature`
(Generic V1, legacy — ruwe hex zonder `sha256=`-prefix).
"""

from __future__ import annotations

from . import security
from .repo import webhook_tests

from .config import env, runtime_context
from .outbound import outbound
from .repo import installation_settings

import asyncio
import hashlib
import hmac
import html
import json
import logging

from . import webhook_targets
import os
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx

from . import db as db_module
from . import mentions as mentions_mod
from .repo import access
from .repo import comments as comments_repo
from .repo import events as events_repo
from .repo import items as items_repo
from .repo import model_classes as model_classes_repo
from .repo import mutes as mutes_repo
from .repo import follows as follows_repo
from .repo import users as users_repo

log = logging.getLogger("betonning.webhooks")

MAX_ATTEMPTS = 3
DELIVERY_TIMEOUT = 10.0
POLL_INTERVAL = 1.0
CONCURRENCY = 5
# Grace-venster: een delivery wordt pas ná deze wachttijd verzendbaar, zodat een
# snel teruggedraaide actie (bv. een net-geplaatste comment die weer verwijderd
# wordt) de agent niet meer triggert (BETON-18). 0 = direct verzendbaar.
TRIGGER_DELAY = 5.0
# Grace-venster specifiek voor antwoord-notificaties (BETON-262): nadat de laatste
# open vraag op een item beantwoord is, wacht Betonning nog even voordat de
# vragensteller wordt genotificeerd, zodat de mens zijn antwoord nog kan bijstellen
# (dat reset het venster). Bewust langer dan TRIGGER_DELAY.
ANSWER_GRACE = 45.0


def trigger_delay() -> float:
    """De trigger-delay in seconden (env `BETONNING_TRIGGER_DELAY`, default 5)."""
    raw = env("BETONNING_TRIGGER_DELAY")
    if raw is None:
        return TRIGGER_DELAY
    try:
        return max(0.0, float(raw))
    except ValueError:
        return TRIGGER_DELAY


def answer_grace() -> float:
    """Grace-venster voor antwoord-notificaties (env `BETONNING_ANSWER_GRACE`,
    default 45s)."""
    raw = env("BETONNING_ANSWER_GRACE")
    if raw is None:
        return ANSWER_GRACE
    try:
        return max(0.0, float(raw))
    except ValueError:
        return ANSWER_GRACE


def _telegram_api() -> str:
    return env("BETONNING_TELEGRAM_API", "https://api.telegram.org")


def telegram_enabled() -> bool:
    """True als er een Telegram-bot-token geconfigureerd is.

    Zonder token kan een telegram-delivery nooit slagen; we maken die dan ook
    niet aan in de fanout (BETON-43) i.p.v. hem 3 retries te laten afbranden.
    """
    return bool(env("BETONNING_TELEGRAM_TOKEN"))


def telegram_worthy(conn: sqlite3.Connection, event: sqlite3.Row) -> bool:
    """Mag dít event een Telegram-ping opleveren? (BETON-313)

    Telegram is een pushkanaal voor noodzakelijke menselijke acties. De webhook-
    fanout naar agents blijft ongefilterd; deze poort geldt uitsluitend voor het
    telegram-kanaal, ná de gewone doelgroepbepaling (wie geadresseerd is, is dus
    al beslist — dit knijpt alleen af op event-soort).

    Twee soorten halen de lat, allebei "iets kan alleen door een mens verder":

    - **Noodstop** (`item.locked`): alleen een mens ontgrendelt.
    - **Een vraagmodule-vraag** (`comment` met `kind='question'`, BETON-219):
      een agent heeft expliciet menselijke input nodig. Of de vraag aan déze
      ontvanger gericht is, is al door de fanout beslist (mention of assignee);
      hier volstaat "het is een vraag" — met één uitzondering: een
      guardrail-REVIEWvraag (BETON-420) blijft eruit. Daar wacht geen werk op;
      die vraag hoort in de UI-inbox, niet op de telefoon. Een guardrail-
      VOORSTEL is sinds BETON-422 geen vraag meer maar een concept op het
      ticket, dus dat komt hier per constructie niet langs.

    Al het andere — gewone comments, statuswijzigingen, toewijzingen, mentions
    in afsluitberichten — komt níet op Telegram (wel in de UI-inbox)."""
    typ = event["type"]
    if typ == "item.locked":
        return True
    if typ in ("comment.created", "comment.updated"):
        cid = json.loads(event["payload"] or "{}").get("comment_id")
        if cid is None:
            return False
        row = conn.execute(
            "SELECT kind, body_md FROM comments WHERE id = ?", (cid,)
        ).fetchone()
        if row is None or row["kind"] != "question":
            return False
        # BETON-420: een guardrail-REVIEWvraag is wél een vraag aan een mens,
        # maar geen telefoon-waardig signaal — er hangt geen werk op te wachten.
        # Hij blijft gewoon in de UI-inbox en in `GET /questions?open=true`
        # staan. Late import: `triage` importeert deze module.
        from . import triage as triage_mod

        if triage_mod.is_guardrail_review_question(row["body_md"]):
            return False
        return True
    return False


def _public_url() -> str:
    # Nieuwe naam eerst; bestaande installaties behouden hun oude instelling.
    for name in ("HEGEMONE_PUBLIC_URL", "BETONNING_PUBLIC_URL"):
        value = os.environ.get(name, "").strip()
        if value:
            return value.rstrip("/")
    return env("BETONNING_PUBLIC_URL", "http://localhost:8000") or "http://localhost:8000"


# --- Webhook-URL-poort (BETON-378) ----------------------------------------
# Een webhook-URL is een uitgaande HTTP-POST vanaf de server: wie hem mag zetten,
# kiest waar Betonning naartoe verbindt én wie de payload leest. Vandaar twee
# lagen: agents mogen hun eigen URL niet zetten (api/me.py), en de URL zelf moet
# door deze poort — zowel bij het opslaan (422) als vlak vóór het vuren.
#
# Loopback (127.0.0.0/8, ::1) en link-local (169.254.0.0/16 — inclusief het
# cloud-metadata-adres 169.254.169.254) zijn altijd verboden: dat zijn de
# adressen waarmee je de server tegen zichzelf keert. Bewust NIET heel RFC1918:
# zelfgehoste ontvangers kunnen op een privénetwerk staan. Wie strakker wil,
# configureert expliciet de allowlist.
ALLOWED_HOSTS_ENV = "BETONNING_WEBHOOK_ALLOWED_HOSTS"
ALLOW_LOOPBACK_ENV = "BETONNING_WEBHOOK_ALLOW_LOOPBACK"


def allowed_webhook_hosts() -> list[str]:
    """De allowlist uit de env (komma-lijst). Leeg = alles behalve loopback/
    link-local (de dev-/huidige-prod-stand)."""
    raw = env(ALLOWED_HOSTS_ENV, "")
    return [h.strip().lower() for h in raw.split(",") if h.strip()]


def loopback_allowed() -> bool:
    """Escape voor tests/dev die een echte mock-receiver op 127.0.0.1 draaien
    (`BETONNING_WEBHOOK_ALLOW_LOOPBACK=1`). Standaard uit."""
    return env(ALLOW_LOOPBACK_ENV, "").strip().lower() not in (
        "",
        "0",
        "false",
        "no",
    )


def _host_matches(host: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        suffix = pattern[2:]
        return host == suffix or host.endswith("." + suffix)
    return host == pattern


def webhook_url_error(url: str | None) -> str | None:
    """None = toegestaan, anders de reden (geschikt als 422-detail)."""
    if url is None or not str(url).strip():
        return None  # leegmaken/ontkoppelen mag altijd
    try:
        parsed = urlsplit(str(url).strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        raw_port = parsed.port
        if raw_port is not None and raw_port == 0:
            return "webhook-url heeft een ongeldige poort"
        port = raw_port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return "webhook-url heeft een ongeldige host of poort"
    if parsed.scheme not in ("http", "https"):
        return "webhook-url moet http of https zijn"
    if not host:
        return "webhook-url mist een host"
    if parsed.username is not None or parsed.password is not None:
        return "webhook-url mag geen gebruikersgegevens bevatten"
    if not loopback_allowed():
        if host == "localhost" or host.endswith(".localhost"):
            return "webhook-host niet toegestaan: localhost"
        ip = webhook_targets.canonical_ip(host)
        if ip is not None and webhook_targets.forbidden(str(ip)):
            return f"webhook-host niet toegestaan: {host}"

    allowed = allowed_webhook_hosts()
    if allowed and not any(_host_matches(host, p) or _host_matches(f"{host}:{port}", p) for p in allowed):
        return f"webhook-host niet toegestaan: {host}"
    return None



# Leesbare werkwoorden per event-type voor het Telegram-bericht.
_TG_VERBS = {
    "item.created": "telegram.verb.1",
    "item.updated": "telegram.verb.2",
    "item.archived": "telegram.verb.3",
    "comment.created": "telegram.verb.4",
    "comment.updated": "telegram.verb.5",
    "relation.created": "telegram.verb.6",
    "relation.deleted": "telegram.verb.7",
}


def _fmt(dt: datetime) -> str:
    """Formatteer naar de db-timestampvorm (`%Y-%m-%dT%H:%M:%S.mmmZ`, UTC)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _backoff_seconds(attempts: int) -> int:
    """Exponentiële backoff: 2s, 4s, 8s, … na resp. 1, 2, 3 mislukkingen."""
    return 2**attempts


def sign(secret: str | None, body: bytes) -> str:
    """HMAC-SHA256 over de body, als `sha256=<hex>`."""
    digest = hmac.new((secret or "").encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def sign_raw(secret: str | None, body: bytes) -> str:
    """HMAC-SHA256 over de body, als ruwe hex (Hermes Generic V1, BETON-104)."""
    return hmac.new((secret or "").encode("utf-8"), body, hashlib.sha256).hexdigest()


def sign_v2(secret: str | None, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 over `"<timestamp>.<body>"`, als ruwe hex (Hermes Generic V2,
    replay-veilig — BETON-104). Tekent over de exacte bytes die verzonden worden:
    de timestamp-string plus een punt, gevolgd door de ruwe body-bytes."""
    signed = f"{timestamp}.".encode("utf-8") + body
    return hmac.new((secret or "").encode("utf-8"), signed, hashlib.sha256).hexdigest()


# --- Fanout (synchroon, in de request) ------------------------------------


def prior_participants(conn: sqlite3.Connection, item_id: int) -> set[str]:
    """Handles die al eerder bij dit item betrokken waren (BETON-110/199).

    Telt mee: de maker (``created_by``), elke comment-auteur, en elke
    @mention in de omschrijving of in een bestaande comment. Gebruikt zodat
    iemand die eerder meepraatte (of gementiond werd) — of het item maakte —
    zonder verse mention toch een nieuwe comment/vrijgave op hetzelfde item te
    zien krijgt — hetzelfde re-trigger-patroon dat de assignee al had.
    """
    handles: set[str] = set()
    item = items_repo.get(conn, item_id)
    if item is not None:
        handles.update(mentions_mod.parse(item["description_md"]))
        if item["created_by"] is not None:
            creator = users_repo.get(conn, item["created_by"])
            if creator is not None:
                handles.add(creator["handle"])
    for c in comments_repo.list_for_item(conn, item_id):
        if c["author_id"] is not None:
            author = users_repo.get(conn, c["author_id"])
            if author is not None:
                handles.add(author["handle"])
        handles.update(mentions_mod.parse(c["body_md"]))
    return handles


def derived_subscribers(conn: sqlite3.Connection, item_id: int) -> list[int]:
    """De afgeleide subscribers-union van een item (BETON-245).

    Dezelfde bronnen als de fanout kan raken: de assignee, alle eerdere
    participants (maker/comment-auteurs/mentions, zie ``prior_participants``),
    de globale ``subscribe_all``-users en de expliciete volgers (BETON-369). Alleen actieve users, ontdubbeld op id,
    stabiel gesorteerd. De mute-status zit hier bewust NIET in — dat leidt de
    caller af uit ``mutes``. Puur een leesfunctie voor het volgers-overzicht.
    """
    ids: set[int] = set()
    item = conn.execute(
        "SELECT assignee_id FROM items WHERE id = ?", (item_id,)
    ).fetchone()
    if item is not None and item["assignee_id"] is not None:
        ids.add(item["assignee_id"])
    for handle in prior_participants(conn, item_id):
        user = users_repo.get_by_handle(conn, handle)
        if user is not None:
            ids.add(user["id"])
    for row in conn.execute("SELECT id FROM users WHERE subscribe_all = 1").fetchall():
        ids.add(row["id"])
    # BETON-369: expliciete volgers horen ook in het overzicht.
    ids |= follows_repo.follower_ids(conn, item_id)
    active = [
        uid
        for uid in ids
        if (u := users_repo.get(conn, uid)) is not None and u["active"]
    ]
    return sorted(active)


def _previous_assignee_id(conn: sqlite3.Connection, event: sqlite3.Row) -> int | None:
    """De id van de vórige assignee, als dít event de toewijzing wijzigde
    (BETON-293).

    Strikt afgebakend — dit is de enige plek in de A-keten die notificaties
    tóevoegt, dus elke voorwaarde is een bewuste rem:

    - alleen ``item.updated`` (het enige event-type met een veld-diff);
    - alleen als ``assignee`` daadwerkelijk in de diff zit;
    - alleen als er een ``from`` ís (van niemand → iemand voegt niets toe);
    - niet bij ``from == to`` (een no-op is geen wijziging).

    De rest van de poorten (actor, actief, mute, `access`-niveau `none`, wel/geen
    webhook_url) doet de gewone `fanout`-lus al — die gelden hier onverkort.
    """
    if event["type"] != "item.updated":
        return None
    payload = json.loads(event["payload"])
    change = payload.get("assignee")
    if not isinstance(change, dict):
        return None
    previous = change.get("from")
    if not previous or previous == change.get("to"):
        return None
    user = users_repo.get_by_handle(conn, previous)
    return user["id"] if user is not None else None


def fanout(
    conn: sqlite3.Connection,
    *,
    event: sqlite3.Row,
    mentions: Iterable[str] = (),
    include_prior_participants: bool = False,
    directed: bool = False,
    delay: float | None = None,
) -> list[int]:
    """Maak deliveries voor de betrokken webhook-users. Geeft hun id's terug.

    ``mentions`` zijn de handles die voor dít event genotificeerd moeten worden.
    Bij ``include_prior_participants`` ontvangen ook eerder betrokken agents
    (maker, eerdere comment-auteurs, eerdere mentions — zie ``prior_participants``)
    een delivery. Dat gebruiken we uitsluitend wanneer werk weer wordt vrijgegeven;
    gewone itemupdates mogen geen participant-spam veroorzaken.

    ``directed`` (BETON-216): het event is expliciet geadresseerd — een comment
    mét @mentions richt zich tot die handles, dus de assignee wordt dan níet
    automatisch toegevoegd (alleen als hij zelf gementiond is). Zo praat een
    assignee-agent niet mee op een vraag die aan iemand anders gericht was
    (BRAND-150: Joop antwoordde op een vraag aan Lobke). subscribe_all is een
    expliciete alles-opt-in en blijft ook op gerichte events gelden.

    Bewust GEEN blinde uitbreiding naar alle assign-agents op het project (was
    BETON-184, teruggedraaid via BETON-201): een agent die nooit iets met het
    item te maken had — niet gemaakt, niet toegewezen, niet gementiond, geen
    comment geplaatst — hoort geen notificatie te krijgen puur omdat hij
    toegangsniveau ``assign`` heeft op het project. Alleen daadwerkelijk
    betrokken agents (of mensen) worden genotificeerd.
    """
    item_id = event["item_id"]
    actor_id = event["actor_id"]

    # ``delay`` overschrijft de standaard trigger-delay (BETON-262: langer grace-
    # venster voor antwoord-notificaties).
    delay = trigger_delay() if delay is None else max(0.0, delay)
    not_before = (
        _fmt(datetime.now(timezone.utc) + timedelta(seconds=delay))
        if delay > 0
        else None
    )

    # BETON-123: het project van het item bepaalt de per-agent toegang. Bij
    # project-loze events (item_id is None) is er geen project → geen filtering.
    project_id: int | None = None
    recipients: set[int] = set()
    if item_id is not None:
        item = conn.execute(
            "SELECT assignee_id, project_id FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        if item is not None:
            project_id = item["project_id"]
            if item["assignee_id"] is not None and not directed:
                recipients.add(item["assignee_id"])
            # BETON-293: de VÓRIGE assignee hoorde tot nu toe nooit dat het ticket
            # bij hem weg was — en kon dus doorwerken aan iets dat niet meer van
            # hem is. Dit is gericht (alleen hij, geen bijvangst) en staat los van
            # `directed`: een toewijzingswijziging is per definitie aan hém
            # geadresseerd, en `directed` speelt alleen bij comment-events, waar
            # nooit een assignee-diff in zit. `build_instructions` maakt hier
            # `stand_down` van — dit type notificatie STOPT werk in plaats van het
            # te starten (werkt dus mét BETON-282 mee).
            previous_assignee_id = _previous_assignee_id(conn, event)
            if previous_assignee_id is not None:
                recipients.add(previous_assignee_id)
            if include_prior_participants:
                for handle in prior_participants(conn, item_id):
                    user = users_repo.get_by_handle(conn, handle)
                    if user is not None:
                        recipients.add(user["id"])
            # BETON-369: expliciete volgers van dít item. Bij een GERICHT event
            # (een comment mét mentions) blijven ze buiten schot tenzij ze zelf
            # gementiond zijn — een volger leest mee, hij hoort niet mee te
            # praten op een vraag aan iemand anders (dezelfde lijn als
            # BETON-216 voor de assignee). `subscribe_all` is bewust wél een
            # alles-opt-in en blijft ook op gerichte events gelden; volgen is
            # dat niet.
            if not directed:
                recipients |= follows_repo.follower_ids(conn, item_id)
    for handle in mentions:
        user = users_repo.get_by_handle(conn, handle)
        if user is not None:
            recipients.add(user["id"])
    for row in conn.execute("SELECT id FROM users WHERE subscribe_all = 1").fetchall():
        recipients.add(row["id"])

    # BETON-245: een user die dit item gemute heeft valt volledig uit de fanout —
    # ook als assignee, participant of subscribe_all. De mute is een filter over
    # de afgeleide doelgroep, niet een aparte subscribers-tabel.
    if item_id is not None:
        recipients -= mutes_repo.muted_user_ids(conn, item_id)

    created: list[int] = []
    for uid in sorted(recipients):
        if uid == actor_id:
            continue
        user = users_repo.get(conn, uid)
        if user is None or not user["active"]:
            continue
        # BETON-123: een agent met effectief niveau 'none' op dit project wordt
        # nooit getriggerd — ook niet via @mention of subscribe_all.
        if (
            project_id is not None
            and access.effective_level(conn, project_id, user) == "none"
        ):
            continue
        # Een user kan via meerdere kanalen bereikbaar zijn (webhook én Telegram).
        channels = []
        if user["webhook_url"] is not None:
            channels.append("webhook")
        # Telegram alleen als er ook een bot-token is; anders is de delivery bij
        # voorbaat kansloos en slaan we hem over (BETON-43). Én alleen voor
        # events die de telegram-lat halen (BETON-313): dit kanaal meldt noodzakelijke acties,
        # geen algemene activiteitenstroom — zie `telegram_worthy`.
        if (
            user["telegram_chat_id"] is not None
            and telegram_enabled()
            and telegram_worthy(conn, event)
        ):
            channels.append("telegram")
        for channel in channels:
            cur = conn.execute(
                "INSERT INTO webhook_deliveries (event_id, user_id, channel, not_before) "
                "VALUES (?, ?, ?, ?)",
                (event["id"], uid, channel, not_before),
            )
            assert cur.lastrowid is not None
            created.append(cur.lastrowid)
    return created


def record_and_fanout(
    conn: sqlite3.Connection,
    *,
    type: str,
    item_id: int | None = None,
    actor_id: int | None = None,
    payload: dict | None = None,
    **fanout_kwargs,
) -> sqlite3.Row:
    """`events_repo.record` + `fanout` in één (BETON-321).

    Het paar herhaalde zich ~10× in de `apply_*`-functies van triage.py/
    decompose.py. `**fanout_kwargs` gaat ongewijzigd door naar `fanout` — dus
    `mentions=`, `directed=`, `include_prior_participants=` en `delay=` werken
    hier hetzelfde als op een losse `fanout`-aanroep. Geeft het opgeslagen
    event terug (zelfde vorm als `events_repo.record`)."""
    event = events_repo.record(
        conn, type=type, item_id=item_id, actor_id=actor_id, payload=payload
    )
    fanout(conn, event=event, **fanout_kwargs)
    return event


def notify_reactivations(conn: sqlite3.Connection, affected: list[dict]) -> None:
    """Schrijf per gereactiveerd deferred-item een `item.updated`-event +
    webhook-fanout (BETON-164).

    `affected` komt van `repo.items.reactivate_deferred` (zelf pure data-access,
    zonder events/fanout). Deze functie draait zowel binnen een verzoek
    (self-heal in `GET /items/{ref}`) als buiten een verzoek (de periodieke
    `deferred_worker.reactivate_loop`); er is dus geen menselijke/agent-actor
    die de overgang aanvroeg.

    De actor is daarom `triage` (BETON-354), dezelfde lijn als de automatische
    noodstop (BETON-338): niet niemand, maar de hoeder van Betonning. Vóór
    BETON-354 stond hier `actor_id=None` en las de tijdlijn "@? status:
    deferred → todo" — een overgang zonder herkenbare afzender. `fanout` slaat
    de actor over, maar triage is hier nooit ontvanger, dus dat filtert niemand
    weg. Valt triage weg (niet-geseede db), dan blijft het `None` en werkt
    alles zoals voorheen.

    De payload draagt naast de state-diff een `reason`-marker
    (`deferred_expired`) zodat de UI de overgang kan benoemen ("uitstel
    verlopen") i.p.v. alleen de kale statuswissel — spiegelt `item.locked`,
    dat zijn aanleiding ook in `payload.reason` meegeeft."""
    triage = users_repo.get_by_handle(conn, "triage")
    actor_id = triage["id"] if triage is not None else None
    for entry in affected:
        from_state = conn.execute(
            "SELECT name FROM states WHERE id = ?", (entry["from_state_id"],)
        ).fetchone()
        to_state = conn.execute(
            "SELECT name FROM states WHERE id = ?", (entry["to_state_id"],)
        ).fetchone()
        payload = {
            "state": {
                "from": from_state["name"] if from_state else None,
                "to": to_state["name"] if to_state else None,
            },
            "deferred_until": {"from": entry["from_deferred_until"], "to": None},
            "reason": "deferred_expired",
        }
        event = events_repo.record(
            conn,
            type="item.updated",
            item_id=entry["id"],
            actor_id=actor_id,
            payload=payload,
        )
        fanout(conn, event=event)


def work_was_unblocked(
    conn: sqlite3.Connection, before_state_id: int | None, after_state_id: int | None
) -> bool:
    """True wanneer een statewisseling uitvoering voor agents vrijgeeft."""
    if before_state_id is None or after_state_id is None:
        return False
    rows = conn.execute(
        "SELECT id, blocks_work FROM states WHERE id IN (?, ?)",
        (before_state_id, after_state_id),
    ).fetchall()
    blocks_work = {row["id"]: bool(row["blocks_work"]) for row in rows}
    return blocks_work.get(before_state_id, False) and not blocks_work.get(
        after_state_id, False
    )


def is_event_still_actionable(conn: sqlite3.Connection, event: sqlite3.Row) -> bool:
    """False als de aanleiding van dit event intussen verdwenen is.

    Bij het vuurmoment (na het delay-venster) her-checken we of een comment-event
    nog een bestaande comment betreft; is die binnen het venster verwijderd, dan
    hoeft de agent niet meer te reageren (BETON-18).
    """
    if event["type"] in ("comment.created", "comment.updated"):
        payload = json.loads(event["payload"])
        comment_id = payload.get("comment_id")
        if comment_id is not None:
            return comments_repo.get(conn, comment_id) is not None
    if event["type"] == "question.answered":
        # De aanleiding = de beantwoorde vraag. Actionable zolang de vraag bestaat
        # en nog steeds beantwoord is (BETON-262).
        payload = json.loads(event["payload"])
        q = comments_repo.get(conn, payload.get("comment_id"))
        return q is not None and q["answered_at"] is not None
    return True


# --- Antwoord-notificaties (BETON-262/263) --------------------------------


def _answer_events_without_delivery(
    conn: sqlite3.Connection, item_id: int, question_id: int
) -> sqlite3.Row | None:
    """Het jongste `question.answered`-event van deze vraag dat nog geen delivery
    heeft (dus nog niet is vrijgegeven). None als er niets te doen is."""
    return conn.execute(
        "SELECT e.* FROM events e WHERE e.item_id = ? AND e.type = 'question.answered' "
        "AND json_extract(e.payload, '$.comment_id') = ? "
        "AND NOT EXISTS (SELECT 1 FROM webhook_deliveries d WHERE d.event_id = e.id) "
        "ORDER BY e.id DESC LIMIT 1",
        (item_id, question_id),
    ).fetchone()


def release_answer_notifications(conn: sqlite3.Connection, item_id: int) -> list[int]:
    """Geef de ingehouden antwoord-notificaties van een item vrij (BETON-262).

    Doet niets zolang er nog open vragen op het item zijn. Zodra álle vragen
    beantwoord zijn, wordt per beantwoorde vraag zijn `question.answered`-event
    gefanout naar de vragensteller, met het antwoord-grace-venster. Geeft de
    aangemaakte delivery-id's terug."""
    if comments_repo.open_questions_for_item(conn, item_id):
        return []
    grace = answer_grace()
    created: list[int] = []
    for q in comments_repo.answered_questions_for_item(conn, item_id):
        ev = _answer_events_without_delivery(conn, item_id, q["id"])
        if ev is None:
            continue
        asker = users_repo.get(conn, q["author_id"]) if q["author_id"] else None
        mentions = {asker["handle"]} if asker else set()
        created += fanout(conn, event=ev, mentions=mentions, directed=True, delay=grace)
    return created


def reset_answer_grace(conn: sqlite3.Connection, question_id: int) -> None:
    """Verschuif het grace-venster van de nog-pending antwoord-delivery(s) van een
    vraag naar voren (BETON-263: bijstellen van een antwoord binnen het venster
    reset de wachttijd)."""
    grace = answer_grace()
    not_before = (
        _fmt(datetime.now(timezone.utc) + timedelta(seconds=grace))
        if grace > 0
        else None
    )
    conn.execute(
        "UPDATE webhook_deliveries SET not_before = ? WHERE status = 'pending' "
        "AND event_id IN (SELECT id FROM events WHERE type = 'question.answered' "
        "AND json_extract(payload, '$.comment_id') = ?)",
        (not_before, question_id),
    )


def answer_locked(conn: sqlite3.Connection, question: sqlite3.Row) -> bool:
    """Is het antwoord op deze vraag al verstuurd (en dus niet meer te wijzigen)?

    True zodra een antwoord-delivery daadwerkelijk is afgeleverd (BETON-263).
    Historische antwoorden (pre-BETON-265, met een answer_comment_id) zijn
    onveranderlijk. Een onbeantwoorde vraag is per definitie niet 'locked'."""
    if question["answered_at"] is None:
        return False
    if question["answer_comment_id"] is not None:
        return True
    r = conn.execute(
        "SELECT 1 FROM webhook_deliveries d JOIN events e ON e.id = d.event_id "
        "WHERE e.type = 'question.answered' "
        "AND json_extract(e.payload, '$.comment_id') = ? AND d.status = 'delivered' "
        "LIMIT 1",
        (question["id"],),
    ).fetchone()
    return r is not None


# --- Delivery (async, in de dispatcher) -----------------------------------


def build_payload(conn: sqlite3.Connection, event: sqlite3.Row) -> dict:
    """De JSON-body die naar de webhook-URL gaat."""
    item = None
    if event["item_id"] is not None:
        row = items_repo.get(conn, event["item_id"])
        if row is not None:
            item = items_repo.serialize(conn, row)
    return {"event": events_repo.serialize(conn, event), "item": item}


def build_agent_policy(conn: sqlite3.Connection, item: sqlite3.Row | None) -> dict:
    """Bepaal wat een agent op basis van de huidige state mag doen."""
    state_name = None
    blocks_work = False
    if item is not None and item["state_id"] is not None:
        state = conn.execute(
            "SELECT name, blocks_work FROM states WHERE id = ?", (item["state_id"],)
        ).fetchone()
        if state is not None:
            state_name = state["name"]
            blocks_work = bool(state["blocks_work"])
    return {
        "state": state_name,
        "work_allowed": not blocks_work,
        "allowed_actions": ["comment"] if blocks_work else ["comment", "execute"],
        "reason": (
            outbound('build_agent_policy.1')
            if blocks_work
            else None
        ),
    }


def _state_transition(
    conn: sqlite3.Connection, event: sqlite3.Row, item: sqlite3.Row
) -> dict:
    """Voeg de betekenis van een statewisseling toe aan een webhook-trigger."""
    if event["type"] != "item.updated":
        return {}
    change = json.loads(event["payload"]).get("state")
    if not isinstance(change, dict):
        return {}

    def describe(name: str | None) -> tuple[dict, str | None]:
        if name is None:
            return {"name": None, "blocks_work": False}, None
        state = conn.execute(
            "SELECT blocks_work, grp FROM states WHERE project_id = ? AND name = ? COLLATE NOCASE",
            (item["project_id"], name),
        ).fetchone()
        blocks_work = bool(state and state["blocks_work"])
        grp = state["grp"] if state is not None else None
        return {"name": name, "blocks_work": blocks_work}, grp

    before, _before_grp = describe(change.get("from"))
    after, after_grp = describe(change.get("to"))
    result: dict = {"state_change": {"from": before, "to": after}}
    # `to_state_grp` blijft los van `state_change` (die dict-vorm ligt vast in
    # tests) — BETON-291/293 gebruiken de state-GROEP (`states.grp`) om te
    # beslissen of een statewissel "afgerond" betekent, nooit door op de naam
    # te matchen (gemigreerde projecten gebruiken andere state-namen dan BETON
    # zelf gebruikt).
    result["to_state_grp"] = after_grp
    if before["blocks_work"] and not after["blocks_work"]:
        result["work_unblocked"] = True
    elif not before["blocks_work"] and after["blocks_work"]:
        result["work_blocked"] = True
    return result


_TRIGGER_EXCERPT_MAX = 300


def build_trigger(
    conn: sqlite3.Connection, event: sqlite3.Row, user: sqlite3.Row
) -> dict | None:
    """Per-ontvanger context: waarom kreeg déze user dit event (BETON-110).

    Alles wordt op verzendmoment herleid uit event/item/user — er wordt niets
    extra gepersisteerd voor de fanout-beslissing zelf. ``type`` is de meest
    specifieke reden die van toepassing is: een verse mention weegt zwaarder
    dan assignee, wat weer zwaarder weegt dan 'was al eerder betrokken'.
    """
    item_id = event["item_id"]
    if item_id is None:
        return None
    item = items_repo.get(conn, item_id)
    if item is None:
        return None

    actor = None
    if event["actor_id"] is not None:
        actor_row = users_repo.get(conn, event["actor_id"])
        actor = actor_row["handle"] if actor_row is not None else None

    excerpt: str | None = None
    mentioned_in: str | None = None
    # BETON-216: aan wie is deze comment gericht? Alleen zinvol bij comment-
    # events; None bij andere events (daar bestaat geen adressering). Een lege
    # lijst betekent "ongerichte comment" (niemand gementiond). Ontvangers die
    # niet in de lijst staan (subscribe_all) weten zo dat ze alleen meelezen.
    addressed_to: list[str] | None = None
    if event["type"] in ("comment.created", "comment.updated"):
        ev_payload = json.loads(event["payload"])
        comment_id = ev_payload.get("comment_id")
        comment = (
            comments_repo.get(conn, comment_id) if comment_id is not None else None
        )
        if comment is not None:
            excerpt = comment["body_md"]
            mentioned_in = "comment"
            addressed_to = sorted(mentions_mod.parse(excerpt))
    if excerpt is None and item["description_md"]:
        excerpt = item["description_md"]
        mentioned_in = "description"

    handle = user["handle"]
    if handle in mentions_mod.parse(excerpt):
        trigger_type = "mention"
    elif item["assignee_id"] == user["id"]:
        trigger_type = "assigned"
    elif handle in prior_participants(conn, item_id):
        trigger_type = "participant"
    else:
        trigger_type = "subscribe_all"

    trigger = {
        "type": trigger_type,
        "mentioned_by": actor,
        "mentioned_in": mentioned_in,
        "addressed_to": addressed_to,
        "excerpt": excerpt[:_TRIGGER_EXCERPT_MAX] if excerpt else None,
        "is_question": bool(excerpt and "?" in excerpt),
    }
    trigger.update(_state_transition(conn, event, item))
    trigger.update(_changed_fields_signal(event, user))
    trigger.update(_relation_signal(event))
    return trigger


def _changed_fields_signal(event: sqlite3.Row, user: sqlite3.Row) -> dict:
    """Welke velden wijzigden er in dit event, voor `item.updated` (BETON-291).

    `event.payload` draagt op dat event-type al een `{veld: {from, to}}`-diff
    (zie `api/items.py:update_item`/`_emit_label_change`) — hier lezen we 'm
    alleen uit, zonder nieuwe data te verzinnen. `changed_fields` is de
    gesorteerde lijst gewijzigde velden; `assignee_changed_to_me` zegt of DEZE
    ontvanger in dit event de nieuwe assignee werd (relevant voor
    `build_instructions`: een labelwijziging is geen "pak dit op").
    Voor niet-`item.updated`-events (mention/comment/relatie/…) geven we niets
    terug — de aanroeper valt dan terug op het bestaande gedrag."""
    if event["type"] != "item.updated":
        return {}
    payload = json.loads(event["payload"])
    changed_fields = sorted(payload.keys())
    signal: dict = {"changed_fields": changed_fields}
    assignee_change = payload.get("assignee")
    if isinstance(assignee_change, dict):
        signal["assignee_changed_to_me"] = assignee_change.get("to") == user["handle"]
        # BETON-293: de spiegel — is het item juist bij DEZE ontvanger WEGgehaald?
        # Dat is het enige signaal waaruit `stand_down` op rij 7 volgt; de
        # ontvanger is dan per definitie niet meer de assignee, dus `build_trigger`
        # zou hem hooguit als 'participant'/'subscribe_all' typeren.
        signal["assignee_changed_from_me"] = assignee_change.get("from") == user[
            "handle"
        ] and assignee_change.get("from") != assignee_change.get("to")
    return signal


def _relation_signal(event: sqlite3.Row) -> dict:
    """Wélke relatie werd er gelegd/verwijderd, gezien vanuit DIT item (BETON-293).

    Cruciaal is de richting. `api/items.py` schrijft het event altijd op het item
    waarop de API-aanroep gedaan werd, met het door de aanroeper gebruikte verbum
    in de payload. Dat verbum is dus al relatief aan dít item:

      - `blocked_by`   → dít item wordt geblokkeerd (rij 19/21);
      - `duplicate_of` → dít item ís het duplicaat (rij 20);
      - `blocks`/`duplicated_by` → dít item is juist de blokkeerder/het canonieke
        item; die kant krijgt géén `stand_down`.

    Dat sluit aan op de opslag (`repo/relations.py`): de opgeslagen `item_id` (src)
    is altijd de blokkeerder resp. het duplicaat.
    """
    if event["type"] not in ("relation.created", "relation.deleted"):
        return {}
    payload = json.loads(event["payload"])
    rel_type = payload.get("type")
    if not isinstance(rel_type, str):
        return {}
    return {"relation_type": rel_type}


def _stand_down_reason(trigger: dict, event_type: str | None) -> str:
    """Waaróm moet deze agent stoppen (BETON-293)? Eén NL-zinsdeel per matrixrij;
    zonder die reden is `stand_down` een bevel zonder grond."""
    if trigger.get("assignee_changed_from_me"):
        return outbound('stand_down_reason.1')
    if event_type == "item.archived":
        return outbound('stand_down_reason.2')
    if event_type == "relation.created":
        if trigger.get("relation_type") == "blocked_by":
            return outbound('stand_down_reason.3')
        if trigger.get("relation_type") == "duplicate_of":
            return outbound('stand_down_reason.4')
    if trigger.get("to_state_grp") == "cancelled":
        return outbound('stand_down_reason.5')
    return outbound('stand_down_reason.6')


def _instruction_reason(trigger: dict) -> str:
    """Waarom kreeg deze agent dit event, in één NL-zinsdeel (voor de instructie)."""
    actor = trigger.get("mentioned_by")
    by = f"@{actor}" if actor else outbound('instruction_reason.1')
    if trigger.get("work_unblocked"):
        return outbound('instruction_reason.2')
    return {
        "mention": outbound('instruction_reason.3', p0=(by)),
        "assigned": outbound('instruction_reason.4'),
        "participant": outbound('instruction_reason.5'),
        "subscribe_all": outbound('instruction_reason.6'),
    }.get(trigger.get("type") or "", outbound('instruction_reason.7'))


# Rangorde bij meerdere gewijzigde velden in één item.updated-event (BETON-291):
# een expliciete lijst i.p.v. laten ontstaan uit de volgorde van if-takken. Alleen
# `assignee` en `state` wegen zwaar genoeg om een actie op te leveren; al het
# overige (labels/priority/description_md/plan_md/milestone/deferred_until/…)
# is louter informatief.
_FIELD_ACTION_RANK = ("assignee", "state")


def _field_based_action(
    trigger: dict, work_allowed: bool, is_assignee: bool = False
) -> str | None:
    """Leid `expected_action` af uit wélk veld wijzigde, niet uit "jij bent
    assignee/participant" (BETON-291, de kern van BETON-282).

    Alleen zinvol voor `item.updated`-events — `build_trigger` zet dan
    `changed_fields` (en evt. `assignee_changed_to_me`/`to_state_grp`) op de
    trigger. Ontbreekt die info (ander event-type, of een handmatig
    samengestelde trigger zoals in de pure unit-tests), dan geven we `None`
    terug — de aanroeper valt dan terug op het bestaande gedrag.
    """
    changed_fields = trigger.get("changed_fields")
    if changed_fields is None:
        return None
    for field in _FIELD_ACTION_RANK:
        if field not in changed_fields:
            continue
        if field == "assignee":
            if trigger.get("assignee_changed_to_me"):
                return "pick_up" if work_allowed else "acknowledge"
            # BETON-293 rij 7: het item is bij DEZE ontvanger weggehaald — stop
            # met waar je mee bezig was. Dit is het enige geval waarin een
            # niet-assignee toch een opdracht krijgt.
            if trigger.get("assignee_changed_from_me"):
                return "stand_down"
            continue
        if field == "state":
            # State-GROEP via `states.grp` (nooit op naam — gemigreerde
            # projecten gebruiken andere namen dan BETON zelf). Belangrijk:
            # deze check moet vóór `work_unblocked`, want een blokkerende state
            # (bv. "blocked", blocks_work=1) naar "done" (blocks_work=0) zet óók
            # `work_unblocked` — dat is geen vrijgave van werk, het item wordt
            # juist gesloten.
            if trigger.get("to_state_grp") in ("completed", "cancelled"):
                # BETON-293 rij 9 (was `none` in A2): het item is afgerond of
                # geannuleerd. Voor de assignee is dat een expliciet stopsein —
                # niet alsnog "even afronden". Voor een meelezer/participant valt
                # er niets te stoppen; die krijgt het louter ter info.
                return "stand_down" if is_assignee else "none"
            if trigger.get("work_unblocked"):
                return "pick_up" if work_allowed else "acknowledge"
            return "none"
    # Geen van de zwaarwegende velden wijzigde (bv. alleen labels/priority/
    # description_md/plan_md) → louter ter info, geen opdracht.
    return "none"


# --- BETON-292: `do`/`do_not`/`read` als gestructureerde velden ------------
#
# De payload was tot dusver alleen "wat mág" (`expected_action`/`instructions`);
# De payload bevat expliciete grenzen ("wat moet vooral NIET") en een leeslijst
# ("welke bron, hoe, waarom") die naast — niet in plaats van — de bestaande
# `instructions`-tekst staat. Grenzen worden AFGELEID uit wat al berekend is
# (`agent_policy`, `access.effective_level`, `trigger.addressed_to`), nooit
# verzonnen.


def _ownership_action(
    trigger: dict, event_type: str | None, is_assignee: bool, work_allowed: bool
) -> str | None:
    """De 'dit is niet (meer) van jou'-gevallen (BETON-293, matrixrijen 7/17/19-21).

    Deze wegen zwaarder dan de gewone triggertype-keuze en worden daarom als
    eerste bekeken. Rij 7 is de reden dat dat móet: bij een weggehaalde
    toewijzing is de ontvanger per definitie niet meer de assignee, dus
    `build_trigger` typeert hem als 'participant' of zelfs 'subscribe_all' —
    beide zouden anders `none` opleveren en het stopsein inslikken.

    Geeft `None` als geen van deze gevallen van toepassing is (de aanroeper
    beslist dan op de gewone manier)."""
    # Rij 7 — het item is bij deze ontvanger weggehaald.
    if trigger.get("assignee_changed_from_me"):
        return "stand_down"
    # BETON-302 — de noodstop staat erop: STOP, ongeacht wie je bent. Net als
    # rij 7 vóór de is_assignee-poort: het event gaat gericht naar de mensen, dus
    # een agent die het tóch ziet (subscribe_all) is per definitie geen assignee
    # en zou anders `none` krijgen — "ter info" in plaats van "stoppen".
    if event_type == "item.locked":
        return "stand_down"
    # De overige rijen gelden alleen voor de assignee: alleen wie eraan wérkt
    # kan gevraagd worden te stoppen. Een meelezer heeft niets te stoppen.
    if not is_assignee:
        return None
    # Rij 17 — het item is gearchiveerd. (`item.deleted` kent geen fanout: dat
    # event wordt met `item_id=None` weggeschreven, zie `api/items.py:delete_item`,
    # dus daar bestaat geen ontvanger voor.)
    if event_type == "item.archived":
        return "stand_down"
    relation_type = trigger.get("relation_type")
    if event_type == "relation.created":
        # Rij 19/20 — richting is alles: alleen `blocked_by`/`duplicate_of` zeggen
        # iets over DIT item (het wordt geblokkeerd / het ís het duplicaat). De
        # tegenhangers `blocks`/`duplicated_by` betekenen juist dat dit item de
        # blokkeerder resp. het canonieke item is; die assignee werkt gewoon door.
        if relation_type in ("blocked_by", "duplicate_of"):
            return "stand_down"
    elif event_type == "relation.deleted":
        # Rij 21 — de blokkade is opgeheven; de tegenhanger van rij 19.
        if relation_type == "blocked_by":
            return "pick_up" if work_allowed else "acknowledge"
    return None


_UNIVERSAL_DO_NOT = (
    "universal_do_not.1",
    "universal_do_not.2",
    "universal_do_not.3",
)


def _action_do(action: str, ref: str) -> str:
    """Wat er van de agent verwacht wordt, per `expected_action`."""
    return {
        "none": outbound('action_do.1'),
        "respond": outbound('action_do.2', p0=(ref)),
        "pick_up": outbound('action_do.3', p0=(ref)),
        "acknowledge": outbound('action_do.4', p0=(ref)),
        "answered": outbound('action_do.5', p0=(ref)),
        "stand_down": (
            outbound('action_do.6', p0=(ref))
        ),
    }[action]


def _action_do_not(
    action: str,
    event_type: str | None,
    ttype: str | None,
    only_reading: bool,
    agent_policy: dict,
    access_level: str | None,
) -> list[str]:
    """De grenzen — expliciet wat vooral NIET mag, afgeleid uit dezelfde
    signalen die `expected_action` al bepalen (BETON-292: dit ontbrak nog
    volledig, en is de hefboom onder BETON-282)."""
    items: list[str] = []
    if action == "none":
        if only_reading:
            items.append(outbound('action_do_not.1'))
        elif ttype == "subscribe_all":
            items.append(outbound('action_do_not.2'))
        else:
            items.append(outbound('action_do_not.3'))
    elif action == "respond":
        items.append(outbound('action_do_not.4'))
    elif action == "pick_up":
        items.append(outbound('action_do_not.5'))
    elif action == "acknowledge":
        items.append(
            outbound('action_do_not.6', p0=(agent_policy.get('state')))
        )
    elif action == "answered":
        items.append(outbound('action_do_not.7'))
    elif action == "stand_down":
        # BETON-293: hier is `do_not` de kern van de boodschap — `stand_down` is
        # sterker dan `none` (ter info): het werk dat al liep moet STOPPEN.
        items.append(outbound('action_do_not.8'))
        items.append(outbound('action_do_not.9'))
        items.append(outbound('action_do_not.10'))

    if action not in ("none", "stand_down") and event_type == "item.moved":
        items.append(outbound('action_do_not.11'))

    if access_level == "respond" and action != "stand_down":
        items.append(
            outbound('action_do_not.12')
        )

    items.extend(outbound(key) for key in _UNIVERSAL_DO_NOT)
    return items


def _action_read(
    action: str,
    event_type: str | None,
    ttype: str | None,
    item: dict,
    ref: str,
) -> list[dict]:
    """De leeslijst: wélke bron, hoe op te halen, waarom (BETON-292). Bij
    `none` en `stand_down` is deze bewust leeg — expliciet niets lezen, niets
    doen. Juist bij `stand_down` (BETON-293) zou een leeslijst een uitnodiging
    zijn om alsnog aan de slag te gaan."""
    if action in ("none", "stand_down"):
        return []
    entries: list[dict] = [
        {
            "wat": outbound('action_read.1'),
            "hoe": f'get_item("{ref}")',
            "waarom": outbound('action_read.2'),
        }
    ]
    project_key = item.get("project")
    if event_type == "item.moved" and project_key:
        entries.append(
            {
                "wat": outbound('action_read.3'),
                "hoe": f'load_memory(project="{project_key}")',
                "waarom": (
                    outbound('action_read.4')
                ),
            }
        )
        return entries
    if action == "pick_up":
        if item.get("has_plan"):
            entries.append(
                {
                    "wat": outbound('action_read.5'),
                    "hoe": f'get_plan("{ref}")',
                    "waarom": (
                        outbound('action_read.6')
                    ),
                }
            )
        if project_key:
            entries.append(
                {
                    "wat": outbound('action_read.7'),
                    "hoe": f'load_memory(project="{project_key}")',
                    "waarom": outbound('action_read.8'),
                }
            )
    elif action == "respond" and ttype == "mention" and project_key:
        entries.append(
            {
                "wat": outbound('action_read.9'),
                "hoe": f'load_memory(project="{project_key}")',
                "waarom": outbound('action_read.10'),
            }
        )
    return entries


def build_instructions(
    user: sqlite3.Row,
    item: dict | None,
    trigger: dict | None,
    agent_policy: dict,
    event_type: str | None = None,
    access_level: str | None = None,
    model_hint: dict | None = None,
) -> dict | None:
    """Zelf-dragende, generieke opdracht in de payload (BETON-246).

    Doel: één vaste Hermes-webhookprompt ("lees de instructies in de payload en
    handel vanuit je rol") volstaat, zodat een prompt-wijziging geen nieuwe
    webhook (en dus geen key-rotatie) meer vereist. We leveren een NL-instructie,
    een machine-leesbare ``expected_action`` én het ``reply``-pad.

    ``expected_action`` (de ontvanger koos "ja, toevoegen"): ``respond`` (plaats een
    comment), ``pick_up`` (pak het werk op), ``acknowledge`` (lees mee; alleen
    reageren mag door de state), ``answered`` (een vraag die de agent stelde is
    inline beantwoord, BETON-280), ``stand_down`` (dit is niet (meer) van jou —
    STOP met wat je aan het doen was, BETON-293) of ``none`` (louter ter info).

    ``stand_down`` is bewust sterker dan ``none``: ``none`` is "ter info, je hoeft
    niets te doen", ``stand_down`` is "je was ergens mee bezig en dat moet nú
    ophouden". Vandaar een lege ``read`` en een ``do_not`` die de kern draagt.

    BETON-290: de payload draagt de brondata (omschrijving/comments) niet meer
    zelf mee — die is onbegrensd en sloopt de truncatie-garantie van de
    Hermes-gateway. ``reply["item_api_url"]`` is daarom het ophaalpad: de agent
    haalt de ticket zelf op (``get_item(ref)`` of een GET op dit pad) in plaats
    van de omschrijving/context uit de payload te lezen.
    """
    if item is None or trigger is None:
        return None
    ref = item["ref"]
    base = _public_url()
    reply = {
        "ref": ref,
        "how": (
            outbound('build_instructions.1', p0=(base), p1=(ref))
        ),
        "url": f"{base}/api/v1/items/{ref}/comments",
        "item_url": f"{base}/{item['project']}/{item['seq']}",
        "item_api_url": f"{base}/api/v1/items/{ref}",
    }

    work_allowed = agent_policy.get("work_allowed", True)
    ttype = trigger.get("type")
    addressed = trigger.get("addressed_to") or []
    handle = user["handle"]
    # Alleen de ECHTE assignee mag "pak dit op" horen. `type == "assigned"` betekent
    # per definitie dat de ontvanger de assignee is (build_trigger zet het alleen
    # dan). `work_unblocked` NIET: de vrijgave-fanout notificeert óók de maker,
    # eerdere participants en gementionden — meestal geen assignees. Die "pick_up"
    # + "aan jou toegewezen" vertellen zou het BRAND-150-ping-pong terugbrengen
    # (meerdere agents pakken hetzelfde item op). Vandaar de expliciete check.
    is_assignee = item.get("assignee") == handle
    # Gericht (BETON-216): een comment mét mentions is aan de gementionden gericht;
    # sta je er niet bij, dan lees je alleen mee — óók als je de assignee bent
    # (BETON-292/BRAND-150: de assignee is geen uitzondering op "aan iemand
    # anders gericht"). Een ongerichte comment heeft `addressed_to == []`
    # (lege lijst, geen mentions) — `bool([])` is False, dus die telt niet als
    # "only_reading" (anders zou elke ongerichte comment op je eigen item ook
    # als "niet voor jou" gelden).
    only_reading = bool(addressed) and handle not in addressed

    # BETON-293: "dit is niet (meer) van jou" weegt zwaarder dan elke andere
    # afleiding en gaat daarom vóórop — zie `_ownership_action`.
    action: str | None
    ownership = _ownership_action(trigger, event_type, is_assignee, work_allowed)
    if ownership is not None:
        action = ownership
    elif only_reading or ttype == "subscribe_all":
        action = "none"
    elif event_type == "question.answered":
        action = "answered"
    elif ttype == "mention":
        action = "respond"
    elif ttype == "assigned" and event_type in ("comment.created", "comment.updated"):
        # BETON-299: een comment-event mag NOOIT 'pick_up' opleveren, ook niet
        # als de ontvanger de assignee is en er geen mentions in de comment
        # staan — `pick_up` hoort alleen bij een daadwerkelijke toewijzing of
        # vrijgave (item.updated/work_unblocked), nooit bij een opmerking. Dit
        # was het gat tussen A2 (BETON-291, alleen item.updated) en A3
        # (BETON-292, liet de actiekeuze met rust).
        action = "respond" if work_allowed else "acknowledge"
    elif ttype == "assigned":
        # BETON-291: `type == "assigned"` betekent alléén "jij bent de assignee",
        # niet "je bent zojuist toegewezen" — dus niet blind pick_up. Als dit
        # event een item.updated is, weten we via `changed_fields` wélk veld er
        # écht wijzigde en beslissen we daarop; anders (bv. een handmatig
        # samengestelde trigger zonder die info) vallen we terug op het oude
        # gedrag.
        action = _field_based_action(trigger, work_allowed, is_assignee=True)
        if action is None:
            action = "pick_up" if work_allowed else "acknowledge"
    elif trigger.get("work_unblocked"):
        # Vrijgave: alleen de assignee pakt op; een niet-assignee (maker/participant)
        # wordt louter geïnformeerd — geen ownership-claim, geen actie-opdracht.
        if is_assignee:
            action = "pick_up" if work_allowed else "acknowledge"
        else:
            action = "none"
    else:
        # BETON-291: dezelfde generieke fallback had hetzelfde probleem — een
        # labelwijziging op een item waarbij je "participant" bent, hoort ook
        # hier geen "respond" op te leveren.
        action = _field_based_action(trigger, work_allowed, is_assignee=is_assignee)
        if action is None:
            action = "respond" if work_allowed else "acknowledge"

    reason = _instruction_reason(trigger)
    verbs = {
        "respond": (
            outbound('build_instructions.2', p0=(ref), p1=(reason), p2=(reply['item_api_url']))
        ),
        "pick_up": (
            outbound('build_instructions.3', p0=(ref), p1=(reason), p2=(reply['item_api_url']))
            + (
                outbound('build_instructions.4', p0=(model_hint['class']), p1=(model_hint['model']))
                if model_hint
                else ""
            )
        ),
        "acknowledge": (
            outbound('build_instructions.5', p0=(ref), p1=(reason), p2=(agent_policy.get('state')), p3=(reply['item_api_url']))
        ),
        "none": (
            outbound('build_instructions.6', p0=(ref), p1=(reason))
        ),
        "answered": (
            outbound('build_instructions.7', p0=(ref))
        ),
        "stand_down": (
            outbound('build_instructions.8', p0=(ref), p1=(_stand_down_reason(trigger, event_type)))
        ),
    }
    # Bij `stand_down` is "reageren doe je via …" contraproductief: dat is precies
    # wat de agent NIET moet doen (BETON-293).
    assert action is not None
    instructions = verbs[action]
    if action != "stand_down":
        instructions = outbound('build_instructions.9', p0=(instructions), p1=(reply['how']))
    if action not in ("none", "stand_down"):
        instructions += "\n\n" + outbound("human_comment_references")
    return {
        "instructions": instructions,
        "expected_action": action,
        "do": _action_do(action, ref),
        "do_not": _action_do_not(
            action, event_type, ttype, only_reading, agent_policy, access_level
        ),
        "read": _action_read(action, event_type, ttype, item, ref),
        "reply": reply,
    }


def wiki_advertisement(conn: sqlite3.Connection, event: sqlite3.Row) -> dict:
    """Adverteer Betonnings memory-provider aan de getriggerde agent (BETON-24).

    De agent krijgt bij elke trigger een *slanke* wegwijzer naar zijn geheugen:
    alleen de URL om de volledige context op te halen — NIET de complete
    wiki-inhoud, en sinds BETON-290 ook NIET meer de paginalijst (die groeit
    onbegrensd mee met de wiki en sloopt de truncatie-garantie van de
    Hermes-gateway net als de rest van de brondata). De agent laadt de inhoud
    on-demand via `context_url` (of `load_memory`/`get_memory_page`)."""
    project_key = None
    if event["item_id"] is not None:
        row = conn.execute(
            "SELECT p.key AS key FROM items i "
            "JOIN projects p ON p.id = i.project_id WHERE i.id = ?",
            (event["item_id"],),
        ).fetchone()
        if row is not None:
            project_key = row["key"]
    base = _public_url()
    context_url = (
        f"{base}/api/v1/projects/{project_key}/wiki/context"
        if project_key
        else f"{base}/api/v1/wiki/context"
    )
    return {
        "context_url": context_url,
        "hint": (
            outbound('wiki_advertisement.1')
        ),
    }


def _telegram_headline(conn: sqlite3.Connection, event: sqlite3.Row, actor: str) -> str | None:
    """Kop voor de twee telegram-waardige events (BETON-313), of None.

    Deze vragen om menselijk ingrijpen — de kop zegt meteen
    waaróm, i.p.v. het generieke actor+werkwoord-sjabloon (dat bij een auto-lock
    bovendien "iemand" zou tonen: er is geen actor)."""
    typ = event["type"]
    if typ == "item.locked":
        return outbound('telegram_headline.1')
    if typ in ("comment.created", "comment.updated"):
        cid = json.loads(event["payload"] or "{}").get("comment_id")
        row = (
            conn.execute("SELECT kind FROM comments WHERE id = ?", (cid,)).fetchone()
            if cid is not None
            else None
        )
        if row is not None and row["kind"] == "question":
            return outbound('telegram_headline.2', p0=(html.escape(actor)))
    return None


def _telegram_text(conn: sqlite3.Connection, event: sqlite3.Row) -> str:
    """Kort, leesbaar Telegram-bericht met een deep-link naar het item."""
    payload = build_payload(conn, event)
    ev = payload["event"]
    item = payload["item"]
    actor = ev["actor"] or outbound('telegram_text.1')
    if item is None:
        verb = outbound(_TG_VERBS.get(ev["type"], "telegram.verb.2"))
        return outbound('telegram_text.2', p0=(html.escape(actor)), p1=(verb))
    ref = item["ref"]
    title = html.escape(item["title"] or "")
    link = f"{_public_url()}/#{ref}"
    reflink = f'<a href="{html.escape(link)}">{ref}</a>'
    # BETON-313: de telegram-waardige events krijgen een eigen kop; de rest valt
    # terug op het generieke actor+werkwoord-sjabloon.
    headline = _telegram_headline(conn, event, actor)
    if headline is not None:
        return f"{headline} {reflink}: {title}\n{link}"
    verb = outbound(_TG_VERBS.get(ev["type"], "telegram.verb.2"))
    # De ref is een klikbare hyperlink naar het ticket; de kale URL staat er nog
    # onder zodat de link ook zichtbaar/kopieerbaar is.
    return f"<b>@{html.escape(actor)}</b> {verb} {reflink}: {title}\n{link}"


# Velden die de agent identificeren + laten weten of hij nog meer moet ophalen.
# Bewust ZONDER `description_md` (onbegrensd, tot 52.950 tekens op prod, BETON-290) —
# de agent haalt die zelf op via `reply.item_api_url` als hij hem nodig heeft.
_DELIVERY_ITEM_FIELDS = (
    "ref",
    "project",
    "seq",
    "title",
    "state",
    "priority",
    "assignee",
    "labels",
    "has_plan",
)


def _slim_item_for_delivery(item: dict | None) -> dict | None:
    """Slank een volledig `items_repo.serialize`-item af tot identificerende
    velden (BETON-290) — geen `description_md`, die is onbegrensd en sloopt de
    truncatie-garantie van de Hermes-gateway."""
    if item is None:
        return None
    return {field: item.get(field) for field in _DELIVERY_ITEM_FIELDS}


def instruction_context(
    conn: sqlite3.Connection, event: sqlite3.Row, user: sqlite3.Row
) -> tuple[sqlite3.Row | None, dict, dict | None, dict | None, str | None]:
    """Bereken de gedeelde bouwstenen voor het opdrachtblok van (event, user):
    `(item_row, agent_policy, trigger, slim_item, access_level)`.

    Dit is precies de opbouw die tot BETON-296 alleen in `build_delivery_payload`
    zat (het push-pad). `inbox.list_for_user` (het pull-pad) gebruikt 'm nu ook,
    zodat `GET /inbox`/MCP `get_inbox` niet langer een event zonder opdracht
    aflevert (BETON-246 gold tot dusver alleen voor webhooks)."""
    item_row = (
        items_repo.get(conn, event["item_id"]) if event["item_id"] is not None else None
    )
    agent_policy = build_agent_policy(conn, item_row)
    trigger = build_trigger(conn, event, user)
    full_item = items_repo.serialize(conn, item_row) if item_row is not None else None
    slim_item = _slim_item_for_delivery(full_item)

    # BETON-292: `respond` (mag reageren, niet oppakken) is een grens die de
    # agent hoort te kennen — afgeleid, niet opnieuw verzonnen. Alleen zinvol
    # met een item (anders geen project om tegen af te zetten).
    access_level = None
    if item_row is not None:
        access_level = access.effective_level(conn, item_row["project_id"], user)

    return item_row, agent_policy, trigger, slim_item, access_level


def _execution_instructions(conn, user, item_row, instructions):
    """Managed agents receive a notification, never a webhook execution grant."""
    if instructions is None or instructions['expected_action'] not in ('pick_up','acknowledge'):
        return instructions
    from .repo import execution
    if execution.binding(conn,user['id']) is None:
        return instructions
    result = dict(instructions)
    result['expected_action'] = 'none'
    result['instructions'] = outbound('execution.notification_only')
    result['do'] = outbound('execution.wait_for_executor')
    result['do_not'] = [*instructions['do_not'],outbound('execution.no_receipt')]
    result['read'] = []
    request = execution.latest(conn,item_row['id']) if item_row is not None else None
    if request is not None and request['user_id']==user['id']:
        result['execution'] = {
            'id':request['id'],'status':request['status'],
            'context_api_url':f"{_public_url()}/api/v1/items/{instructions['reply']['ref']}/executions/{request['id']}",
        }
    result['reply'] = None
    return result


def build_agent_instructions(
    conn: sqlite3.Connection, event: sqlite3.Row, user: sqlite3.Row
) -> dict | None:
    """Het opdrachtblok (`instructions`/`expected_action`/`do`/`do_not`/`read`/
    `reply`) voor (event, user) — de ÉÉN bron van waarheid die push
    (`_send_webhook` via `build_delivery_payload`) én pull
    (`inbox.list_for_user`, BETON-296) beide aanroepen. `None` als er geen item
    bij dit event hoort (geen opdracht zonder item om op te handelen)."""
    _item_row, agent_policy, trigger, slim_item, access_level = instruction_context(
        conn, event, user
    )
    if slim_item is None:
        return None
    instructions = build_instructions(
        user,
        slim_item,
        trigger,
        agent_policy,
        event_type=event["type"],
        access_level=access_level,
        model_hint=model_classes_repo.hint_for(
            conn, event["item_id"], user["handle"]
        ),
    )
    return _execution_instructions(conn,user,_item_row,instructions)



def test_target_fingerprint(user) -> str:
    """Bind alleen de test aan het opgeslagen doel; nooit URL/key in het event."""
    body = json.dumps([user['webhook_url'], user['webhook_secret']]).encode()
    return hmac.new(security._media_secret().encode(), b'hegemone:webhook-test:v1:' + body, hashlib.sha256).hexdigest()


def build_delivery_payload(
    conn: sqlite3.Connection, event: sqlite3.Row, user: sqlite3.Row
) -> dict:
    """De JSON-body voor een webhook-delivery aan `user` (BETON-246/290).

    Pure sync opbouw (geen I/O buiten de db) zodat dezelfde functie zowel door
    `_send_webhook` als door verificatiescripts/tests aangeroepen kan worden —
    één plek die niet stilletjes uit de pas kan lopen met wat er echt over de
    wire gaat.

    **Sleutelvolgorde is bewust** (BETON-290): de Hermes-gateway rendert de
    prompt met `json.dumps(payload, indent=2)[:4000]` — een harde knip. Het
    opdrachtdeel (`expected_action`/`instructions`/`reply`) staat daarom
    vooraan, zodat het de knip altijd overleeft, ook bij een item met een
    onbegrensd lange `description_md`. Bron-inhoud (`context`, `wiki.pages`,
    `item.description_md`) is verwijderd — die was onbegrensd en gaf geen
    enkele garantie; de agent haalt die zelf op (zie `reply.item_api_url`).
    """
    if event['type'] == 'webhook.test':
        return {
            'test': True, 'expected_action': 'stand_down',
            'instructions': outbound('test.instructions'),
            'do': [], 'do_not': [outbound('test.do_not')], 'read': [],
            'reply': None, 'trigger': {'type': 'connection_test'}, 'agent_policy': {'stand_down': True},
            'event': {'id': event['id'], 'type': 'webhook.test', 'created_at': event['created_at']},
            'item': None, 'wiki': None,
        }
    _item_row, agent_policy, trigger, slim_item, access_level = instruction_context(
        conn, event, user
    )

    instr = None
    if slim_item is not None:
        instr = build_instructions(
            user,
            slim_item,
            trigger,
            agent_policy,
            event_type=event["type"],
            access_level=access_level,
            model_hint=model_classes_repo.hint_for(
                conn, event["item_id"], user["handle"]
            ),
        )

    instr = _execution_instructions(conn,user,_item_row,instr)
    payload: dict = {}
    if instr is not None:
        # Plat op topniveau (instructions / expected_action / do / do_not / read /
        # reply), zoals het goedgekeurde ontwerp op BETON-246 — vooraan (BETON-290)
        # en `do`/`do_not`/`read` direct ná `instructions` (BETON-292).
        payload["expected_action"] = instr["expected_action"]
        payload["instructions"] = instr["instructions"]
        payload["do"] = instr["do"]
        payload["do_not"] = instr["do_not"]
        payload["read"] = instr["read"]
        payload["reply"] = instr["reply"]
        if "execution" in instr:
            payload["execution"] = instr["execution"]
    payload["trigger"] = trigger
    payload["agent_policy"] = agent_policy
    payload["event"] = events_repo.serialize(conn, event)
    payload["item"] = slim_item
    payload["wiki"] = wiki_advertisement(conn, event)
    return payload


async def _send_webhook(
    conn: sqlite3.Connection, client: httpx.AsyncClient, delivery: sqlite3.Row
) -> str | None:
    """POST de event-payload naar de webhook-URL. None = geslaagd, anders de fout."""
    event = conn.execute(
        "SELECT * FROM events WHERE id = ?", (delivery["event_id"],)
    ).fetchone()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?", (delivery["user_id"],)
    ).fetchone()

    payload = build_delivery_payload(conn, event, user)
    body = json.dumps(payload).encode("utf-8")
    secret = user["webhook_secret"]
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    headers = {
        "Content-Type": "application/json",
        "X-Betonning-Event": event["type"],
        "X-Betonning-Signature": sign(secret, body),
        # Hermes Agent-compatibele headers (BETON-104): Generic V2 (replay-veilig,
        # aanbevolen) + Generic V1 (legacy, ruwe hex zonder prefix).
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Signature-V2": sign_v2(secret, timestamp, body),
        "X-Webhook-Signature": sign_raw(secret, body),
    }
    try:
        reason = webhook_url_error(user["webhook_url"])
        if reason:
            return reason
        target, host_headers, extensions = await webhook_targets.pinned_target(
            user["webhook_url"], allow_loopback=loopback_allowed(),
        )
        resp = await client.post(target, content=body, headers={**headers, **host_headers},
                                 extensions=extensions, follow_redirects=False)
        if 200 <= resp.status_code < 300:
            return None
        return f"HTTP {resp.status_code}"
    except Exception as exc:  # noqa: BLE001 — netwerk/timeout mag de loop niet breken
        return f"Webhook-netwerkfout ({exc.__class__.__name__})"


async def _send_telegram(
    conn: sqlite3.Connection, client: httpx.AsyncClient, delivery: sqlite3.Row
) -> str | None:
    """Stuur het event als Telegram-bericht. None = geslaagd, anders de fout."""
    token = env("BETONNING_TELEGRAM_TOKEN")
    if not token:
        log.warning(
            "Geen BETONNING_TELEGRAM_TOKEN; telegram-delivery %s overgeslagen",
            delivery["id"],
        )
        return "telegram-token ontbreekt"
    event = conn.execute(
        "SELECT * FROM events WHERE id = ?", (delivery["event_id"],)
    ).fetchone()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?", (delivery["user_id"],)
    ).fetchone()
    try:
        resp = await client.post(
            f"{_telegram_api()}/bot{token}/sendMessage",
            json={
                "chat_id": user["telegram_chat_id"],
                "text": _telegram_text(conn, event),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        if 200 <= resp.status_code < 300:
            return None
        return f"HTTP {resp.status_code}"
    except Exception as exc:  # noqa: BLE001
        return str(exc) or exc.__class__.__name__


def _record_result(
    conn: sqlite3.Connection,
    delivery: sqlite3.Row,
    error: str | None,
    *,
    now_dt: datetime,
    max_attempts: int,
) -> None:
    """Boek het resultaat: delivered, of een retry inplannen, of definitief failed."""
    if error is None:
        conn.execute(
            "UPDATE webhook_deliveries SET status = 'delivered', "
            "attempts = attempts + 1, last_error = NULL WHERE id = ?",
            (delivery["id"],),
        )
        return

    attempts = delivery["attempts"] + 1
    if attempts >= max_attempts:
        conn.execute(
            "UPDATE webhook_deliveries SET status = 'failed', attempts = ?, "
            "last_error = ? WHERE id = ?",
            (attempts, error, delivery["id"]),
        )
        log.warning(
            "%s-delivery %s definitief mislukt na %d pogingen: %s",
            delivery["channel"],
            delivery["id"],
            attempts,
            error,
        )
    else:
        retry_at = _fmt(now_dt + timedelta(seconds=_backoff_seconds(attempts)))
        conn.execute(
            "UPDATE webhook_deliveries SET attempts = ?, last_error = ?, "
            "next_retry_at = ? WHERE id = ?",
            (attempts, error, retry_at, delivery["id"]),
        )


def _reject_delivery(conn: sqlite3.Connection, delivery: sqlite3.Row, reason: str) -> None:
    """Boek een delivery definitief af zónder HTTP-call (BETON-378).

    Status `failed` (niet `cancelled`): `cancelled` betekent hier "de aanleiding
    is weg" (BETON-18), en dit is een weigering. Terminaal, dus géén retry — de
    host wordt bij een volgende poging niet ineens toegestaan."""
    conn.execute(
        "UPDATE webhook_deliveries SET status = 'failed', attempts = attempts + 1, "
        "last_error = ? WHERE id = ?",
        (reason, delivery["id"]),
    )
    log.warning("webhook-delivery %s geweigerd: %s", delivery["id"], reason)


async def _attempt(
    conn: sqlite3.Connection,
    client: httpx.AsyncClient,
    delivery: sqlite3.Row,
    *,
    now_dt: datetime,
    max_attempts: int,
) -> None:
    event = conn.execute('SELECT type,payload FROM events WHERE id=?', (delivery['event_id'],)).fetchone()
    if event is not None and event['type'] == 'webhook.test':
        user = users_repo.get(conn, delivery['user_id'])
        fingerprint = json.loads(event['payload']).get('test_target')
        if user is None or not user['active'] or not user['webhook_url'] or fingerprint != test_target_fingerprint(user):
            webhook_tests.cancel(conn, delivery['id'])
            return
    if delivery["channel"] == "telegram":
        error = await _send_telegram(conn, client, delivery)
    else:
        # Poort op vuurmoment: de URL kan gezet zijn vóór deze check bestond, of
        # de allowlist kan sindsdien versmald zijn. Weigeren = niet verbinden.
        user = conn.execute(
            "SELECT webhook_url FROM users WHERE id = ?", (delivery["user_id"],)
        ).fetchone()
        reason = webhook_url_error(user["webhook_url"] if user else None)
        if reason is not None:
            _reject_delivery(conn, delivery, reason)
            return
        error = await _send_webhook(conn, client, delivery)
    _record_result(conn, delivery, error, now_dt=now_dt, max_attempts=max_attempts)


async def deliver_pending(
    conn: sqlite3.Connection,
    client: httpx.AsyncClient,
    *,
    now: datetime | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    concurrency: int = CONCURRENCY,
) -> int:
    """Verwerk de nu-verzendbare deliveries één keer. Geeft het aantal terug.

    Deliveries lopen parallel (begrensd door ``concurrency``) zodat één trage
    ontvanger de andere niet blokkeert; de sqlite-writes zijn onafhankelijk
    (UPDATE per id) en serialiseren vanzelf op de single-thread event-loop.
    """
    now_dt = now or datetime.now(timezone.utc)
    now_str = _fmt(now_dt)
    rows = conn.execute(
        "SELECT * FROM webhook_deliveries WHERE status = 'pending' "
        "AND (not_before IS NULL OR not_before <= ?) "
        "AND (next_retry_at IS NULL OR next_retry_at <= ?) ORDER BY id",
        (now_str, now_str),
    ).fetchall()

    sem = asyncio.Semaphore(concurrency)

    async def _one(delivery: sqlite3.Row) -> None:
        async with sem:
            event = conn.execute(
                "SELECT * FROM events WHERE id = ?", (delivery["event_id"],)
            ).fetchone()
            # Na het delay-venster: is de aanleiding er nog? Zo niet, annuleer.
            if event is None or not is_event_still_actionable(conn, event):
                conn.execute(
                    "UPDATE webhook_deliveries SET status = 'cancelled', "
                    "last_error = 'aanleiding verdwenen binnen delay-venster' "
                    "WHERE id = ?",
                    (delivery["id"],),
                )
                return
            await _attempt(
                conn, client, delivery, now_dt=now_dt, max_attempts=max_attempts
            )

    await asyncio.gather(*(_one(d) for d in rows))
    return len(rows)


# --- Inzicht + replay (BETON-52) ------------------------------------------


def serialize_delivery(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "user_id": row["user_id"],
        "channel": row["channel"],
        "status": row["status"],
        "attempts": row["attempts"],
        "last_error": row["last_error"],
        "next_retry_at": row["next_retry_at"],
        "created_at": row["created_at"],
    }


def list_deliveries(
    conn: sqlite3.Connection, *, status: str | None = None, limit: int = 50
) -> list[dict]:
    """Deliveries, recentste eerst. ``status`` filtert (bv. 'failed').

    Verrijkt elke rij met ``target_handle`` (de doel-user) en ``event_type``
    (het type gebeurtenis) via een join — die zijn niet client-side af te
    leiden (geen events-endpoint) en de UI toont ze in het leveringen-paneel
    (BETON-174). ``d.*`` blijft de basis, dus ``serialize_delivery`` werkt
    ongewijzigd zonder kolomnaambotsing."""
    query = (
        "SELECT d.*, u.handle AS target_handle, e.type AS event_type "
        "FROM webhook_deliveries d "
        "LEFT JOIN users u ON u.id = d.user_id "
        "LEFT JOIN events e ON e.id = d.event_id"
    )
    params: list = []
    if status is not None:
        query += " WHERE d.status = ?"
        params.append(status)
    query += " ORDER BY d.id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [
        {
            **serialize_delivery(r),
            "target_handle": r["target_handle"],
            "event_type": r["event_type"],
        }
        for r in rows
    ]


def get_delivery(conn: sqlite3.Connection, delivery_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM webhook_deliveries WHERE id = ?", (delivery_id,)
    ).fetchone()


def replay_delivery(conn: sqlite3.Connection, delivery_id: int) -> dict | None:
    """Zet een delivery terug in de queue (reset attempts/not_before/next_retry_at).

    De dispatcher pikt hem in zijn eigen tempo weer op. None als de delivery
    niet bestaat."""
    row = get_delivery(conn, delivery_id)
    if row is None:
        return None
    conn.execute(
        "UPDATE webhook_deliveries SET status = 'pending', attempts = 0, "
        "last_error = NULL, next_retry_at = NULL, not_before = NULL WHERE id = ?",
        (delivery_id,),
    )
    fresh = get_delivery(conn, delivery_id)
    assert fresh is not None
    return serialize_delivery(fresh)


async def dispatcher_loop(
    db_path: str, stop_event: asyncio.Event, *, interval: float = POLL_INTERVAL
) -> None:
    """Achtergrondtaak: verwerk deliveries tot stop_event gezet is."""
    if not telegram_enabled():
        log.info(
            "BETONNING_TELEGRAM_TOKEN niet gezet; telegram-deliveries worden "
            "overgeslagen (geen fanout naar Telegram)."
        )
    async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT, trust_env=False, follow_redirects=False) as client:
        while not stop_event.is_set():
            conn = db_module.connect(db_path)
            try:
                stored = installation_settings.get(conn)
                values = stored['settings'] if stored else {}
                context = {'BETONNING_LANGUAGE': values.get('language', 'en'),
                           'BETONNING_PUBLIC_URL': values.get('public_url', 'http://localhost:8000')}
                with runtime_context(context):
                    await deliver_pending(conn, client)
            except Exception:  # noqa: BLE001 — de loop mag nooit sterven
                log.exception("dispatcher-ronde mislukt")
            finally:
                conn.close()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
