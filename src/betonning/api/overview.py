"""Overzicht-endpoint (BETON-371): ``GET /overview``.

Eén gebatchte stand van zaken over álle levende projecten — de tellers die de
UI-view "Overzicht" toont. De logica (en het query-budget) zit in
`repo/overview.py`; dit is een dunne route.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..deps import current_user, get_db
from ..repo import overview as overview_repo

router = APIRouter(tags=["overview"])


@router.get("/overview")
def get_overview(
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    return overview_repo.project_overview(conn, user["id"], user["handle"])
