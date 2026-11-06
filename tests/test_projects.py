"""Projecten en states."""

from __future__ import annotations


def _make_project(client, auth, key="SOS", name="SOS"):
    return client.post(
        "/api/v1/projects", json={"key": key, "name": name}, headers=auth
    )


def test_create_and_list_project(client, auth):
    r = _make_project(client, auth)
    assert r.status_code == 201
    assert r.json()["key"] == "SOS"

    r = client.get("/api/v1/projects", headers=auth)
    assert r.status_code == 200
    assert [p["key"] for p in r.json()] == ["SOS"]


def test_create_project_requires_auth(client):
    r = client.post("/api/v1/projects", json={"key": "X", "name": "X"})
    assert r.status_code == 401


def test_duplicate_project_conflicts(client, auth):
    _make_project(client, auth)
    r = _make_project(client, auth)
    assert r.status_code == 409


def test_new_project_has_default_states(client, auth):
    _make_project(client, auth)
    r = client.get("/api/v1/projects/SOS/states", headers=auth)
    assert r.status_code == 200
    names = [s["name"] for s in r.json()]
    assert {"backlog", "todo", "in-progress", "done"} <= set(names)


def test_default_state_set_order_closed_and_blocks_work(client, auth):
    """De zes basiskolommen staan in werkvolgorde met hun uitvoeringsbeleid."""
    _make_project(client, auth)
    states = client.get("/api/v1/projects/SOS/states", headers=auth).json()
    assert [s["name"] for s in states] == [
        "backlog", "todo", "in-progress", "deferred", "done", "cancelled",
    ]
    closed = {s["name"] for s in states if s["closed"]}
    assert closed == {"done", "cancelled"}
    blocks_work = {s["name"] for s in states if s["blocks_work"]}
    assert blocks_work == {"backlog", "deferred"}


def test_create_state_accepts_closed(client, auth):
    _make_project(client, auth)
    r = client.post(
        "/api/v1/projects/SOS/states",
        json={"name": "archived", "group": "cancelled", "closed": True},
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["closed"] is True
    # Default blijft open als 'closed' niet is meegegeven.
    r2 = client.post(
        "/api/v1/projects/SOS/states",
        json={"name": "scheduled", "group": "unstarted"},
        headers=auth,
    )
    assert r2.json()["closed"] is False


def test_create_and_update_state_blocks_work(client, auth):
    _make_project(client, auth)
    r = client.post(
        "/api/v1/projects/SOS/states",
        json={"name": "wachten", "group": "unstarted", "blocks_work": True},
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["blocks_work"] is True

    r = client.patch(
        "/api/v1/projects/SOS/states/wachten",
        json={"blocks_work": False},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["blocks_work"] is False


def test_rename_state(client, auth):
    """BETON-177: naam is bewerkbaar; bestaande items behouden hun (hernoemde)
    state omdat items via state_id refereren, niet via de naam."""
    _make_project(client, auth)
    item = client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "x", "state": "todo"},
        headers=auth,
    ).json()

    r = client.patch(
        "/api/v1/projects/SOS/states/todo",
        json={"name": "in behandeling"},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "in behandeling"

    fetched = client.get(f"/api/v1/items/{item['ref']}", headers=auth).json()
    assert fetched["state"] == "in behandeling"


def test_rename_state_duplicate_conflicts_409(client, auth):
    _make_project(client, auth)
    r = client.patch(
        "/api/v1/projects/SOS/states/todo",
        json={"name": "done"},
        headers=auth,
    )
    assert r.status_code == 409


def test_rename_state_empty_name_422(client, auth):
    _make_project(client, auth)
    r = client.patch(
        "/api/v1/projects/SOS/states/todo",
        json={"name": ""},
        headers=auth,
    )
    assert r.status_code == 422


def test_update_state_color(client, auth):
    _make_project(client, auth)
    r = client.patch(
        "/api/v1/projects/SOS/states/todo",
        json={"color": "#abcdef"},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["color"] == "#abcdef"


def test_update_state_sort_order(client, auth):
    _make_project(client, auth)
    r = client.patch(
        "/api/v1/projects/SOS/states/todo",
        json={"sort_order": 42},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["sort_order"] == 42


def test_rename_state_same_name_case_change_allowed(client, auth):
    """Alleen hoofdletters wijzigen van je eigen naam mag (geen self-conflict)."""
    _make_project(client, auth)
    r = client.patch(
        "/api/v1/projects/SOS/states/todo",
        json={"name": "Todo"},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Todo"


def test_update_unknown_state_404(client, auth):
    _make_project(client, auth)
    r = client.patch(
        "/api/v1/projects/SOS/states/onbekend",
        json={"blocks_work": True},
        headers=auth,
    )
    assert r.status_code == 404


def test_states_unknown_project_404(client, auth):
    r = client.get("/api/v1/projects/NOPE/states", headers=auth)
    assert r.status_code == 404


def test_create_custom_state(client, auth):
    _make_project(client, auth)
    r = client.post(
        "/api/v1/projects/SOS/states",
        json={"name": "waiting", "group": "started", "color": "#111111"},
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["name"] == "waiting"


def test_duplicate_state_conflicts(client, auth):
    _make_project(client, auth)
    r = client.post(
        "/api/v1/projects/SOS/states",
        json={"name": "todo", "group": "unstarted"},
        headers=auth,
    )
    assert r.status_code == 409


def test_delete_state(client, auth):
    _make_project(client, auth)
    client.post(
        "/api/v1/projects/SOS/states",
        json={"name": "waiting", "group": "started"},
        headers=auth,
    )
    r = client.delete("/api/v1/projects/SOS/states/waiting", headers=auth)
    assert r.status_code == 204

    names = [s["name"] for s in client.get("/api/v1/projects/SOS/states", headers=auth).json()]
    assert "waiting" not in names


def test_delete_unknown_state_404(client, auth):
    _make_project(client, auth)
    r = client.delete("/api/v1/projects/SOS/states/onbekend", headers=auth)
    assert r.status_code == 404


def test_delete_state_with_items_conflicts_409(client, auth):
    _make_project(client, auth)
    client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "x", "state": "todo"},
        headers=auth,
    )
    r = client.delete("/api/v1/projects/SOS/states/todo", headers=auth)
    assert r.status_code == 409

    # Onaangetast: state bestaat nog en het item staat er nog steeds in.
    names = [s["name"] for s in client.get("/api/v1/projects/SOS/states", headers=auth).json()]
    assert "todo" in names


def test_delete_last_remaining_state_conflicts_409(client, auth):
    _make_project(client, auth)
    states = client.get("/api/v1/projects/SOS/states", headers=auth).json()
    # Alle-op-één-na wegwerken, ze bevatten geen items.
    for s in states[:-1]:
        r = client.delete(f"/api/v1/projects/SOS/states/{s['name']}", headers=auth)
        assert r.status_code == 204

    last = states[-1]["name"]
    r = client.delete(f"/api/v1/projects/SOS/states/{last}", headers=auth)
    assert r.status_code == 409

    names = [s["name"] for s in client.get("/api/v1/projects/SOS/states", headers=auth).json()]
    assert names == [last]


def test_archive_project_hides_from_default_list(client, auth):
    _make_project(client, auth)
    r = client.delete("/api/v1/projects/SOS", headers=auth)
    assert r.status_code == 204

    r = client.get("/api/v1/projects", headers=auth)
    assert [p["key"] for p in r.json()] == []


def test_archived_project_visible_with_flag(client, auth):
    _make_project(client, auth)
    client.delete("/api/v1/projects/SOS", headers=auth)

    r = client.get("/api/v1/projects?archived=true", headers=auth)
    assert r.status_code == 200
    keys = [p["key"] for p in r.json()]
    assert keys == ["SOS"]
    assert r.json()[0]["archived_at"] is not None


def test_restore_project(client, auth):
    _make_project(client, auth)
    client.delete("/api/v1/projects/SOS", headers=auth)

    r = client.post("/api/v1/projects/SOS/restore", headers=auth)
    assert r.status_code == 200
    assert r.json()["archived_at"] is None

    r = client.get("/api/v1/projects", headers=auth)
    assert [p["key"] for p in r.json()] == ["SOS"]


def test_archive_unknown_project_404(client, auth):
    r = client.delete("/api/v1/projects/NOPE", headers=auth)
    assert r.status_code == 404


def test_restore_unknown_project_404(client, auth):
    r = client.post("/api/v1/projects/NOPE/restore", headers=auth)
    assert r.status_code == 404


def test_archive_project_requires_auth(client, auth):
    _make_project(client, auth)
    r = client.delete("/api/v1/projects/SOS")
    assert r.status_code == 401


def test_archived_project_still_serves_items(client, auth):
    """Archiveren verbergt het project maar laat items/refs intact."""
    _make_project(client, auth)
    created = client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "leeft nog"},
        headers=auth,
    ).json()
    client.delete("/api/v1/projects/SOS", headers=auth)

    r = client.get(f"/api/v1/items/{created['ref']}", headers=auth)
    assert r.status_code == 200
    assert r.json()["title"] == "leeft nog"


# --- Projectomschrijving (BETON-26) ---------------------------------------


def test_create_project_with_description(client, auth):
    r = client.post(
        "/api/v1/projects",
        json={"key": "SOS", "name": "SOS", "description": "Persoonlijk dashboard."},
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["description"] == "Persoonlijk dashboard."


def test_update_project_description(client, auth):
    _make_project(client, auth)
    r = client.patch(
        "/api/v1/projects/SOS",
        json={"description": "Nu met uitleg."},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["description"] == "Nu met uitleg."
    # Blijft persistent in de lijst.
    listed = client.get("/api/v1/projects", headers=auth).json()
    assert listed[0]["description"] == "Nu met uitleg."


def test_update_project_name_only_keeps_description(client, auth):
    client.post(
        "/api/v1/projects",
        json={"key": "SOS", "name": "Oud", "description": "Blijft staan."},
        headers=auth,
    )
    r = client.patch("/api/v1/projects/SOS", json={"name": "Nieuw"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["name"] == "Nieuw"
    assert r.json()["description"] == "Blijft staan."


def test_update_unknown_project_404(client, auth):
    r = client.patch("/api/v1/projects/NOPE", json={"description": "x"}, headers=auth)
    assert r.status_code == 404


def test_update_project_requires_auth(client, auth):
    _make_project(client, auth)
    r = client.patch("/api/v1/projects/SOS", json={"description": "x"})
    assert r.status_code == 401


# --- Case-insensitieve states & labels (BETON-35) -------------------------


def test_item_state_resolution_is_case_insensitive(client, auth):
    _make_project(client, auth)
    ref = client.post(
        "/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth
    ).json()["ref"]
    # State 'todo' bestaat lowercase; 'Todo'/'TODO' moeten resolven.
    assert client.patch(
        f"/api/v1/items/{ref}", json={"state": "Todo"}, headers=auth
    ).status_code == 200
    assert client.patch(
        f"/api/v1/items/{ref}", json={"state": "IN-PROGRESS"}, headers=auth
    ).status_code == 200


def test_duplicate_state_case_insensitive_conflicts(client, auth):
    _make_project(client, auth)
    # 'todo' bestaat al → 'Todo' is een duplicaat (409), niet een tweede kolom.
    r = client.post(
        "/api/v1/projects/SOS/states",
        json={"name": "Todo", "group": "unstarted"},
        headers=auth,
    )
    assert r.status_code == 409


def test_project_label_lookup_is_case_insensitive(client, auth):
    _make_project(client, auth)
    client.post("/api/v1/projects/SOS/labels", json={"name": "bug"}, headers=auth)
    # Verwijderen met andere case moet het bestaande label vinden.
    assert client.delete(
        "/api/v1/projects/SOS/labels/BUG", headers=auth
    ).status_code == 204
    assert {label_entry["name"] for label_entry in client.get("/api/v1/projects/SOS/labels", headers=auth).json()} == {"routine", "standaard", "complex"}


# --- Triage opt-in + backfill (fase 3, BETON-22) --------------------------


def test_project_defaults_to_triage_disabled(client, auth):
    r = _make_project(client, auth)
    assert r.json()["triage_enabled"] is False


def test_set_triage_optin_toggles(client, auth):
    _make_project(client, auth)
    r = client.put("/api/v1/projects/SOS/triage", json={"enabled": True}, headers=auth)
    assert r.status_code == 200
    assert r.json()["triage_enabled"] is True
    r = client.put("/api/v1/projects/SOS/triage", json={"enabled": False}, headers=auth)
    assert r.json()["triage_enabled"] is False


def test_backfill_requires_optin(client, auth):
    _make_project(client, auth)
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    # Zonder opt-in → 400.
    assert client.post("/api/v1/projects/SOS/triage/backfill", headers=auth).status_code == 400
    # Met opt-in → plant de items opnieuw in.
    client.put("/api/v1/projects/SOS/triage", json={"enabled": True}, headers=auth)
    r = client.post("/api/v1/projects/SOS/triage/backfill", headers=auth)
    assert r.status_code == 200
    assert r.json()["queued"] == 1


def test_triage_endpoints_require_auth(client, auth):
    _make_project(client, auth)
    assert client.put("/api/v1/projects/SOS/triage", json={"enabled": True}).status_code == 401
    assert client.post("/api/v1/projects/SOS/triage/backfill").status_code == 401


# --- Projectlabel-beheer (UI-parity) --------------------------------------


def test_create_and_delete_project_label(client, auth):
    _make_project(client, auth)
    r = client.post(
        "/api/v1/projects/SOS/labels", json={"name": "bug", "color": "#d1441a"}, headers=auth
    )
    assert r.status_code == 201 and r.json()["name"] == "bug"
    # Duplicaat → 409.
    assert client.post(
        "/api/v1/projects/SOS/labels", json={"name": "bug"}, headers=auth
    ).status_code == 409
    # Verwijderen → weg uit de lijst.
    assert client.delete("/api/v1/projects/SOS/labels/bug", headers=auth).status_code == 204
    assert {label_entry["name"] for label_entry in client.get("/api/v1/projects/SOS/labels", headers=auth).json()} == {"routine", "standaard", "complex"}


def test_delete_unknown_project_label_404(client, auth):
    _make_project(client, auth)
    assert client.delete("/api/v1/projects/SOS/labels/nope", headers=auth).status_code == 404


# --- Wiki-compiler opt-in + backfill (BETON-24) ---------------------------


def test_project_defaults_to_wiki_compile_disabled(client, auth):
    r = _make_project(client, auth)
    assert r.json()["wiki_compile_enabled"] is False


def test_set_wiki_compile_optin_toggles(client, auth):
    _make_project(client, auth)
    r = client.put("/api/v1/projects/SOS/wiki-compile", json={"enabled": True}, headers=auth)
    assert r.status_code == 200 and r.json()["wiki_compile_enabled"] is True
    r = client.put("/api/v1/projects/SOS/wiki-compile", json={"enabled": False}, headers=auth)
    assert r.json()["wiki_compile_enabled"] is False


def test_wiki_compile_backfill_requires_optin(client, auth):
    _make_project(client, auth)
    created = client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth).json()
    # Zonder opt-in → 400.
    assert client.post(
        "/api/v1/projects/SOS/wiki-compile/backfill", headers=auth
    ).status_code == 400
    # Met opt-in: alleen closed items worden ingepland. Nieuw item is niet closed → 0.
    client.put("/api/v1/projects/SOS/wiki-compile", json={"enabled": True}, headers=auth)
    r = client.post("/api/v1/projects/SOS/wiki-compile/backfill", headers=auth)
    assert r.status_code == 200 and r.json()["queued"] == 0
    # Zet het item op done → dan plant backfill het wél in.
    client.patch(f"/api/v1/items/{created['ref']}", json={"state": "done"}, headers=auth)
    r = client.post("/api/v1/projects/SOS/wiki-compile/backfill", headers=auth)
    assert r.json()["queued"] == 1


def test_wiki_compile_endpoints_require_auth(client, auth):
    _make_project(client, auth)
    assert client.put(
        "/api/v1/projects/SOS/wiki-compile", json={"enabled": True}
    ).status_code == 401
    assert client.post("/api/v1/projects/SOS/wiki-compile/backfill").status_code == 401


# --- Agent-toegang (BETON-123) --------------------------------------------


def _seed_agents(conn):
    from betonning.repo import users as users_repo

    users_repo.create(conn, handle="claude", display_name="Claude", kind="agent",
                      agent_type="coding")
    users_repo.create(conn, handle="smid", display_name="Smid", kind="agent",
                      agent_type="hermes")
    conn.commit()


def test_access_default_all_assign(client, auth, conn):
    _make_project(client, auth)
    _seed_agents(conn)
    r = client.get("/api/v1/projects/SOS/access", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["type_defaults"] == {}
    eff = {a["handle"]: a["effective"] for a in body["agents"]}
    assert eff == {"claude": "assign", "smid": "assign"}


def test_set_type_access(client, auth, conn):
    _make_project(client, auth)
    _seed_agents(conn)
    r = client.put("/api/v1/projects/SOS/access/type/hermes", json={"level": "none"},
                   headers=auth)
    assert r.status_code == 200
    eff = {a["handle"]: a["effective"] for a in r.json()["agents"]}
    assert eff["smid"] == "none" and eff["claude"] == "assign"


def test_set_agent_override_and_inherit(client, auth, conn):
    _make_project(client, auth)
    _seed_agents(conn)
    client.put("/api/v1/projects/SOS/access/type/hermes", json={"level": "none"},
               headers=auth)
    # override wint van type-default
    r = client.put("/api/v1/projects/SOS/access/agent/smid", json={"level": "respond"},
                   headers=auth)
    eff = {a["handle"]: a["effective"] for a in r.json()["agents"]}
    assert eff["smid"] == "respond"
    # inherit (null) → terug naar type-default (none)
    r = client.put("/api/v1/projects/SOS/access/agent/smid", json={"level": None},
                   headers=auth)
    eff = {a["handle"]: a["effective"] for a in r.json()["agents"]}
    assert eff["smid"] == "none"


def test_access_unknown_project_404(client, auth):
    assert client.get("/api/v1/projects/NOPE/access", headers=auth).status_code == 404


def test_access_invalid_type_422(client, auth):
    _make_project(client, auth)
    r = client.put("/api/v1/projects/SOS/access/type/bogus", json={"level": "none"},
                   headers=auth)
    assert r.status_code == 422


def test_access_unknown_agent_404(client, auth):
    _make_project(client, auth)
    r = client.put("/api/v1/projects/SOS/access/agent/ghost", json={"level": "none"},
                   headers=auth)
    assert r.status_code == 404


def test_access_invalid_level_422(client, auth, conn):
    _make_project(client, auth)
    _seed_agents(conn)
    r = client.put("/api/v1/projects/SOS/access/type/hermes", json={"level": "banana"},
                   headers=auth)
    assert r.status_code == 422


def test_access_requires_auth(client, auth):
    _make_project(client, auth)
    assert client.get("/api/v1/projects/SOS/access").status_code == 401
    assert client.put(
        "/api/v1/projects/SOS/access/type/hermes", json={"level": "none"}
    ).status_code == 401


def test_list_projects_carries_last_activity(client, auth, conn):
    """BETON-475: de kiezer groepeert op `last_activity_at`; leeg project = null."""
    _make_project(client, auth)
    client.post("/api/v1/projects", json={"key": "LEEG", "name": "Leeg"}, headers=auth)
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    conn.execute("UPDATE items SET updated_at = '2026-01-01T00:00:00.000Z'")
    conn.commit()
    rows = {p["key"]: p for p in client.get("/api/v1/projects", headers=auth).json()}
    assert rows["SOS"]["last_activity_at"] == "2026-01-01T00:00:00.000Z"
    assert rows["LEEG"]["last_activity_at"] is None

    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=auth)
    rows = {p["key"]: p for p in client.get("/api/v1/projects", headers=auth).json()}
    assert rows["SOS"]["last_activity_at"] > "2026-01-01T00:00:00.000Z"


def test_access_levels_are_human_only(client, auth, conn):
    """Een agent mag zijn eigen (of andermans) toegangsniveau niet zetten: dan
    is de `respond`-grens van BETON-123 met één PUT weg."""
    from betonning.repo import users as users_repo

    _make_project(client, auth)
    _, key = users_repo.create(conn, handle="smid", display_name="Smid",
                               kind="agent", agent_type="hermes")
    conn.commit()
    smid = {"Authorization": f"Bearer {key}"}
    client.put("/api/v1/projects/SOS/access/type/hermes", json={"level": "respond"},
               headers=auth)

    r = client.put("/api/v1/projects/SOS/access/agent/smid", json={"level": "assign"},
                   headers=smid)
    assert r.status_code == 403
    r = client.put("/api/v1/projects/SOS/access/type/hermes", json={"level": "assign"},
                   headers=smid)
    assert r.status_code == 403
    eff = {a["handle"]: a["effective"]
           for a in client.get("/api/v1/projects/SOS/access", headers=auth).json()["agents"]}
    assert eff["smid"] == "respond"


def test_agent_cannot_archive_or_restore_project(client, auth, conn):
    """BETON-482: archiveren haalt een project uit alle sweeps (BETON-413). Dat
    beslist een mens; een agent krijgt 403. Aanmaken en wijzigen blijven open."""
    from betonning.repo import users as users_repo

    _, agent_key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent", agent_type="coding"
    )
    conn.commit()
    agent = {"Authorization": f"Bearer {agent_key}"}
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=agent)

    assert client.delete("/api/v1/projects/SOS", headers=agent).status_code == 403
    assert client.delete("/api/v1/projects/SOS", headers=auth).status_code == 204
    r = client.post("/api/v1/projects/SOS/restore", headers=agent)
    assert r.status_code == 403
    assert client.post("/api/v1/projects/SOS/restore", headers=auth).status_code == 200


def test_creation_date_available_for_quiet_classification(client, auth):
    """Nieuwe lege projecten hebben ook zonder ticketactiviteit een leeftijd."""
    created = _make_project(client, auth).json()["created_at"]
    listed = client.get("/api/v1/projects", headers=auth).json()[0]
    overview = client.get("/api/v1/overview", headers=auth).json()[0]
    assert listed["created_at"] == created
    assert overview["created_at"] == created
    assert overview["last_activity_at"] is None


def test_project_key_normalization_and_html_rejection(client, auth):
    assert client.post("/api/v1/projects", headers=auth,
                       json={"key": "lower", "name": "Test"}).json()["key"] == "LOWER"
    for key in ['" oncut=alert(1) x="', '<script>', 'a/b', 'a b', 'é']:
        assert client.post("/api/v1/projects", headers=auth,
                           json={"key": key, "name": "Test"}).status_code == 422
