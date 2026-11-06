"""Content-addressed bestandsopslag voor attachments.

Bytes worden op disk bewaard onder `<base>/<sha[:2]>/<sha>`. Content-addressed:
identieke bytes → hetzelfde pad, dus uploads dedupliceren en schrijven is
idempotent. De DB houdt de metadata; deze module kent alleen de bytes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def disk_path(base: str | Path, sha: str) -> Path:
    """Pad op disk voor een sha (twee-teken-shard tegen te volle mappen)."""
    return Path(base) / sha[:2] / sha


def write_bytes(base: str | Path, sha: str, data: bytes) -> None:
    """Schrijf idempotent: bestaat het content-adres al, dan niets doen."""
    p = disk_path(base, sha)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_bytes(data)


def read_bytes(base: str | Path, sha: str) -> bytes | None:
    p = disk_path(base, sha)
    return p.read_bytes() if p.exists() else None
