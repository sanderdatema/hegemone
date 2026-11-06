"""Command-schema + deterministische uitvoerder voor chat-met-triage (BETON-120)."""

from __future__ import annotations

import pytest

from betonning import triage_commands as tc
from betonning.repo import access
from betonning.repo import items as items_repo
from betonning.repo import labels as labels_repo
from betonning.repo import projects as projects_repo
from betonning.repo import relations as relations_repo


@pytest.fixture
def setup(conn, seed_cast):
    p = projects_repo.create(conn, key="SOS", name="SOS")
    return {
        "project_id": p["id"],
        "triage_id": seed_cast["triage"]["id"],
        "claude_id": seed_cast["claude"]["id"],
        "smid_id": seed_cast["smid"]["id"],
    }


def _make_item(conn, project_id, title, *, state=None):
    seq = projects_repo.next_seq(conn, project_id)
    conn.execute(
        "INSERT INTO items (project_id, seq, title) VALUES (?, ?, ?)",
        (project_id, seq, title),
    )
    conn.commit()
    key = conn.execute("SELECT key FROM projects WHERE id = ?", (project_id,)).fetchone()["key"]
    item = items_repo.get_by_ref(conn, f"{key}-{seq}")
    if state is not None:
        st = conn.execute(
            "SELECT id FROM states WHERE project_id = ? AND name = ?", (project_id, state)
        ).fetchone()
        items_repo.update(conn, item["id"], {"state_id": st["id"]})
    return items_repo.get(conn, item["id"])


def _ref(row, key="SOS") -> str:
    return f"{key}-{row['seq']}"


# --- resolve_targets ---------------------------------------------------------


def test_resolve_targets_by_explicit_refs(conn, setup):
    item = _make_item(conn, setup["project_id"], "Een item")
    targets = tc.resolve_targets(conn, setup["project_id"], {"refs": [_ref(item)]})
    assert [t["id"] for t in targets] == [item["id"]]


def test_resolve_targets_unknown_ref_raises(conn, setup):
    with pytest.raises(ValueError, match="Onbekend item"):
        tc.resolve_targets(conn, setup["project_id"], {"refs": ["SOS-999"]})


def test_resolve_targets_ref_from_other_project_raises(conn, setup):
    other = projects_repo.create(conn, key="SKY", name="Sky")
    conn.commit()
    item = _make_item(conn, other["id"], "Elders")
    with pytest.raises(ValueError, match="hoort niet bij dit project"):
        tc.resolve_targets(conn, setup["project_id"], {"refs": [f"SKY-{item['seq']}"]})


def test_resolve_targets_filter_state_closed(conn, setup):
    open_item = _make_item(conn, setup["project_id"], "Open")
    done_item = _make_item(conn, setup["project_id"], "Klaar", state="done")
    targets = tc.resolve_targets(
        conn, setup["project_id"], {"filter": {"state_closed": True}}
    )
    ids = {t["id"] for t in targets}
    assert ids == {done_item["id"]}
    assert open_item["id"] not in ids


def test_resolve_targets_filter_state_open(conn, setup):
    open_item = _make_item(conn, setup["project_id"], "Open", state="todo")
    done_item = _make_item(conn, setup["project_id"], "Klaar", state="done")
    targets = tc.resolve_targets(
        conn, setup["project_id"], {"filter": {"state_open": True}}
    )
    ids = {t["id"] for t in targets}
    assert open_item["id"] in ids
    assert done_item["id"] not in ids


def test_resolve_targets_filter_state_by_name(conn, setup):
    todo_item = _make_item(conn, setup["project_id"], "Te doen", state="todo")
    done_item = _make_item(conn, setup["project_id"], "Klaar", state="done")
    targets = tc.resolve_targets(conn, setup["project_id"], {"filter": {"state": "todo"}})
    assert {t["id"] for t in targets} == {todo_item["id"]}
    assert done_item["id"] not in {t["id"] for t in targets}


def test_resolve_targets_filter_updated_before_days(conn, setup):
    old_item = _make_item(conn, setup["project_id"], "Oud", state="done")
    conn.execute(
        "UPDATE items SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now','-40 days') "
        "WHERE id = ?",
        (old_item["id"],),
    )
    recent_item = _make_item(conn, setup["project_id"], "Recent", state="done")
    conn.commit()
    targets = tc.resolve_targets(
        conn, setup["project_id"],
        {"filter": {"state_closed": True, "updated_before_days": 30}},
    )
    ids = {t["id"] for t in targets}
    assert ids == {old_item["id"]}
    assert recent_item["id"] not in ids


def test_resolve_targets_filter_excludes_archived_by_default(conn, setup):
    item = _make_item(conn, setup["project_id"], "Weg", state="done")
    items_repo.archive(conn, item["id"])
    targets = tc.resolve_targets(
        conn, setup["project_id"], {"filter": {"state_closed": True}}
    )
    assert item["id"] not in {t["id"] for t in targets}


def test_resolve_targets_include_archived_for_restore(conn, setup):
    item = _make_item(conn, setup["project_id"], "Weg")
    items_repo.archive(conn, item["id"])
    targets = tc.resolve_targets(
        conn, setup["project_id"], {"refs": [_ref(item)]}, include_archived=True
    )
    assert [t["id"] for t in targets] == [item["id"]]


def test_resolve_targets_filter_label_and_assignee(conn, setup):
    item = _make_item(conn, setup["project_id"], "Met label")
    label = labels_repo.create(conn, project_id=setup["project_id"], name="bug")
    labels_repo.add_to_item(conn, item["id"], label["id"])
    items_repo.update(conn, item["id"], {"assignee_id": setup["claude_id"]})
    other = _make_item(conn, setup["project_id"], "Zonder label")

    by_label = tc.resolve_targets(conn, setup["project_id"], {"filter": {"label": "bug"}})
    assert {t["id"] for t in by_label} == {item["id"]}

    by_assignee = tc.resolve_targets(
        conn, setup["project_id"], {"filter": {"assignee": "claude"}}
    )
    assert {t["id"] for t in by_assignee} == {item["id"]}
    assert other["id"] not in {t["id"] for t in by_assignee}


# --- validate -----------------------------------------------------------------


def test_validate_unknown_verb(conn, setup):
    cmd = tc.Command(verb="hard_delete", project_id=setup["project_id"])
    errors = tc.validate(conn, cmd)
    assert any("Onbekend commando" in e for e in errors)


def test_validate_unknown_project(conn, setup):
    cmd = tc.Command(verb="archive", project_id=999999, selector={"refs": ["SOS-1"]})
    errors = tc.validate(conn, cmd)
    assert any("Onbekend project" in e for e in errors)


def test_validate_create_item_requires_title(conn, setup):
    cmd = tc.Command(verb="create_item", project_id=setup["project_id"], params={})
    errors = tc.validate(conn, cmd)
    assert any("titel" in e for e in errors)


def test_validate_create_item_with_title_is_clean(conn, setup):
    cmd = tc.Command(
        verb="create_item", project_id=setup["project_id"], params={"title": "Nieuw"}
    )
    assert tc.validate(conn, cmd) == []


def test_validate_requires_selector_for_mutating_verbs(conn, setup):
    cmd = tc.Command(verb="archive", project_id=setup["project_id"])
    errors = tc.validate(conn, cmd)
    assert any("selector" in e for e in errors)


def test_validate_no_matching_items(conn, setup):
    cmd = tc.Command(
        verb="archive", project_id=setup["project_id"],
        selector={"filter": {"state_closed": True}},
    )
    errors = tc.validate(conn, cmd)
    assert any("matcht" in e for e in errors)


def test_validate_cross_project_ref_rejected(conn, setup):
    other = projects_repo.create(conn, key="SKY", name="Sky")
    conn.commit()
    item = _make_item(conn, other["id"], "Elders")
    cmd = tc.Command(
        verb="archive", project_id=setup["project_id"],
        selector={"refs": [f"SKY-{item['seq']}"]},
    )
    errors = tc.validate(conn, cmd)
    assert any("hoort niet bij dit project" in e for e in errors)


def test_validate_set_state_unknown_state(conn, setup):
    item = _make_item(conn, setup["project_id"], "Item")
    cmd = tc.Command(
        verb="set_state", project_id=setup["project_id"],
        selector={"refs": [_ref(item)]}, params={"state": "nonexistent"},
    )
    errors = tc.validate(conn, cmd)
    assert any("Onbekende state" in e for e in errors)


def test_validate_set_priority_invalid(conn, setup):
    item = _make_item(conn, setup["project_id"], "Item")
    cmd = tc.Command(
        verb="set_priority", project_id=setup["project_id"],
        selector={"refs": [_ref(item)]}, params={"priority": "banana"},
    )
    errors = tc.validate(conn, cmd)
    assert any("priority" in e for e in errors)


def test_validate_set_assignee_respects_beton_123_access(conn, setup):
    """BETON-123: een agent zonder 'assign'-toegang op dit project mag niet
    worden toegewezen, ook niet via chat-commando."""
    access.set_type_access(conn, setup["project_id"], "hermes", "none")
    conn.commit()
    item = _make_item(conn, setup["project_id"], "Item")
    cmd = tc.Command(
        verb="set_assignee", project_id=setup["project_id"],
        selector={"refs": [_ref(item)]}, params={"assignee": "smid"},
    )
    errors = tc.validate(conn, cmd)
    assert any("mag niet toegewezen worden" in e for e in errors)


def test_validate_set_assignee_allows_coding_agent(conn, setup):
    access.set_type_access(conn, setup["project_id"], "hermes", "none")
    conn.commit()
    item = _make_item(conn, setup["project_id"], "Item")
    cmd = tc.Command(
        verb="set_assignee", project_id=setup["project_id"],
        selector={"refs": [_ref(item)]}, params={"assignee": "claude"},
    )
    assert tc.validate(conn, cmd) == []


def test_validate_add_relation_unknown_type_and_target(conn, setup):
    item = _make_item(conn, setup["project_id"], "Item")
    cmd = tc.Command(
        verb="add_relation", project_id=setup["project_id"],
        selector={"refs": [_ref(item)]},
        params={"relation_type": "bogus", "target_ref": "SOS-999"},
    )
    errors = tc.validate(conn, cmd)
    assert any("relatietype" in e for e in errors)
    assert any("doel-item" in e for e in errors)


# --- execute ------------------------------------------------------------------


def test_execute_archive_single_with_fanout(conn, setup):
    item = _make_item(conn, setup["project_id"], "Item")
    events_before = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    refs = tc.execute(
        conn,
        tc.Command(verb="archive", project_id=setup["project_id"], selector={"refs": [_ref(item)]}),
        setup["triage_id"],
        fanout=True,
    )
    assert refs == [_ref(item)]
    assert items_repo.get(conn, item["id"])["archived_at"] is not None
    events_after = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    assert events_after == events_before + 1


def test_execute_bulk_archive_writes_events_without_fanout(conn, setup):
    a = _make_item(conn, setup["project_id"], "A", state="done")
    conn.execute(
        "UPDATE items SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now','-40 days') "
        "WHERE id = ?",
        (a["id"],),
    )
    b = _make_item(conn, setup["project_id"], "B", state="done")
    conn.execute(
        "UPDATE items SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now','-40 days') "
        "WHERE id = ?",
        (b["id"],),
    )
    conn.commit()

    deliveries_before = conn.execute(
        "SELECT COUNT(*) AS n FROM webhook_deliveries"
    ).fetchone()["n"]
    events_before = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]

    refs = tc.execute(
        conn,
        tc.Command(
            verb="archive", project_id=setup["project_id"],
            selector={"filter": {"state_closed": True, "updated_before_days": 30}},
        ),
        setup["triage_id"],
        fanout=False,
    )
    assert set(refs) == {_ref(a), _ref(b)}
    assert items_repo.get(conn, a["id"])["archived_at"] is not None
    assert items_repo.get(conn, b["id"])["archived_at"] is not None

    events_after = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    assert events_after == events_before + 2  # audit blijft compleet

    deliveries_after = conn.execute(
        "SELECT COUNT(*) AS n FROM webhook_deliveries"
    ).fetchone()["n"]
    assert deliveries_after == deliveries_before  # geen fanout bij bulk


def test_execute_restore(conn, setup):
    item = _make_item(conn, setup["project_id"], "Item")
    items_repo.archive(conn, item["id"])
    refs = tc.execute(
        conn,
        tc.Command(verb="restore", project_id=setup["project_id"], selector={"refs": [_ref(item)]}),
        setup["triage_id"],
        fanout=True,
    )
    assert refs == [_ref(item)]
    assert items_repo.get(conn, item["id"])["archived_at"] is None


def test_execute_set_state(conn, setup):
    item = _make_item(conn, setup["project_id"], "Item")
    tc.execute(
        conn,
        tc.Command(
            verb="set_state", project_id=setup["project_id"],
            selector={"refs": [_ref(item)]}, params={"state": "done"},
        ),
        setup["triage_id"], fanout=True,
    )
    data = items_repo.serialize(conn, items_repo.get(conn, item["id"]))
    assert data["state"] == "done"


def test_execute_set_assignee(conn, setup):
    item = _make_item(conn, setup["project_id"], "Item")
    tc.execute(
        conn,
        tc.Command(
            verb="set_assignee", project_id=setup["project_id"],
            selector={"refs": [_ref(item)]}, params={"assignee": "claude"},
        ),
        setup["triage_id"], fanout=True,
    )
    data = items_repo.serialize(conn, items_repo.get(conn, item["id"]))
    assert data["assignee"] == "claude"


def test_execute_add_and_remove_label(conn, setup):
    item = _make_item(conn, setup["project_id"], "Item")
    tc.execute(
        conn,
        tc.Command(
            verb="add_label", project_id=setup["project_id"],
            selector={"refs": [_ref(item)]}, params={"label": "bug"},
        ),
        setup["triage_id"], fanout=True,
    )
    data = items_repo.serialize(conn, items_repo.get(conn, item["id"]))
    assert "bug" in data["labels"]

    tc.execute(
        conn,
        tc.Command(
            verb="remove_label", project_id=setup["project_id"],
            selector={"refs": [_ref(item)]}, params={"label": "bug"},
        ),
        setup["triage_id"], fanout=True,
    )
    data = items_repo.serialize(conn, items_repo.get(conn, item["id"]))
    assert "bug" not in data["labels"]


def test_execute_add_relation(conn, setup):
    a = _make_item(conn, setup["project_id"], "A")
    b = _make_item(conn, setup["project_id"], "B")
    tc.execute(
        conn,
        tc.Command(
            verb="add_relation", project_id=setup["project_id"],
            selector={"refs": [_ref(a)]},
            params={"relation_type": "blocks", "target_ref": _ref(b)},
        ),
        setup["triage_id"], fanout=True,
    )
    rels = relations_repo.for_item(conn, a["id"])
    assert _ref(b) in rels["blocks"]


def test_execute_create_item(conn, setup):
    refs = tc.execute(
        conn,
        tc.Command(
            verb="create_item", project_id=setup["project_id"],
            params={"title": "Vers ticket"},
        ),
        setup["triage_id"], fanout=True,
    )
    assert len(refs) == 1
    item = items_repo.get_by_ref(conn, refs[0])
    assert item["title"] == "Vers ticket"
    assert item["created_by"] == setup["triage_id"]


@pytest.fixture(autouse=True)
def legacy_dutch_chat_contract(monkeypatch):
    """De bestaande Nederlandstalige chat-/validatiecontracten blijven expliciet."""
    monkeypatch.setenv('HEGEMONE_LANGUAGE', 'nl')
