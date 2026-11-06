"""Server-side filtering op state, priority, label, assignee, q en limit."""

from __future__ import annotations

import pytest

from betonning.repo import users as users_repo


@pytest.fixture
def seeded(client, auth, conn):
    """Project SOS met een handvol items, een tweede user en labels."""
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)

    # Tweede user voor assignee-filter.
    users_repo.create(conn, handle="claude", display_name="Claude", kind="agent")

    def mk(title, **body):
        body["title"] = title
        return client.post("/api/v1/projects/SOS/items", json=body, headers=auth).json()

    a = mk("Fix login bug", state="todo", priority="high", assignee="claude")
    b = mk("Refactor betonning core", state="in-progress", priority="low")
    c = mk("Write docs", state="todo", priority="medium", assignee="person")

    # Labels rechtstreeks seeden (label-CRUD komt in fase 2).
    project_id = conn.execute("SELECT id FROM projects WHERE key='SOS'").fetchone()[
        "id"
    ]
    conn.execute(
        "INSERT INTO labels (project_id, name, color) VALUES (?, 'opus', '#f00')",
        (project_id,),
    )
    label_id = conn.execute("SELECT id FROM labels WHERE name='opus'").fetchone()["id"]
    item_id = conn.execute(
        "SELECT id FROM items WHERE title = 'Refactor betonning core'"
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO item_labels (item_id, label_id) VALUES (?, ?)",
        (item_id, label_id),
    )
    return {"a": a, "b": b, "c": c}


def _refs(resp):
    return {i["ref"] for i in resp.json()}


def test_filter_by_state(client, auth, seeded):
    r = client.get("/api/v1/projects/SOS/items?state=todo", headers=auth)
    assert r.status_code == 200
    assert _refs(r) == {"SOS-1", "SOS-3"}


def test_filter_by_state_is_case_insensitive(client, auth, seeded):
    """BETON-35: ook de lijst-filter matcht case-insensitief (`Todo`/`TODO`)."""
    for value in ("Todo", "TODO"):
        r = client.get(f"/api/v1/projects/SOS/items?state={value}", headers=auth)
        assert r.status_code == 200
        assert _refs(r) == {"SOS-1", "SOS-3"}


def test_filter_by_assignee_is_case_insensitive(client, auth, seeded):
    r = client.get("/api/v1/projects/SOS/items?assignee=Claude", headers=auth)
    assert _refs(r) == {"SOS-1"}


def test_filter_by_priority(client, auth, seeded):
    r = client.get("/api/v1/projects/SOS/items?priority=high", headers=auth)
    assert _refs(r) == {"SOS-1"}


def test_filter_by_assignee(client, auth, seeded):
    r = client.get("/api/v1/projects/SOS/items?assignee=claude", headers=auth)
    assert _refs(r) == {"SOS-1"}


def test_filter_by_label(client, auth, seeded):
    r = client.get("/api/v1/projects/SOS/items?label=opus", headers=auth)
    assert _refs(r) == {"SOS-2"}


def test_filter_by_q_wordpart(client, auth, seeded):
    r = client.get("/api/v1/projects/SOS/items?q=refac", headers=auth)
    assert _refs(r) == {"SOS-2"}


def test_filter_by_q_bare_seq(client, auth, seeded):
    """BETON-187: enkel het ticketnummer vindt het ticket ook in project-scope,
    ook al komt het nummer nergens letterlijk in titel/omschrijving voor."""
    r = client.get("/api/v1/projects/SOS/items?q=2", headers=auth)
    assert _refs(r) == {"SOS-2"}


def test_filter_by_q_full_ref(client, auth, seeded):
    r = client.get("/api/v1/projects/SOS/items?q=SOS-2", headers=auth)
    assert _refs(r) == {"SOS-2"}


def test_filter_by_q_ref_other_project_empty(client, auth, seeded):
    """Een ref met een andere project-key hoort niet in déze project-scope."""
    r = client.get("/api/v1/projects/SOS/items?q=BRAND-2", headers=auth)
    assert _refs(r) == set()


def test_filter_by_q_seq_combined_with_other_filter(client, auth, seeded):
    """Ref/seq-match bypast de tekstmatch, maar de overige filters blijven gelden."""
    r = client.get("/api/v1/projects/SOS/items?q=2&state=todo", headers=auth)
    assert _refs(r) == set()  # SOS-2 staat in-progress, niet todo

    r = client.get("/api/v1/projects/SOS/items?q=1&state=todo", headers=auth)
    assert _refs(r) == {"SOS-1"}


def test_filter_by_q_seq_no_match_falls_back_to_text(client, auth, seeded):
    """Geen ticket met dat seq → gewone tekst-zoek mag alsnog matchen."""
    r = client.get("/api/v1/projects/SOS/items?q=999", headers=auth)
    assert _refs(r) == set()


def test_filter_by_q_nonsense_empty(client, auth, seeded):
    """BETON-230: een verzonnen term geeft 0 resultaten, geen fuzzy-ruis."""
    r = client.get("/api/v1/projects/SOS/items?q=poepie", headers=auth)
    assert _refs(r) == set()


def test_filter_by_q_midword_substring(client, auth, seeded):
    """BETON-230: een echte mid-word-substring ('eton' in 'betonning') matcht
    nog steeds via de substring-fallback, ook al is het geen FTS-prefix."""
    r = client.get("/api/v1/projects/SOS/items?q=eton", headers=auth)
    assert _refs(r) == {"SOS-2"}


def test_filter_combination(client, auth, seeded):
    r = client.get(
        "/api/v1/projects/SOS/items?state=todo&assignee=claude", headers=auth
    )
    assert _refs(r) == {"SOS-1"}


def test_filter_combination_empty(client, auth, seeded):
    r = client.get("/api/v1/projects/SOS/items?state=todo&priority=low", headers=auth)
    assert _refs(r) == set()


def test_limit(client, auth, seeded):
    r = client.get("/api/v1/projects/SOS/items?limit=1", headers=auth)
    assert len(r.json()) == 1


def test_list_unknown_project_404(client, auth, seeded):
    assert client.get("/api/v1/projects/NOPE/items", headers=auth).status_code == 404


def test_list_requires_auth(client, seeded):
    assert client.get("/api/v1/projects/SOS/items").status_code == 401


def test_compact_shape(client, auth, seeded):
    r = client.get("/api/v1/projects/SOS/items?state=todo", headers=auth)
    item = r.json()[0]
    assert set(item.keys()) == {
        "ref",
        "title",
        "state",
        "priority",
        "workload",
        "assignee",
        "labels",
        "children_done",
        "children_total",
        "deferred_until",
        "due_date",
        "milestone",
        "archived_at",
        "locked",
        "has_guardrail",  # BETON-420
        "has_guardrail_proposal",  # BETON-422
        "created_at",
        "last_activity_at",
        "has_open_question",
        "has_unread",
        "relations",  # BETON-344
        "parent",  # BETON-344
    }


# --- BETON-359: closed_limit / offset / state-counts ------------------------


@pytest.fixture
def closed_seeded(client, auth, conn):
    """Project GROOT met 5 items in 'done' (closed=1) en 2 in 'todo' (open).

    De done-items krijgen expliciete, oplopende `updated_at`-tijdstippen
    (rechtstreeks via SQL — anders vallen ze door snel-achter-elkaar aanmaken
    te dicht bij elkaar om de closed_limit-ordening betrouwbaar te toetsen).
    """
    client.post("/api/v1/projects", json={"key": "GROOT", "name": "GROOT"}, headers=auth)

    def mk(title, state):
        return client.post(
            "/api/v1/projects/GROOT/items", json={"title": title, "state": state}, headers=auth
        ).json()

    done = [mk(f"Done {i}", "done") for i in range(1, 6)]
    todo = [mk(f"Todo {i}", "todo") for i in range(1, 3)]

    # done[0] = oudste activiteit, done[4] = meest recente.
    for i, item in enumerate(done):
        item_id = conn.execute(
            "SELECT id FROM items WHERE title = ?", (item["title"],)
        ).fetchone()["id"]
        conn.execute(
            "UPDATE items SET updated_at = ? WHERE id = ?",
            (f"2026-01-0{i + 1}T00:00:00.000Z", item_id),
        )
    conn.commit()
    return {"done": done, "todo": todo}


def test_closed_limit_keeps_newest_n_per_closed_state(client, auth, closed_seeded):
    r = client.get("/api/v1/projects/GROOT/items?closed_limit=2", headers=auth)
    assert r.status_code == 200
    refs_by_title = {i["title"]: i["ref"] for i in r.json()}
    done = closed_seeded["done"]
    # Alleen de 2 nieuwste done-items (done[3], done[4]) blijven over.
    assert done[3]["title"] in refs_by_title
    assert done[4]["title"] in refs_by_title
    assert done[0]["title"] not in refs_by_title
    assert done[1]["title"] not in refs_by_title
    assert done[2]["title"] not in refs_by_title


def test_closed_limit_leaves_open_states_untouched(client, auth, closed_seeded):
    r = client.get("/api/v1/projects/GROOT/items?closed_limit=2", headers=auth)
    titles = {i["title"] for i in r.json()}
    for item in closed_seeded["todo"]:
        assert item["title"] in titles


def test_without_closed_limit_all_items_come_back(client, auth, closed_seeded):
    """None (het default) = ongewijzigd gedrag — bestaande aanroepers (MCP,
    REST zonder dit param) krijgen nog steeds alles."""
    r = client.get("/api/v1/projects/GROOT/items", headers=auth)
    assert len(r.json()) == 7


def test_state_and_closed_limit_combine(client, auth, closed_seeded):
    """closed_limit filtert per state — met een expliciete state-filter erbij
    blijft alleen die state over, wél begrensd."""
    r = client.get("/api/v1/projects/GROOT/items?state=done&closed_limit=2", headers=auth)
    assert len(r.json()) == 2


def test_offset_paginates_within_a_filtered_state(client, auth, closed_seeded):
    r_all = client.get("/api/v1/projects/GROOT/items?state=done", headers=auth)
    all_refs = [i["ref"] for i in r_all.json()]
    assert len(all_refs) == 5

    r_page = client.get(
        "/api/v1/projects/GROOT/items?state=done&limit=2&offset=2", headers=auth
    )
    page_refs = [i["ref"] for i in r_page.json()]
    assert page_refs == all_refs[2:4]


def test_state_counts(client, auth, closed_seeded):
    r = client.get("/api/v1/projects/GROOT/state-counts", headers=auth)
    assert r.status_code == 200
    counts = r.json()
    assert counts["done"] == 5
    assert counts["todo"] == 2


def test_state_counts_excludes_archived(client, auth, closed_seeded):
    ref = closed_seeded["done"][0]["ref"]
    client.delete(f"/api/v1/items/{ref}", headers=auth)  # archiveert (BETON-59)

    r = client.get("/api/v1/projects/GROOT/state-counts", headers=auth)
    assert r.json()["done"] == 4

    r_incl = client.get("/api/v1/projects/GROOT/state-counts?archived=true", headers=auth)
    assert r_incl.json()["done"] == 5


def test_closed_limit_requires_positive_value(client, auth, closed_seeded):
    r = client.get("/api/v1/projects/GROOT/items?closed_limit=0", headers=auth)
    assert r.status_code == 422
