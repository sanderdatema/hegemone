"""Users-repository: aanmaken en opzoeken (incl. auth via api_key_hash)."""

from __future__ import annotations

import re
import sqlite3

from ..security import generate_api_key, hash_api_key
from . import access
from .. import credential_policy

# BETON-207: virtuele assignees. Triage/decompose wijzen coding-werk toe aan
# `coding-agent` (gedeelde coding-queue) i.p.v. aan claude/codex/zcode, en aan
# `hermes` als geen specifieke Hermes-agent duidelijk past. Beide zijn user-rijen
# met is_virtual=1 (migratie 027) — wel toewijsbaar, geen echte agent.
VIRTUAL_CODING = "coding-agent"
VIRTUAL_HERMES = "hermes-agent"

# BETON-385: tekenset + lengte voor handles — moet dekken wat `mentions.py`
# als `@handle` herkent (`_MENTION`) zodat een aangemaakte handle altijd
# mentionbaar is. Max 32 tekens, begint met een letter/cijfer.
HANDLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")


def validate_handle(handle: str) -> str:
    """Strip whitespace en een leidende `@`, valideer tegen `HANDLE_RE`.

    Geeft de genormaliseerde handle terug of raist `ValueError` (API/CLI
    vertalen dat naar resp. 422 en een nette foutmelding)."""
    v = (handle or "").strip().lstrip("@")
    if not HANDLE_RE.match(v):
        raise ValueError(
            "handle moet 1-32 tekens zijn (letters, cijfers, _ of -), "
            "beginnend met een letter of cijfer"
        )
    return v


def _row_is_virtual(row: sqlite3.Row | dict) -> bool:
    """True als deze user-rij een virtuele (pseudo-)agent is (is_virtual=1)."""
    try:
        return bool(row["is_virtual"])
    except (KeyError, IndexError):
        return False


def avatar_url_for(row: sqlite3.Row) -> str | None:
    """Capability-URL naar de avatar-bytes, of None als er geen avatar is.

    De `?v=`-suffix (eerste 8 tekens van de sha256) breekt de browsercache zodra
    de avatar verandert — het content-adres wijzigt immers mee met de bytes."""
    sha = row["avatar_sha256"]
    if not sha:
        return None
    return f"/api/v1/users/{row['handle']}/avatar?v={sha[:8]}"


def handle_of(conn: sqlite3.Connection, user_id: int | None) -> str | None:
    """De handle bij een user-id; None voor None of een onbekend id."""
    if user_id is None:
        return None
    r = conn.execute("SELECT handle FROM users WHERE id = ?", (user_id,)).fetchone()
    return r["handle"] if r else None


def serialize(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "handle": row["handle"],
        "display_name": row["display_name"],
        "kind": row["kind"],
        "agent_type": row["agent_type"],
        "is_virtual": _row_is_virtual(row),
        "description": row["description"],
        "active": bool(row["active"]),
        "subscribe_all": bool(row["subscribe_all"]),
        "has_webhook": row["webhook_url"] is not None,
        "has_telegram": row["telegram_chat_id"] is not None,
        "avatar_url": avatar_url_for(row),
    }


def serialize_admin(row: sqlite3.Row) -> dict:
    """Als `serialize`, plus `webhook_url` (BETON-113) — alleen voor mens-
    gate-de endpoints (`current_human`). De URL is geen geheim (een LAN-adres),
    maar `webhook_secret` blijft ook hier write-only: eenmaal gezet, nooit meer
    teruggegeven. Nodig zodat de beheer-UI de URL kan voorinvullen zonder 'm
    breed via de publieke user-lijst te lekken."""
    return {**serialize(row), "webhook_url": row["webhook_url"],
            "api_key_expires_at": row["api_key_expires_at"],
            "api_key_scopes": None if row["api_key_scopes"] is None else sorted(credential_policy.scopes(row)),
            "api_key_projects": None if row["api_key_projects"] is None else sorted(credential_policy.projects(row))}


def create(
    conn: sqlite3.Connection,
    *,
    handle: str,
    display_name: str,
    kind: str = "agent",
    agent_type: str | None = None,
    description: str | None = None,
    api_key: str | None = None,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
    subscribe_all: bool = False,
) -> tuple[dict, str]:
    """Maak een user aan. Geeft (serialized_user, ruwe_api_key) terug.

    De ruwe key wordt alleen hier teruggegeven; opgeslagen wordt enkel de hash.
    """
    key = api_key or generate_api_key()
    cur = conn.execute(
        """
        INSERT INTO users (handle, display_name, kind, agent_type, description,
                           api_key_hash, webhook_url, webhook_secret, subscribe_all)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            handle,
            display_name,
            kind,
            agent_type,
            description,
            hash_api_key(key),
            webhook_url,
            webhook_secret,
            int(subscribe_all),
        ),
    )
    row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    assert row is not None
    return serialize_admin(row), key


def get_by_api_key(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    """Zoek een actieve user op de hash van de aangeboden Bearer-key.

    `is_virtual = 0` (BETON-468): virtuele queues (`coding-agent`,
    `hermes-agent`) authenticeren nooit, ook niet als er een geldige hash staat.
    Dit is de énige key-lookup: REST (`deps`), de media-poort en de MCP-mount
    lopen er allemaal doorheen."""
    row = conn.execute(
        "SELECT * FROM users WHERE api_key_hash = ? AND active = 1 AND is_virtual = 0",
        (hash_api_key(key),),
    ).fetchone()
    return row if credential_policy.valid(row) else None


def get_by_handle(conn: sqlite3.Connection, handle: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE handle = ?", (handle,)).fetchone()


class VirtualUserError(ValueError):
    """Een virtuele queue krijgt geen API-key (BETON-468)."""


def rotate_api_key(conn: sqlite3.Connection, handle: str) -> tuple[dict, str] | None:
    """Vervang de API-key-hash voor een bestaande user. Gooit `VirtualUserError`
    voor een virtuele user: die heeft een sentinel-hash en geen key.

    Net als bij create() wordt de ruwe key alleen aan de caller teruggegeven; in
    de database komt uitsluitend de hash terecht.
    """
    existing = get_by_handle(conn, handle)
    if existing is not None and existing["is_virtual"]:
        raise VirtualUserError(handle)
    key = generate_api_key()
    cur = conn.execute(
        "UPDATE users SET api_key_hash = ? WHERE handle = ?",
        (hash_api_key(key), handle),
    )
    if cur.rowcount == 0:
        return None
    row = get_by_handle(conn, handle)
    assert row is not None
    return serialize_admin(row), key


def get(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def first_human(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """De eerste actieve mens (op id), of None (BETON-375).

    Terugvalbestemming als er niemand is die een vraag kán beantwoorden — bv. een
    stil item dat aan de virtuele `coding-agent`-queue hangt: die rij
    authenticeert nooit (migratie 027) en zou de vraag dus nergens laten
    aankomen. Bewust "de eerste mens" en niet een vaste persoonsnaam: het is een
    rol-eigenschap, net als bij `_lock_notify_handles` (BETON-302)."""
    return conn.execute(
        "SELECT * FROM users WHERE kind = 'human' AND active = 1 ORDER BY id LIMIT 1"
    ).fetchone()


def set_telegram(conn: sqlite3.Connection, handle: str, chat_id: str | None) -> bool:
    """Koppel (of ontkoppel met None) een Telegram-chat aan een user."""
    cur = conn.execute(
        "UPDATE users SET telegram_chat_id = ? WHERE handle = ?", (chat_id, handle)
    )
    return cur.rowcount > 0


def set_webhook(
    conn: sqlite3.Connection, handle: str, url: str, secret: str | None
) -> bool:
    """Zet de webhook-url (+ optioneel secret) van een agent (BETON-83/84):
    zonder dit kon een admin een Hermes-agent nooit een webhook geven, want die
    heeft geen eigen API-key om zichzelf via /me/settings te configureren."""
    cur = conn.execute(
        "UPDATE users SET webhook_url = ?, webhook_secret = ? WHERE handle = ?",
        (url, secret, handle),
    )
    return cur.rowcount > 0


def list_all(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM users ORDER BY handle").fetchall()
    return [serialize(r) for r in rows]


# --- agent_type-helpers (BETON-88 fundament) --------------------------------
# Voor toekomstig gebruik door de triage-guard: coding-agents (Claude Code,
# Codex) volgen een ander pad dan Hermes-agents en mogen niet als Hermes-
# doelwit behandeld worden.


def is_hermes_agent(row: sqlite3.Row | dict) -> bool:
    """True als deze user-rij een Hermes-agent is (agent_type='hermes')."""
    try:
        value = row["agent_type"]
    except (KeyError, IndexError):
        return False
    return value == "hermes"


def visible_queue_ids(
    conn: sqlite3.Connection, user_row: sqlite3.Row | dict
) -> list[int]:
    """De assignee-ids waarvan 'Mijn tickets' items moet tonen (BETON-207).

    Een échte coding-agent ziet naast z'n eigen tickets ook de gedeelde
    `coding-agent`-queue; een échte Hermes-agent ook de `hermes-agent`-queue. Zo
    is de virtuele toewijzing daadwerkelijk vindbaar (anders wijst triage naar een
    queue die niemand pollt). Mensen en de virtuele users zelf zien enkel hun eigen
    id."""
    ids = [user_row["id"]]
    if not _row_is_virtual(user_row):
        handle = {"coding": VIRTUAL_CODING, "hermes": VIRTUAL_HERMES}.get(
            user_row["agent_type"]
        )
        if handle:
            v = get_by_handle(conn, handle)
            if v is not None:
                ids.append(v["id"])
    return ids


def collapse_to_virtual(conn: sqlite3.Connection, handle: str | None) -> str | None:
    """Map een concrete coding-agent naar de virtuele coding-queue (BETON-207).

    Claude/Codex/zcode (agent_type='coding', niet-virtueel) → `coding-agent`.
    Mensen, specifieke Hermes-agents en de al-virtuele assignees blijven
    ongemoeid: triage kiest zelf al de virtuele `hermes` bij twijfel, en mensen
    blijven ongewijzigd. Een onbekende handle wordt onveranderd teruggegeven."""
    if not handle:
        return handle
    u = get_by_handle(conn, handle)
    if u is None:
        return handle
    if u["agent_type"] == "coding" and not _row_is_virtual(u):
        return VIRTUAL_CODING
    return handle


# --- Agent-beheer (BETON-72) ----------------------------------------------

# Kolommen die een menselijke beheerder mag aanpassen. De `handle` staat er
# bewust NIET bij: attributie (items.assignee_id, comments.author_id,
# events.actor_id) en @mention-matching hangen aan de handle — die wijzigen
# breekt bestaande verwijzingen.
# webhook_url/webhook_secret staan hier óók (naast _SETTINGS_COLUMNS hieronder):
# zonder admin-schrijftoegang kan een mens een Hermes-agent nooit een webhook
# geven, want die heeft geen eigen API-key om zichzelf te settingen (BETON-83/84).
_ADMIN_COLUMNS = (
    "api_key_expires_at", "api_key_scopes", "api_key_projects",
    "display_name",
    "kind",
    "agent_type",
    "description",
    "active",
    "webhook_url",
    "webhook_secret",
)


def admin_update(conn: sqlite3.Connection, user_id: int, fields: dict) -> sqlite3.Row:
    """Werk beheer-velden van een user bij (alleen kolommen uit ``_ADMIN_COLUMNS``).

    ``fields`` is doorgaans de exclude_unset-dump van een request-model."""
    updates = {k: v for k, v in fields.items() if k in _ADMIN_COLUMNS}
    import json
    for key in ("api_key_scopes", "api_key_projects"):
        if key in updates and updates[key] is not None:
            updates[key] = json.dumps(updates[key])
    if updates:
        set_clause = ", ".join(f"{col} = ?" for col in updates)
        values = [int(v) if isinstance(v, bool) else v for v in updates.values()]
        conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", (*values, user_id))
    return get_required(conn, user_id)


def set_avatar(
    conn: sqlite3.Connection, user_id: int, *, sha256: str, content_type: str
) -> sqlite3.Row:
    """Koppel een (op disk opgeslagen) avatar aan een user. De bytes zelf staan
    content-addressed op disk (storage.py); hier alleen de verwijzing."""
    conn.execute(
        "UPDATE users SET avatar_sha256 = ?, avatar_content_type = ? WHERE id = ?",
        (sha256, content_type, user_id),
    )
    return get_required(conn, user_id)


def clear_avatar(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    """Verwijder de avatar-verwijzing (terug naar initialen). De bytes op disk
    blijven staan — content-addressed/dedup, mogelijk gedeeld."""
    conn.execute(
        "UPDATE users SET avatar_sha256 = NULL, avatar_content_type = NULL WHERE id = ?",
        (user_id,),
    )
    return get_required(conn, user_id)


def deactivate(conn: sqlite3.Connection, user_id: int) -> None:
    """Zet ``active = 0`` (soft-delete). Geen hard-delete: users worden
    gerefereerd door items/comments/events; ``get_by_api_key`` filtert al op
    ``active = 1`` zodat een gedeactiveerde user niet meer kan inloggen."""
    conn.execute("UPDATE users SET active = 0 WHERE id = ?", (user_id,))


def assignable_agents(
    conn: sqlite3.Connection, project_id: int | None = None
) -> list[dict]:
    """Actieve agents die triage/decompose als assignee mogen kiezen (BETON-67).

    De bot `triage` zit er niet bij (die wijst niet aan zichzelf toe). BETON-207:
    de échte coding-agents (claude/codex/zcode) zitten er óók niet meer in — voor
    algemeen codewerk kiest triage de virtuele `coding-agent` (gedeelde queue).
    De specifieke Hermes-agents blijven (voor een duidelijke specialist-match) en
    de virtuele `hermes` staat erin voor het geval geen Hermes-agent past. Geeft
    handle + description mee zodat het expertise-routeren in de LLM-context kan.

    Met `project_id` (BETON-123) worden agents met een effectief toegangsniveau
    onder ``assign`` op dat project weggefilterd, zodat de bot ze niet toewijst.
    Zonder `project_id` blijft het de globale roster (geen per-project-filter).
    """
    rows = conn.execute(
        "SELECT id, handle, description, kind, agent_type FROM users "
        "WHERE active = 1 AND kind = 'agent' AND handle != 'triage' "
        "AND NOT (COALESCE(agent_type, '') = 'coding' AND COALESCE(is_virtual, 0) = 0) "
        "ORDER BY handle"
    ).fetchall()
    if project_id is not None:
        rows = [
            r for r in rows if access.effective_level(conn, project_id, r) == "assign"
        ]
    return [{"handle": r["handle"], "description": r["description"]} for r in rows]


_SETTINGS_COLUMNS = (
    "webhook_url",
    "webhook_secret",
    "subscribe_all",
    "telegram_chat_id",
    "active",
    "description",
)


def serialize_settings(row: sqlite3.Row) -> dict:
    """Eigen instellingen (BETON-49): geen ruw ``webhook_secret`` in de response —
    alleen of er één gezet is (write-only key-material)."""
    return {
        "handle": row["handle"],
        "display_name": row["display_name"],
        "kind": row["kind"],
        "webhook_url": row["webhook_url"],
        "has_webhook_secret": row["webhook_secret"] is not None,
        "subscribe_all": bool(row["subscribe_all"]),
        "telegram_chat_id": row["telegram_chat_id"],
        "active": bool(row["active"]),
        # description hoort bij de eigen instellingen (het UI-paneel BETON-173
        # bewerkt 'm) — meesturen zodat het paneel een altijd-verse waarde heeft
        # i.p.v. te leunen op het bij login geladen /me-object.
        "description": row["description"],
    }


def update_settings(
    conn: sqlite3.Connection, user_id: int, fields: dict
) -> sqlite3.Row:
    """Werk de eigen webhook/telegram-instellingen bij (alleen de meegegeven velden).

    ``fields`` is de exclude_unset-dump van het request-model; enkel kolommen uit
    ``_SETTINGS_COLUMNS`` worden toegepast (user-beheer van anderen kan hier niet)."""
    updates = {k: v for k, v in fields.items() if k in _SETTINGS_COLUMNS}
    if updates:
        set_clause = ", ".join(f"{col} = ?" for col in updates)
        values = [int(v) if isinstance(v, bool) else v for v in updates.values()]
        conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", (*values, user_id))
    return get_required(conn, user_id)


def get_required(conn: sqlite3.Connection, row_id: int) -> sqlite3.Row:
    """Lees een rij die door de caller als write-postconditie wordt verwacht."""
    row = get(conn, row_id)
    if row is None:
        raise LookupError("Gebruiker ontbreekt na de verwachte bewerking")
    return row
