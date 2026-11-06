"""Begrensd inlezen van multipart-uploads (BETON-380).

`UploadFile.read()` zonder argument trekt het hele bestand het geheugen in. Voor
een 10 MB-limiet is dat nog te overzien, maar het is de verkeerde volgorde: eerst
alles inlezen en dán de lengte controleren. `read_limited` leest in chunks en
stopt zodra de teller de limiet passeert.

Let op de reikwijdte: Starlette's multipart-parser heeft de body op dat moment al
volledig gelezen (en boven ~1 MiB naar een tijdelijk bestand gespoold). Deze
functie begrenst dus het *geheugen van de handler*, niet wat er over de lijn
kwam. De echte poort vóór inlezen is de body-size-middleware in `server.py`, die
multipart een ruimere cap geeft dan JSON.
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile

CHUNK_SIZE = 64 * 1024


async def read_limited(file: UploadFile, max_size: int) -> bytes:
    """Lees hooguit ``max_size`` bytes; daarboven 413 zonder de rest te lezen."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size:
            raise HTTPException(
                status_code=413,
                detail=f"Bestand te groot (max {max_size // (1024 * 1024)} MB)",
            )
        chunks.append(chunk)
    return b"".join(chunks)
