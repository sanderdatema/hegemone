"""/me endpoint: wie ben ik (op basis van de Bearer-key) + eigen instellingen."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import webhooks, credential_policy
from ..deps import current_user, get_db
from ..repo import users as users_repo

router = APIRouter(tags=["me"])


@router.get("/me")
def get_me(user: sqlite3.Row = Depends(current_user)) -> dict:
    return {**users_repo.serialize(user), "credential_policy": {
        "scopes": sorted(credential_policy.scopes(user)),
        "projects": None if credential_policy.projects(user) is None else sorted(credential_policy.projects(user)),
        "expires_at": user["api_key_expires_at"],
    }}


@router.get("/users")
def list_users(
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    """Alle users — voedt o.a. de @mention-autocomplete in de UI."""
    return users_repo.list_all(conn)


class MeSettingsUpdate(BaseModel):
    webhook_url: str | None = None
    webhook_secret: str | None = None
    subscribe_all: bool | None = None
    telegram_chat_id: str | None = None
    active: bool | None = None
    description: str | None = Field(default=None, max_length=4000)


# Velden die het bezorgkanaal van een user bepalen: alleen een mens zet die
# (voor zichzelf én voor agents). Zie update_me_settings (BETON-378).
_CHANNEL_FIELDS = ("webhook_url", "webhook_secret", "telegram_chat_id")


@router.get("/users/me/settings")
def get_me_settings(user: sqlite3.Row = Depends(current_user)) -> dict:
    """Eigen webhook/telegram-instellingen (BETON-49). Géén user-beheer van
    anderen: dit endpoint werkt uitsluitend op de ingelogde user."""
    return users_repo.serialize_settings(user)


@router.patch("/users/me/settings")
def update_me_settings(
    body: MeSettingsUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    """Werk de eigen instellingen bij (partial update, alleen meegegeven velden).

    Een agent mag zijn eigen **bezorgkanaal** niet zetten (BETON-378): met een
    zelfgekozen `webhook_url` bepaalt hij waar de server naartoe verbindt (SSRF)
    en wie de payloads van andermans tickets meeleest. Dat blijft mensenwerk via
    `PATCH /users/{handle}` of `python -m betonning.admin set-webhook` — precies
    de route waarlangs Hermes-agents (die geen eigen key hebben) al werden
    geconfigureerd (BETON-83/84). De rest van de instellingen blijft van hemzelf."""
    updates = body.model_dump(exclude_unset=True)
    # Deny-by-default: alles wat geen mens is (ook een onbekende toekomstige kind).
    if user["kind"] != "human":
        blocked = [f for f in _CHANNEL_FIELDS if f in updates]
        if blocked:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Een agent kan zijn eigen bezorgkanaal niet zetten "
                    f"({', '.join(blocked)}); een mens doet dat via PATCH /users/{{handle}}"
                ),
            )
    if "webhook_url" in updates:
        reason = webhooks.webhook_url_error(updates["webhook_url"])
        if reason is not None:
            raise HTTPException(status_code=422, detail=reason)
    users_repo.update_settings(conn, user["id"], updates)
    fresh = users_repo.get_required(conn, user["id"])
    return users_repo.serialize_settings(fresh)
