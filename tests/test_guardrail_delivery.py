"""Bezorging van guardrails aan agents (BETON-420, fase 2).

Twee lagen, nooit dubbel: projectbrede guardrails staan bovenaan de
wiki-context (`load_memory`), gescopede komen als `applicable_guardrails` mee
in `get_item` van een ticket dat een van de scope-labels draagt.
"""

from __future__ import annotations

import sqlite3

import pytest

from betonning.repo import guardrails as guardrails_repo
from betonning.repo import items as items_repo
from betonning.repo import wiki as wiki_repo


@pytest.fixture
def seeded(client, auth, conn: sqlite3.Connection):
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    for name in ("prompts", "ui"):
        client.post("/api/v1/projects/SOS/labels", json={"name": name}, headers=auth)
    for title in ("een", "twee", "drie"):
        client.post("/api/v1/projects/SOS/items", json={"title": title}, headers=auth)
    client.post(
        "/api/v1/wiki",
        json={"slug": "globaal", "title": "Globaal", "body_md": "globale kennis"},
        headers=auth,
    )
    client.post(
        "/api/v1/projects/SOS/wiki",
        json={"slug": "lokaal", "title": "Lokaal", "body_md": "projectkennis"},
        headers=auth,
    )
    return conn


def _project_id(conn, key="SOS"):
    return conn.execute("SELECT id FROM projects WHERE key = ?", (key,)).fetchone()["id"]


def _set(conn, ref, text="Houd prompts kort.", review_by="2099-01-01", scope=()):
    item = items_repo.get_by_ref(conn, ref)
    guardrails_repo.set_guardrail(
        conn, item["id"], text=text, review_by=review_by, set_by=None
    )
    if scope:
        ids = [
            conn.execute(
                "SELECT l.id FROM labels l JOIN projects p ON p.id = l.project_id "
                "WHERE p.key = ? AND l.name = ?",
                (ref.split("-")[0], name),
            ).fetchone()["id"]
            for name in scope
        ]
        guardrails_repo.set_scope(conn, item["id"], ids)
    return item


# --- Stap 2.1: guardrail-blok in de wiki-context ---------------------------


def test_blok_staat_bovenaan_de_projectcontext(seeded):
    conn = seeded
    _set(conn, "SOS-1", text="Houd prompts kort.")
    md = wiki_repo.context_markdown(conn, _project_id(conn))
    assert md.startswith(wiki_repo.GUARDRAIL_HEADING)
    assert "SOS-1" in md
    assert "Houd prompts kort." in md
    assert "2099-01-01" in md
    # De wiki-body staat er onverkort onder.
    assert md.index(wiki_repo.GUARDRAIL_HEADING) < md.index("# Globale memory")
    assert "globale kennis" in md and "projectkennis" in md


def test_globale_context_krijgt_geen_blok(seeded):
    conn = seeded
    _set(conn, "SOS-1")
    md = wiki_repo.context_markdown(conn, None)
    assert wiki_repo.GUARDRAIL_HEADING not in md


def test_gescopede_opgeheven_en_gearchiveerde_staan_er_niet_in(seeded):
    conn = seeded
    _set(conn, "SOS-1", text="gescoped", scope=("prompts",))
    _set(conn, "SOS-2", text="opgeheven")
    guardrails_repo.lift(conn, items_repo.get_by_ref(conn, "SOS-2")["id"])
    _set(conn, "SOS-3", text="gearchiveerd")
    conn.execute(
        "UPDATE items SET archived_at = '2020-01-01' WHERE id = ?",
        (items_repo.get_by_ref(conn, "SOS-3")["id"],),
    )
    md = wiki_repo.context_markdown(conn, _project_id(conn))
    assert wiki_repo.GUARDRAIL_HEADING not in md
    for text in ("gescoped", "opgeheven", "gearchiveerd"):
        assert text not in md


def test_blok_verdringt_geen_wiki_paginas(seeded):
    """Het blok staat buiten de budgetverdeling: de wiki-body die zonder blok
    geladen zou worden, blijft exact hetzelfde mét blok."""
    conn = seeded
    pid = _project_id(conn)
    zonder = wiki_repo.context_markdown(conn, pid, budget=200)
    _set(conn, "SOS-1", text="x" * 400)
    met = wiki_repo.context_markdown(conn, pid, budget=200)
    assert met.endswith(zonder)
    assert met.startswith(wiki_repo.GUARDRAIL_HEADING)


def test_compile_context_krijgt_het_blok_niet(seeded):
    """De wiki-compiler herschrijft pagina-bodies; kreeg hij het blok, dan ging
    hij guardrails ín wiki-pagina's schrijven."""
    conn = seeded
    _set(conn, "SOS-1", text="Houd prompts kort.")
    md = wiki_repo.compile_context(conn, _project_id(conn))
    assert wiki_repo.GUARDRAIL_HEADING not in md
    assert "Houd prompts kort." not in md


def test_context_endpoint_levert_het_blok(seeded, client, auth):
    conn = seeded
    _set(conn, "SOS-1", text="Houd prompts kort.")
    r = client.get("/api/v1/projects/SOS/wiki/context", headers=auth)
    assert r.status_code == 200
    assert r.text.startswith(wiki_repo.GUARDRAIL_HEADING)
# --- Stap 2.2: get_item draagt de toepasselijke guardrails -----------------


def test_get_item_draagt_gescopede_guardrail_van_ander_ticket(seeded, client, auth):
    conn = seeded
    _set(conn, "SOS-1", text="prompt-regel", scope=("prompts",))
    client.post("/api/v1/items/SOS-2/labels/prompts", headers=auth)

    data = client.get("/api/v1/items/SOS-2", headers=auth).json()
    assert [g["ref"] for g in data["applicable_guardrails"]] == ["SOS-1"]
    assert data["applicable_guardrails"][0]["guardrail_md"] == "prompt-regel"


def test_get_item_zonder_het_label_krijgt_niets(seeded, client, auth):
    conn = seeded
    _set(conn, "SOS-1", text="prompt-regel", scope=("prompts",))
    data = client.get("/api/v1/items/SOS-3", headers=auth).json()
    assert data["applicable_guardrails"] == []


def test_projectbrede_guardrail_zit_niet_in_applicable(seeded, client, auth):
    """Die heeft de agent al uit de wiki-context; dubbel leveren is dubbel
    betalen."""
    conn = seeded
    _set(conn, "SOS-1", text="projectbreed")
    client.post("/api/v1/items/SOS-2/labels/prompts", headers=auth)
    data = client.get("/api/v1/items/SOS-2", headers=auth).json()
    assert data["applicable_guardrails"] == []


def test_ticket_ziet_zijn_eigen_guardrail_niet_in_applicable(seeded, client, auth):
    conn = seeded
    client.post("/api/v1/items/SOS-1/labels/prompts", headers=auth)
    _set(conn, "SOS-1", text="eigen", scope=("prompts",))
    data = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert data["applicable_guardrails"] == []
    assert data["guardrail_md"] == "eigen"  # die zit al in serialize
