"""Task-aware memory selection stays bounded and within authorized scopes."""
import pytest

from betonning.repo import projects, wiki


@pytest.mark.parametrize("context,expected", [
    ({"title": "Cache recovery"}, "cache"),
    ({"title": "Cache recovery", "description_md": "Read [[deploy]]"}, "deploy"),
    ({"title": "Cache recovery", "plan_md": "Read [[SOS:deploy]]"}, "deploy"),
    ({"title": "Cache recovery", "description_md": "Read [[OTHER:deploy]]"}, "cache"),
])
def test_task_selection_prefers_old_relevant_complete_pages(conn, monkeypatch, context, expected):
    project = projects.create(conn, key="SOS", name="Sample")
    bodies = {}
    for index, slug in enumerate(("cache", "deploy", "unrelated")):
        bodies[slug] = slug.upper() + "x" * 440 + "COMPLETE-END"
        page = wiki.create(conn, project_id=project["id"], slug=slug, title=slug.title(), body_md=bodies[slug])
        conn.execute("UPDATE wiki_pages SET updated_at=? WHERE id=?", (f"200{index}-01-01", page["id"]))
    budget = 1000
    baseline = wiki.context_markdown(conn, project["id"], budget=budget)
    assert bodies["unrelated"] in baseline
    assert bodies[expected] not in baseline
    monkeypatch.setattr(wiki, "guardrail_block", lambda *_: "MANDATORY-GUARDRAIL" * 100)
    md = wiki.context_markdown(conn, project["id"], budget=budget,
                               ticket_context={"project_key": "SOS", **context})
    guardrail, body = md.split("\n\n", 1)
    assert guardrail == "MANDATORY-GUARDRAIL" * 100
    assert len(body) <= budget
    assert bodies[expected] in body
    assert "Taakselectie" in body
    for slug in bodies:
        if slug != expected:
            assert bodies[slug] not in body
            assert f"`{slug}`" in body


def test_equal_relevance_uses_existing_deterministic_tiebreak(conn):
    project = projects.create(conn, key="SOS", name="Sample")
    for slug in ("alpha", "omega"):
        page = wiki.create(conn, project_id=project["id"], slug=slug, title="Cache", body_md=slug + "x" * 450)
        conn.execute("UPDATE wiki_pages SET updated_at='2000-01-01' WHERE id=?", (page["id"],))
    context = {"project_key": "SOS", "title": "Cache"}
    md = wiki.context_markdown(conn, project["id"], budget=900, ticket_context=context)
    assert "omega" + "x" * 450 in md
    assert "alpha" + "x" * 450 not in md
    assert md == wiki.context_markdown(conn, project["id"], budget=900, ticket_context=context)


def test_ticket_context_api_preserves_scope_and_default(client, auth, project):
    client.post('/api/v1/projects', headers=auth, json={'key': 'OTHER', 'name': 'Other'})
    own = client.post('/api/v1/projects/SOS/items', headers=auth, json={'title': 'Cache'}).json()
    other = client.post('/api/v1/projects/OTHER/items', headers=auth, json={'title': 'Private'}).json()
    client.post('/api/v1/projects/SOS/wiki', headers=auth,
                json={'slug': 'cache', 'title': 'Cache', 'body_md': 'Complete knowledge'})
    agent = client.post('/api/v1/users', headers=auth, json={'handle': 'reader', 'display_name': 'Reader'}).json()
    client.patch('/api/v1/users/reader', headers=auth,
                 json={'api_key_scopes': ['read'], 'api_key_projects': ['SOS']})
    scoped = {'Authorization': f"Bearer {agent['api_key']}"}
    url = '/api/v1/projects/SOS/wiki/context'
    baseline = client.get(url, headers=scoped)
    selected = client.get(url, headers=scoped, params={'ticket_ref': own['ref']})
    assert baseline.status_code == selected.status_code == 200
    assert baseline.text == selected.text  # everything fits; no change needed
    missing = client.get(url, headers=scoped, params={'ticket_ref': 'SOS-9999'})
    foreign = client.get(url, headers=scoped, params={'ticket_ref': other['ref']})
    assert missing.status_code == foreign.status_code == 404
    assert missing.json() == foreign.json()
    assert client.get('/api/v1/projects/OTHER/wiki/context', headers=scoped,
                      params={'ticket_ref': other['ref']}).status_code == 403
    assert client.get('/api/v1/wiki/context', headers=scoped,
                      params={'ticket_ref': own['ref']}).status_code == 422


@pytest.mark.parametrize("link,expected", [("[[cache|Guide]]", "LOCAL"), ("[[global:cache]]", "GLOBAL")])
def test_explicit_links_resolve_local_before_global(conn, link, expected):
    project = projects.create(conn, key="SOS", name="Sample")
    for project_id, marker in ((project["id"], "LOCAL"), (None, "GLOBAL")):
        wiki.create(conn, project_id=project_id, slug="cache", title="Cache", body_md=marker + "x" * 450)
    md = wiki.context_markdown(conn, project["id"], budget=900,
                               ticket_context={"project_key": "SOS", "description_md": link})
    assert expected + "x" * 450 in md
    other = "GLOBAL" if expected == "LOCAL" else "LOCAL"
    assert other + "x" * 450 not in md
