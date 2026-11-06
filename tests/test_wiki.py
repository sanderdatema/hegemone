"""Wiki / memory-provider: repo-scoping + CRUD-API + agent-context (BETON-24)."""

from __future__ import annotations

from betonning.repo import projects as projects_repo
from betonning.repo import wiki as wiki_repo


# --- Repo -----------------------------------------------------------------


def test_slugify_and_validation():
    assert wiki_repo.slugify("Deploy Gotchas!") == "deploy-gotchas"
    assert wiki_repo.is_valid_slug("deploy-gotchas")
    assert not wiki_repo.is_valid_slug("Deploy Gotchas")


def test_same_slug_allowed_across_scopes(conn):
    p = projects_repo.create(conn, key="SOS", name="SOS")
    conn.commit()
    wiki_repo.create(conn, project_id=None, slug="stijl", title="Globaal", body_md="g")
    wiki_repo.create(conn, project_id=p["id"], slug="stijl", title="Project", body_md="p")
    conn.commit()
    assert wiki_repo.get_by_slug(conn, None, "stijl")["title"] == "Globaal"
    assert wiki_repo.get_by_slug(conn, p["id"], "stijl")["title"] == "Project"


def test_list_index_covers_all_scopes(conn):
    """BETON-306: de cross-scope index draagt (scope, slug) over álle scopes;
    scope = 'global' voor globale pagina's, anders de project-key."""
    p = projects_repo.create(conn, key="SOS", name="SOS")
    conn.commit()
    wiki_repo.create(conn, project_id=None, slug="stijl", title="G", body_md="g")
    wiki_repo.create(conn, project_id=p["id"], slug="stijl", title="P", body_md="p")
    wiki_repo.create(conn, project_id=p["id"], slug="deploy", title="D", body_md="d")
    conn.commit()
    index = wiki_repo.list_index(conn)
    assert {"scope": "global", "slug": "stijl"} in index
    assert {"scope": "SOS", "slug": "stijl"} in index
    assert {"scope": "SOS", "slug": "deploy"} in index
    assert len(index) == 3


def test_wiki_index_endpoint(client, auth, project):
    client.post("/api/v1/wiki", json={"slug": "g", "title": "G"}, headers=auth)
    client.post(
        "/api/v1/projects/SOS/wiki", json={"slug": "p", "title": "P"}, headers=auth
    )
    r = client.get("/api/v1/wiki/index", headers=auth)
    assert r.status_code == 200
    index = r.json()
    assert {"scope": "global", "slug": "g"} in index
    assert {"scope": "SOS", "slug": "p"} in index


def test_wiki_index_requires_auth(client):
    assert client.get("/api/v1/wiki/index").status_code == 401


def test_wiki_index_does_not_collide_with_slug_route(client, auth):
    """`/wiki/index` mag niet als slug 'index' worden gelezen (route-volgorde)."""
    r = client.get("/api/v1/wiki/index", headers=auth)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_context_markdown_merges_global_and_project(conn):
    p = projects_repo.create(conn, key="SOS", name="SOS")
    conn.commit()
    wiki_repo.create(conn, project_id=None, slug="g", title="Globale regel", body_md="altijd")
    wiki_repo.create(conn, project_id=p["id"], slug="pp", title="Projectregel", body_md="hier")
    conn.commit()
    # Globale context bevat alleen globaal.
    g = wiki_repo.context_markdown(conn, None)
    assert "Globale regel" in g and "Projectregel" not in g
    # Projectcontext bevat beide, met herkomst-koppen.
    both = wiki_repo.context_markdown(conn, p["id"])
    assert "# Globale memory" in both and "# Projectmemory" in both
    assert "altijd" in both and "hier" in both


def test_context_markdown_under_budget_is_full(conn):
    wiki_repo.create(
        conn, project_id=None, slug="g", title="Regel",
        body_md="eerste alinea\n\ntweede alinea met details",
    )
    conn.commit()
    # Ruim budget → volledige inhoud, geen inkort-melding.
    md = wiki_repo.context_markdown(conn, None, budget=10_000)
    assert "eerste alinea" in md and "tweede alinea met details" in md
    assert wiki_repo.INDEX_HEADING not in md


def test_context_markdown_over_budget_keeps_pages_whole(conn):
    """Boven het budget: volledige pagina's tot het budget op is, rest als index.

    Inkorten tot losse eerste alinea's leverde een blob op waarin vrijwel elke
    pagina alleen zijn eigen titel herhaalde (BETON-352).
    """
    wiki_repo.create(
        conn, project_id=None, slug="oud", title="Oud",
        body_md="# Oud\n\noude inhoud die niet meer past " + ("vulling " * 20),
    )
    conn.commit()
    wiki_repo.create(
        conn, project_id=None, slug="nieuw", title="Nieuw",
        body_md="# Nieuw\n\nverse inhoud " + ("vulling " * 20),
    )
    conn.commit()
    md = wiki_repo.context_markdown(conn, None, budget=500)  # inclusief bronmetadata
    # De meest recent bijgewerkte pagina gaat volledig mee...
    assert "verse inhoud" in md
    # ...de andere staat alleen als index-regel met zijn blurb.
    assert "oude inhoud die niet meer past" not in md
    assert "`oud` — Oud" in md
    assert "# Niet geladen (index)" in md


def test_context_index_blurb_skips_title_echo(conn):
    """Een leidende H1 die de titel herhaalt levert geen bruikbare blurb op."""
    assert wiki_repo._blurb("# Regel\n\nde echte uitleg") == "de echte uitleg"
    assert wiki_repo._blurb("# Regel") == ""


def test_context_markdown_respects_budget(conn):
    for i in range(6):
        wiki_repo.create(
            conn, project_id=None, slug=f"p{i}", title=f"P{i}",
            body_md=f"# P{i}\n\n" + ("inhoud " * 40),
        )
        conn.commit()
    md = wiki_repo.context_markdown(conn, None, budget=900)
    assert len(md) <= 900
    # Er gaat wél iets volledigs mee — geen lege index-only blob.
    assert "inhoud inhoud" in md


def test_context_markdown_budget_too_small_falls_back_to_index(conn):
    wiki_repo.create(
        conn, project_id=None, slug="groot", title="Groot",
        body_md="# Groot\n\nkop-alinea\n\n" + ("veel tekst " * 50) + "STAART",
    )
    conn.commit()
    md = wiki_repo.context_markdown(conn, None, budget=50)
    assert "STAART" not in md
    assert "`groot` — Groot" in md


def test_context_budget_default_and_env(conn, monkeypatch):
    monkeypatch.delenv("BETONNING_WIKI_CONTEXT_BUDGET", raising=False)
    assert wiki_repo.context_budget() == wiki_repo.DEFAULT_CONTEXT_BUDGET
    monkeypatch.setenv("BETONNING_WIKI_CONTEXT_BUDGET", "123")
    assert wiki_repo.context_budget() == 123
    # Onzin-waarde valt terug op de default.
    monkeypatch.setenv("BETONNING_WIKI_CONTEXT_BUDGET", "notanumber")
    assert wiki_repo.context_budget() == wiki_repo.DEFAULT_CONTEXT_BUDGET


def test_context_budget_zero_means_unlimited(conn):
    wiki_repo.create(
        conn, project_id=None, slug="g", title="Regel",
        body_md="eerste\n\ntweede lange alinea die normaal weggelaten zou worden",
    )
    conn.commit()
    md = wiki_repo.context_markdown(conn, None, budget=0)
    assert "tweede lange alinea die normaal weggelaten zou worden" in md
    assert wiki_repo.INDEX_HEADING not in md


# --- Globale wiki-API ------------------------------------------------------


def _create_global(client, auth, slug="stijl", title="Stijl", body="regels"):
    return client.post(
        "/api/v1/wiki", json={"slug": slug, "title": title, "body_md": body}, headers=auth
    )


def test_global_crud(client, auth):
    r = _create_global(client, auth)
    assert r.status_code == 201 and r.json()["slug"] == "stijl"
    assert [p["slug"] for p in client.get("/api/v1/wiki", headers=auth).json()] == ["stijl"]
    r = client.patch("/api/v1/wiki/stijl", json={"body_md": "nieuw"}, headers=auth)
    assert r.json()["body_md"] == "nieuw"
    assert client.get("/api/v1/wiki/stijl", headers=auth).json()["body_md"] == "nieuw"
    assert client.delete("/api/v1/wiki/stijl", headers=auth).status_code == 204
    assert client.get("/api/v1/wiki/stijl", headers=auth).status_code == 404


def test_global_duplicate_conflict_and_invalid_slug(client, auth):
    _create_global(client, auth)
    assert _create_global(client, auth).status_code == 409
    # Slug wordt geslugificeerd → "twee-woorden", blijft geldig.
    r = _create_global(client, auth, slug="Twee Woorden")
    assert r.status_code == 201 and r.json()["slug"] == "twee-woorden"


def test_global_context_endpoint(client, auth):
    _create_global(client, auth, slug="a", title="Regel A", body="doe X")
    r = client.get("/api/v1/wiki/context", headers=auth)
    assert r.status_code == 200
    assert "Regel A" in r.text and "doe X" in r.text
    # 'context' is geen slug maar de context-route.
    assert client.get("/api/v1/wiki/context", headers=auth).headers[
        "content-type"
    ].startswith("text/markdown")


# --- Projectwiki-API -------------------------------------------------------


def test_project_scoped_pages(client, auth, project):
    client.post(
        "/api/v1/projects/SOS/wiki",
        json={"slug": "conventies", "title": "Conventies", "body_md": "tabs"},
        headers=auth,
    )
    # Projectpagina staat niet in de globale lijst.
    assert client.get("/api/v1/wiki", headers=auth).json() == []
    assert [p["slug"] for p in client.get("/api/v1/projects/SOS/wiki", headers=auth).json()] == [
        "conventies"
    ]


def test_project_context_includes_global(client, auth, project):
    _create_global(client, auth, slug="g", title="Globaal", body="voor iedereen")
    client.post(
        "/api/v1/projects/SOS/wiki",
        json={"slug": "p", "title": "Projectje", "body_md": "alleen SOS"},
        headers=auth,
    )
    r = client.get("/api/v1/projects/SOS/wiki/context", headers=auth)
    assert "voor iedereen" in r.text and "alleen SOS" in r.text


def test_project_wiki_unknown_project_404(client, auth):
    assert client.get("/api/v1/projects/NOPE/wiki", headers=auth).status_code == 404


def test_wiki_requires_auth(client):
    assert client.get("/api/v1/wiki").status_code == 401
    assert client.post("/api/v1/wiki", json={"slug": "x", "title": "x"}).status_code == 401


# --- Verwijderen is mens-only (BETON-377) ----------------------------------


def _agent_auth(conn, handle="claude"):
    from betonning.repo import users as users_repo

    _, key = users_repo.create(conn, handle=handle, display_name=handle, kind="agent")
    conn.commit()
    return {"Authorization": f"Bearer {key}"}


def test_global_delete_forbidden_for_agent(client, auth, conn):
    _create_global(client, auth)
    agent_auth = _agent_auth(conn)
    r = client.delete("/api/v1/wiki/stijl", headers=agent_auth)
    assert r.status_code == 403
    # Pagina + revisie blijven intact.
    assert client.get("/api/v1/wiki/stijl", headers=auth).status_code == 200
    revs = client.get("/api/v1/wiki/stijl/revisions", headers=auth).json()
    assert len(revs) == 1


def test_global_delete_allowed_for_human(client, auth):
    _create_global(client, auth)
    assert client.delete("/api/v1/wiki/stijl", headers=auth).status_code == 204


def test_project_delete_forbidden_for_agent(client, auth, conn, project):
    client.post(
        "/api/v1/projects/SOS/wiki",
        json={"slug": "conventies", "title": "Conventies", "body_md": "tabs"},
        headers=auth,
    )
    agent_auth = _agent_auth(conn)
    r = client.delete("/api/v1/projects/SOS/wiki/conventies", headers=agent_auth)
    assert r.status_code == 403
    assert client.get("/api/v1/projects/SOS/wiki/conventies", headers=auth).status_code == 200


def test_project_delete_allowed_for_human(client, auth, project):
    client.post(
        "/api/v1/projects/SOS/wiki",
        json={"slug": "conventies", "title": "Conventies", "body_md": "tabs"},
        headers=auth,
    )
    r = client.delete("/api/v1/projects/SOS/wiki/conventies", headers=auth)
    assert r.status_code == 204


# --- Edit history / revisions (BETON-209) ---------------------------------


def test_create_records_initial_revision_with_author(conn):
    from betonning.repo import users as users_repo

    person, _ = users_repo.create(conn, handle="person", display_name="S", kind="human")
    page = wiki_repo.create(
        conn, project_id=None, slug="stijl", title="Stijl", body_md="v1",
        author_id=person["id"],
    )
    conn.commit()
    revs = wiki_repo.list_revisions(conn, page["id"])
    assert len(revs) == 1
    assert wiki_repo.serialize_revision(revs[0]) == {
        "id": revs[0]["id"], "page_id": page["id"], "title": "Stijl",
        "author": "person", "created_at": revs[0]["created_at"],
    }


def test_update_records_revision_only_on_content_change(conn):
    from betonning.repo import users as users_repo

    a, _ = users_repo.create(conn, handle="claude", display_name="C", kind="agent")
    page = wiki_repo.create(conn, project_id=None, slug="s", title="T", body_md="v1")
    conn.commit()
    wiki_repo.update(conn, page["id"], {"body_md": "v2"}, author_id=a["id"])
    conn.commit()
    assert len(wiki_repo.list_revisions(conn, page["id"])) == 2
    # No-op PATCH (zelfde inhoud) → géén nieuwe revisie.
    wiki_repo.update(conn, page["id"], {"body_md": "v2"}, author_id=a["id"])
    conn.commit()
    assert len(wiki_repo.list_revisions(conn, page["id"])) == 2


def test_list_revisions_tolerates_null_author(conn):
    """Backfill-/soft-deleted auteur → author None (geen crash op de LEFT JOIN)."""
    page = wiki_repo.create(conn, project_id=None, slug="s", title="T", body_md="v1")
    wiki_repo.record_revision(conn, page["id"], title="T", body_md="oud", author_id=None)
    conn.commit()
    revs = wiki_repo.list_revisions(conn, page["id"])
    assert any(wiki_repo.serialize_revision(r)["author"] is None for r in revs)


def test_revisions_endpoint_lists_newest_first(client, auth):
    _create_global(client, auth, body="v1")
    client.patch("/api/v1/wiki/stijl", json={"body_md": "v2"}, headers=auth)
    revs = client.get("/api/v1/wiki/stijl/revisions", headers=auth).json()
    assert len(revs) == 2
    assert [r["author"] for r in revs] == ["person", "person"]
    # Nieuwste eerst.
    assert revs[0]["created_at"] >= revs[1]["created_at"]


def test_get_revision_returns_body_and_predecessor(client, auth):
    _create_global(client, auth, body="v1")
    client.patch("/api/v1/wiki/stijl", json={"body_md": "v2"}, headers=auth)
    revs = client.get("/api/v1/wiki/stijl/revisions", headers=auth).json()
    newest, oldest = revs[0]["id"], revs[1]["id"]
    detail = client.get(f"/api/v1/wiki/stijl/revisions/{newest}", headers=auth).json()
    assert detail["revision"]["body_md"] == "v2"
    assert detail["previous"]["body_md"] == "v1"
    # De allereerste revisie heeft geen voorganger → previous None.
    first = client.get(f"/api/v1/wiki/stijl/revisions/{oldest}", headers=auth).json()
    assert first["previous"] is None


def test_restore_appends_revision_without_mutating_history(client, auth):
    _create_global(client, auth, body="v1")
    client.patch("/api/v1/wiki/stijl", json={"body_md": "v2"}, headers=auth)
    revs = client.get("/api/v1/wiki/stijl/revisions", headers=auth).json()
    oldest = revs[-1]["id"]
    r = client.post(f"/api/v1/wiki/stijl/revisions/{oldest}/restore", headers=auth)
    assert r.status_code == 200 and r.json()["body_md"] == "v1"
    # Pagina toont weer v1.
    assert client.get("/api/v1/wiki/stijl", headers=auth).json()["body_md"] == "v1"
    # Historie is niet gemuteerd maar aangevuld: 3 revisies (v1, v2, restore→v1).
    revs2 = client.get("/api/v1/wiki/stijl/revisions", headers=auth).json()
    assert len(revs2) == 3


def test_revision_from_other_page_is_404(client, auth):
    _create_global(client, auth, slug="een", body="a")
    _create_global(client, auth, slug="twee", body="b")
    rev_een = client.get("/api/v1/wiki/een/revisions", headers=auth).json()[0]["id"]
    # Revisie van 'een' opvragen onder slug 'twee' → 404.
    assert client.get(f"/api/v1/wiki/twee/revisions/{rev_een}", headers=auth).status_code == 404


def test_project_revisions_scoped(client, auth, project):
    client.post(
        f"/api/v1/projects/{project}/wiki",
        json={"slug": "p", "title": "P", "body_md": "v1"}, headers=auth,
    )
    client.patch(
        f"/api/v1/projects/{project}/wiki/p", json={"body_md": "v2"}, headers=auth
    )
    revs = client.get(f"/api/v1/projects/{project}/wiki/p/revisions", headers=auth).json()
    assert len(revs) == 2


def test_compile_context_keeps_project_pages_whole(conn):
    """De compiler herschrijft project-bodies, dus die moeten volledig mee.

    Globale pagina's raakt hij niet aan → alleen als index (BETON-352).
    """
    p = projects_repo.create(conn, key="SOS", name="SOS")
    conn.commit()
    wiki_repo.create(
        conn, project_id=None, slug="g", title="Globaal",
        body_md="# Globaal\n\nglobale uitleg\n\nGLOBALE-STAART",
    )
    wiki_repo.create(
        conn, project_id=p["id"], slug="pp", title="Projectregel",
        body_md="# Projectregel\n\nproject-inhoud die behouden moet blijven",
    )
    conn.commit()
    md = wiki_repo.compile_context(conn, p["id"])
    assert "project-inhoud die behouden moet blijven" in md
    assert "GLOBALE-STAART" not in md
    assert "`g` — Globaal" in md


def test_compile_context_falls_back_to_index_above_budget(conn):
    p = projects_repo.create(conn, key="SOS", name="SOS")
    conn.commit()
    wiki_repo.create(
        conn, project_id=p["id"], slug="oud", title="Oud",
        body_md="# Oud\n\n" + ("oude tekst " * 40) + "OUDE-STAART",
    )
    conn.commit()
    wiki_repo.create(
        conn, project_id=p["id"], slug="nieuw", title="Nieuw",
        body_md="# Nieuw\n\n" + ("verse tekst " * 40),
    )
    conn.commit()
    md = wiki_repo.compile_context(conn, p["id"], budget=600)
    assert "verse tekst verse tekst" in md
    assert "OUDE-STAART" not in md
    assert "`oud` — Oud" in md
