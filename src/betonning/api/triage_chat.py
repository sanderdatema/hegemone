"""Chat-met-triage-endpoints (BETON-120): een mens converseert met de triage-bot.

Geschaald als de wiki: een globale thread op `/triage-chat` en één thread per
project op `/projects/{key}/triage-chat`. Per scope is er één actieve sessie
(`repo/triage_chat.active_session`); "Nieuw gesprek" archiveert die en de volgende
call start een verse. Alleen mensen mogen chatten (`current_human` → 403 voor
agents); zonder LLM-client → 503 (zoals enrich/decompose).

De motor (`triage_chat_engine`) doet het echte werk: `run_turn` (query-lus →
reply/proposal), `confirm` (voert een bevestigd voorstel uit als user `triage`,
met de mens als opdrachtgever in de audit-log) en `cancel`.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..deps import (
    current_human,
    get_db,
    require_project,
    llm_errors_as_502,
    llm_rate_limited,
    require_llm_client,
)
from ..models import TriageChatConfirm, TriageChatMessage
from ..repo import triage_chat as chat_repo
from ..triage_chat_engine import (
    ConfirmationRequired,
    LLMError,
    ProposalNotPending,
    cancel,
    confirm,
    run_turn,
)

router = APIRouter(tags=["triage-chat"])


def _project_id(conn: sqlite3.Connection, key: str) -> int:
    return require_project(conn, key)["id"]


def _serialize_session(conn: sqlite3.Connection, project_id: int | None) -> dict:
    """De actieve sessie van een scope: berichtenhistorie + eventueel het
    openstaande voorstel."""
    session = chat_repo.active_session(conn, project_id)
    messages = [
        chat_repo.serialize_message(m)
        for m in chat_repo.list_messages(conn, session["id"])
    ]
    pending = chat_repo.get_pending(conn, session["id"])
    return {
        "session_id": session["id"],
        "project_id": project_id,
        "messages": messages,
        "pending": chat_repo.serialize_message(pending) if pending else None,
    }


# --- Globale thread --------------------------------------------------------


@router.get("/triage-chat")
def get_global(
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    return _serialize_session(conn, None)


@router.post("/triage-chat")
def post_global(
    body: TriageChatMessage,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_human),
    _rate: sqlite3.Row = Depends(llm_rate_limited),
    llm=Depends(require_llm_client),
) -> dict:
    with llm_errors_as_502(LLMError):
        return run_turn(conn, llm, body.message, user["id"], project_id=None)


@router.post("/triage-chat/archive")
def archive_global(
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    session = chat_repo.active_session(conn, None)
    chat_repo.archive_session(conn, session["id"])
    return _serialize_session(conn, None)


# --- Projectthread ---------------------------------------------------------


@router.get("/projects/{key}/triage-chat")
def get_project(
    key: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    return _serialize_session(conn, _project_id(conn, key))


@router.post("/projects/{key}/triage-chat")
def post_project(
    key: str,
    body: TriageChatMessage,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_human),
    _rate: sqlite3.Row = Depends(llm_rate_limited),
    llm=Depends(require_llm_client),
) -> dict:
    with llm_errors_as_502(LLMError):
        return run_turn(conn, llm, body.message, user["id"], project_id=_project_id(conn, key))


@router.post("/projects/{key}/triage-chat/archive")
def archive_project(
    key: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    pid = _project_id(conn, key)
    session = chat_repo.active_session(conn, pid)
    chat_repo.archive_session(conn, session["id"])
    return _serialize_session(conn, pid)


# --- Voorstel bevestigen / annuleren (scope-onafhankelijk: op message_id) --


@router.post("/triage-chat/{message_id}/confirm")
def confirm_message(
    message_id: int,
    body: TriageChatConfirm | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_human),
) -> dict:
    typed_count = body.typed_count if body else None
    try:
        return confirm(conn, message_id, user["id"], typed_count=typed_count)
    except ProposalNotPending as exc:
        raise HTTPException(status_code=409, detail="Voorstel is niet (meer) open") from exc
    except ConfirmationRequired as exc:
        # Veiligheidsrem: typ het aantal om een bulk-actie te bevestigen.
        raise HTTPException(
            status_code=409,
            detail={"error": "confirmation_required", "total": exc.total},
        ) from exc


@router.post("/triage-chat/{message_id}/cancel")
def cancel_message(
    message_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> dict:
    try:
        return cancel(conn, message_id)
    except ProposalNotPending as exc:
        raise HTTPException(status_code=409, detail="Voorstel is niet (meer) open") from exc
