"""Attachments-repository: metadata rond op disk opgeslagen bijlagen.

De bytes staan op disk (zie storage.py); hier alleen de DB-rijen. De publieke
URL is content-addressed (`/api/v1/attachments/<sha256>`) en dus stabiel en
zonder Bearer op te halen — bewust een capability-URL (LAN-dienst): wie de
niet-raadbare hash heeft, kan de afbeelding zien.

Sinds BETON-374 zijn naast afbeeldingen ook tekst, log, JSON en PDF toegestaan.
Twee regels houden dat veilig:

- **Het type komt uit de inhoud, nooit uit de client.** BETON-380 sniffte al op
  magic bytes; tekst en JSON hébben die niet, dus daar is de inhoud zélf de
  toets: JSON moet parsen, tekst moet als UTF-8 decoderen zonder NUL-byte. Wat
  er niet doorheen komt is geen tekstbestand. De bestandsextensie beslist
  bewust níets: dezelfde bytes moeten altijd hetzelfde type opleveren, anders
  breekt de content-addressed dedup (`get_by_sha` doet `ORDER BY id ASC LIMIT
  1` op de aanname dat één sha één content_type is, BETON-394). `.log` en
  `.csv` komen dus als `text/plain` binnen; de extensie leeft voort in
  `filename`.
- **Alleen afbeeldingen mogen `inline`.** Een niet-afbeelding die inline op de
  origin geserveerd wordt is een andere risicoklasse (HTML/SVG zou daar script
  kunnen uitvoeren); die gaan als `attachment` naar buiten. SVG en HTML staan
  daarom sowieso niet op de whitelist — een SVG is XML met scriptcapaciteit, en
  de winst (een vector-screenshot) weegt daar niet tegenop.
"""

from __future__ import annotations

from ..config import env

import json
import sqlite3

IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
TEXT_TYPES = {"text/plain", "application/json"}

# Per-type maximum. Afbeeldingen houden de bestaande 10 MB; tekst/PDF zijn
# leesmateriaal voor mens én LLM en hebben aan 5 MB genoeg.
TYPE_LIMITS = {
    "image/png": 10 * 1024 * 1024,
    "image/jpeg": 10 * 1024 * 1024,
    "image/gif": 10 * 1024 * 1024,
    "image/webp": 10 * 1024 * 1024,
    "application/pdf": 5 * 1024 * 1024,
    "text/plain": 5 * 1024 * 1024,
    "application/json": 5 * 1024 * 1024,
}

# Globale bovengrens: de grootste per-type-limiet. `bodylimit` leunt hierop voor
# de multipart-cap, en de upload-handler leest hiermee in — de scherpere
# per-type-limiet slaat daarna pas toe.
MAX_SIZE = max(TYPE_LIMITS.values())  # 10 MB


def limit_for(content_type: str) -> int:
    return TYPE_LIMITS.get(content_type, MAX_SIZE)


def is_image(content_type: str | None) -> bool:
    return (content_type or "").split(";")[0].strip().lower() in IMAGE_TYPES


def sniff_image_type(head: bytes) -> str | None:
    """Bepaal het afbeeldingstype uit de magic bytes (BETON-380).

    De `content_type` uit een multipart-part komt van de client en is dus een
    bewering, geen feit: een .exe met `Content-Type: image/png` kwam er langs de
    whitelist heen. We sniffen daarom zelf en slaan het gesniffte type op — de
    geclaimde header is daarmee irrelevant. None = geen herkende afbeelding.
    """
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _is_utf8_text(data: bytes) -> bool:
    """Tekst = decodeert als UTF-8 en bevat geen NUL-byte.

    De NUL-check vangt binaire troep die toevallig geldig UTF-8 is (bv. een
    bestand dat vrijwel alleen uit nulbytes bestaat); echte tekstbestanden
    hebben er geen.
    """
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def sniff_type(data: bytes) -> str | None:
    """Bepaal het opgeslagen content-type uit de bytes zelf (BETON-374).

    Deterministisch en volgordelijk, zodat dezelfde bytes altijd hetzelfde type
    opleveren (dedup-invariant):

    1. magic bytes van een afbeelding;
    2. `%PDF-` → PDF;
    3. begint met `{` of `[` én parseert als JSON → `application/json`
       (de haakjes-poort houdt een logregel als ``123`` uit de JSON-tak);
    4. geldige UTF-8 zonder NUL → `text/plain` (dus ook .log, .csv, .md);
    5. anders None = niet toegestaan.
    """
    image = sniff_image_type(data[:16])
    if image is not None:
        return image
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    stripped = data.lstrip()
    if stripped[:1] in (b"{", b"[") and _is_utf8_text(data):
        try:
            json.loads(data.decode("utf-8"))
        except ValueError:
            pass
        else:
            return "application/json"
    if _is_utf8_text(data):
        return "text/plain"
    return None


def url_for(sha256: str) -> str:
    return f"/api/v1/attachments/{sha256}"


def serialize(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "size": row["size"],
        "sha256": row["sha256"],
        "url": url_for(row["sha256"]),
        "created_by": row["created_by_handle"]
        if "created_by_handle" in row.keys()
        else None,
        "created_at": row["created_at"],
    }


def create(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    item_id: int,
    filename: str,
    content_type: str,
    size: int,
    sha256: str,
    created_by: int | None,
) -> dict:
    cur = conn.execute(
        """INSERT INTO attachments
               (project_id, item_id, filename, content_type, size, sha256, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (project_id, item_id, filename, content_type, size, sha256, created_by),
    )
    assert cur.lastrowid is not None
    row = get(conn, cur.lastrowid)
    assert row is not None
    return row


def get(conn: sqlite3.Connection, attachment_id: int) -> dict | None:
    row = conn.execute(
        """SELECT a.*, u.handle AS created_by_handle FROM attachments a
           LEFT JOIN users u ON u.id = a.created_by WHERE a.id = ?""",
        (attachment_id,),
    ).fetchone()
    return serialize(row) if row else None


def get_by_sha(conn: sqlite3.Connection, sha256: str) -> sqlite3.Row | None:
    """Eén rij voor dit content-adres (bytes/content_type zijn identiek).

    Meerdere items kunnen onafhankelijk dezelfde bytes uploaden, elk met zijn
    eigen ``filename``. Zonder ordening is `LIMIT 1` willekeurig — welke rij de
    query-planner teruggeeft is een implementatiedetail, niet een garantie.
    De OUDSTE rij wint (`ORDER BY id ASC`), zodat de naam die eerst is
    uitgedeeld stabiel blijft."""
    return conn.execute(
        "SELECT * FROM attachments WHERE sha256 = ? ORDER BY id ASC LIMIT 1",
        (sha256,),
    ).fetchone()


def list_for_item(conn: sqlite3.Connection, item_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT a.*, u.handle AS created_by_handle FROM attachments a
           LEFT JOIN users u ON u.id = a.created_by
           WHERE a.item_id = ? ORDER BY a.id""",
        (item_id,),
    ).fetchall()
    return [serialize(r) for r in rows]


def quota_error(conn, user_id, project_id, size):
    """Logische bytequota; aanroeper houdt een IMMEDIATE-transactie vast."""

    user_limit = int(env("BETONNING_UPLOAD_USER_QUOTA", 512 * 1024 * 1024))
    project_limit = int(env("BETONNING_UPLOAD_PROJECT_QUOTA", 2 * 1024 * 1024 * 1024))
    own = conn.execute(
        "SELECT COALESCE(SUM(size),0) FROM attachments WHERE created_by=?", (user_id,)
    ).fetchone()[0]
    project = conn.execute(
        "SELECT COALESCE(SUM(size),0) FROM attachments WHERE project_id=?",
        (project_id,),
    ).fetchone()[0]
    if own + size > user_limit:
        return "Uploadquota van gebruiker bereikt"
    if project + size > project_limit:
        return "Uploadquota van project bereikt"
    return None
