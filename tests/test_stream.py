"""Fase E — live SSE-stream over de events-tabel.

De 401-check gaat via een gewone request (de auth-dependency draait vóór de
stream). De frame-opbouw testen we door de async generator zelf te draaien —
de TestClient buffert een oneindige stream en is daar ongeschikt voor.
"""

from __future__ import annotations

import asyncio
import json

from betonning.api import stream as stream_mod


class _FakeRequest:
    """Minimale request: 'verbreekt' na `disconnect_after` checks."""

    def __init__(self, disconnect_after: int = 1):
        self._n = 0
        self._after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._n += 1
        return self._n > self._after


def _first_frame(db_path: str, since: int, from_latest: bool = False) -> str | None:
    async def go():
        agen = stream_mod._event_generator(
            _FakeRequest(), db_path, since, from_latest=from_latest
        )
        try:
            async for frame in agen:
                return frame
        finally:
            await agen.aclose()
        return None

    return asyncio.run(go())


def _data_of(frame: str) -> dict:
    for line in frame.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())
    raise AssertionError(f"geen data-regel in frame: {frame!r}")


def test_stream_requires_auth(client, project):
    # Auth-dependency draait vóór de stream → gewone (niet-streaming) 401.
    assert client.get("/api/v1/events/stream").status_code == 401


def test_stream_delivers_backlog(client, auth, db_path, project):
    client.post("/api/v1/projects/SOS/items", json={"title": "eerste"}, headers=auth)
    frame = _first_frame(db_path, since=0)
    assert frame is not None and frame.startswith("id:")
    assert _data_of(frame)["type"] == "item.created"


def test_stream_resumes_from_since(client, auth, conn, db_path, project):
    client.post("/api/v1/projects/SOS/items", json={"title": "een"}, headers=auth)
    last = conn.execute("SELECT MAX(id) AS m FROM events").fetchone()["m"]
    client.post("/api/v1/projects/SOS/items", json={"title": "twee"}, headers=auth)
    frame = _first_frame(db_path, since=last)
    assert _data_of(frame)["payload"]["title"] == "twee"


def test_stream_heartbeat_when_idle(client, auth, db_path, project):
    # Geen events na `since` → eerste frame is een heartbeat-comment.
    frame = _first_frame(db_path, since=999999)
    assert frame.startswith(":") and "heartbeat" in frame


def test_stream_frame_carries_compact_item(client, auth, db_path, project):
    # BETON-186: het SSE-frame draagt een compacte item-snapshot mee (ref/
    # project/item) zodat de UI het event incrementeel kan toepassen.
    client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "verrijk mij", "priority": "high"},
        headers=auth,
    )
    data = _data_of(_first_frame(db_path, since=0))
    assert data["ref"] == "SOS-1"
    assert data["project"] == "SOS"
    assert data["item"]["ref"] == "SOS-1"
    assert data["item"]["title"] == "verrijk mij"
    assert data["item"]["priority"] == "high"
    assert data["item"]["archived_at"] is None


def test_stream_item_updated_carries_new_state(client, auth, conn, db_path, project):
    # Een statuswissel komt met de níeuwe state in de snapshot binnen, zodat de
    # UI de kaart naar de andere kolom kan verplaatsen zonder reload.
    client.post("/api/v1/projects/SOS/items", json={"title": "loop"}, headers=auth)
    last = conn.execute("SELECT MAX(id) AS m FROM events").fetchone()["m"]
    client.patch("/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=auth)
    data = _data_of(_first_frame(db_path, since=last))
    assert data["type"] == "item.updated"
    assert data["item"]["state"] == "in-progress"


def test_stream_archived_snapshot_marks_archived(client, auth, conn, db_path, project):
    # Archiveren → de snapshot heeft archived_at gezet; de UI haalt de kaart
    # daarmee van het board (tenzij het archief zichtbaar is).
    client.post("/api/v1/projects/SOS/items", json={"title": "weg"}, headers=auth)
    last = conn.execute("SELECT MAX(id) AS m FROM events").fetchone()["m"]
    client.delete("/api/v1/items/SOS-1", headers=auth)
    data = _data_of(_first_frame(db_path, since=last))
    assert data["type"] == "item.archived"
    assert data["item"]["archived_at"] is not None


def test_stream_from_latest_skips_backlog(client, auth, db_path, project):
    # Met from_latest begint de stream bij het laatste event; bestaande
    # backlog wordt niet opnieuw afgespeeld → eerste frame is een heartbeat.
    client.post("/api/v1/projects/SOS/items", json={"title": "oud"}, headers=auth)
    frame = _first_frame(db_path, since=0, from_latest=True)
    assert frame.startswith(":") and "heartbeat" in frame
