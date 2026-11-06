"""Begrensd inlezen van uploads (BETON-380): `uploads.read_limited`."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from betonning import uploads


class FakeUploadFile:
    """Minimale UploadFile-vervanger die telt hoeveel bytes zijn opgevraagd."""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0
        self.read_total = 0

    async def read(self, size: int = -1) -> bytes:
        chunk = self._data[self._pos :] if size < 0 else self._data[self._pos : self._pos + size]
        self._pos += len(chunk)
        self.read_total += len(chunk)
        return chunk


def test_read_limited_returns_all_bytes_under_limit():
    f = FakeUploadFile(b"x" * 1000)
    assert asyncio.run(uploads.read_limited(f, 10_000)) == b"x" * 1000


def test_read_limited_raises_413_over_limit():
    f = FakeUploadFile(b"x" * 5000)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(uploads.read_limited(f, 100))
    assert exc.value.status_code == 413


def test_read_limited_stops_reading_at_the_limit():
    # 11 MB aangeboden, 10 MB cap: de handler mag niet het hele bestand
    # het geheugen in trekken vóór hij de lengte controleert.
    f = FakeUploadFile(b"x" * (11 * 1024 * 1024))
    with pytest.raises(HTTPException):
        asyncio.run(uploads.read_limited(f, 10 * 1024 * 1024))
    assert f.read_total <= 10 * 1024 * 1024 + uploads.CHUNK_SIZE


def test_read_limited_accepts_exactly_the_limit():
    f = FakeUploadFile(b"x" * 256)
    assert len(asyncio.run(uploads.read_limited(f, 256))) == 256
