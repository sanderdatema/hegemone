"""Gearchiveerde projecten vallen uit de cross-project reads (BETON-413).

De regel (al vastgelegd in `repo/overview.py`): een read die over ÁLLE
projecten sweept laat gearchiveerde projecten weg; een read die één project
expliciet noemt niet — anders wordt archiveren eenrichtingsverkeer en is de
historie niet meer te lezen. Onderaan staan de tegentesten voor die tweede
soort.

Elke test zet hetzelfde toneel: twee projecten, waarvan er één gearchiveerd is,
met in beide een item. Het item van het levende project hoort erin te zitten,
dat van het gearchiveerde niet.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from betonning.repo import users as users_repo
from conftest import _create


@pytest.fixture
def two_projects(client: TestClient, auth: dict) -> tuple[str, str]:
    """LIVE en OUD; archiveer OUD pas na het opbouwen van de testinhoud."""
    for key in ("LIVE", "OUD"):
        client.post("/api/v1/projects", json={"key": key, "name": key}, headers=auth)
    return "LIVE", "OUD"


@pytest.fixture
def claude_auth(conn: sqlite3.Connection) -> dict:
    _, key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent", agent_type="coding"
    )
    return {"Authorization": f"Bearer {key}"}


# --- /me/issues -----------------------------------------------------------


def test_my_issues_skips_archived_project(
    client: TestClient, auth: dict, claude_auth: dict, two_projects
):
    live, oud = two_projects
    _create(client, auth, live, title="echt werk", assignee="claude")
    _create(client, auth, oud, title="dood werk", assignee="claude")

    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    refs = [i["ref"] for i in client.get("/api/v1/me/issues", headers=claude_auth).json()]
    assert refs == ["LIVE-1"]


def test_my_issues_returns_it_again_after_restore(
    client: TestClient, auth: dict, claude_auth: dict, two_projects
):
    """Archiveren is omkeerbaar: het filter zit in de query, niet in de data."""
    live, oud = two_projects
    _create(client, auth, oud, title="dood werk", assignee="claude")
    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    assert client.get("/api/v1/me/issues", headers=claude_auth).json() == []

    client.post(f"/api/v1/projects/{oud}/restore", headers=auth)
    refs = [i["ref"] for i in client.get("/api/v1/me/issues", headers=claude_auth).json()]
    assert refs == ["OUD-1"]


# --- /inbox ---------------------------------------------------------------


def test_inbox_skips_events_from_archived_project(
    client: TestClient, auth: dict, claude_auth: dict, two_projects
):
    """De poort zit in de SQL, niet in de Python-lus: anders vult een
    gearchiveerd project nog steeds het scan-venster."""
    live, oud = two_projects
    for key in (live, oud):
        ref = _create(client, auth, key, title="iets").json()["ref"]
        # Toewijzen ná het aanmaken: pas de assignee-diff op `item.updated`
        # levert een inbox-reden ("assigned"), niet het aanmaken zelf.
        client.patch(f"/api/v1/items/{ref}", json={"assignee": "claude"}, headers=auth)

    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    inbox = client.get("/api/v1/inbox", headers=claude_auth).json()
    assert {e["ref"] for e in inbox["items"]} == {"LIVE-1"}


def test_due_entry_skips_archived_project(
    client: TestClient, auth: dict, claude_auth: dict, two_projects
):
    live, oud = two_projects
    _create(client, auth, live, title="echt", assignee="claude", due_date="2020-01-01")
    _create(client, auth, oud, title="dood", assignee="claude", due_date="2020-01-01")

    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    inbox = client.get("/api/v1/inbox", headers=claude_auth).json()
    due = [e for e in inbox["items"] if e["reason"] == "due"]
    assert [e["ref"] for e in due] == ["LIVE-1"]


def test_guardrail_concept_entry_skips_archived_project(
    client: TestClient, conn: sqlite3.Connection, auth: dict, claude_auth: dict,
    two_projects,
):
    """BETON-422: `concept_entries` is een cross-project sweep, dus
    `LIVE_PROJECT` hoort erin — anders blijft een gearchiveerd project om
    beslissingen vragen die niemand meer neemt."""
    live, oud = two_projects
    for key in (live, oud):
        _create(client, auth, key, title="draagt een concept")
        r = client.post(
            f"/api/v1/items/{key}-1/guardrail/propose",
            json={"guardrail_md": f"regel {key}"},
            headers=claude_auth,
        )
        assert r.status_code == 200

    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    inbox = client.get("/api/v1/inbox", headers=auth).json()
    concepts = [e for e in inbox["items"] if e["reason"] == "guardrail"]
    assert [e["ref"] for e in concepts] == [f"{live}-1"]


# --- /questions -----------------------------------------------------------


def test_open_questions_skips_archived_project(
    client: TestClient, auth: dict, claude_auth: dict, two_projects
):
    """Deze query had helemaal geen archief-poort, ook niet op item-niveau."""
    live, oud = two_projects
    for key in (live, oud):
        ref = _create(client, auth, key, title="iets", assignee="claude").json()["ref"]
        client.post(
            f"/api/v1/items/{ref}/comments",
            json={"body_md": "Welke kant op?", "kind": "question"},
            headers=auth,
        )

    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    open_qs = client.get("/api/v1/questions?open=true", headers=claude_auth).json()
    assert [q["item"]["ref"] for q in open_qs] == ["LIVE-1"]


def test_open_questions_skips_archived_item(
    client: TestClient, auth: dict, claude_auth: dict, two_projects
):
    """Ook het item-niveau ontbrak: een gearchiveerd ticket bleef om antwoord
    vragen."""
    live, _oud = two_projects
    ref = _create(client, auth, live, title="iets", assignee="claude").json()["ref"]
    client.post(
        f"/api/v1/items/{ref}/comments",
        json={"body_md": "Welke kant op?", "kind": "question"},
        headers=auth,
    )
    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    assert client.get("/api/v1/questions?open=true", headers=claude_auth).json()

    client.delete(f"/api/v1/items/{ref}", headers=auth)  # archiveert
    assert client.get("/api/v1/questions?open=true", headers=claude_auth).json() == []


# --- /search --------------------------------------------------------------


def test_search_skips_archived_project(client: TestClient, auth: dict, two_projects):
    live, oud = two_projects
    _create(client, auth, live, title="zeppelin in bedrijf")
    _create(client, auth, oud, title="zeppelin uit bedrijf")

    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    hits = client.get("/api/v1/search?q=zeppelin", headers=auth).json()
    assert [h["ref"] for h in hits] == ["LIVE-1"]


def test_search_substring_fallback_skips_archived_project(
    client: TestClient, auth: dict, two_projects
):
    """De substring-fallback (BETON-230) is een eigen tak en moet hetzelfde doen."""
    live, oud = two_projects
    _create(client, auth, live, title="luchtschiploods noord")
    _create(client, auth, oud, title="luchtschiploods zuid")

    # "chipl" is geen woord-prefix, dus FTS levert niets en de substring-tak
    # beslist; beide titels bevatten het fragment.
    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    hits = client.get("/api/v1/search?q=chipl", headers=auth).json()
    assert [h["ref"] for h in hits] == ["LIVE-1"]


def test_search_comment_hits_skip_archived_project(
    client: TestClient, auth: dict, two_projects
):
    """Comment-treffers (BETON-370) zijn de derde tak."""
    live, oud = two_projects
    for key in (live, oud):
        ref = _create(client, auth, key, title="iets").json()["ref"]
        client.post(
            f"/api/v1/items/{ref}/comments",
            json={"body_md": "over kortegolf gesproken"},
            headers=auth,
        )

    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    hits = client.get("/api/v1/search?q=kortegolf", headers=auth).json()
    assert [h["ref"] for h in hits] == ["LIVE-1"]


def test_search_include_archived_returns_them_again(
    client: TestClient, conn: sqlite3.Connection, auth: dict, two_projects
):
    """Eén schakelaar: `include_archived` haalt ze wél terug. Op de repo getoetst
    omdat `GET /search` die vlag (nog) niet als query-parameter aanbiedt."""
    from betonning.repo import items as items_repo

    _live, oud = two_projects
    _create(client, auth, oud, title="zeppelin uit bedrijf")

    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    assert items_repo.search(conn, "zeppelin") == []
    hits = items_repo.search(conn, "zeppelin", include_archived=True)
    assert [h["ref"] for h in hits] == ["OUD-1"]


def test_ref_candidates_skips_archived_project(
    client: TestClient, auth: dict, two_projects
):
    """Het `#`-menu (BETON-254) is ook een cross-project sweep."""
    live, oud = two_projects
    _create(client, auth, live, title="echt")
    _create(client, auth, oud, title="dood")

    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    hits = client.get(
        "/api/v1/ref-candidates", headers=auth, params={"q": "1", "project": live}
    ).json()
    assert [h["ref"] for h in hits] == ["LIVE-1"]

    hits = client.get(
        "/api/v1/ref-candidates", headers=auth, params={"q": "OUD"}
    ).json()
    assert hits == []


def test_full_ref_still_finds_a_ticket_in_an_archived_project(
    client: TestClient, auth: dict, two_projects
):
    """"OUD-1" noemt zijn project zelf — gerichte lookup, geen sweep. Een kaal
    nummer matcht over alle projecten en valt wél onder de poort."""
    _live, oud = two_projects
    _create(client, auth, oud, title="dood werk")

    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    hits = client.get("/api/v1/search?q=OUD-1", headers=auth).json()
    assert [h["ref"] for h in hits] == ["OUD-1"]

    assert client.get("/api/v1/search?q=1", headers=auth).json() == []


# --- tegentesten: expliciet gescopede reads blijven werken -----------------


def test_explicitly_scoped_reads_still_see_archived_project(
    client: TestClient, auth: dict, two_projects
):
    _live, oud = two_projects
    ref = _create(client, auth, oud, title="dood werk").json()["ref"]

    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    assert client.get(f"/api/v1/items/{ref}", headers=auth).status_code == 200
    items = client.get(f"/api/v1/projects/{oud}/items", headers=auth).json()
    assert [i["ref"] for i in items] == [ref]
    activity = client.get(f"/api/v1/projects/{oud}/activity", headers=auth).json()
    assert activity, "de historie van een gearchiveerd project blijft leesbaar"


# --- guardrails (BETON-420) -----------------------------------------------


def test_guardrail_in_archived_project_falls_out(
    client: TestClient, conn: sqlite3.Connection, auth: dict, two_projects
):
    """Een guardrail op een ticket in een gearchiveerd project telt niet mee in
    het plafond en wordt aan niemand meer aangeboden."""
    from betonning.repo import guardrails as guardrails_repo
    from betonning.repo import items as items_repo

    live, oud = two_projects
    for key in (live, oud):
        client.post(f"/api/v1/projects/{key}/labels", json={"name": "prompts"}, headers=auth)
        _create(client, auth, key, title="draagt de guardrail")
        _create(client, auth, key, title="draagt het label")
        client.post(f"/api/v1/items/{key}-2/labels/prompts", headers=auth)
        item = items_repo.get_by_ref(conn, f"{key}-1")
        guardrails_repo.set_guardrail(
            conn, item["id"], text=f"regel {key}", review_by="2099-01-01", set_by=None
        )

    live_id = conn.execute("SELECT id FROM projects WHERE key = ?", (live,)).fetchone()["id"]
    oud_id = conn.execute("SELECT id FROM projects WHERE key = ?", (oud,)).fetchone()["id"]
    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    assert guardrails_repo.project_wide_count(conn, live_id) == 1
    assert guardrails_repo.project_wide_count(conn, oud_id) == 0
    assert [g["ref"] for g in guardrails_repo.project_wide(conn, live_id)] == [f"{live}-1"]
    assert guardrails_repo.project_wide(conn, oud_id) == []

    assert client.post("/api/v1/projects/OUD/restore", headers=auth).status_code == 200
    # Gescoped: hetzelfde beeld via applicable_for_item.
    for key in (live, oud):
        item = items_repo.get_by_ref(conn, f"{key}-1")
        label = conn.execute(
            "SELECT l.id FROM labels l JOIN projects p ON p.id = l.project_id "
            "WHERE p.key = ? AND l.name = 'prompts'",
            (key,),
        ).fetchone()["id"]
        guardrails_repo.set_scope(conn, item["id"], [label])
    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204

    live_target = items_repo.get_by_ref(conn, f"{live}-2")
    oud_target = items_repo.get_by_ref(conn, f"{oud}-2")
    assert [g["ref"] for g in guardrails_repo.applicable_for_item(conn, live_target["id"])] == [
        f"{live}-1"
    ]
    assert guardrails_repo.applicable_for_item(conn, oud_target["id"]) == []


def test_guardrail_review_finder_skips_archived_project(
    client: TestClient, conn: sqlite3.Connection, auth: dict, two_projects
):
    """De zesde poll-query hangt aan `_eligibility_where()`; zonder die poort
    blijft triage reviewvragen stellen op een project dat weg is."""
    from betonning import triage_worker
    from betonning.repo import guardrails as guardrails_repo
    from betonning.repo import items as items_repo
    from betonning.repo import users as users_repo

    live, oud = two_projects
    triage, _ = users_repo.create(
        conn, handle="triage", display_name="Triage", kind="agent"
    )
    conn.commit()
    for key in (live, oud):
        client.put(f"/api/v1/projects/{key}/triage", json={"enabled": True}, headers=auth)
        _create(client, auth, key, title="met guardrail")
        item = items_repo.get_by_ref(conn, f"{key}-1")
        guardrails_repo.set_guardrail(
            conn, item["id"], text="regel", review_by="2020-01-01", set_by=None
        )

    assert client.delete("/api/v1/projects/OUD", headers=auth).status_code == 204
    found = triage_worker.find_guardrails_due_review(
        conn, triage_user_id=triage["id"], limit=10
    )
    assert found == [items_repo.get_by_ref(conn, f"{live}-1")["id"]]
