"""Telling van inkomende MCP-requests per JSON-RPC-methode en per user (BETON-467).

Doel: verklaren waarom er ~13 `POST /mcp/` per uitgevoerde toolcall binnenkomen.
Alleen tellers in het geheugen; er wordt nooit een request-body gelogd of
bewaard. Eén INFO-logregel per interval (lazy bij de eerstvolgende request) en
bij shutdown.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter

log = logging.getLogger("betonning.mcp_stats")

FLUSH_INTERVAL = 3600.0
MAX_PEEK_BYTES = 1_048_576  # groter dan dit: body niet parsen, methode "?"


def method_of(body: bytes) -> str:
    """JSON-RPC-methode uit een request-body. Batch → methodes samengevoegd;
    onleesbaar → "?"."""
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return "?"
    items = data if isinstance(data, list) else [data]
    names = sorted(
        {str(i.get("method", "?")) if isinstance(i, dict) else "?" for i in items}
    )
    return ",".join(names) if names else "?"


class McpStats:
    def __init__(self, interval: float = FLUSH_INTERVAL, clock=time.monotonic):
        self._counts: Counter = Counter()
        self._interval = interval
        self._clock = clock
        self._since = clock()
        self._lock = threading.Lock()

    def record(self, http_method: str, rpc_method: str | None, handle: str) -> None:
        line = None
        with self._lock:
            self._counts[(http_method, rpc_method or "-", handle)] += 1
            if self._clock() - self._since >= self._interval:
                line = self._drain()
        if line:
            log.info(line)

    def flush(self) -> None:
        with self._lock:
            line = self._drain()
        if line:
            log.info(line)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._counts)

    def _drain(self) -> str | None:
        counts, self._counts = self._counts, Counter()
        self._since = self._clock()
        if not counts:
            return None
        parts = [
            f"{h}:{m}:{r}={n}" for (m, r, h), n in sorted(counts.items())
        ]
        return f"mcp-requests total={sum(counts.values())} " + " ".join(parts)
