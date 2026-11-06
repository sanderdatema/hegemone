"""Relations: gericht opgeslagen, in beide richtingen opvraagbaar."""

from __future__ import annotations

import pytest

from conftest import _create


@pytest.fixture
def project(project, client, auth):
    for _ in range(3):
        client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    return project


def _relations(client, auth, ref):
    return client.get(f"/api/v1/items/{ref}", headers=auth).json()["relations"]


def test_blocks_visible_both_directions(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-2"},
        headers=auth,
    )
    assert r.status_code == 201
    assert _relations(client, auth, "SOS-1")["blocks"] == ["SOS-2"]
    assert _relations(client, auth, "SOS-2")["blocked_by"] == ["SOS-1"]


def test_blocked_by_normalizes(client, auth, project):
    # SOS-1 is blocked_by SOS-2  ==  SOS-2 blocks SOS-1
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocked_by", "target": "SOS-2"},
        headers=auth,
    )
    assert _relations(client, auth, "SOS-1")["blocked_by"] == ["SOS-2"]
    assert _relations(client, auth, "SOS-2")["blocks"] == ["SOS-1"]


def test_duplicate_of_both_directions(client, auth, project):
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "duplicate_of", "target": "SOS-2"},
        headers=auth,
    )
    assert _relations(client, auth, "SOS-1")["duplicate_of"] == ["SOS-2"]
    assert _relations(client, auth, "SOS-2")["duplicated_by"] == ["SOS-1"]


def test_relates_to_symmetric(client, auth, project):
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "relates_to", "target": "SOS-3"},
        headers=auth,
    )
    assert _relations(client, auth, "SOS-1")["relates_to"] == ["SOS-3"]
    assert _relations(client, auth, "SOS-3")["relates_to"] == ["SOS-1"]


def test_relates_to_no_duplicate_when_added_both_directions(client, auth, project):
    # Dezelfde symmetrische relatie vanuit beide kanten toevoegen mag maar één
    # relatie opleveren, niet twee (BETON-20).
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "relates_to", "target": "SOS-3"},
        headers=auth,
    )
    client.post(
        "/api/v1/items/SOS-3/relations",
        json={"type": "relates_to", "target": "SOS-1"},
        headers=auth,
    )
    assert _relations(client, auth, "SOS-1")["relates_to"] == ["SOS-3"]
    assert _relations(client, auth, "SOS-3")["relates_to"] == ["SOS-1"]


def test_relates_to_delete_from_reverse_direction(client, auth, project):
    # Canonieke opslag betekent dat verwijderen ook vanuit de andere kant lukt.
    client.post(
        "/api/v1/items/SOS-3/relations",
        json={"type": "relates_to", "target": "SOS-1"},
        headers=auth,
    )
    r = client.request(
        "DELETE",
        "/api/v1/items/SOS-1/relations",
        json={"type": "relates_to", "target": "SOS-3"},
        headers=auth,
    )
    assert r.status_code == 200
    assert _relations(client, auth, "SOS-1")["relates_to"] == []
    assert _relations(client, auth, "SOS-3")["relates_to"] == []


def test_migration_cleans_existing_duplicate_relations(conn, user_key):
    # Simuleer legacy-data: symmetrisch paar in beide richtingen + een
    # self-relatie, en draai migratie 009 opnieuw. (user_key zorgt voor een
    # user met id=1 zodat items.created_by de FK niet schendt.)
    from betonning import db as db_module

    conn.execute("INSERT INTO projects (key, name) VALUES ('X', 'X')")
    pid = conn.execute("SELECT id FROM projects WHERE key='X'").fetchone()["id"]
    ids = []
    for seq in (1, 2):
        conn.execute(
            "INSERT INTO items (project_id, seq, title, created_by) "
            "VALUES (?, ?, 'x', 1)",
            (pid, seq),
        )
        ids.append(conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"])
    a, b = ids
    conn.execute(
        "INSERT INTO relations (item_id, related_item_id, type) VALUES (?, ?, 'relates_to')",
        (a, b),
    )
    conn.execute(
        "INSERT INTO relations (item_id, related_item_id, type) VALUES (?, ?, 'relates_to')",
        (b, a),
    )
    conn.execute(
        "INSERT INTO relations (item_id, related_item_id, type) VALUES (?, ?, 'relates_to')",
        (a, a),
    )
    conn.commit()

    sql = db_module._migration_files()  # (versie, sql)-lijst
    body = next(s for v, s in sql if v == 9)
    conn.executescript(body)
    conn.commit()

    rows = conn.execute(
        "SELECT item_id, related_item_id FROM relations WHERE type='relates_to'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["item_id"] < rows[0]["related_item_id"]


def test_relation_writes_event(client, auth, project):
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-2"},
        headers=auth,
    )
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert events[-1]["type"] == "relation.created"


def test_relates_to_writes_event_on_both_items(client, auth, project):
    """BETON-138: relates_to is symmetrisch, dus het doel-ticket hoort óók een
    relation.created-event te zien (live-activity + UI-tweeweg).
    Gerichte types (blocks, duplicate_of) schrijven het event alleen op de bron."""
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "relates_to", "target": "SOS-3"},
        headers=auth,
    )
    # Bron-ticket SOS-1 heeft het event.
    src_events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert src_events[-1]["type"] == "relation.created"
    # Doel-ticket SOS-3 heeft óók het event (de mirror).
    dst_events = client.get("/api/v1/items/SOS-3/activity", headers=auth).json()
    assert any(
        e["type"] == "relation.created" and e["payload"].get("target") == "SOS-1"
        for e in dst_events
    )


def test_relates_to_delete_writes_event_on_both_items(client, auth, project):
    """BETON-138: ook bij verwijderen van een relates_to-relatie krijgt het
    doel-ticket een relation.deleted-event (mirror)."""
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "relates_to", "target": "SOS-3"},
        headers=auth,
    )
    client.request(
        "DELETE",
        "/api/v1/items/SOS-1/relations",
        json={"type": "relates_to", "target": "SOS-3"},
        headers=auth,
    )
    # Beide tickets hebben een relation.deleted-event.
    src_events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    dst_events = client.get("/api/v1/items/SOS-3/activity", headers=auth).json()
    assert src_events[-1]["type"] == "relation.deleted"
    assert any(e["type"] == "relation.deleted" for e in dst_events)


def test_self_relation_400(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-1"},
        headers=auth,
    )
    assert r.status_code == 400


def test_relation_unknown_target_404(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-999"},
        headers=auth,
    )
    assert r.status_code == 404


def test_relation_requires_auth(client, project):
    r = client.post(
        "/api/v1/items/SOS-1/relations", json={"type": "blocks", "target": "SOS-2"}
    )
    assert r.status_code == 401


# --- BETON-344: relaties op de kaart (list/board-pad) -----------------------


def _card(client, auth, project, ref):
    items = client.get(f"/api/v1/projects/{project}/items", headers=auth).json()
    return next(i for i in items if i["ref"] == ref)


def test_list_card_carries_relations_both_directions(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-2"},
        headers=auth,
    )
    assert r.status_code == 201

    assert _card(client, auth, project, "SOS-1")["relations"]["blocks"] == ["SOS-2"]
    assert _card(client, auth, project, "SOS-2")["relations"]["blocked_by"] == ["SOS-1"]


def test_list_card_relations_include_all_five_verbs_shape(client, auth, project):
    """Zonder relaties zijn alle vijf verba aanwezig als lege lijst — de UI hoeft
    dan niet op een ontbrekende sleutel te controleren."""
    relations = _card(client, auth, project, "SOS-3")["relations"]
    assert relations == {
        "blocks": [],
        "blocked_by": [],
        "duplicate_of": [],
        "duplicated_by": [],
        "relates_to": [],
    }


def test_list_card_relations_relates_to_symmetric(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "relates_to", "target": "SOS-2"},
        headers=auth,
    )
    assert r.status_code == 201

    assert _card(client, auth, project, "SOS-1")["relations"]["relates_to"] == ["SOS-2"]
    assert _card(client, auth, project, "SOS-2")["relations"]["relates_to"] == ["SOS-1"]


def test_list_card_relations_duplicate_of(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "duplicate_of", "target": "SOS-2"},
        headers=auth,
    )
    assert r.status_code == 201

    assert _card(client, auth, project, "SOS-1")["relations"]["duplicate_of"] == ["SOS-2"]
    assert _card(client, auth, project, "SOS-2")["relations"]["duplicated_by"] == ["SOS-1"]


def test_list_card_relations_match_detail_endpoint(client, auth, project):
    """De kaart (bulk) en de volle GET /items/{ref} (single) moeten dezelfde
    relaties tonen — het zijn twee losse code-paden (_relations_bulk vs.
    relations.for_item) die niet uit elkaar mogen drijven (spiegelt BETON-320)."""
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-2"},
        headers=auth,
    )
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "relates_to", "target": "SOS-3"},
        headers=auth,
    )

    card = _card(client, auth, project, "SOS-1")["relations"]
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()["relations"]
    assert card == detail


def test_stream_snapshot_carries_relations(client, auth, conn, project):
    """De SSE-item-snapshot (BETON-186) draagt dezelfde relaties als de kaart —
    anders wist een live event de relatierij i.p.v. hem te zetten (BETON-344)."""
    from betonning.repo import items as items_repo
    from betonning.repo import relations as relations_repo

    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-2"},
        headers=auth,
    )
    row = items_repo.get_by_ref(conn, "SOS-1")
    full = items_repo.serialize(conn, row)
    full["relations"] = relations_repo.for_item(conn, row["id"])
    snapshot = items_repo.compact(full)
    assert snapshot["relations"]["blocks"] == ["SOS-2"]


# --- BETON-344: "subtaak van" op de kaart (parent zit niet in relations) ----


def test_list_card_carries_parent(client, auth, project):
    """`parent` komt uit `items.parent_id`, niet de relations-tabel — eigen
    self-join in `_COMPACT_SELECT`, dus los van `_relations_bulk` getest."""
    r = _create(client, auth, project, title="kind", parent="SOS-1")
    assert r.status_code == 201
    child = r.json()["ref"]

    assert _card(client, auth, project, child)["parent"] == "SOS-1"


def test_list_card_parent_null_for_top_level_item(client, auth, project):
    assert _card(client, auth, project, "SOS-1")["parent"] is None


def test_list_card_parent_matches_detail_endpoint(client, auth, project):
    r = _create(client, auth, project, title="kind", parent="SOS-1")
    child = r.json()["ref"]

    assert _card(client, auth, project, child)["parent"] == "SOS-1"
    assert client.get(f"/api/v1/items/{child}", headers=auth).json()["parent"] == "SOS-1"


def test_assigned_open_card_carries_parent(client, auth, conn, project):
    """`list_assigned_open` (BETON-55, eigen hand-geschreven SQL naast
    `_COMPACT_SELECT`) moet dezelfde `parent_seq`-join hebben — anders breekt
    `_compact_rows` op de ontbrekende kolom voor dit pad."""
    from betonning.repo import items as items_repo
    from betonning.repo import users as users_repo

    r = _create(client, auth, project, title="kind", parent="SOS-1", assignee="person")
    assert r.status_code == 201
    child = r.json()["ref"]

    person = users_repo.get_by_handle(conn, "person")
    open_items = items_repo.list_assigned_open(conn, person["id"])
    row = next(i for i in open_items if i["ref"] == child)
    assert row["parent"] == "SOS-1"


# BETON-471: relations_detail draagt per relatie ref/titel/state; `relations`
# en `children` blijven ongewijzigd voor MCP/agents.
def test_relations_detail_has_title_and_state(client, auth, project):
    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "blocks", "target": "SOS-2"},
        headers=auth,
    )
    client.patch("/api/v1/items/SOS-2", json={"title": "Tweede"}, headers=auth)
    data = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert data["relations"]["blocks"] == ["SOS-2"]
    [d] = data["relations_detail"]["blocks"]
    assert d["ref"] == "SOS-2" and d["title"] == "Tweede" and d["state"]
    other = client.get("/api/v1/items/SOS-2", headers=auth).json()
    assert [x["ref"] for x in other["relations_detail"]["blocked_by"]] == ["SOS-1"]


def test_children_detail_has_title(client, auth, project):
    client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "Kind", "parent": "SOS-1"},
        headers=auth,
    )
    data = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert data["children"] == ["SOS-4"]
    assert data["children_detail"][0]["title"] == "Kind"
    assert data["children_detail"][0]["ref"] == "SOS-4"


def test_relations_query_count_independent_of_relation_count(conn, client, auth, project):
    from betonning.repo import items as items_repo
    from betonning.repo import relations as relations_repo

    def count(item_id):
        queries: list[str] = []
        conn.set_trace_callback(queries.append)
        try:
            relations_repo.for_item_detail(conn, item_id)
            relations_repo.for_item(conn, item_id)
        finally:
            conn.set_trace_callback(None)
        return len(queries)

    client.post(
        "/api/v1/items/SOS-1/relations",
        json={"type": "relates_to", "target": "SOS-2"},
        headers=auth,
    )
    item1 = items_repo.get_by_ref(conn, "SOS-1")
    few = count(item1["id"])
    for _ in range(6):
        r = client.post("/api/v1/projects/SOS/items", json={"title": "n"}, headers=auth)
        client.post(
            "/api/v1/items/SOS-1/relations",
            json={"type": "relates_to", "target": r.json()["ref"]},
            headers=auth,
        )
    assert len(relations_repo.for_item_detail(conn, item1["id"])["relates_to"]) == 7
    assert count(item1["id"]) == few
