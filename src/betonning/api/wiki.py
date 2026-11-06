"""Wiki-endpoints: markdown-kennispagina's globaal of per project + agent-context.

Betonning fungeert hiermee als memory-provider (BETON-24): agents lezen de wiki
via de context-endpoints en laden die als geheugen. Globale pagina's gelden voor
alle projecten; projectpagina's alleen binnen hun project. De context-routes staan
vóór de `{slug}`-routes zodat "context" geen slug kaapt.
"""

from __future__ import annotations

from ..outbound import outbound

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import db as db_module, credential_policy
from ..deps import current_human, current_user, get_db, require_project
from ..models import WikiPageCreate, WikiPageUpdate
from ..repo import wiki as wiki_repo
from ..repo import wiki_review

router = APIRouter(tags=["wiki"])


def _submit_review(conn, *args, **kwargs):
    result = wiki_review.submit(conn, *args, **kwargs)
    return {**result, 'message': outbound('wiki.pending_review')}


def _project_id(conn: sqlite3.Connection, key: str) -> int:
    return require_project(conn, key)["id"]


def _create_page(
    conn: sqlite3.Connection,
    project_id: int | None,
    body: WikiPageCreate,
    author_id: int | None = None,
) -> dict:
    slug = wiki_repo.slugify(body.slug)
    if not wiki_repo.is_valid_slug(slug):
        raise HTTPException(status_code=422, detail=f"Ongeldige slug: {body.slug!r}")
    if wiki_repo.get_by_slug(conn, project_id, slug) is not None:
        raise HTTPException(status_code=409, detail=f"Wiki-pagina bestaat al: {slug}")
    with db_module.transaction(conn):
        if wiki_review.needs_review(conn, project_id, slug, author_id):
            return _submit_review(conn, project_id, slug, body.title, body.body_md, author_id)
        row = wiki_repo.create(
            conn, project_id=project_id, slug=slug, title=body.title,
            body_md=body.body_md, author_id=author_id,
        )
    return wiki_repo.serialize(row)


def _get_page(conn: sqlite3.Connection, project_id: int | None, slug: str) -> dict:
    row = wiki_repo.get_by_slug(conn, project_id, slug)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Onbekende wiki-pagina: {slug}")
    return wiki_repo.serialize(row)


def _update_page(
    conn: sqlite3.Connection,
    project_id: int | None,
    slug: str,
    body: WikiPageUpdate,
    author_id: int | None = None,
) -> dict:
    row = wiki_repo.get_by_slug(conn, project_id, slug)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Onbekende wiki-pagina: {slug}")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    with db_module.transaction(conn):
        if wiki_review.needs_review(conn, project_id, slug, author_id):
            return _submit_review(conn, project_id, slug, fields.get("title", row["title"]),
                                      fields.get("body_md", row["body_md"]), author_id)
        row = wiki_repo.update(conn, row["id"], fields, author_id=author_id)
    return wiki_repo.serialize(row)


def _list_revisions(conn: sqlite3.Connection, project_id: int | None, slug: str) -> list[dict]:
    row = wiki_repo.get_by_slug(conn, project_id, slug)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Onbekende wiki-pagina: {slug}")
    return [wiki_repo.serialize_revision(r) for r in wiki_repo.list_revisions(conn, row["id"])]


def _get_revision(
    conn: sqlite3.Connection, project_id: int | None, slug: str, revision_id: int
) -> dict:
    """De volledige snapshot van één revisie + de voorganger (voor de diff)."""
    page = wiki_repo.get_by_slug(conn, project_id, slug)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Onbekende wiki-pagina: {slug}")
    rev = wiki_repo.get_revision(conn, revision_id)
    if rev is None or rev["page_id"] != page["id"]:
        raise HTTPException(status_code=404, detail=f"Onbekende revisie: {revision_id}")
    prev = wiki_repo.predecessor_revision(conn, page["id"], rev["created_at"], rev["id"])
    return {
        "revision": wiki_repo.serialize_revision(rev, include_body=True),
        "previous": wiki_repo.serialize_revision(prev, include_body=True) if prev else None,
    }


def _restore_revision(
    conn: sqlite3.Connection,
    project_id: int | None,
    slug: str,
    revision_id: int,
    author_id: int | None,
) -> dict:
    """Zet de pagina-inhoud terug naar een revisie. Dit muteert de historie niet:
    de restore legt een nieuwe revisie vast (auteur = wie terugzette)."""
    page = wiki_repo.get_by_slug(conn, project_id, slug)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Onbekende wiki-pagina: {slug}")
    rev = wiki_repo.get_revision(conn, revision_id)
    if rev is None or rev["page_id"] != page["id"]:
        raise HTTPException(status_code=404, detail=f"Onbekende revisie: {revision_id}")
    with db_module.transaction(conn):
        if wiki_review.needs_review(conn, project_id, slug, author_id):
            return _submit_review(conn, project_id, slug, rev["title"], rev["body_md"], author_id)
        row = wiki_repo.update(
            conn, page["id"], {"title": rev["title"], "body_md": rev["body_md"]},
            author_id=author_id,
        )
    return wiki_repo.serialize(row)


def _delete_page(conn: sqlite3.Connection, project_id: int | None, slug: str) -> None:
    row = wiki_repo.get_by_slug(conn, project_id, slug)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Onbekende wiki-pagina: {slug}")
    with db_module.transaction(conn):
        wiki_repo.delete(conn, row["id"])


def _context(conn: sqlite3.Connection, project_id: int | None) -> Response:
    md = wiki_repo.context_markdown(conn, project_id)
    return Response(content=md, media_type="text/markdown; charset=utf-8")


# --- Globale wiki ----------------------------------------------------------


@router.get("/wiki")
def list_global(
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    return [wiki_repo.serialize(r) for r in wiki_repo.list_pages(conn, None)]


@router.post("/wiki", status_code=201)
def create_global(
    body: WikiPageCreate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    return _create_page(conn, None, body, author_id=user["id"])


@router.get("/wiki/context")
def context_global(
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> Response:
    """De globale memory als één markdown-blob (voor agents)."""
    return _context(conn, None)


@router.get("/wiki/index")
def wiki_index(
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    """Lichte cross-scope index ``[{scope, slug}]`` over álle scopes (BETON-306).

    Voedt de levend/dood-markering van gekwalificeerde interlinks
    (``[[BETON:slug]]``) in de UI; alleen slugs, geen bodies. Staat vóór de
    ``/wiki/{slug}``-route zodat "index" geen slug kaapt."""
    allowed = credential_policy.projects(user)
    return [row for row in wiki_repo.list_index(conn)
            if allowed is None or row["scope"] == "global" or row["scope"] in allowed]


@router.get("/wiki/{slug}")
def get_global(
    slug: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    return _get_page(conn, None, slug)


@router.patch("/wiki/{slug}")
def update_global(
    slug: str,
    body: WikiPageUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    return _update_page(conn, None, slug, body, author_id=user["id"])


@router.get("/wiki/{slug}/revisions")
def list_revisions_global(
    slug: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    return _list_revisions(conn, None, slug)


@router.get("/wiki/{slug}/revisions/{revision_id}")
def get_revision_global(
    slug: str,
    revision_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    return _get_revision(conn, None, slug, revision_id)


@router.post("/wiki/{slug}/revisions/{revision_id}/restore")
def restore_revision_global(
    slug: str,
    revision_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    return _restore_revision(conn, None, slug, revision_id, author_id=user["id"])


@router.delete("/wiki/{slug}", status_code=204)
def delete_global(
    slug: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> None:
    """Verwijdert een wiki-pagina onherroepelijk. Mens-only (BETON-377)."""
    _delete_page(conn, None, slug)


# --- Projectwiki -----------------------------------------------------------


@router.get("/projects/{key}/wiki")
def list_project(
    key: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    pid = _project_id(conn, key)
    return [wiki_repo.serialize(r) for r in wiki_repo.list_pages(conn, pid)]


@router.post("/projects/{key}/wiki", status_code=201)
def create_project(
    key: str,
    body: WikiPageCreate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    return _create_page(conn, _project_id(conn, key), body, author_id=user["id"])


@router.get("/projects/{key}/wiki/context")
def context_project(
    key: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> Response:
    """De memory voor een project: globale + projectpagina's samengevoegd."""
    return _context(conn, _project_id(conn, key))


@router.get("/projects/{key}/wiki/{slug}")
def get_project(
    key: str,
    slug: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    return _get_page(conn, _project_id(conn, key), slug)


@router.patch("/projects/{key}/wiki/{slug}")
def update_project(
    key: str,
    slug: str,
    body: WikiPageUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    return _update_page(conn, _project_id(conn, key), slug, body, author_id=user["id"])


@router.get("/projects/{key}/wiki/{slug}/revisions")
def list_revisions_project(
    key: str,
    slug: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> list[dict]:
    return _list_revisions(conn, _project_id(conn, key), slug)


@router.get("/projects/{key}/wiki/{slug}/revisions/{revision_id}")
def get_revision_project(
    key: str,
    slug: str,
    revision_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_user),
) -> dict:
    return _get_revision(conn, _project_id(conn, key), slug, revision_id)


@router.post("/projects/{key}/wiki/{slug}/revisions/{revision_id}/restore")
def restore_revision_project(
    key: str,
    slug: str,
    revision_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    return _restore_revision(
        conn, _project_id(conn, key), slug, revision_id, author_id=user["id"]
    )


@router.delete("/projects/{key}/wiki/{slug}", status_code=204)
def delete_project(
    key: str,
    slug: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: sqlite3.Row = Depends(current_human),
) -> None:
    """Verwijdert een wiki-pagina onherroepelijk. Mens-only (BETON-377)."""
    _delete_page(conn, _project_id(conn, key), slug)
