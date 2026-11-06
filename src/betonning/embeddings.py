"""Embeddings: OpenAI-compatibele client + SQLite-store + cosine-similarity.

Voor dedup in de triage-bot (BETON-22). Vectoren staan als float32-blob in
`item_embeddings`; similarity wordt in Python berekend (cosine) over de vectoren
van één project — bij ~1000 items ruim snel genoeg, geen vector-extensie nodig.

Config via env (server-side):
  BETONNING_EMBED_BASE_URL   — OpenAI-compatibel endpoint, bv. https://.../v1
  BETONNING_EMBED_API_KEY    — bearer-key
  BETONNING_EMBED_MODEL      — bv. text-embedding-3-small
  BETONNING_EMBED_DIMENSIONS — optioneel (int); dwingt de vectorlengte af
"""

from __future__ import annotations

from .config import env

import math
import sqlite3
from array import array
from typing import Protocol

import httpx


class EmbeddingClient(Protocol):
    """Seam: tekst → vector. Testbaar met een fake."""

    def embed(self, text: str) -> list[float]: ...


class OpenAICompatEmbeddings:
    """Client tegen een OpenAI-compatibel /embeddings-endpoint."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        dimensions: int | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._timeout = timeout

    def embed(self, text: str) -> list[float]:
        payload: dict = {"model": self._model, "input": text}
        if self._dimensions:
            payload["dimensions"] = self._dimensions
        resp = httpx.post(
            f"{self._base_url}/embeddings",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


def client_from_env() -> OpenAICompatEmbeddings | None:
    base = env("BETONNING_EMBED_BASE_URL")
    key = env("BETONNING_EMBED_API_KEY")
    model = env("BETONNING_EMBED_MODEL")
    if not (base and key and model):
        return None
    dims_raw = env("BETONNING_EMBED_DIMENSIONS")
    dims = int(dims_raw) if dims_raw else None
    return OpenAICompatEmbeddings(base, key, model, dimensions=dims,
                                  timeout=float(env("BETONNING_EMBED_TIMEOUT", "30")))


# --- Vector-serialisatie (float32-blob) -----------------------------------


def pack_vector(vec: list[float]) -> bytes:
    return array("f", vec).tobytes()


def unpack_vector(blob: bytes) -> list[float]:
    a = array("f")
    a.frombytes(blob)
    return list(a)


# --- Store ----------------------------------------------------------------


def upsert(
    conn: sqlite3.Connection, item_id: int, model: str, vec: list[float]
) -> None:
    conn.execute(
        """INSERT INTO item_embeddings (item_id, model, dims, vector, updated_at)
           VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
           ON CONFLICT(item_id) DO UPDATE SET
               model = excluded.model, dims = excluded.dims,
               vector = excluded.vector, updated_at = excluded.updated_at""",
        (item_id, model, len(vec), pack_vector(vec)),
    )


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def find_similar(
    conn: sqlite3.Connection,
    project_id: int,
    query_vec: list[float],
    *,
    top_k: int = 10,
    exclude_item_id: int | None = None,
) -> list[tuple[int, float]]:
    """Top-k gelijkende items (op cosine) binnen één project, excl. gearchiveerde
    en het item zelf. Geeft [(item_id, score)] aflopend gesorteerd."""
    rows = conn.execute(
        """SELECT e.item_id AS item_id, e.vector AS vector FROM item_embeddings e
           JOIN items i ON i.id = e.item_id
           WHERE i.project_id = ? AND i.archived_at IS NULL""",
        (project_id,),
    ).fetchall()
    scored: list[tuple[int, float]] = []
    for r in rows:
        if exclude_item_id is not None and r["item_id"] == exclude_item_id:
            continue
        scored.append((r["item_id"], cosine(query_vec, unpack_vector(r["vector"]))))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:top_k]
