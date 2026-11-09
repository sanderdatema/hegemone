"""MCP-server: de (async) memory-tools tegen een in-process ASGI-app (BETON-24).

`_client` wordt gepatcht naar een httpx.AsyncClient met ASGITransport zodat de
tools tegen de echte app praten zonder netwerk of draaiende server.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from betonning import db as db_module
from betonning import mcp_server
from betonning.repo import projects as projects_repo
from betonning.repo import users as users_repo
from betonning.server import create_app


@pytest.fixture(autouse=True)
def isolated_mcp_configuration(tmp_path, monkeypatch):
    """Nooit een echte gebruikersconfiguratie of impliciete key in tooltests lezen."""
    monkeypatch.setenv("BETONNING_CONFIG", str(tmp_path / "mcp-unconfigured.json"))
    monkeypatch.delenv("BETONNING_API_KEY", raising=False)
    monkeypatch.setenv("BETONNING_BASE_URL", "http://test")


@pytest.fixture
def mcp_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "mcp.db")
    db_module.init_db(db_path).close()  # migreren (ASGITransport draait geen lifespan)
    conn = db_module.connect(db_path)
    _, key = users_repo.create(
        conn, handle="person", display_name="Person", kind="human"
    )
    projects_repo.create(conn, key="SOS", name="SOS")
    conn.close()

    # _resolve_key leest BETONNING_API_KEY uit de env (alternatief: bt-config).
    # Zet die hier expliciet, zodat de tests niet afhangen van een toevallig
    # aanwezige lokale bt-config (BETON-146: die kan afwezig zijn).
    monkeypatch.setenv("BETONNING_API_KEY", key)
    monkeypatch.setenv("BETONNING_BASE_URL", "http://test")

    app = create_app(db_path, enable_dispatcher=False)
    # _client(key) → een AsyncClient tegen de app; de tool-tests toetsen de logica,
    # niet de per-request auth, dus de baked-in key volstaat hier.
    monkeypatch.setattr(
        mcp_server,
        "_client",
        lambda k=None: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {key}"},
        ),
    )
    return app


def _run(coro):
    return asyncio.run(coro)


def _ctx_with_auth(value):
    """Fake FastMCP-Context met een inkomende Authorization-header."""
    request = SimpleNamespace(headers={"authorization": value})
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


def _ctx_without_auth():
    """Fake FastMCP-Context op het http-transport, zónder Authorization-header."""
    return SimpleNamespace(
        request_context=SimpleNamespace(request=SimpleNamespace(headers={}))
    )


def _ctx_stdio():
    """Fake FastMCP-Context zonder request (stdio-transport)."""
    return SimpleNamespace(request_context=SimpleNamespace(request=None))


# --- Key-resolutie (per-request passthrough) -------------------------------


def test_resolve_key_prefers_incoming_bearer():
    assert (
        mcp_server._resolve_key(_ctx_with_auth("Bearer bt_agent_key")) == "bt_agent_key"
    )


def test_resolve_key_falls_back_to_configured(monkeypatch):
    monkeypatch.setenv("BETONNING_API_KEY", "bt_configured")
    monkeypatch.setenv("BETONNING_BASE_URL", "http://x")
    assert mcp_server._resolve_key(None) == "bt_configured"


def test_resolve_key_raises_without_any_key(monkeypatch):
    monkeypatch.delenv("BETONNING_API_KEY", raising=False)
    monkeypatch.setenv("BETONNING_CONFIG", "/nonexistent/config.json")
    with pytest.raises(RuntimeError):
        mcp_server._resolve_key(_ctx_with_auth("nonsense"))  # geen geldige Bearer


def test_config_tolerates_unreadable_file(monkeypatch):
    # Bij de HTTP-service staat er geen (leesbaar) configbestand; base_url komt uit
    # de env en de key per request. Een lees-/permissiefout mag niet crashen.
    monkeypatch.setenv("BETONNING_BASE_URL", "http://127.0.0.1")
    monkeypatch.delenv("BETONNING_API_KEY", raising=False)
    monkeypatch.setenv("BETONNING_CONFIG", "/unreadable/config.json")
    cfg = mcp_server._config()
    assert cfg["base_url"] == "http://127.0.0.1"
    assert cfg["api_key"] is None


def test_client_uses_passed_key(monkeypatch):
    monkeypatch.setenv("BETONNING_BASE_URL", "http://host")
    client = mcp_server._client("bt_specific")
    assert client.headers["authorization"] == "Bearer bt_specific"
    _run(client.aclose())


# --- Tools -----------------------------------------------------------------


def test_set_and_load_memory_global(mcp_env):
    _run(mcp_server.set_memory("stijl", "Stijl", "wees beknopt"))
    md = _run(mcp_server.load_memory())
    assert "wees beknopt" in md
    assert [p["slug"] for p in _run(mcp_server.list_memory_pages())] == ["stijl"]


def test_set_memory_upserts(mcp_env):
    _run(mcp_server.set_memory("s", "T", "een"))
    updated = _run(mcp_server.set_memory("s", "T", "twee"))
    assert updated["body_md"] == "twee"


def test_project_memory_merges_global(mcp_env):
    _run(mcp_server.set_memory("g", "Globaal", "voor allen"))
    _run(mcp_server.set_memory("p", "Proj", "alleen SOS", project="SOS"))
    md = _run(mcp_server.load_memory(project="SOS"))
    assert "voor allen" in md and "alleen SOS" in md
    assert [p["slug"] for p in _run(mcp_server.list_memory_pages(project="SOS"))] == [
        "p"
    ]


def test_get_memory_page(mcp_env):
    _run(mcp_server.set_memory("weg", "Weg", "tijdelijk"))
    assert _run(mcp_server.get_memory_page("weg"))["title"] == "Weg"


def test_delete_memory_page_tool_removed(mcp_env):
    """BETON-377: verwijderen van een wiki-pagina is mens-only, geen MCP-tool meer."""
    assert not hasattr(mcp_server, "delete_memory_page")


def test_list_projects_and_search(mcp_env):
    assert [p["key"] for p in _run(mcp_server.list_projects())] == ["SOS"]
    assert isinstance(_run(mcp_server.search_tickets("iets")), list)


# --- Ticket-tools (BETON-45) -----------------------------------------------


def test_create_and_get_item(mcp_env):
    created = _run(mcp_server.create_item("SOS", "Kaart tekenen", "een `omschrijving`"))
    ref = created["ref"]
    assert ref.startswith("SOS-")
    fetched = _run(mcp_server.get_item(ref))
    assert fetched["title"] == "Kaart tekenen"
    assert fetched["comments"] == []
    assert fetched["relations"]["blocks"] == []


def test_get_item_unknown_ref_raises_clean_error(mcp_env):
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.get_item("SOS-999"))
    assert "404" in str(exc.value)


def test_plan_roundtrip_via_update_and_get_plan(mcp_env):
    """BETON-218: het zware model zet een plan via update_item; get_item toont
    has_plan; sinds BETON-430 staat het plan ook inline in get_item."""
    created = _run(mcp_server.create_item("SOS", "Grote klus"))
    ref = created["ref"]
    _run(mcp_server.update_item(ref, plan_md="## Handover\n1. doe A\n2. doe B"))
    fetched = _run(mcp_server.get_item(ref))
    assert fetched["has_plan"] is True
    assert fetched["plan_md"] == "## Handover\n1. doe A\n2. doe B"
    plan = _run(mcp_server.get_plan(ref))
    assert plan["plan_md"].startswith("## Handover")


def test_create_item_with_plan_md(mcp_env):
    """BETON-430: plan_md direct bij create_item, zonder tweede update_item."""
    created = _run(mcp_server.create_item("SOS", "Klus", plan_md="## Plan\n1. A"))
    assert created["has_plan"] is True
    plan = _run(mcp_server.get_plan(created["ref"]))
    assert plan["plan_md"] == "## Plan\n1. A"


def test_get_item_without_plan_has_no_plan_md(mcp_env):
    created = _run(mcp_server.create_item("SOS", "Kaal"))
    fetched = _run(mcp_server.get_item(created["ref"]))
    assert fetched["has_plan"] is False
    assert "plan_md" not in fetched


def test_get_item_truncates_long_plan_with_marker(mcp_env):
    limit = mcp_server.PLAN_INLINE_MAX
    long_plan = "x" * (limit + 500)
    created = _run(mcp_server.create_item("SOS", "Lang", plan_md=long_plan))
    ref = created["ref"]
    fetched = _run(mcp_server.get_item(ref))
    assert fetched["plan_md"].startswith("x" * limit)
    assert fetched["plan_md"].count("x") == limit
    assert f'get_plan("{ref}")' in fetched["plan_md"]
    # get_plan geeft nog steeds alles
    assert _run(mcp_server.get_plan(ref))["plan_md"] == long_plan


def test_get_item_plan_at_limit_is_not_truncated(mcp_env):
    limit = mcp_server.PLAN_INLINE_MAX
    created = _run(mcp_server.create_item("SOS", "Precies", plan_md="y" * limit))
    fetched = _run(mcp_server.get_item(created["ref"]))
    assert fetched["plan_md"] == "y" * limit


@pytest.fixture
def agent_env(tmp_path, monkeypatch):
    """Als mcp_env, maar met een agent-user ('claude') als aanroeper en een
    mens ('person') ernaast; as_human()/as_agent() wisselt de aanroeper."""
    db_path = str(tmp_path / "mcp_agent.db")
    db_module.init_db(db_path).close()
    conn = db_module.connect(db_path)
    _, human_key = users_repo.create(
        conn, handle="person", display_name="Person", kind="human"
    )
    _, agent_key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent"
    )
    projects_repo.create(conn, key="SOS", name="SOS")
    conn.close()
    app = create_app(db_path, enable_dispatcher=False)
    current = {"key": agent_key}
    monkeypatch.setattr(
        mcp_server,
        "_client",
        lambda k=None: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {current['key']}"},
        ),
    )
    monkeypatch.setenv("BETONNING_API_KEY", agent_key)
    monkeypatch.setenv("BETONNING_BASE_URL", "http://test")
    app.state.as_human = lambda: current.update(key=human_key)
    app.state.as_agent = lambda: current.update(key=agent_key)
    return app


def test_create_item_agent_without_plan_gets_next_step(agent_env):
    """BETON-430: een agent die zonder plan_md aanmaakt krijgt een herinnering."""
    item = _run(mcp_server.create_item("SOS", "Zonder plan"))
    assert 'update_item("SOS-1", plan_md=' in item["next_step"]
    assert "BETON-301" in item["next_step"]


def test_create_item_agent_with_plan_gets_no_next_step(agent_env):
    item = _run(mcp_server.create_item("SOS", "Met plan", plan_md="## Plan", labels=["standaard"]))
    assert "next_step" not in item


def test_create_item_human_without_plan_gets_no_next_step(agent_env):
    agent_env.state.as_human()
    item = _run(mcp_server.create_item("SOS", "Mens zonder plan"))
    assert "next_step" not in item


def test_first_comment_on_own_planless_ticket_warns_agent(agent_env):
    ref = _run(mcp_server.create_item("SOS", "Eigen"))["ref"]
    first = _run(mcp_server.comment_item(ref, "eerste"))
    assert "plan_md" in first["warning"]
    assert "BETON-301" in first["warning"]
    second = _run(mcp_server.comment_item(ref, "tweede"))
    assert "warning" not in second


def test_first_comment_with_plan_does_not_warn(agent_env):
    ref = _run(mcp_server.create_item("SOS", "Met plan", plan_md="## P"))["ref"]
    assert "warning" not in _run(mcp_server.comment_item(ref, "eerste"))


def test_first_comment_by_human_does_not_warn(agent_env):
    ref = _run(mcp_server.create_item("SOS", "Eigen"))["ref"]
    agent_env.state.as_human()
    assert "warning" not in _run(mcp_server.comment_item(ref, "mens reageert"))


def test_first_comment_on_ticket_of_someone_else_does_not_warn(agent_env):
    agent_env.state.as_human()
    ref = _run(mcp_server.create_item("SOS", "Van person"))["ref"]
    agent_env.state.as_agent()
    assert "warning" not in _run(mcp_server.comment_item(ref, "agent reageert"))


def test_list_items_filters_by_state(mcp_env):
    _run(mcp_server.create_item("SOS", "todo-taak", state="todo"))
    _run(mcp_server.create_item("SOS", "bezig-taak", state="in-progress"))
    todos = _run(mcp_server.list_items("SOS", state="todo"))
    assert [i["title"] for i in todos] == ["todo-taak"]


def test_list_items_unknown_project_raises(mcp_env):
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.list_items("NOPE"))
    assert "404" in str(exc.value)


def test_create_item_unknown_state_raises(mcp_env):
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.create_item("SOS", "x", state="onbekend"))
    assert "400" in str(exc.value)


def test_create_item_with_milestone_labels_and_due_date(mcp_env):
    # Milestone en labels moeten al bij het aanmaken bestaan (BETON-176).
    _run(mcp_server.create_milestone("SOS", "v1.0"))
    _run(mcp_server.create_label("SOS", "bug", color="#e74c3c"))
    created = _run(
        mcp_server.create_item(
            "SOS",
            "met velden",
            milestone="v1.0",
            due_date="2026-08-01",
            labels=["bug"],
        )
    )
    assert created["milestone"] == "v1.0"
    assert created["due_date"] == "2026-08-01"
    assert created["labels"] == ["bug"]


def test_update_item_changes_fields(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "oud", "beschrijving"))["ref"]
    updated = _run(mcp_server.update_item(ref, title="nieuw", priority="high"))
    assert updated["title"] == "nieuw"
    assert updated["priority"] == "high"


def test_update_item_sets_deferred_until_and_due_date(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "uitstellen"))["ref"]
    updated = _run(
        mcp_server.update_item(ref, deferred_until="2026-08-01", due_date="2026-08-15")
    )
    assert updated["deferred_until"].startswith("2026-08-01")
    assert updated["due_date"] == "2026-08-15"
    assert updated["state"] == "deferred"


def test_get_attachment_returns_image(mcp_env):
    """BETON-202: de get_attachment-tool haalt de afgeschermde serve-route op met
    de agent-Bearer en geeft de afbeelding als MCP-Image terug."""
    import os

    key = os.environ["BETONNING_API_KEY"]
    auth = {"Authorization": f"Bearer {key}"}
    tc = TestClient(mcp_env)
    tc.post(
        "/api/v1/projects/SOS/items", json={"title": "Met screenshot"}, headers=auth
    )
    png = b"\x89PNG\r\n\x1a\n fake-screenshot"
    up = tc.post(
        "/api/v1/items/SOS-1/attachments",
        files={"file": ("shot.png", png, "image/png")},
        headers=auth,
    )
    sha = up.json()["sha256"]

    img = _run(mcp_server.get_attachment(sha))
    assert img.data == png
    assert img._format == "png"


def test_get_attachment_returns_text_for_a_log(mcp_env):
    """BETON-374: een tekst-attachment komt als tekst terug, niet als `Image`.

    De oude tak maakte er `Image(format="plain")` van met tekstbytes erin.
    """
    import os

    key = os.environ["BETONNING_API_KEY"]
    auth = {"Authorization": f"Bearer {key}"}
    tc = TestClient(mcp_env)
    tc.post("/api/v1/projects/SOS/items", json={"title": "Met log"}, headers=auth)
    log = b"2026-09-02 12:00 INFO alles goed\n"
    up = tc.post(
        "/api/v1/items/SOS-1/attachments",
        files={"file": ("server.log", log, "application/octet-stream")},
        headers=auth,
    )
    out = _run(mcp_server.get_attachment(up.json()["sha256"]))
    assert isinstance(out, str)
    assert out == log.decode()


def test_get_attachment_truncates_long_text(mcp_env, monkeypatch):
    """Een logbestand mag 5 MB zijn; dat hoort niet ongevraagd in de context."""
    import os

    monkeypatch.setattr(mcp_server, "ATTACHMENT_TEXT_LIMIT", 10)
    key = os.environ["BETONNING_API_KEY"]
    auth = {"Authorization": f"Bearer {key}"}
    tc = TestClient(mcp_env)
    tc.post("/api/v1/projects/SOS/items", json={"title": "Lang log"}, headers=auth)
    up = tc.post(
        "/api/v1/items/SOS-1/attachments",
        files={"file": ("groot.log", b"x" * 50, "text/plain")},
        headers=auth,
    )
    out = _run(mcp_server.get_attachment(up.json()["sha256"]))
    assert out.startswith("x" * 10)
    assert "afgekapt: nog 40 tekens" in out


def test_get_attachment_pdf_points_at_the_rest_api(mcp_env):
    """Een PDF is hier niet te lezen — zeg dat, in plaats van een kapotte Image."""
    import os

    key = os.environ["BETONNING_API_KEY"]
    auth = {"Authorization": f"Bearer {key}"}
    tc = TestClient(mcp_env)
    tc.post("/api/v1/projects/SOS/items", json={"title": "Met pdf"}, headers=auth)
    up = tc.post(
        "/api/v1/items/SOS-1/attachments",
        files={"file": ("rapport.pdf", b"%PDF-1.7\nx\n", "application/pdf")},
        headers=auth,
    )
    out = _run(mcp_server.get_attachment(up.json()["sha256"]))
    assert isinstance(out, str)
    assert "application/pdf" in out
    assert "/api/v1/attachments/" in out


def test_update_item_unknown_ref_raises(mcp_env):
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.update_item("SOS-999", title="x"))
    assert "404" in str(exc.value)


def test_set_state_sets_state(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "taak", state="todo"))["ref"]
    moved = _run(mcp_server.set_state(ref, "in-progress"))
    assert moved["state"] == "in-progress"


def test_set_state_unknown_state_raises(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "taak"))["ref"]
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.set_state(ref, "onbekend"))
    assert "400" in str(exc.value)


def test_move_item_is_deprecated_alias_for_set_state(mcp_env):
    # BETON-183: move_item blijft bestaan (Hermes-agents gebruiken 'm al) en doet
    # exact hetzelfde als set_state.
    ref = _run(mcp_server.create_item("SOS", "taak", state="todo"))["ref"]
    moved = _run(mcp_server.move_item(ref, "in-progress"))
    assert moved["state"] == "in-progress"


def test_move_item_unknown_state_raises(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "taak"))["ref"]
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.move_item(ref, "onbekend"))
    assert "400" in str(exc.value)


def test_transfer_item_moves_to_other_project(mcp_env):
    # BETON-183/244: transfer_item wrapt REST POST /items/{ref}/move
    # (projectverplaatsing), in tegenstelling tot set_state (kolomwissel binnen
    # hetzelfde project). De move is in-place: het item behoudt zijn id en de
    # oude ref bestaat daarna niet meer.
    conn = db_module.connect(mcp_env.state.db_path)
    projects_repo.create(conn, key="BAR", name="Bar")
    conn.close()

    ref = _run(mcp_server.create_item("SOS", "taak"))["ref"]
    original_id = _run(mcp_server.get_item(ref))["id"]
    transferred = _run(mcp_server.transfer_item(ref, "BAR"))
    assert transferred["ref"].startswith("BAR-")
    assert transferred["id"] == original_id  # zelfde item, alleen de ref wijzigt

    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.get_item(ref))
    assert "404" in str(exc.value)


def test_comment_item_appears_in_get(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "taak"))["ref"]
    _run(mcp_server.comment_item(ref, "klaar, tests groen"))
    fetched = _run(mcp_server.get_item(ref))
    assert [c["body_md"] for c in fetched["comments"]] == ["klaar, tests groen"]


def test_comment_item_unknown_ref_raises(mcp_env):
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.comment_item("SOS-999", "hoi"))
    assert "404" in str(exc.value)


def test_relate_items_creates_relation(mcp_env):
    a = _run(mcp_server.create_item("SOS", "eerst"))["ref"]
    b = _run(mcp_server.create_item("SOS", "daarna"))["ref"]
    _run(mcp_server.relate_items(a, "blocks", b))
    fetched = _run(mcp_server.get_item(a))
    assert fetched["relations"]["blocks"] == [b]


def test_relate_items_unknown_target_raises(mcp_env):
    a = _run(mcp_server.create_item("SOS", "eerst"))["ref"]
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.relate_items(a, "blocks", "SOS-999"))
    assert "404" in str(exc.value)


# --- P1-ticket-tools (BETON-146: archive/unrelate/comments/activity) -------


def test_archive_item_soft_only(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "wegwezen"))["ref"]
    # Soft-archive: 204 No Content, archived_at wordt gezet (GET geeft het item
    # nog steeds terug, maar met archived_at ingevuld). Geen hard-delete meer via
    # deze tool (BETON-377): dat kan alleen een mens, via de UI.
    result = _run(mcp_server.archive_item(ref))
    assert result is None  # 204 = geen body
    fetched = _run(mcp_server.get_item(ref))
    assert fetched["archived_at"] is not None


def test_archive_item_no_longer_accepts_hard(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "wegwezen"))["ref"]
    with pytest.raises(TypeError):
        _run(mcp_server.archive_item(ref, hard=True))


def test_unrelate_items_removes_relation(mcp_env):
    a = _run(mcp_server.create_item("SOS", "eerst"))["ref"]
    b = _run(mcp_server.create_item("SOS", "daarna"))["ref"]
    _run(mcp_server.relate_items(a, "relates_to", b))
    assert _run(mcp_server.get_item(a))["relations"]["relates_to"] == [b]
    _run(mcp_server.unrelate_items(a, "relates_to", b))
    assert _run(mcp_server.get_item(a))["relations"]["relates_to"] == []


def test_unrelate_items_unknown_relation_raises(mcp_env):
    a = _run(mcp_server.create_item("SOS", "eerst"))["ref"]
    b = _run(mcp_server.create_item("SOS", "daarna"))["ref"]
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.unrelate_items(a, "relates_to", b))
    assert "404" in str(exc.value)


def test_edit_comment_updates_body(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "taak"))["ref"]
    _run(mcp_server.comment_item(ref, "origineel"))
    # API geeft comment-id in de activity, maar niet direct in de response.
    # Haal het id via get_item.
    comments = _run(mcp_server.get_item(ref))["comments"]
    cid = comments[0]["id"]
    _run(mcp_server.edit_comment(ref, cid, "bewerkt"))
    fetched = _run(mcp_server.get_item(ref))
    assert [c["body_md"] for c in fetched["comments"]] == ["bewerkt"]


def test_delete_comment_removes_it(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "taak"))["ref"]
    _run(mcp_server.comment_item(ref, "weg"))
    cid = _run(mcp_server.get_item(ref))["comments"][0]["id"]
    _run(mcp_server.delete_comment(ref, cid))
    assert _run(mcp_server.get_item(ref))["comments"] == []


def test_list_item_activity_shows_events(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "taak"))["ref"]
    activity = _run(mcp_server.list_item_activity(ref))
    # Minimaal het item.created-event.
    assert any(e["type"] == "item.created" for e in activity)


def test_list_item_activity_unknown_ref_raises(mcp_env):
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.list_item_activity("SOS-999"))
    assert "404" in str(exc.value)


def test_list_project_activity_shows_events(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "taak"))["ref"]
    activity = _run(mcp_server.list_project_activity("SOS"))
    assert [e["type"] for e in activity] == ["item.created"]
    assert activity[0]["ref"] == ref


def test_list_project_activity_since_id_filters(mcp_env):
    _run(mcp_server.create_item("SOS", "eerste"))
    first_id = _run(mcp_server.list_project_activity("SOS"))[0]["id"]
    ref2 = _run(mcp_server.create_item("SOS", "tweede"))["ref"]

    activity = _run(mcp_server.list_project_activity("SOS", since_id=first_id))
    assert [e["ref"] for e in activity] == [ref2]


def test_list_project_activity_unknown_project_raises(mcp_env):
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.list_project_activity("NOPE"))
    assert "404" in str(exc.value)


# --- P1-config-tools (BETON-146: milestones + states) ---------------------


def test_list_milestones_empty_then_created(mcp_env):
    assert _run(mcp_server.list_milestones("SOS")) == []
    _run(mcp_server.create_milestone("SOS", "v1.0"))
    ms = _run(mcp_server.list_milestones("SOS"))
    assert [m["name"] for m in ms] == ["v1.0"]


def test_create_milestone_with_due_date(mcp_env):
    ms = _run(mcp_server.create_milestone("SOS", "v2.0", due_date="2026-12-01"))
    assert ms["name"] == "v2.0"
    assert ms["due_date"] is not None


def test_update_milestone_completes_it(mcp_env):
    _run(mcp_server.create_milestone("SOS", "v1.0"))
    updated = _run(mcp_server.update_milestone("SOS", "v1.0", status="completed"))
    assert updated["status"] == "completed"


def test_list_states_shows_default_kanban(mcp_env):
    states = _run(mcp_server.list_states("SOS"))
    [s["name"] for s in states]
    # De default-states komen uit de migratie/create-app; minimaal backlog.
    assert len(states) > 0
    assert any(
        s["group"] in ("backlog", "unstarted", "started", "completed", "cancelled")
        for s in states
    )


def test_create_state_adds_column(mcp_env):
    created = _run(
        mcp_server.create_state("SOS", "qa", group="started", blocks_work=True)
    )
    assert created["name"] == "qa"
    assert created["group"] == "started"
    assert created["blocks_work"] is True
    states = _run(mcp_server.list_states("SOS"))
    assert "qa" in [s["name"] for s in states]


def test_update_state_changes_work_policy(mcp_env):
    updated = _run(mcp_server.update_state("SOS", "backlog", blocks_work=False))
    assert updated["blocks_work"] is False


def test_create_state_invalid_group_raises(mcp_env):
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.create_state("SOS", "x", group="onbekend"))
    # FastAPI-validation → 422 of 400 afhankelijk van de schema-check.
    assert ("422" in str(exc.value)) or ("400" in str(exc.value))


def test_delete_state(mcp_env):
    _run(mcp_server.create_state("SOS", "qa", group="started"))
    assert _run(mcp_server.delete_state("SOS", "qa")) == "Verwijderd: SOS/qa"
    states = _run(mcp_server.list_states("SOS"))
    assert "qa" not in [s["name"] for s in states]


def test_delete_state_unknown_raises(mcp_env):
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.delete_state("SOS", "bestaatniet"))
    assert "404" in str(exc.value)


# --- P2-config-tools (BETON-147: project-CRUD + labels + triage) -----------


def test_create_project_and_archive_restore(mcp_env):
    created = _run(mcp_server.create_project("SUB", "Sub-project", "een omschrijving"))
    assert created["key"] == "SUB"
    assert created["name"] == "Sub-project"
    assert created["description"] == "een omschrijving"
    # Standaard staat het project in de lijst.
    assert "SUB" in [p["key"] for p in _run(mcp_server.list_projects())]
    # Soft-archive: verdwijnt uit de default-lijst.
    assert _run(mcp_server.archive_project("SUB")) == "Gearchiveerd: SUB"
    default = [p["key"] for p in _run(mcp_server.list_projects())]
    assert "SUB" not in default
    # Restore: terug in de lijst.
    restored = _run(mcp_server.restore_project("SUB"))
    assert restored["key"] == "SUB"
    assert "SUB" in [p["key"] for p in _run(mcp_server.list_projects())]


def test_create_project_duplicate_raises(mcp_env):
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.create_project("SOS", "al bestaand"))
    assert "409" in str(exc.value)


def test_update_project_changes_fields(mcp_env):
    updated = _run(mcp_server.update_project("SOS", name="SOS-hernoemd"))
    assert updated["name"] == "SOS-hernoemd"


def test_archive_project_unknown_raises(mcp_env):
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.archive_project("NOPE"))
    assert "404" in str(exc.value)


def test_list_create_delete_label(mcp_env):
    assert {label_entry["name"] for label_entry in _run(mcp_server.list_labels("SOS"))} == {"routine", "standaard", "complex"}
    created = _run(mcp_server.create_label("SOS", "bug", color="#e74c3c"))
    assert created["name"] == "bug"
    assert created["color"] == "#e74c3c"
    labels = _run(mcp_server.list_labels("SOS"))
    assert [label_entry["name"] for label_entry in labels] == ["bug", "complex", "routine", "standaard"]
    assert _run(mcp_server.delete_label("SOS", "bug")) == "Verwijderd: SOS/bug"
    assert {label_entry["name"] for label_entry in _run(mcp_server.list_labels("SOS"))} == {"routine", "standaard", "complex"}


def test_delete_label_with_slash(mcp_env):
    """BETON-449: een `/` in de labelnaam moet verwijderbaar zijn."""
    for name in ("Kind/Bug", "Stream Deck/XL"):
        _run(mcp_server.create_label("SOS", name))
        assert _run(mcp_server.delete_label("SOS", name)) == f"Verwijderd: SOS/{name}"
    assert {label_entry["name"] for label_entry in _run(mcp_server.list_labels("SOS"))} == {"routine", "standaard", "complex"}


def test_create_label_duplicate_raises(mcp_env):
    _run(mcp_server.create_label("SOS", "dup"))
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.create_label("SOS", "dup"))
    assert "409" in str(exc.value)


def test_delete_label_unknown_raises(mcp_env):
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.delete_label("SOS", "bestaatniet"))
    assert "404" in str(exc.value)


def test_set_triage_enabled(mcp_env):
    project = _run(mcp_server.set_triage_enabled("SOS", True))
    assert project["triage_enabled"] is True
    off = _run(mcp_server.set_triage_enabled("SOS", False))
    assert off["triage_enabled"] is False


def test_backfill_triage_without_optin_raises(mcp_env):
    # SOS heeft triage uit (default in de test-fixture) → 400.
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.backfill_triage("SOS"))
    assert "400" in str(exc.value)


# --- P3-session-tools (BETON-150: my-issues + inbox) -----------------------


def test_get_my_issues_assigned_to_me(mcp_env):
    # De fixture-user heet 'person'. Wijs een item aan hem toe.
    _run(mcp_server.create_item("SOS", "mijn taak", state="todo", assignee="person"))
    issues = _run(mcp_server.get_my_issues())
    titles = [i["title"] for i in issues]
    assert "mijn taak" in titles


def test_get_my_issues_excludes_unassigned(mcp_env):
    # Item zonder assignee → niet in my-issues.
    _run(mcp_server.create_item("SOS", "zonder eigenaar", state="todo"))
    issues = _run(mcp_server.get_my_issues())
    assert "zonder eigenaar" not in [i["title"] for i in issues]


def test_get_inbox_returns_expected_shape(mcp_env):
    # De inbox-wrapper retourneert de volledige structuur die de API levert.
    # De reason-logica zelf (mention/assigned/comment) staat in tests/test_inbox.py;
    # hier toetsen we alleen dat de MCP-tool de API correct doorgeeft.
    inbox = _run(mcp_server.get_inbox())
    assert set(inbox.keys()) >= {"items", "unread_count", "last_seen_event_id"}
    assert isinstance(inbox["items"], list)
    assert isinstance(inbox["unread_count"], int)
    # Verse inbox (geen events die 'person' raken) → leeg en 0 ongelezen.
    assert inbox["items"] == []
    assert inbox["unread_count"] == 0


def test_get_inbox_passes_limit(mcp_env):
    # limit wordt als query-param doorgegeven; structuur blijft intact.
    inbox = _run(mcp_server.get_inbox(limit=5))
    assert "items" in inbox
    assert len(inbox["items"]) <= 5


def test_server_registers_all_tools(mcp_env):
    server = mcp_server.build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"load_memory", "set_memory", "list_memory_pages", "search_tickets"} <= names
    assert {
        "list_items",
        "get_item",
        "create_item",
        "update_item",
        "set_state",
        "move_item",
        "transfer_item",
        "comment_item",
        "relate_items",
    } <= names
    # P1-batch (BETON-146): kern-tools voor agents
    assert {
        "archive_item",
        "unrelate_items",
        "edit_comment",
        "delete_comment",
        "list_item_activity",
        "list_project_activity",
        "list_milestones",
        "create_milestone",
        "update_milestone",
        "list_states",
        "create_state",
        "update_state",
        "delete_state",
    } <= names
    # BETON-202: afbeelding-attachment ophalen (screenshots)
    assert "get_attachment" in names
    # P2-batch (BETON-147): project-CRUD + labels + triage-toggle
    assert {
        "create_project",
        "update_project",
        "archive_project",
        "restore_project",
        "list_labels",
        "create_label",
        "delete_label",
        "set_triage_enabled",
        "backfill_triage",
    } <= names
    # P3-batch (BETON-150): session-start (my-issues + inbox)
    assert {"get_my_issues", "get_inbox"} <= names
    # Vraagmodule (BETON-219)
    assert {"ask_question", "get_open_questions", "withdraw_question"} <= names
    # BETON-466
    assert {
        "mute_item",
        "unmute_item",
        "add_label",
        "remove_label",
        "list_users",
        "upload_attachment",
        "create_items",
    } <= names


# --- Vraagmodule (BETON-219) ----------------------------------------------


def test_ask_question_with_options(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "Kleuren"))["ref"]
    q = _run(mcp_server.ask_question(ref, "Rood of blauw?", options=["rood", "blauw"]))
    assert q["kind"] == "question"
    assert q["question_options"] == ["rood", "blauw"]
    fetched = _run(mcp_server.get_item(ref))
    assert fetched["comments"][0]["kind"] == "question"


def test_ask_free_text_question(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "Open vraag"))["ref"]
    q = _run(mcp_server.ask_question(ref, "Wat denk je?"))
    assert q["kind"] == "question"
    assert q["question_options"] is None


def test_withdraw_question(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "Vraagitem"))["ref"]
    q = _run(mcp_server.ask_question(ref, "Rood of blauw?"))
    out = _run(mcp_server.withdraw_question(q["id"], "antwoord kwam in de chat"))
    assert out["withdrawn_reason"] == "antwoord kwam in de chat"
    assert _run(mcp_server.get_open_questions()) == []
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.withdraw_question(q["id"], "nogmaals"))
    assert "409" in str(exc.value)


def test_get_open_questions_returns_directed(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "Vraagitem"))["ref"]
    _run(mcp_server.ask_question(ref, "Rood of blauw?"))
    # person is de maker → ziet de open vraag.
    open_qs = _run(mcp_server.get_open_questions())
    assert len(open_qs) == 1
    assert open_qs[0]["item"]["ref"] == ref
    assert open_qs[0]["kind"] == "question"


def test_ask_question_bad_options_raises(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "x"))["ref"]
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.ask_question(ref, "?", options=["a", "a"]))
    assert "422" in str(exc.value)


def test_server_advertises_conventions_via_instructions():
    """De agent krijgt bij de MCP-handshake instructies mee (BETON-36/33): laad je
    geheugen + de kernconventies (in-progress bij oppakken, witregels)."""
    server = mcp_server.build_server()
    instr = server.instructions or ""
    assert "load_memory" in instr
    assert "in-progress" in instr
    assert "witregel" in instr


def test_server_instructions_advertise_plan_field(monkeypatch):
    """BETON-388: het plan/handover-veld (BETON-218) wordt actief geadverteerd —
    zowel de instructie om er zelf een te zetten bij het aanmaken van een ticket,
    als de instructie om 'm op te halen vóór je aan een ticket begint."""
    server = mcp_server.build_server()
    instr = server.instructions or ""
    assert "plan_md" in instr
    assert "get_plan" in instr
    assert "has_plan" in instr


def test_create_item_docstring_advertises_plan_field():
    """BETON-388/430: create_item heeft een plan_md-parameter en de docstring
    zegt dat de agent die meteen moet vullen."""
    doc = mcp_server.create_item.__doc__ or ""
    assert "plan_md" in doc
    assert "plan_md" in mcp_server.create_item.__code__.co_varnames


def test_get_item_docstring_advertises_inline_plan():
    """BETON-430: get_item meldt dat het plan inline zit en wijst voor een
    afgekapt plan naar get_plan."""
    doc = mcp_server.get_item.__doc__ or ""
    assert "has_plan" in doc
    assert "plan_md" in doc
    assert "get_plan" in doc


def test_list_items_docstring_advertises_has_plan():
    """BETON-388: list_items (de eerste blik op een project) moet de agent al
    op has_plan wijzen, vóórdat hij een ticket oppakt."""
    doc = mcp_server.list_items.__doc__ or ""
    assert "has_plan" in doc
    assert "get_plan" in doc


def test_update_item_docstring_advertises_plan_field():
    """update_item is waar plan_md daadwerkelijk gezet wordt — de docstring moet
    het BETON-218-veld en de BETON-301-lock uitleggen."""
    doc = mcp_server.update_item.__doc__ or ""
    assert "plan_md" in doc
    assert "get_plan" in doc


def test_mcp_mounted_in_app(tmp_path):
    # De MCP wordt in de Betonning-app gemount op /mcp/ (BETON-24). Eén lifespan-run
    # → session-manager draait; het endpoint bestaat (GET → geen 404).
    db_path = str(tmp_path / "mount.db")
    db_module.init_db(db_path).close()
    app = create_app(db_path, enable_dispatcher=False, enable_mcp=True)
    with TestClient(app) as c:
        assert c.get("/mcp/").status_code != 404  # gemount


# --- Key-resolutie op het http-transport (BETON-381) -----------------------


def test_resolve_key_no_config_fallback_over_http(monkeypatch):
    """Over http telt alleen de header van de agent zelf.

    Zou de service-key hier invallen, dan handelt een header-loze request
    stilletjes als de service-user: verkeerde attributie en een gat in de auth.
    """
    monkeypatch.setenv("BETONNING_API_KEY", "bt_service")
    monkeypatch.setenv("BETONNING_BASE_URL", "http://x")
    with pytest.raises(RuntimeError, match="Bearer"):
        mcp_server._resolve_key(_ctx_without_auth())


def test_resolve_key_still_uses_config_over_stdio(monkeypatch):
    """Stdio (lokale Claude Code) heeft per definitie geen header."""
    monkeypatch.setenv("BETONNING_API_KEY", "bt_service")
    monkeypatch.setenv("BETONNING_BASE_URL", "http://x")
    assert mcp_server._resolve_key(None) == "bt_service"
    assert mcp_server._resolve_key(_ctx_stdio()) == "bt_service"


# --- Bearer-poort op de mount (BETON-381) ----------------------------------


INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def mounted(tmp_path):
    """App met een echte MCP-mount + één geldige key."""
    db_path = str(tmp_path / "gate.db")
    db_module.init_db(db_path).close()
    conn = db_module.connect(db_path)
    _, key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent", agent_type="coding"
    )
    conn.close()
    app = create_app(db_path, enable_dispatcher=False, enable_mcp=True)
    return app, key


def test_mcp_initialize_without_bearer_is_401(mounted):
    app, _ = mounted
    with TestClient(app) as c:
        r = c.post("/mcp/", json=INITIALIZE, headers=MCP_HEADERS)
        assert r.status_code == 401
        assert r.json()["detail"] == "Ontbrekende API-key"


def test_mcp_initialize_with_unknown_key_is_401(mounted):
    app, _ = mounted
    with TestClient(app) as c:
        r = c.post(
            "/mcp/",
            json=INITIALIZE,
            headers={**MCP_HEADERS, "Authorization": "Bearer bt_bestaat_niet"},
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "Ongeldige API-key"


def test_mcp_get_without_bearer_is_401(mounted):
    """Ook de SSE-kant van het transport zit achter de poort."""
    app, _ = mounted
    with TestClient(app) as c:
        assert c.get("/mcp/").status_code == 401


def test_mcp_initialize_with_valid_key_passes_the_gate(mounted):
    app, key = mounted
    with TestClient(app) as c:
        r = c.post(
            "/mcp/",
            json=INITIALIZE,
            headers={**MCP_HEADERS, "Authorization": f"Bearer {key}"},
        )
        # De poort laat door; wat de MCP-laag er verder van vindt is niet wat
        # deze test bewaakt.
        assert r.status_code != 401
        assert r.status_code == 200
        assert r.headers.get("mcp-session-id")


# --- Guardrails (BETON-420) ------------------------------------------------


def test_get_item_docstring_advertises_guardrails():
    """Een guardrail is bindend; de agent moet 'm herkennen in de respons."""
    doc = mcp_server.get_item.__doc__ or ""
    assert "guardrail_md" in doc
    assert "applicable_guardrails" in doc
    assert "bindend" in doc.lower()


def test_load_memory_docstring_advertises_guardrails():
    doc = mcp_server.load_memory.__doc__ or ""
    assert "guardrail" in doc.lower()
    assert "bindend" in doc.lower()


def test_propose_guardrail_tool_is_registered_with_the_threshold(mcp_env):
    server = mcp_server.build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert "propose_guardrail" in names

    doc = mcp_server.propose_guardrail.__doc__ or ""
    assert "regressietest" in doc
    assert "drempel" in doc.lower()
    # BETON-422: het is een CONCEPT, en de tool kan ook een opheffing voorstellen.
    assert "CONCEPT" in doc
    assert "kind=\"lift\"" in doc
    # Goedkeuren en opheffen zijn mens-only: daar is bewust géén tool voor.
    assert {"set_guardrail", "lift_guardrail", "approve_guardrail"} & names == set()


def test_propose_guardrail_places_a_concept(mcp_env):
    """BETON-422: geen vraag-comment meer; het concept staat op het ticket en
    bindt niets."""
    ref = _run(mcp_server.create_item("SOS", "Prompt-ding"))["ref"]
    item = _run(mcp_server.propose_guardrail(ref, "Houd prompts voor model X kort."))
    assert item["guardrail_proposal"]["kind"] == "set"
    assert item["guardrail_proposal"]["guardrail_md"] == "Houd prompts voor model X kort."
    assert item["has_guardrail"] is False
    fresh = _run(mcp_server.get_item(ref))
    assert fresh["guardrail_md"] is None
    assert fresh["comments"] == []


@pytest.mark.parametrize("body, warns", [("x" * 801, True), ("Korte samenvatting.\n\n" + "x" * 801, False), ("x" * 800, False)])
def test_lange_agent_comment_krijgt_samenvattingshint(agent_env, body, warns):
    ref = _run(mcp_server.create_item("SOS", "Uitleg", plan_md="Stappen"))["ref"]
    comment = _run(mcp_server.comment_item(ref, body))
    assert ("samenvatting" in comment.get("warning", "")) is warns


def test_human_lange_comment_geen_samenvattingshint(agent_env):
    agent_env.state.as_human()
    ref = _run(mcp_server.create_item("SOS", "Uitleg"))["ref"]
    assert "warning" not in _run(mcp_server.comment_item(ref, "x" * 900))


def test_update_item_geeft_handover_door(agent_env, monkeypatch):
    monkeypatch.setenv("HEGEMONE_LANGUAGE", "nl")
    server = mcp_server.build_server()
    tool = next(tool for tool in _run(server.list_tools()) if tool.name == "update_item")
    field = tool.inputSchema["properties"]["handover_md"]
    assert any(option.get("maxLength") == 300 for option in field.get("anyOf", [field]))
    ref = _run(mcp_server.create_item("SOS", "Test", plan_md="Plan"))["ref"]
    with pytest.raises(RuntimeError, match="handover_md"):
        _run(mcp_server.update_item(ref, assignee="person"))
    with pytest.raises(RuntimeError, match="422"):
        _run(mcp_server.update_item(ref, assignee="person", handover_md="x" * 301))
    item = _run(mcp_server.update_item(ref, assignee="person", handover_md="Wil je de knop testen?"))
    assert item["assignee"] == "person"
    assert _run(mcp_server.get_item(ref))["comments"][0]["body_md"] == "**Nodig van @person:** Wil je de knop testen?"
    question = _run(mcp_server.ask_question(ref, "Werkt de knop?"))
    assert question["kind"] == "question"


def test_plan_en_samenvattingshint_blijven_beide_bewaard(agent_env):
    ref = _run(mcp_server.create_item("SOS", "Uitleg"))["ref"]
    comment = _run(mcp_server.comment_item(ref, "x" * 900))
    assert "plan_md" in comment["warning"]
    assert "samenvatting" in comment["warning"]


# --- BETON-466: mute_item / unmute_item -----------------------------------


async def _subscribers(ref):
    async with mcp_server._client("x") as client:
        return await mcp_server._call(
            client, "GET", f"/api/v1/items/{ref}/subscribers"
        )


def _muted_handles(ref):
    return {s["handle"] for s in _run(_subscribers(ref))["subscribers"] if s["muted"]}


def test_mute_and_unmute_item_for_caller(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "Lawaai"))["ref"]
    out = _run(mcp_server.mute_item(ref))
    assert out == {"ref": ref, "handle": "person", "muted": True}
    assert _muted_handles(ref) == {"person"}
    assert _run(mcp_server.unmute_item(ref))["muted"] is False
    assert _muted_handles(ref) == set()


def test_mute_item_unknown_ref_raises(mcp_env):
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.mute_item("SOS-999"))
    assert "404" in str(exc.value)


# --- BETON-466: add_label / remove_label ----------------------------------


def test_add_and_remove_single_label_keeps_others(mcp_env):
    _run(mcp_server.create_label("SOS", "bug"))
    _run(mcp_server.create_label("SOS", "area/ui"))
    ref = _run(mcp_server.create_item("SOS", "Labels", labels=["bug"]))["ref"]
    item = _run(mcp_server.add_label(ref, "area/ui"))
    assert sorted(item["labels"]) == ["area/ui", "bug"]
    item = _run(mcp_server.remove_label(ref, "area/ui"))
    assert item["labels"] == ["bug"]


def test_add_label_unknown_label_raises(mcp_env):
    ref = _run(mcp_server.create_item("SOS", "Labels"))["ref"]
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.add_label(ref, "bestaat-niet"))
    assert "400" in str(exc.value)


# --- BETON-466: list_users ------------------------------------------------


def test_list_users_filters_kind_and_leaks_no_secrets(mcp_env, tmp_path):
    conn = db_module.connect(str(tmp_path / "mcp.db"))
    users_repo.create(
        conn,
        handle="smid",
        display_name="Smid",
        kind="agent",
        agent_type="hermes",
        webhook_url="http://10.23.45.67:9000/hook",
        webhook_secret="geheim",
    )
    conn.close()
    everyone = _run(mcp_server.list_users())
    assert {"person", "smid"} <= {u["handle"] for u in everyone}
    agents = _run(mcp_server.list_users(kind="agent"))
    assert {u["kind"] for u in agents} == {"agent"}
    assert "person" not in {u["handle"] for u in agents}
    smid = next(u for u in agents if u["handle"] == "smid")
    assert smid["agent_type"] == "hermes"
    dump = str(everyone)
    for forbidden in ("webhook_url", "10.23.45.67", "geheim", "api_key"):
        assert forbidden not in dump


# --- BETON-466: upload_attachment -----------------------------------------

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_upload_attachment_returns_url_and_markdown(mcp_env):
    import base64

    ref = _run(mcp_server.create_item("SOS", "Bewijs"))["ref"]
    out = _run(
        mcp_server.upload_attachment(
            ref, "scherm.png", base64.b64encode(_PNG).decode()
        )
    )
    assert out["url"].startswith("/api/v1/attachments/")
    assert out["markdown"] == f"![scherm.png]({out['url']})"
    assert out["content_type"] == "image/png"


def test_upload_attachment_too_large_rejected_before_decoding(mcp_env, monkeypatch):
    from betonning.repo import attachments as attachments_repo

    def boom(*a, **k):
        raise AssertionError("gedecodeerd")

    monkeypatch.setattr(mcp_server.base64, "b64decode", boom)
    ref = _run(mcp_server.create_item("SOS", "Bewijs"))["ref"]
    too_big = "A" * (attachments_repo.MAX_SIZE * 4 // 3 + 100)
    with pytest.raises(RuntimeError) as exc:
        _run(mcp_server.upload_attachment(ref, "groot.png", too_big))
    assert "te groot" in str(exc.value)


def test_upload_attachment_unsupported_type_raises(mcp_env):
    import base64

    ref = _run(mcp_server.create_item("SOS", "Bewijs"))["ref"]
    with pytest.raises(RuntimeError) as exc:
        _run(
            mcp_server.upload_attachment(
                ref, "x.bin", base64.b64encode(b"\x00\x01\x02").decode()
            )
        )
    assert "415" in str(exc.value)


# --- BETON-466: create_items ----------------------------------------------


def test_create_items_mixed_results_continue_after_error(mcp_env):
    results = _run(
        mcp_server.create_items(
            "SOS",
            [
                {"title": "een", "plan_md": "stappen", "workload": "light"},
                {"title": "twee", "workload": "bestaat-niet"},
                {"title": "drie", "onbekend_veld": 1},
                {"title": "vier"},
            ],
        )
    )
    assert [r["ok"] for r in results] == [True, False, False, True]
    assert results[0]["ref"] == "SOS-1"
    assert "422" in results[1]["error"]
    assert results[3]["ref"] == "SOS-2"  # de mislukte items kostten geen ref
    assert "next_step" not in results[0]


def test_create_items_rejects_more_than_fifty(mcp_env):
    with pytest.raises(RuntimeError):
        _run(mcp_server.create_items("SOS", [{"title": str(i)} for i in range(51)]))
    assert _run(mcp_server.list_items("SOS")) == []


def test_tool_definitions_stay_compact():
    """BETON-467: naam + beschrijving + schema van alle tools kosten elke
    sessie context. Stand na inkorten: 30.588 tekens; drempel = +10%. Groei je
    erboven, kort dan eerst een docstring in (werkwijze staat in de
    serverinstructies)."""
    import json

    server = mcp_server.build_server()
    tools = asyncio.run(server.list_tools())
    total = sum(
        len(
            json.dumps(
                {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
            )
        )
        for t in tools
    )
    assert total <= 33_600, total


def test_me_is_cached_per_key_with_ttl(mcp_env, monkeypatch):
    """BETON-467: create_item/comment_item doen niet elke keer GET /me."""
    mcp_server._ME_CACHE.clear()
    calls = []
    orig = mcp_server._call

    async def counting(client, method, path, **kw):
        if path == "/api/v1/me":
            calls.append(path)
        return await orig(client, method, path, **kw)

    monkeypatch.setattr(mcp_server, "_call", counting)
    _run(mcp_server.create_item("SOS", "een"))
    _run(mcp_server.create_item("SOS", "twee"))
    assert len(calls) == 1

    # na de TTL wordt opnieuw opgehaald
    key = next(iter(mcp_server._ME_CACHE))
    stamp, me = mcp_server._ME_CACHE[key]
    mcp_server._ME_CACHE[key] = (stamp - mcp_server._ME_TTL - 1, me)
    _run(mcp_server.create_item("SOS", "drie"))
    assert len(calls) == 2


@pytest.fixture
def mcp_as_agent(tmp_path, monkeypatch):
    """Zelfde als mcp_env, maar de MCP-aanroeper is een agent met gegeven handle."""

    def make(handle: str, agent_type: str = "coding"):
        db_path = str(tmp_path / f"{handle}.db")
        db_module.init_db(db_path).close()
        conn = db_module.connect(db_path)
        _, key = users_repo.create(
            conn, handle=handle, display_name=handle, kind="agent", agent_type=agent_type
        )
        projects_repo.create(conn, key="SOS", name="SOS")
        conn.close()
        monkeypatch.setenv("BETONNING_API_KEY", key)
        monkeypatch.setenv("BETONNING_BASE_URL", "http://test")
        app = create_app(db_path, enable_dispatcher=False)
        monkeypatch.setattr(
            mcp_server,
            "_client",
            lambda k=None: httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": f"Bearer {key}"},
            ),
        )
        mcp_server._ME_CACHE.clear()
        return app

    return make


def _ticket_met_klasse(cls):
    created = _run(mcp_server.create_item("SOS", "klasse-ticket", labels=[cls]))
    return created["ref"]


def test_get_item_model_for_you_claude_en_codex(mcp_as_agent):
    mcp_as_agent("claude")
    ref = _ticket_met_klasse("complex")
    assert _run(mcp_server.get_item(ref))["model_for_you"] == {
        "class": "complex", "model": "opus"}

    mcp_as_agent("codex")
    ref = _ticket_met_klasse("routine")
    assert _run(mcp_server.get_item(ref))["model_for_you"] == {
        "class": "routine", "model": "gpt-5.4-mini"}


def test_get_item_model_for_you_onbekend_harnas_is_null(mcp_as_agent):
    mcp_as_agent("smid", agent_type="hermes")
    ref = _ticket_met_klasse("complex")
    assert _run(mcp_server.get_item(ref))["model_for_you"] is None


def test_get_item_model_for_you_null_voor_mens(mcp_env):
    created = _run(mcp_server.create_item("SOS", "mens"))
    assert _run(mcp_server.get_item(created["ref"]))["model_for_you"] is None


def test_agent_krijgt_hint_bij_ontbrekende_werkklasse(agent_env):
    item = _run(mcp_server.create_item("SOS", "Taak", plan_md="Plan"))
    assert "routine, standaard of complex" in item["next_step"]


def test_agent_mag_geen_modellabel_aanmaken(agent_env):
    with pytest.raises(RuntimeError, match="werkklasse"):
        _run(mcp_server.create_label("SOS", "sonnet"))


def test_tool_configuration_is_isolated_from_user_files(tmp_path, monkeypatch):
    from pathlib import Path

    def only_synthetic_configuration(path, *args, **kwargs):
        assert path == tmp_path / "mcp-unconfigured.json"
        raise FileNotFoundError

    monkeypatch.setattr(Path, "read_text", only_synthetic_configuration)
    assert mcp_server._config() == {"base_url": "http://test", "api_key": None}
