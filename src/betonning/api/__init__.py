"""API-routers: me, projects (+states/labels/milestones), items, search, wiki,
deliveries (webhook-inzicht/replay), overview (cross-project stand, BETON-371)."""

from fastapi import APIRouter

from . import (
    attachments,
    deliveries,
    inbox,
    installation,
    configuration,
    items,
    me,
    media,
    overview,
    onboarding,
    projects,
    search,
    settings,
    setup,
    sessions,
    stream,
    triage_chat,
    users,
    wiki,
    wiki_review,
)

router = APIRouter(prefix="/api/v1")
router.include_router(me.router)
router.include_router(sessions.router)
router.include_router(setup.router)
router.include_router(onboarding.router)
router.include_router(users.router)
router.include_router(projects.router)
router.include_router(items.router)
router.include_router(search.router)
router.include_router(stream.router)
router.include_router(attachments.router)
router.include_router(media.router)
router.include_router(wiki_review.router)
router.include_router(wiki.router)
router.include_router(triage_chat.router)
router.include_router(deliveries.router)
router.include_router(inbox.router)
router.include_router(overview.router)
router.include_router(settings.router)
router.include_router(installation.router)
router.include_router(configuration.router)
