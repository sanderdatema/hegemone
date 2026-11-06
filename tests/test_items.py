"""Items: aanmaken, ophalen op ref, updaten, sequence-nummering."""

from __future__ import annotations

import json

import pytest

from conftest import _create


@pytest.fixture
def project(project, conn):
    # BETON-303: de parent-close-suggestie/umbrella-auto-close komt op naam van
    # `triage` — zonder die user in de fixture wordt de comment overgeslagen.
    from betonning.repo import users as users_repo

    if users_repo.get_by_handle(conn, "triage") is None:
        users_repo.create(conn, handle="triage", display_name="Triage", kind="agent")
        conn.commit()
    return project


def test_create_item_defaults(client, auth, project):
    r = _create(client, auth, project, title="Eerste ticket")
    assert r.status_code == 201
    body = r.json()
    assert body["ref"] == "SOS-1"
    assert body["title"] == "Eerste ticket"
    assert body["state"] == "backlog"  # default state
    assert body["priority"] == "none"
    assert body["created_by"] == "person"


def test_create_item_empty_strings_niet_gezet(client, auth, project):
    """BETON-160: lege strings op create betekenen "niet gezet", niet een
    onbekende-user/state/parent/milestone-fout (spiegelt het PATCH-pad)."""
    r = _create(
        client,
        auth,
        project,
        title="Leeg overal",
        state="",
        assignee="",
        parent="",
        milestone="",
    )
    assert r.status_code == 201
    body = r.json()
    assert body["state"] == "backlog"  # default state, niet leeg → fout
    assert body["assignee"] is None
    assert body["parent"] is None
    assert body["milestone"] is None


def test_list_includes_created_at(client, auth, project):
    """BETON-30: de compacte lijst draagt created_at zodat de UI het op de kaart
    kan tonen."""
    _create(client, auth, project, title="Met datum")
    items = client.get(f"/api/v1/projects/{project}/items", headers=auth).json()
    assert items and items[0]["created_at"]


def test_sequence_increments_per_project(client, auth, project):
    r1 = _create(client, auth, project, title="a")
    r2 = _create(client, auth, project, title="b")
    assert r1.json()["ref"] == "SOS-1"
    assert r2.json()["ref"] == "SOS-2"


def test_get_item_by_ref(client, auth, project):
    _create(client, auth, project, title="Detail")
    r = client.get("/api/v1/items/SOS-1", headers=auth)
    assert r.status_code == 200
    assert r.json()["ref"] == "SOS-1"
    assert r.json()["children"] == []


@pytest.mark.parametrize("ref", ["SOS-1", "sos-1", "SoS-1", "sOs-1"])
def test_get_item_by_ref_case_insensitive(client, auth, project, ref):
    """Refs zijn case-insensitief (BETON-12): elke schrijfwijze resolvet gelijk."""
    _create(client, auth, project, title="Detail")
    r = client.get(f"/api/v1/items/{ref}", headers=auth)
    assert r.status_code == 200
    assert r.json()["ref"] == "SOS-1"  # canoniek uppercase in de respons


def test_get_unknown_item_404(client, auth, project):
    assert client.get("/api/v1/items/SOS-999", headers=auth).status_code == 404


def test_get_invalid_ref_404(client, auth, project):
    assert client.get("/api/v1/items/garbage", headers=auth).status_code == 404


def test_get_unknown_project_ref_404(client, auth, project):
    assert client.get("/api/v1/items/NOPE-1", headers=auth).status_code == 404


def test_item_endpoints_require_auth(client, project):
    assert client.get("/api/v1/items/SOS-1").status_code == 401


def test_create_with_state_and_priority(client, auth, project):
    r = _create(client, auth, project, title="x", state="todo", priority="high")
    assert r.status_code == 201
    assert r.json()["state"] == "todo"
    assert r.json()["priority"] == "high"


def test_create_with_unknown_state_400(client, auth, project):
    r = _create(client, auth, project, title="x", state="nonexistent")
    assert r.status_code == 400


def test_create_with_unknown_assignee_400(client, auth, project):
    r = _create(client, auth, project, title="x", assignee="ghost")
    assert r.status_code == 400


def test_patch_updates_fields(client, auth, project):
    _create(client, auth, project, title="x")
    r = client.patch(
        "/api/v1/items/SOS-1",
        json={"state": "in-progress", "priority": "urgent", "title": "hernoemd"},
        headers=auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "in-progress"
    assert body["priority"] == "urgent"
    assert body["title"] == "hernoemd"


def test_patch_to_completed_sets_completed_at(client, auth, project):
    _create(client, auth, project, title="x")
    r = client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=auth)
    assert r.json()["completed_at"] is not None


def test_patch_assignee_and_clear(client, auth, project):
    _create(client, auth, project, title="x")
    r = client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    assert r.json()["assignee"] == "person"
    r = client.patch("/api/v1/items/SOS-1", json={"assignee": ""}, headers=auth)
    assert r.json()["assignee"] is None


def test_patch_parent_sets_child(client, auth, project):
    _create(client, auth, project, title="parent")
    _create(client, auth, project, title="child")
    r = client.patch("/api/v1/items/SOS-2", json={"parent": "SOS-1"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["parent"] == "SOS-1"
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert detail["children"] == ["SOS-2"]


def test_children_detail_includes_state(client, auth, project):
    """BETON-203: children_detail draagt de state van elk kind mee (naast de
    ref-only `children`), zodat de UI de subtakenlijst per status kan kleuren."""
    _create(client, auth, project, title="parent")
    _create(client, auth, project, title="child")
    client.patch("/api/v1/items/SOS-2", json={"parent": "SOS-1"}, headers=auth)
    client.patch("/api/v1/items/SOS-2", json={"state": "in-progress"}, headers=auth)
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert detail["children_detail"] == [
        {"ref": "SOS-2", "title": "child", "state": "in-progress"}
    ]  # titel erbij: BETON-471


def test_patch_unknown_item_404(client, auth, project):
    r = client.patch("/api/v1/items/SOS-999", json={"priority": "low"}, headers=auth)
    assert r.status_code == 404


# --- Optimistic concurrency (BETON-44) ------------------------------------


def test_patch_without_precondition_is_last_writer_wins(client, auth, project):
    """Zonder precondition blijft het oude gedrag: gewoon 200."""
    _create(client, auth, project, title="x")
    r = client.patch("/api/v1/items/SOS-1", json={"priority": "high"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["priority"] == "high"


def test_patch_stale_expected_updated_at_conflicts(client, auth, project):
    """Een verouderd expected_updated_at → 409 met het actuele item in de body."""
    _create(client, auth, project, title="x")
    r = client.patch(
        "/api/v1/items/SOS-1",
        json={"priority": "high", "expected_updated_at": "1999-01-01T00:00:00.000Z"},
        headers=auth,
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["item"]["ref"] == "SOS-1"
    # Niets gewijzigd: priority staat nog op de oude waarde.
    fresh = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert fresh["priority"] == "none"


def test_patch_matching_expected_updated_at_succeeds(client, auth, project):
    """Een kloppend expected_updated_at laat de PATCH normaal door."""
    created = _create(client, auth, project, title="x").json()
    r = client.patch(
        "/api/v1/items/SOS-1",
        json={"priority": "high", "expected_updated_at": created["updated_at"]},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["priority"] == "high"


def test_concurrent_double_patch_second_conflicts(client, auth, project):
    """Twee agents lezen hetzelfde updated_at; de eerste PATCH wint, de tweede
    (met hetzelfde, nu verouderde, token) krijgt 409."""
    created = _create(client, auth, project, title="x").json()
    token = created["updated_at"]

    first = client.patch(
        "/api/v1/items/SOS-1",
        json={"title": "door agent A", "expected_updated_at": token},
        headers=auth,
    )
    assert first.status_code == 200
    assert first.json()["updated_at"] != token  # token is nu verouderd

    second = client.patch(
        "/api/v1/items/SOS-1",
        json={"title": "door agent B", "expected_updated_at": token},
        headers=auth,
    )
    assert second.status_code == 409
    assert second.json()["error_code"] == "ticket_changed"
    assert second.json()["detail"]["item"]["title"] == "door agent A"
    assert (
        client.get("/api/v1/items/SOS-1", headers=auth).json()["title"]
        == "door agent A"
    )


def test_patch_if_match_header_conflicts(client, auth, project):
    """De If-Match-header werkt als precondition en wint van het body-veld."""
    _create(client, auth, project, title="x")
    r = client.patch(
        "/api/v1/items/SOS-1",
        json={"priority": "high"},
        headers={**auth, "If-Match": "1999-01-01T00:00:00.000Z"},
    )
    assert r.status_code == 409


def test_patch_if_match_header_matches(client, auth, project):
    """If-Match met het actuele updated_at → 200."""
    created = _create(client, auth, project, title="x").json()
    r = client.patch(
        "/api/v1/items/SOS-1",
        json={"priority": "high"},
        headers={**auth, "If-Match": created["updated_at"]},
    )
    assert r.status_code == 200
    assert r.json()["priority"] == "high"


# --- BETON-53: due_date ---------------------------------------------------


def test_create_with_due_date(client, auth, project):
    """Een item kan bij aanmaken een streefdatum krijgen."""
    r = _create(client, auth, project, title="Met due", due_date="2030-06-01")
    assert r.status_code == 201
    assert r.json()["due_date"] == "2030-06-01"


def test_due_date_defaults_none(client, auth, project):
    r = _create(client, auth, project, title="Zonder due")
    assert r.json()["due_date"] is None


def test_patch_sets_and_clears_due_date(client, auth, project):
    """due_date zetten/wissen via PATCH; wissen laat de state met rust (geen
    state-flip, anders dan deferred_until)."""
    _create(client, auth, project, title="x", state="todo")
    r = client.patch(
        "/api/v1/items/SOS-1", json={"due_date": "2030-01-01"}, headers=auth
    )
    assert r.json()["due_date"] == "2030-01-01"
    assert r.json()["state"] == "todo"
    r = client.patch("/api/v1/items/SOS-1", json={"due_date": ""}, headers=auth)
    assert r.json()["due_date"] is None
    assert r.json()["state"] == "todo"


def test_due_date_in_compact_list(client, auth, project):
    _create(client, auth, project, title="Met due", due_date="2030-06-01")
    items = client.get(f"/api/v1/projects/{project}/items", headers=auth).json()
    assert items[0]["due_date"] == "2030-06-01"


def test_list_filter_due_before(client, auth, project):
    """?due_before= geeft alleen items met een due_date op of vóór de grens; items
    zonder due_date vallen buiten het filter."""
    _create(client, auth, project, title="vroeg", due_date="2030-01-01")
    _create(client, auth, project, title="laat", due_date="2030-12-31")
    _create(client, auth, project, title="geen datum")

    items = client.get(
        f"/api/v1/projects/{project}/items?due_before=2030-06-01", headers=auth
    ).json()
    refs = {i["title"] for i in items}
    assert refs == {"vroeg"}

    # Grensdatum telt mee (<=).
    items = client.get(
        f"/api/v1/projects/{project}/items?due_before=2030-12-31", headers=auth
    ).json()
    assert {i["title"] for i in items} == {"vroeg", "laat"}


# --- BETON-218: plan/handover-veld -----------------------------------------


def test_create_with_plan_md(client, auth, project):
    """BETON-430: plan_md bij aanmaken -> has_plan true, GET /plan geeft de
    tekst, en het item.created-event draagt alleen een marker."""
    plan = "## Stap 1\n" + "geheime planinhoud " * 50
    r = client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "Met plan", "plan_md": plan},
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["has_plan"] is True
    assert "plan_md" not in r.json()
    got = client.get("/api/v1/items/SOS-1/plan", headers=auth).json()
    assert got["plan_md"] == plan
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    created = [e for e in events if e["type"] == "item.created"][0]
    assert created["payload"]["plan_md"] == {"changed": True, "cleared": False}
    assert "geheime planinhoud" not in str(created)


def test_create_without_plan_md_has_no_plan(client, auth, project):
    _create(client, auth, project, title="Zonder plan")
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert detail["has_plan"] is False
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    created = [e for e in events if e["type"] == "item.created"][0]
    assert "plan_md" not in created["payload"]


def test_plan_set_via_patch_and_fetched_on_demand(client, auth, project):
    """Plan zetten via PATCH; de detail-serialisatie adverteert alleen has_plan
    (het plan zelf zit er bewust niet in), de inhoud komt via GET /plan."""
    _create(client, auth, project, title="Met plan")
    r = client.patch(
        "/api/v1/items/SOS-1", json={"plan_md": "## Stap 1\ndoe iets"}, headers=auth
    )
    assert r.status_code == 200
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert detail["has_plan"] is True
    assert "plan_md" not in detail
    plan = client.get("/api/v1/items/SOS-1/plan", headers=auth).json()
    assert plan["plan_md"] == "## Stap 1\ndoe iets"


def test_plan_absent_by_default(client, auth, project):
    _create(client, auth, project, title="Zonder plan")
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert detail["has_plan"] is False
    assert (
        client.get("/api/v1/items/SOS-1/plan", headers=auth).json()["plan_md"] is None
    )


def test_plan_cleared_with_empty_string(client, auth, project):
    """ "" wist het plan (zelfde idioom als due_date)."""
    _create(client, auth, project, title="x")
    client.patch("/api/v1/items/SOS-1", json={"plan_md": "plan"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"plan_md": ""}, headers=auth)
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert detail["has_plan"] is False


def test_plan_event_carries_marker_not_content(client, auth, project):
    """Het item.updated-event markeert alleen dát het plan wijzigde — de inhoud
    (potentieel groot) hoort niet in het event-log of de webhook-payloads."""
    _create(client, auth, project, title="x")
    big_plan = "regel\n" * 200
    client.patch("/api/v1/items/SOS-1", json={"plan_md": big_plan}, headers=auth)
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    plan_events = [e for e in events if "plan_md" in (e.get("payload") or {})]
    assert len(plan_events) == 1
    assert plan_events[0]["payload"]["plan_md"] == {"changed": True, "cleared": False}
    assert "regel" not in str(plan_events[0]["payload"])


def test_plan_noop_patch_writes_no_event(client, auth, project):
    """Zelfde plan opnieuw zetten is een no-op: geen write, geen event."""
    _create(client, auth, project, title="x")
    client.patch("/api/v1/items/SOS-1", json={"plan_md": "plan"}, headers=auth)
    before = len(client.get("/api/v1/items/SOS-1/activity", headers=auth).json())
    client.patch("/api/v1/items/SOS-1", json={"plan_md": "plan"}, headers=auth)
    after = len(client.get("/api/v1/items/SOS-1/activity", headers=auth).json())
    assert after == before


def test_plan_endpoint_unknown_item_404(client, auth, project):
    assert client.get("/api/v1/items/SOS-999/plan", headers=auth).status_code == 404


# --- BETON-301: omschrijving/plan op slot zodra er een comment is ----------


def _agent_headers(conn, handle="lobke"):
    from betonning.repo import users as users_repo

    _, key = users_repo.create(conn, handle=handle, display_name=handle, kind="agent")
    conn.commit()
    return {"Authorization": f"Bearer {key}"}


def test_agent_can_edit_description_before_any_comment(client, auth, conn, project):
    _create(client, auth, project, title="x")
    r = client.patch(
        "/api/v1/items/SOS-1",
        json={"description_md": "nieuw"},
        headers=_agent_headers(conn),
    )
    assert r.status_code == 200


def test_agent_can_set_plan_before_any_comment(client, auth, conn, project):
    _create(client, auth, project, title="x")
    r = client.patch(
        "/api/v1/items/SOS-1", json={"plan_md": "plan"}, headers=_agent_headers(conn)
    )
    assert r.status_code == 200


def test_agent_cannot_edit_description_after_comment(client, auth, conn, project):
    _create(client, auth, project, title="x")
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=auth)
    r = client.patch(
        "/api/v1/items/SOS-1",
        json={"description_md": "nieuw"},
        headers=_agent_headers(conn),
    )
    assert r.status_code == 409


def test_agent_cannot_set_plan_after_comment(client, auth, conn, project):
    _create(client, auth, project, title="x")
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=auth)
    r = client.patch(
        "/api/v1/items/SOS-1", json={"plan_md": "plan"}, headers=_agent_headers(conn)
    )
    assert r.status_code == 409


def test_agent_cannot_clear_plan_after_comment(client, auth, conn, project):
    """"" wist het plan — ook dat is een agent-wijziging en dus geblokkeerd."""
    _create(client, auth, project, title="x")
    client.patch("/api/v1/items/SOS-1", json={"plan_md": "plan"}, headers=auth)
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=auth)
    r = client.patch(
        "/api/v1/items/SOS-1", json={"plan_md": ""}, headers=_agent_headers(conn)
    )
    assert r.status_code == 409


def test_agent_can_still_edit_other_fields_after_comment(client, auth, conn, project):
    """De guard geldt alleen voor omschrijving/plan — titel/state/labels blijven vrij."""
    _create(client, auth, project, title="x")
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=auth)
    agent = _agent_headers(conn)
    assert client.patch(
        "/api/v1/items/SOS-1", json={"title": "nieuwe titel"}, headers=agent
    ).status_code == 200
    assert client.patch(
        "/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=agent
    ).status_code == 200


def test_agent_description_noop_after_comment_stays_silent(client, auth, conn, project):
    """Dezelfde waarde opnieuw zetten is een stille no-op, geen 409 — de guard
    grijpt alleen bij een échte wijziging."""
    _create(client, auth, project, title="x", description_md="ongewijzigd")
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=auth)
    r = client.patch(
        "/api/v1/items/SOS-1",
        json={"description_md": "ongewijzigd"},
        headers=_agent_headers(conn),
    )
    assert r.status_code == 200


def test_human_can_edit_description_after_comment(client, auth, project):
    _create(client, auth, project, title="x")
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=auth)
    r = client.patch(
        "/api/v1/items/SOS-1", json={"description_md": "nieuw"}, headers=auth
    )
    assert r.status_code == 200


def test_human_can_set_plan_after_comment(client, auth, project):
    _create(client, auth, project, title="x")
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=auth)
    r = client.patch("/api/v1/items/SOS-1", json={"plan_md": "plan"}, headers=auth)
    assert r.status_code == 200


def test_count_for_item_helper(client, auth, conn, project):
    from betonning.repo import comments as comments_repo
    from betonning.repo import items as items_repo

    _create(client, auth, project, title="a")  # SOS-1
    _create(client, auth, project, title="b")  # SOS-2
    item1 = items_repo.get_by_ref(conn, "SOS-1")
    item2 = items_repo.get_by_ref(conn, "SOS-2")
    assert comments_repo.count_for_item(conn, item1["id"]) == 0

    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "een"}, headers=auth)
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "twee"}, headers=auth)
    assert comments_repo.count_for_item(conn, item1["id"]) == 2
    assert comments_repo.count_for_item(conn, item2["id"]) == 0


def test_count_for_item_excludes_triage_comments(client, auth, conn, project):
    """Persons beslissing: triage-comments tellen niet mee — een automatische
    classificatie (BETON-189) is geen discussie, en zou anders de BETON-218-
    planworkflow blokkeren nog vóórdat er ooit een plan geschreven is."""
    from betonning.repo import comments as comments_repo
    from betonning.repo import items as items_repo
    from betonning.repo import users as users_repo

    triage = users_repo.get_by_handle(conn, "triage")  # de `project`-fixture zaait 'm al
    _create(client, auth, project, title="a")  # SOS-1
    item = items_repo.get_by_ref(conn, "SOS-1")
    comments_repo.create(
        conn, item_id=item["id"], author_id=triage["id"], body_md="[Triage] ..."
    )
    conn.commit()
    assert comments_repo.count_for_item(conn, item["id"]) == 0

    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "echt"}, headers=auth)
    assert comments_repo.count_for_item(conn, item["id"]) == 1


def test_agent_can_set_plan_after_triage_comment(client, auth, conn, project):
    """De kern van de beslissing: een triage-comment alleen blokkeert de
    BETON-218-planworkflow niet."""
    from betonning.repo import comments as comments_repo
    from betonning.repo import items as items_repo
    from betonning.repo import users as users_repo

    triage = users_repo.get_by_handle(conn, "triage")  # de `project`-fixture zaait 'm al
    _create(client, auth, project, title="x")  # SOS-1
    item = items_repo.get_by_ref(conn, "SOS-1")
    comments_repo.create(
        conn, item_id=item["id"], author_id=triage["id"], body_md="[Triage] classificatie"
    )
    conn.commit()

    r = client.patch(
        "/api/v1/items/SOS-1", json={"plan_md": "plan"}, headers=_agent_headers(conn, "codex")
    )
    assert r.status_code == 200


# --- BETON-39: deferred_until --------------------------------------------


def test_create_with_deferred_until(client, auth, project):
    """BETON-212: het nieuw-item-formulier kan direct een uitsteldatum meegeven —
    de create-endpoint accepteert deferred_until en het item start in deferred."""
    r = _create(
        client, auth, project, title="Later oppakken", deferred_until="2999-01-01"
    )
    assert r.status_code == 201
    body = r.json()
    assert body["deferred_until"] == "2999-01-01"
    assert body["state"] == "deferred"


def test_set_deferred_until_moves_to_deferred_state(client, auth, project):
    """deferred_until zetten verplaatst het item naar de deferred-state en vult
    het veld."""
    _create(client, auth, project, title="Wacht op iets")
    r = client.patch(
        "/api/v1/items/SOS-1",
        json={"deferred_until": "2999-01-01"},
        headers=auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["deferred_until"] == "2999-01-01"
    assert body["state"] == "deferred"


def test_clear_deferred_until_moves_back_to_active_state(client, auth, project):
    """BETON-165: deferred_until wissen terwijl de state nog deferred is en de
    caller zelf geen state meegeeft, verplaatst het item terug naar de actieve
    default-state (todo) — anders blijft het voor altijd in Deferred hangen,
    want de reactivate-loop filtert juist op deferred_until IS NOT NULL."""
    _create(client, auth, project, title="x")
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2999-01-01"}, headers=auth
    )
    r = client.patch("/api/v1/items/SOS-1", json={"deferred_until": None}, headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["deferred_until"] is None
    assert body["state"] == "todo"


def test_clear_deferred_until_with_explicit_state_wins(client, auth, project):
    """BETON-165: een expliciete state in dezelfde PATCH wint van de impliciete
    undefer-flip."""
    _create(client, auth, project, title="x")
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2999-01-01"}, headers=auth
    )
    r = client.patch(
        "/api/v1/items/SOS-1",
        json={"deferred_until": None, "state": "in-progress"},
        headers=auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["deferred_until"] is None
    assert body["state"] == "in-progress"


def test_clear_deferred_until_when_not_deferred_state_keeps_state(
    client, auth, project
):
    """Als de state al niet meer deferred is (bv. handmatig al aangepast), laat
    het wissen van deferred_until de state met rust — er is dan niets impliciets
    om terug te draaien."""
    _create(client, auth, project, title="x")
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2999-01-01"}, headers=auth
    )
    client.patch("/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=auth)
    r = client.patch("/api/v1/items/SOS-1", json={"deferred_until": None}, headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["deferred_until"] is None
    assert body["state"] == "in-progress"


# --- BETON-191/194: overdracht haalt het item uit in-progress ----------------


@pytest.fixture
def agent_auth(conn):
    """Een agent-user (claude) met eigen key — de 'overdrager' in de
    BETON-191/194-tests (de actor mag niet dezelfde zijn als de nieuwe assignee)."""
    from betonning.repo import users as users_repo

    _, key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent"
    )
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def second_agent_auth(conn):
    """Een tweede agent-user (codex) — als actor bij tests die claude als
    NIEUWE assignee toewijzen (actor mag niet == nieuwe assignee zijn)."""
    from betonning.repo import users as users_repo

    _, key = users_repo.create(conn, handle="codex", display_name="Codex", kind="agent")
    return {"Authorization": f"Bearer {key}"}


def test_handoff_to_human_moves_in_progress_to_todo(client, auth, agent_auth, project):
    """Een agent draagt een in-progress item over aan de mens (Person): het item
    hoort niet in de 'wordt actief aan gewerkt'-kolom te blijven en gaat terug
    naar todo."""
    _create(client, auth, project, title="Werk waarvoor input nodig is")
    client.patch("/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=auth)
    r = client.patch(
        "/api/v1/items/SOS-1", json={"assignee": "person", "handover_md": "Controleer dit ticket."}, headers=agent_auth
    )
    assert r.status_code == 200
    body = r.json()
    assert body["assignee"] == "person"
    assert body["state"] == "todo"


def test_handoff_records_state_change_in_event(client, auth, agent_auth, conn, project):
    """De impliciete state-flip staat in het item.updated-event (from/to), zodat
    activiteitenlog en fanout de wisseling zien."""
    import json

    _create(client, auth, project, title="x")
    client.patch("/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=auth)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person", "handover_md": "Controleer dit ticket."}, headers=agent_auth)
    payloads = [
        json.loads(e["payload"])
        for e in conn.execute(
            "SELECT payload FROM events WHERE type = 'item.updated'"
        ).fetchall()
    ]
    state_changes = [p["state"] for p in payloads if "state" in p]
    assert {"from": "in-progress", "to": "todo"} in state_changes


def test_human_self_assign_keeps_in_progress(client, auth, project):
    """De actor≠assignee-poort: Person die het werk zélf oppakt (zichzelf
    toewijst) wordt niet meteen naar todo teruggetrokken."""
    _create(client, auth, project, title="Doe ik zelf")
    client.patch("/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=auth)
    r = client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    assert r.json()["state"] == "in-progress"


def test_handoff_to_agent_also_moves_to_todo(
    client, auth, agent_auth, second_agent_auth, project
):
    """BETON-194: de flip geldt niet alleen bij overdracht aan een mens — ook
    toewijzen aan een ANDERE agent haalt het item uit in-progress. De nieuwe
    assignee begint immers vers, niet halverwege iemand anders' werk."""
    _create(client, auth, project, title="Agent-werk")
    client.patch("/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=auth)
    # codex draagt over aan claude (actor != nieuwe assignee).
    r = client.patch(
        "/api/v1/items/SOS-1", json={"assignee": "claude"}, headers=second_agent_auth
    )
    assert r.json()["state"] == "todo"
    assert r.json()["assignee"] == "claude"


def test_agent_self_assign_keeps_in_progress(client, auth, agent_auth, project):
    """De actor≠assignee-poort geldt ook voor agents: claude die het werk zélf
    oppakt (zichzelf toewijst) wordt niet teruggetrokken naar todo."""
    _create(client, auth, project, title="Agent pakt zelf op")
    client.patch("/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=auth)
    r = client.patch(
        "/api/v1/items/SOS-1", json={"assignee": "claude"}, headers=agent_auth
    )
    assert r.json()["state"] == "in-progress"


def test_handoff_from_backlog_keeps_state(client, auth, agent_auth, project):
    """De flip geldt alleen vanuit een 'started' (in-progress) state; een backlog-
    item dat aan de mens gaat, blijft in backlog."""
    _create(client, auth, project, title="Nog in backlog")  # default = backlog
    r = client.patch(
        "/api/v1/items/SOS-1", json={"assignee": "person", "handover_md": "Controleer dit ticket."}, headers=agent_auth
    )
    assert r.json()["state"] == "backlog"


def test_handoff_from_done_keeps_state(client, auth, agent_auth, project):
    """BETON-194: gesloten states (done/cancelled) blijven ongemoeid — een
    assignee-wijziging op een afgerond ticket heropent het niet naar todo."""
    _create(client, auth, project, title="Al afgerond")
    client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=agent_auth)
    r = client.patch(
        "/api/v1/items/SOS-1", json={"assignee": "person", "handover_md": "Controleer dit ticket."}, headers=agent_auth
    )
    assert r.json()["state"] == "done"


def test_handoff_with_explicit_state_wins(client, auth, agent_auth, project):
    """Een expliciete state in dezelfde PATCH wint van de impliciete todo-flip."""
    _create(client, auth, project, title="x")
    client.patch("/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=auth)
    r = client.patch(
        "/api/v1/items/SOS-1",
        json={"assignee": "person", "state": "done", "handover_md": "Controleer het resultaat."},
        headers=agent_auth,
    )
    assert r.json()["state"] == "done"
    assert r.json()["assignee"] == "person"


def test_reactivate_deferred_moves_expired_back_and_clears(client, auth, conn, project):
    """Een item met een verlopen deferred_until keert terug naar todo en het veld
    wordt gewist."""
    from betonning.repo import items as items_repo

    _create(client, auth, project, title="Verlopen")
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2000-01-01"}, headers=auth
    )

    affected = items_repo.reactivate_deferred(conn)
    conn.commit()
    assert len(affected) == 1

    fresh = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert fresh["deferred_until"] is None
    assert fresh["state"] == "todo"


def test_reactivate_deferred_leaves_future(client, auth, conn, project):
    """Een toekomstige deferred_until blijft staan bij de reactivatie-check."""
    from betonning.repo import items as items_repo

    _create(client, auth, project, title="Toekomst")
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2999-01-01"}, headers=auth
    )

    affected = items_repo.reactivate_deferred(conn)
    conn.commit()
    assert affected == []

    fresh = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert fresh["deferred_until"] == "2999-01-01"
    assert fresh["state"] == "deferred"


def test_reactivate_deferred_restores_prior_state(client, auth, conn, project):
    """BETON-199: een item dat vanuit 'in-progress' werd uitgesteld, keert na de
    deferred_until-datum terug naar 'in-progress' — niet naar todo."""
    from betonning.repo import items as items_repo

    _create(client, auth, project, title="Onderweg")
    client.patch("/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=auth)
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2000-01-01"}, headers=auth
    )

    affected = items_repo.reactivate_deferred(conn)
    conn.commit()
    assert len(affected) == 1

    fresh = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert fresh["deferred_until"] is None
    assert fresh["state"] == "in-progress"


def test_reactivate_deferred_created_directly_falls_back_to_todo(
    client, auth, conn, project
):
    """BETON-199: een item dat rechtstreeks in deferred is aangemaakt (geen
    vorige state) keert terug naar todo, niet naar backlog."""
    from betonning.repo import items as items_repo

    _create(client, auth, project, title="Direct deferred", state="deferred")
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2000-01-01"}, headers=auth
    )

    affected = items_repo.reactivate_deferred(conn)
    conn.commit()
    assert len(affected) == 1

    fresh = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert fresh["deferred_until"] is None
    assert fresh["state"] == "todo"


def test_undefer_via_patch_restores_prior_state(client, auth, project):
    """BETON-199: handmatig deferred_until wissen terwijl de state nog deferred
    is, herstelt ook de state waar het item vandaan kwam."""
    client.post("/api/v1/projects/SOS/states", headers=auth,
                json={"name": "review", "group": "started"})
    _create(client, auth, project, title="Handmatig terug")
    client.patch("/api/v1/items/SOS-1", json={"state": "review"}, headers=auth)
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2999-01-01"}, headers=auth
    )

    r = client.patch("/api/v1/items/SOS-1", json={"deferred_until": None}, headers=auth)
    assert r.json()["state"] == "review"


def test_get_item_self_heals_expired_deferred(client, auth, project):
    """De item-detail-read zet een verlopen deferred-item vanzelf terug (self-heal)."""
    _create(client, auth, project, title="Zelf-heal")
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2000-01-01"}, headers=auth
    )
    fresh = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert fresh["deferred_until"] is None
    assert fresh["state"] == "todo"


def test_reactivate_deferred_writes_event_and_notifies_assignee(
    client, auth, conn, project, db_path
):
    """BETON-164: een sweep is niet stil — het reactiveren van een verlopen
    deferred-item schrijft een item.updated-event ({from,to} voor state en
    deferred_until) én maakt een webhook-delivery voor de assignee.

    Gaat bewust via de echte worker-entrypoint (`deferred_worker._run_sweep`,
    dezelfde functie die de lifespan-loop aanroept) i.p.v. losse
    `reactivate_deferred`/`notify_reactivations`-calls naast elkaar — anders
    bewijst de test niet dat de sweep de notificatie ook echt aanroept."""
    from betonning import deferred_worker
    from betonning.repo import users as users_repo

    users_repo.create(
        conn,
        handle="agent1",
        display_name="Agent1",
        kind="agent",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s3cret",
    )
    _create(client, auth, project, title="Verlopen met assignee", assignee="agent1")
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2000-01-01"}, headers=auth
    )

    affected = deferred_worker._run_sweep(db_path)
    assert len(affected) == 1

    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    # BETON-354: het reactivatie-event is herkenbaar aan zijn `reason`-marker;
    # de actor is sindsdien `triage` i.p.v. niemand.
    reactivation_events = [
        e
        for e in events
        if e["type"] == "item.updated"
        and (e.get("payload") or {}).get("reason") == "deferred_expired"
    ]
    assert len(reactivation_events) == 1
    payload = reactivation_events[0]["payload"]
    assert payload["state"] == {"from": "deferred", "to": "todo"}
    assert payload["deferred_until"] == {"from": "2000-01-01", "to": None}

    reactivation_event_id = reactivation_events[0]["id"]
    deliveries = conn.execute(
        "SELECT wd.* FROM webhook_deliveries wd JOIN users u ON u.id = wd.user_id "
        "WHERE u.handle = 'agent1' AND wd.event_id = ?",
        (reactivation_event_id,),
    ).fetchall()
    assert len(deliveries) == 1


def test_deferred_worker_sweep_reactivates_expired(client, auth, project, db_path):
    """De tijd-gedreven worker-sweep (BETON-39) zet een verlopen deferred-item terug,
    ook zonder dat iemand het item opent."""
    from betonning import deferred_worker

    _create(client, auth, project, title="Sweep")
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2000-01-01"}, headers=auth
    )

    affected = deferred_worker._run_sweep(db_path)
    assert len(affected) == 1

    fresh = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert fresh["deferred_until"] is None
    assert fresh["state"] == "todo"


def test_deferred_worker_loop_runs_and_stops(client, auth, project, db_path):
    """De reactivate_loop draait minstens één sweep en stopt netjes op stop_event —
    bewijst dat de lifespan-wiring werkt zonder op een item-read te leunen."""
    import asyncio

    from betonning import db as db_module
    from betonning import deferred_worker

    _create(client, auth, project, title="Loop")
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2000-01-01"}, headers=auth
    )

    async def run() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(
            deferred_worker.reactivate_loop(db_path, stop, interval_seconds=60)
        )
        try:
            for _ in range(200):
                await asyncio.sleep(0.01)
                c = db_module.connect(db_path)
                row = c.execute(
                    "SELECT deferred_until FROM items WHERE title = 'Loop'"
                ).fetchone()
                c.close()
                if row["deferred_until"] is None:
                    break
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(run())

    fresh = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert fresh["deferred_until"] is None
    assert fresh["state"] == "todo"


# --- BETON-50: subtaak-voortgang -----------------------------------------


def _child_of(client, auth, project, parent_ref, title):
    return client.post(
        f"/api/v1/projects/{project}/items",
        json={"title": title, "parent": parent_ref},
        headers=auth,
    ).json()["ref"]


def test_children_counts_on_parent(client, auth, project):
    """serialize/compact tellen levende subtaken; done = subtaken in een
    closed-group state."""
    _create(client, auth, project, title="Ouder")  # SOS-1
    c1 = _child_of(client, auth, project, "SOS-1", "a")
    _child_of(client, auth, project, "SOS-1", "b")

    parent = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert parent["children_total"] == 2
    assert parent["children_done"] == 0

    client.patch(f"/api/v1/items/{c1}", json={"state": "done"}, headers=auth)
    parent = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert parent["children_done"] == 1

    # Ook op de compacte lijst.
    items = client.get(f"/api/v1/projects/{project}/items", headers=auth).json()
    row = next(i for i in items if i["ref"] == "SOS-1")
    assert row["children_total"] == 2 and row["children_done"] == 1


def test_last_child_done_posts_single_suggestion(client, auth, project):
    """Zodra de laatste subtaak done/cancelled is, komt er precies één
    suggestie-comment op de ouder."""
    _create(client, auth, project, title="Ouder")  # SOS-1
    c1 = _child_of(client, auth, project, "SOS-1", "a")
    c2 = _child_of(client, auth, project, "SOS-1", "b")

    # Eerste subtaak done → nog niet alles af → geen suggestie.
    client.patch(f"/api/v1/items/{c1}", json={"state": "done"}, headers=auth)
    parent = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert not any("[Subtaken]" in c["body_md"] for c in parent["comments"])

    # Laatste subtaak cancelled → alles af → één suggestie, op naam van triage
    # (BETON-303: niet de agent/user die de laatste subtaak sloot).
    client.patch(f"/api/v1/items/{c2}", json={"state": "cancelled"}, headers=auth)
    parent = client.get("/api/v1/items/SOS-1", headers=auth).json()
    suggestions = [c for c in parent["comments"] if "[Subtaken]" in c["body_md"]]
    assert len(suggestions) == 1
    assert suggestions[0]["author"] == "triage"

    # Heropenen en opnieuw sluiten → geen tweede suggestie (idempotent).
    client.patch(f"/api/v1/items/{c2}", json={"state": "todo"}, headers=auth)
    client.patch(f"/api/v1/items/{c2}", json={"state": "done"}, headers=auth)
    parent = client.get("/api/v1/items/SOS-1", headers=auth).json()
    suggestions = [c for c in parent["comments"] if "[Subtaken]" in c["body_md"]]
    assert len(suggestions) == 1


def test_parent_suggestion_marks_own_comment_evaluated(client, auth, conn, project):
    """BETON-303: de suggestie-comment krijgt meteen `evaluated_at` — anders zou
    triage zijn eigen comment als onbeantwoorde reactie oppakken (zelf-lus)."""
    _create(client, auth, project, title="Ouder")  # SOS-1
    c1 = _child_of(client, auth, project, "SOS-1", "a")
    client.patch(f"/api/v1/items/{c1}", json={"state": "done"}, headers=auth)

    row = conn.execute(
        "SELECT evaluated_at FROM comments WHERE body_md LIKE '%[Subtaken]%'"
    ).fetchone()
    assert row is not None
    assert row["evaluated_at"] is not None


def test_parent_suggestion_directed_at_assignee(client, auth, conn, project):
    """BETON-303: de suggestie is gericht (directed) aan de assignee van de
    ouder — een willekeurige derde krijgt geen delivery, de assignee wel."""
    from betonning.repo import users as users_repo

    users_repo.create(
        conn,
        handle="lobke",
        display_name="Lobke",
        kind="agent",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
    )
    users_repo.create(
        conn,
        handle="joop",
        display_name="Joop",
        kind="agent",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
    )
    conn.commit()

    _create(client, auth, project, title="Ouder", assignee="lobke")  # SOS-1
    c1 = _child_of(client, auth, project, "SOS-1", "a")
    client.patch(f"/api/v1/items/{c1}", json={"state": "done"}, headers=auth)

    def _deliveries_for(handle):
        return conn.execute(
            "SELECT wd.* FROM webhook_deliveries wd JOIN users u ON u.id = wd.user_id "
            "WHERE u.handle = ? ORDER BY wd.id",
            (handle,),
        ).fetchall()

    assert len(_deliveries_for("lobke")) >= 1
    assert len(_deliveries_for("joop")) == 0


def test_parent_suggestion_skipped_without_triage_user(client, auth, conn, project):
    """Ontbreekt de triage-user in dit systeem, dan wordt de suggestie
    overgeslagen — niet ten onrechte teruggevallen op de sluitende actor."""
    conn.execute("DELETE FROM users WHERE handle = 'triage'")
    conn.commit()

    _create(client, auth, project, title="Ouder")  # SOS-1
    c1 = _child_of(client, auth, project, "SOS-1", "a")
    client.patch(f"/api/v1/items/{c1}", json={"state": "done"}, headers=auth)

    parent = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert not any("[Subtaken]" in c["body_md"] for c in parent["comments"])


# --- BETON-215: agent-umbrella's automatisch sluiten ------------------------


def _hermes_umbrella(client, conn, project, title="Overleg energie 2026-07-13"):
    """Maak een Hermes-authored umbrella (lege omschrijving) aan; geeft (ref, key)."""
    from betonning.repo import users as users_repo

    lobke = users_repo.get_by_handle(conn, "lobke")
    if lobke is None:
        _, key = users_repo.create(
            conn,
            handle="lobke",
            display_name="Lobke",
            kind="agent",
            agent_type="hermes",
        )
        conn.commit()
    else:  # pragma: no cover — meerdere umbrellas in één test
        raise AssertionError("lobke bestaat al")
    r = client.post(
        f"/api/v1/projects/{project}/items",
        json={"title": title},
        headers={"Authorization": f"Bearer {key}"},
    )
    return r.json()["ref"], key


def test_agent_umbrella_autocloses_when_children_resolved(client, auth, conn, project):
    """BETON-215: een Hermes-authored umbrella sluit automatisch zodra de
    laatste subtaak done/cancelled is — met een comment en een state-event,
    en completed_at gezet."""
    parent_ref, _ = _hermes_umbrella(client, conn, project)
    c1 = _child_of(client, auth, project, parent_ref, "a")
    c2 = _child_of(client, auth, project, parent_ref, "b")

    client.patch(f"/api/v1/items/{c1}", json={"state": "done"}, headers=auth)
    parent = client.get(f"/api/v1/items/{parent_ref}", headers=auth).json()
    assert parent["state"] not in ("done", "cancelled")  # nog niet alles af

    client.patch(f"/api/v1/items/{c2}", json={"state": "cancelled"}, headers=auth)
    parent = client.get(f"/api/v1/items/{parent_ref}", headers=auth).json()
    assert parent["state"] == "done"
    assert parent["completed_at"] is not None
    closes = [c for c in parent["comments"] if "automatisch gesloten" in c["body_md"]]
    assert len(closes) == 1
    assert closes[0]["author"] == "triage"  # BETON-303: niet lobke (de umbrella-maker)
    events = client.get(f"/api/v1/items/{parent_ref}/activity", headers=auth).json()
    assert any(
        e["type"] == "item.updated"
        and e["payload"].get("state", {}).get("to") == "done"
        for e in events
    )


def test_umbrella_autoclose_comment_not_fanned_out(client, auth, conn, project):
    """BETON-303: de umbrella-auto-close-comment wordt (net als vóór deze fix)
    niet apart gefanout — alleen het item.updated-event. Anders krijgt de
    umbrella-maker een dubbele ping (state-wijziging + comment) op precies het
    moment dat deze ticketbatch juist ruis probeert te verminderen."""
    parent_ref, _ = _hermes_umbrella(client, conn, project)
    conn.execute(
        "UPDATE users SET webhook_url = 'http://example.invalid/hook', "
        "webhook_secret = 's' WHERE handle = 'lobke'"
    )
    conn.commit()
    c1 = _child_of(client, auth, project, parent_ref, "a")

    client.patch(f"/api/v1/items/{c1}", json={"state": "done"}, headers=auth)

    comment_deliveries = conn.execute(
        "SELECT wd.* FROM webhook_deliveries wd "
        "JOIN events e ON e.id = wd.event_id JOIN users u ON u.id = wd.user_id "
        "WHERE u.handle = 'lobke' AND e.type = 'comment.created'"
    ).fetchall()
    assert len(comment_deliveries) == 0


def test_agent_umbrella_autoclose_is_idempotent(client, auth, conn, project):
    """Heropenen en opnieuw sluiten van een kind sluit de (al dichte) umbrella
    niet nogmaals — geen tweede close-comment."""
    parent_ref, _ = _hermes_umbrella(client, conn, project)
    c1 = _child_of(client, auth, project, parent_ref, "a")
    client.patch(f"/api/v1/items/{c1}", json={"state": "done"}, headers=auth)
    client.patch(f"/api/v1/items/{c1}", json={"state": "todo"}, headers=auth)
    client.patch(f"/api/v1/items/{c1}", json={"state": "done"}, headers=auth)
    parent = client.get(f"/api/v1/items/{parent_ref}", headers=auth).json()
    assert parent["state"] == "done"
    closes = [c for c in parent["comments"] if "automatisch gesloten" in c["body_md"]]
    assert len(closes) == 1


def test_human_parent_still_gets_suggestion_not_autoclose(client, auth, project):
    """Een mens-gemaakte ouder sluit NIET automatisch — de bestaande
    suggestie-comment (BETON-50) blijft het gedrag."""
    _create(client, auth, project, title="Ouder")  # SOS-1, maker person (mens)
    c1 = _child_of(client, auth, project, "SOS-1", "a")
    client.patch(f"/api/v1/items/{c1}", json={"state": "done"}, headers=auth)
    parent = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert parent["state"] != "done"
    assert any("kan dit item dicht?" in c["body_md"] for c in parent["comments"])


# --- BETON-68: last_activity_at op de kaart -------------------------------


def test_last_activity_at_without_comments_equals_updated_at(client, auth, project):
    """Zonder comments is `last_activity_at` gewoon `updated_at`."""
    ref = _create(client, auth, project, title="Zonder comments").json()["ref"]
    item = client.get(f"/api/v1/items/{ref}", headers=auth).json()
    assert item["last_activity_at"] == item["updated_at"]


def test_new_comment_bumps_last_activity_at(client, auth, conn, project):
    """Een nieuwe comment maakt `last_activity_at` recenter dan `updated_at`,
    zonder `updated_at` zelf aan te raken (dat blijft de concurrency-token,
    BETON-44)."""
    ref = _create(client, auth, project, title="Met comment").json()["ref"]
    before = client.get(f"/api/v1/items/{ref}", headers=auth).json()

    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "hoi"}, headers=auth)
    # Zet de comment-timestamp expliciet later dan het item, zodat de test niet
    # afhangt van of create+comment binnen dezelfde millisecond vallen.
    conn.execute(
        "UPDATE comments SET created_at = ?, updated_at = ? "
        "WHERE item_id = (SELECT id FROM items WHERE seq = 1)",
        ("2999-01-01T00:00:00.000Z", "2999-01-01T00:00:00.000Z"),
    )
    conn.commit()

    after = client.get(f"/api/v1/items/{ref}", headers=auth).json()
    assert after["updated_at"] == before["updated_at"]  # niet gebumpt door de comment
    assert after["last_activity_at"] == "2999-01-01T00:00:00.000Z"
    assert after["last_activity_at"] > after["updated_at"]

    # Ook op de compacte lijst.
    items = client.get(f"/api/v1/projects/{project}/items", headers=auth).json()
    row = next(i for i in items if i["ref"] == ref)
    assert row["last_activity_at"] == "2999-01-01T00:00:00.000Z"


def test_edited_comment_bumps_last_activity_at(client, auth, conn, project):
    """Ook het bewerken van een bestaande comment telt als activiteit."""
    ref = _create(client, auth, project, title="Bewerkte comment").json()["ref"]
    c = client.post(
        f"/api/v1/items/{ref}/comments", json={"body_md": "origineel"}, headers=auth
    ).json()

    client.patch(
        f"/api/v1/items/{ref}/comments/{c['id']}",
        json={"body_md": "bewerkt"},
        headers=auth,
    )
    conn.execute(
        "UPDATE comments SET updated_at = ? WHERE id = ?",
        ("2999-01-01T00:00:00.000Z", c["id"]),
    )
    conn.commit()

    item = client.get(f"/api/v1/items/{ref}", headers=auth).json()
    assert item["last_activity_at"] == "2999-01-01T00:00:00.000Z"


def test_move_item_in_place_carries_everything(client, auth, project):
    """BETON-244: verplaatsen gebeurt in-place — het item behoudt zijn id en krijgt
    alleen een nieuwe ref. Comments, relaties, attachments en subtaken verhuizen
    dus mee; de oude ref bestaat niet meer, de nieuwe wél. Labels worden geremapt
    naar het doelproject, de milestone gewist."""
    client.post("/api/v1/projects", json={"key": "DOEL", "name": "Doel"}, headers=auth)
    client.post("/api/v1/projects/SOS/labels", json={"name": "bug"}, headers=auth)
    client.post(
        "/api/v1/projects/SOS/milestones", json={"name": "v1.0.0"}, headers=auth
    )

    ref = _create(
        client,
        auth,
        "SOS",
        title="Verhuizer",
        description_md="mijn omschrijving",
        priority="high",
        assignee="person",
        milestone="v1.0.0",
    ).json()["ref"]
    item_id = client.get(f"/api/v1/items/{ref}", headers=auth).json()["id"]
    client.post(f"/api/v1/items/{ref}/labels/bug", headers=auth)
    client.post(
        f"/api/v1/items/{ref}/comments", json={"body_md": "gaat mee"}, headers=auth
    )
    other = _create(client, auth, "SOS", title="Ander").json()["ref"]
    client.post(
        f"/api/v1/items/{ref}/relations",
        json={"type": "relates_to", "target": other},
        headers=auth,
    )
    child = _child_of(client, auth, "SOS", ref, "subtaak")

    mv = client.post(
        f"/api/v1/items/{ref}/move", json={"project": "DOEL"}, headers=auth
    )
    assert mv.status_code == 200
    new = mv.json()
    assert new["ref"] == "DOEL-1"
    assert new["project"] == "DOEL"
    assert new["id"] == item_id  # zelfde item, alleen de ref wijzigt
    assert new["title"] == "Verhuizer"
    assert new["description_md"] == "mijn omschrijving"
    assert new["priority"] == "high"
    assert new["assignee"] == "person"
    assert new["labels"] == ["bug"]
    assert new["milestone"] is None  # milestone hoort bij het bronproject → gewist
    assert new["state"] == "backlog"  # default-state van het doelproject

    # label is aangemaakt in het doelproject
    doel_labels = {
        lbl["name"]
        for lbl in client.get("/api/v1/projects/DOEL/labels", headers=auth).json()
    }
    assert "bug" in doel_labels

    # oude ref bestaat niet meer, nieuwe wél
    assert client.get(f"/api/v1/items/{ref}", headers=auth).status_code == 404
    detail = client.get("/api/v1/items/DOEL-1", headers=auth).json()

    # comments, relaties en subtaken verhuisden mee (verwijzen naar hetzelfde id)
    assert [c["body_md"] for c in detail["comments"]] == ["gaat mee"]
    assert other in detail["relations"]["relates_to"]
    assert detail["children_total"] == 1
    # het kind blijft in het bronproject (parent_id-link blijft, cross-project)
    assert client.get(f"/api/v1/items/{child}", headers=auth).json()["parent"] == "DOEL-1"


def test_move_item_records_moved_event(client, auth, conn, project):
    """BETON-244: de move schrijft één item.moved-event met from/to op hetzelfde
    item (dat door de meeverhuisde tijdlijn zichtbaar blijft)."""
    client.post("/api/v1/projects", json={"key": "DOEL", "name": "Doel"}, headers=auth)
    ref = _create(client, auth, "SOS", title="Verhuizer").json()["ref"]
    item_id = client.get(f"/api/v1/items/{ref}", headers=auth).json()["id"]

    client.post(f"/api/v1/items/{ref}/move", json={"project": "DOEL"}, headers=auth)

    row = conn.execute(
        "SELECT payload FROM events WHERE type = 'item.moved' AND item_id = ?",
        (item_id,),
    ).fetchone()
    assert row is not None
    payload = json.loads(row["payload"])
    assert payload == {"from": ref, "to": "DOEL-1"}


def test_move_item_clears_deferred_context(client, auth, conn, project):
    """BETON-244: een verplaatst item mag geen deferred-context uit het bronproject
    meenemen — anders zou reactivate_deferred het later naar een bron-project-state
    zetten (cross-project state-corruptie)."""
    from betonning.repo import items as items_repo

    client.post("/api/v1/projects", json={"key": "DOEL", "name": "Doel"}, headers=auth)
    ref = _create(client, auth, "SOS", title="Uitgesteld").json()["ref"]
    row = items_repo.get_by_ref(conn, ref)
    # zet een deferred_until + deferred_from_state_id (verwijst naar bron-state)
    src_state = conn.execute(
        "SELECT id FROM states WHERE project_id = ? LIMIT 1", (row["project_id"],)
    ).fetchone()["id"]
    conn.execute(
        "UPDATE items SET deferred_until = '2000-01-01T00:00:00.000Z', "
        "deferred_from_state_id = ? WHERE id = ?",
        (src_state, row["id"]),
    )
    conn.commit()

    mv = client.post(f"/api/v1/items/{ref}/move", json={"project": "DOEL"}, headers=auth)
    assert mv.status_code == 200
    moved = items_repo.get_by_ref(conn, mv.json()["ref"])
    assert moved["deferred_until"] is None
    assert moved["deferred_from_state_id"] is None


def test_move_item_triggers_fanout_in_target_project(client, auth, conn, project):
    """BETON-166/244: het verplaatste item triggert een webhook-delivery voor de
    assignee op het item.moved-event."""
    from betonning.repo import users as users_repo

    client.post("/api/v1/projects", json={"key": "DOEL", "name": "Doel"}, headers=auth)
    users_repo.create(
        conn,
        handle="agent1",
        display_name="Agent1",
        kind="agent",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s3cret",
    )
    ref = _create(client, auth, "SOS", title="Verhuizer", assignee="agent1").json()[
        "ref"
    ]

    mv = client.post(
        f"/api/v1/items/{ref}/move", json={"project": "DOEL"}, headers=auth
    )
    assert mv.status_code == 200
    new_ref = mv.json()["ref"]

    deliveries = conn.execute(
        "SELECT wd.* FROM webhook_deliveries wd "
        "JOIN users u ON u.id = wd.user_id "
        "JOIN events e ON e.id = wd.event_id "
        "JOIN items i ON i.id = e.item_id "
        "JOIN projects p ON p.id = i.project_id "
        "WHERE u.handle = 'agent1' AND e.type = 'item.moved' AND p.key = 'DOEL'"
    ).fetchall()
    assert len(deliveries) == 1
    assert new_ref == "DOEL-1"


def test_move_item_to_same_project_400(client, auth, project):
    ref = _create(client, auth, "SOS", title="Blijf").json()["ref"]
    r = client.post(f"/api/v1/items/{ref}/move", json={"project": "SOS"}, headers=auth)
    assert r.status_code == 400


def test_move_item_unknown_project_404(client, auth, project):
    ref = _create(client, auth, "SOS", title="Blijf").json()["ref"]
    r = client.post(f"/api/v1/items/{ref}/move", json={"project": "NOPE"}, headers=auth)
    assert r.status_code == 404


def test_compact_and_compact_rows_projection_parity(client, auth, conn, project):
    """BETON-320: `compact()` (single-item-pad, o.a. de SSE-snapshot in
    `api/stream.py`) en `_compact_rows` (het gebatchte list-pad) moeten uit
    dezelfde canonieke projectie komen. Voorheen dreven ze uit elkaar
    (`locked`/`last_activity_at` verschillend berekend) — deze test bewaakt
    zowel veldset- als waarde-pariteit voor de gevoelige velden."""
    from betonning.repo import items as items_repo
    from betonning.repo import projects as projects_repo
    from betonning.repo import users as users_repo

    _, other_key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent"
    )
    other_auth = {"Authorization": f"Bearer {other_key}"}

    ref = _create(client, auth, "SOS", title="Pariteit").json()["ref"]

    # Vreemde comment (BETON-68): verhoogt last_activity_at boven updated_at
    # én maakt het item ongelezen voor de viewer (BETON-294).
    r = client.post(
        f"/api/v1/items/{ref}/comments", json={"body_md": "hoi"}, headers=other_auth
    )
    assert r.status_code == 201

    row = items_repo.get_by_ref(conn, ref)
    items_repo.lock(conn, row["id"])  # BETON-302

    viewer = users_repo.get_by_handle(conn, "person")
    project_row = projects_repo.get_by_key(conn, "SOS")

    row = items_repo.get_by_ref(conn, ref)
    serialized = items_repo.serialize(conn, row, viewer_id=viewer["id"])
    single = items_repo.compact(serialized)

    bulk_list = items_repo.list_items(
        conn, project_row["id"], viewer_id=viewer["id"]
    )
    bulk = next(r for r in bulk_list if r["ref"] == ref)

    assert set(single.keys()) == set(bulk.keys())
    assert single["locked"] is True
    assert bulk["locked"] is True
    for key in ("locked", "last_activity_at", "has_unread"):
        assert single[key] == bulk[key], key
    assert single == bulk


# --- _in_clause bulk-helper (BETON-326) ------------------------------------
#
# `_in_clause` vervangt de 9 herhaalde `",".join("?" * len(ids))`-plekken.
# Elke geraakte bulk-helper hieronder krijgt zowel een lege als een niet-lege
# id-lijst: leeg moet de bekende leegwaarde geven zonder een query af te
# vuren (de guard blijft bij de caller, `_in_clause` zelf guardt niets), en
# niet-leeg moet de bestaande mapping/set opleveren.


def _no_query(db_path, call) -> None:
    """Roep `call(conn)` aan en faal als er een SELECT wordt afgevuurd."""
    from betonning import db as db_module

    traced = db_module.connect(db_path)
    statements: list[str] = []
    traced.set_trace_callback(statements.append)
    try:
        result = call(traced)
    finally:
        traced.close()
    assert not any("SELECT" in s for s in statements), statements
    return result


def test_children_counts_bulk_empty_and_non_empty(db_path, client, auth, conn, project):
    from betonning.repo import items as items_repo

    ref = _create(client, auth, project, title="Ouder").json()["ref"]
    parent_row = items_repo.get_by_ref(conn, ref)
    _create(client, auth, project, title="Kind", parent=ref).json()["ref"]
    conn.commit()

    assert _no_query(db_path, lambda c: items_repo._children_counts_bulk(c, [])) == {}

    result = items_repo._children_counts_bulk(conn, [parent_row["id"]])
    assert result[parent_row["id"]] == (0, 1)


def test_last_comment_activity_bulk_empty_and_non_empty(
    db_path, client, auth, conn, project
):
    from betonning.repo import items as items_repo

    ref = _create(client, auth, project, title="Met comment").json()["ref"]
    row = items_repo.get_by_ref(conn, ref)
    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "hoi"}, headers=auth)
    conn.commit()

    assert (
        _no_query(db_path, lambda c: items_repo._last_comment_activity_bulk(c, []))
        == {}
    )

    result = items_repo._last_comment_activity_bulk(conn, [row["id"]])
    assert row["id"] in result


def test_open_questions_bulk_empty_and_non_empty(db_path, client, auth, conn, project):
    from betonning.repo import items as items_repo

    ref = _create(client, auth, project, title="Met vraag").json()["ref"]
    row = items_repo.get_by_ref(conn, ref)
    client.post(
        f"/api/v1/items/{ref}/comments",
        json={"body_md": "wat vind je?", "kind": "question"},
        headers=auth,
    )
    conn.commit()

    assert _no_query(db_path, lambda c: items_repo._open_questions_bulk(c, [])) == set()

    result = items_repo._open_questions_bulk(conn, [row["id"]])
    assert result == {row["id"]}


def test_labels_bulk_empty_and_non_empty(db_path, client, auth, conn, project):
    from betonning.repo import items as items_repo

    client.post(
        f"/api/v1/projects/{project}/labels", json={"name": "bug"}, headers=auth
    )
    ref = _create(client, auth, project, title="Met label").json()["ref"]
    row = items_repo.get_by_ref(conn, ref)
    r = client.post(f"/api/v1/items/{ref}/labels/bug", headers=auth)
    assert r.status_code == 201
    conn.commit()

    assert _no_query(db_path, lambda c: items_repo._labels_bulk(c, [])) == {}

    result = items_repo._labels_bulk(conn, [row["id"]])
    assert result[row["id"]] == ["bug"]


def test_list_assigned_open_empty_and_non_empty(db_path, client, auth, conn, project):
    from betonning.repo import items as items_repo
    from betonning.repo import users as users_repo

    ref = _create(client, auth, project, title="Toegewezen").json()["ref"]
    client.patch(f"/api/v1/items/{ref}", json={"assignee": "person"}, headers=auth)
    person = users_repo.get_by_handle(conn, "person")

    assert _no_query(db_path, lambda c: items_repo.list_assigned_open(c, [])) == []

    result = items_repo.list_assigned_open(conn, [person["id"]])
    assert [r["ref"] for r in result] == [ref]


def test_agent_can_set_deferred_until_only_after_comment(client, auth, conn, project):
    """BETON-343 repro: een agent die uitsluitend deferred_until meestuurt mag
    niet stuklopen op de description/plan-lock — die velden worden niet
    aangeraakt."""
    _create(client, auth, project, title="x")
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=auth)
    r = client.patch(
        "/api/v1/items/SOS-1",
        json={"deferred_until": "2999-01-01"},
        headers=_agent_headers(conn),
    )
    assert r.status_code == 200
    assert r.json()["deferred_until"] == "2999-01-01"


def test_reactivation_event_has_triage_actor_and_reason(client, auth, conn, project):
    """BETON-354: de deferred→todo-overgang krijgt een herkenbare afzender.

    Vóór deze wijziging schreef `notify_reactivations` het `item.updated`-event
    met `actor_id=None`; de tijdlijn toonde dan "@?" — een transitie door een
    onbekende. De actor is nu `triage` (zelfde lijn als de automatische noodstop,
    BETON-338) en de payload draagt de aanleiding als `reason`, zodat de UI
    "uitstel verlopen" kan tonen i.p.v. alleen de kale statuswissel."""
    from betonning import webhooks
    from betonning.repo import items as items_repo

    _create(client, auth, project, title="Verlopen")
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2000-01-01"}, headers=auth
    )

    affected = items_repo.reactivate_deferred(conn)
    webhooks.notify_reactivations(conn, affected)
    conn.commit()

    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    reactivation = [
        e
        for e in events
        if (e.get("payload") or {}).get("reason") == "deferred_expired"
    ]
    assert len(reactivation) == 1
    assert reactivation[0]["actor"] == "triage"
    assert reactivation[0]["payload"]["state"]["to"] == "todo"


def test_reactivation_event_without_triage_user_keeps_null_actor(
    client, auth, conn, project
):
    """BETON-354: zonder `triage`-user blijft de actor leeg — de reactivatie
    zelf mag nooit op een ontbrekende bot stuklopen (spiegelt de vangnet-tak in
    `_lock_item`, BETON-338)."""
    from betonning import webhooks
    from betonning.repo import items as items_repo

    _create(client, auth, project, title="Verlopen")
    client.patch(
        "/api/v1/items/SOS-1", json={"deferred_until": "2000-01-01"}, headers=auth
    )
    conn.execute("DELETE FROM users WHERE handle = 'triage'")
    conn.commit()

    affected = items_repo.reactivate_deferred(conn)
    webhooks.notify_reactivations(conn, affected)
    conn.commit()

    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    reactivation = [
        e
        for e in events
        if (e.get("payload") or {}).get("reason") == "deferred_expired"
    ]
    assert len(reactivation) == 1
    assert reactivation[0]["actor"] is None


@pytest.fixture(autouse=True)
def legacy_dutch_system_text(monkeypatch):
    """De bestaande Nederlandstalige oudercomment-contracten blijven getest."""
    monkeypatch.setenv('HEGEMONE_LANGUAGE', 'nl')
