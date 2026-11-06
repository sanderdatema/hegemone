"""Werklast-veld (BETON-311, fase 1): aanmaken, wijzigen, wissen, filteren.

Fase 1 is additief — `workload` komt naast `priority`; priority verdwijnt pas
in fase 2 uit de surface. Gedrag testen via de API, niet de implementatie.
"""

from __future__ import annotations


def _create(client, auth, **body):
    body.setdefault("title", "x")
    return client.post("/api/v1/projects/SOS/items", json=body, headers=auth)


def test_create_with_workload(client, auth, project):
    r = _create(client, auth, workload="heavy")
    assert r.status_code == 201
    assert r.json()["workload"] == "heavy"


def test_create_without_workload_is_empty(client, auth, project):
    """Leeg = nog niet geschat (het signaal waarop triage later bijspringt)."""
    r = _create(client, auth)
    assert r.status_code == 201
    assert r.json()["workload"] is None


def test_create_rejects_unknown_workload(client, auth, project):
    r = _create(client, auth, workload="gigantic")
    assert r.status_code == 422


def test_create_rejects_dutch_workload(client, auth, project):
    """De API-waarden zijn Engels (light/medium/heavy); Dutch alleen in de UI."""
    r = _create(client, auth, workload="zwaar")
    assert r.status_code == 422


def test_update_sets_workload(client, auth, project):
    _create(client, auth)
    r = client.patch("/api/v1/items/SOS-1", json={"workload": "light"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["workload"] == "light"


def test_update_changes_workload(client, auth, project):
    _create(client, auth, workload="light")
    r = client.patch("/api/v1/items/SOS-1", json={"workload": "heavy"}, headers=auth)
    assert r.json()["workload"] == "heavy"


def test_update_clears_workload_with_null(client, auth, project):
    """Wissen (terug naar 'nog niet geschat') gaat via null."""
    _create(client, auth, workload="medium")
    r = client.patch("/api/v1/items/SOS-1", json={"workload": None}, headers=auth)
    assert r.status_code == 200
    assert r.json()["workload"] is None


def test_detail_carries_workload(client, auth, project):
    _create(client, auth, workload="medium")
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["workload"] == "medium"


def test_list_carries_workload(client, auth, project):
    _create(client, auth, workload="heavy")
    items = client.get("/api/v1/projects/SOS/items", headers=auth).json()
    assert items[0]["workload"] == "heavy"


def test_filter_by_workload(client, auth, project):
    _create(client, auth, title="licht ding", workload="light")
    _create(client, auth, title="zwaar ding", workload="heavy")
    _create(client, auth, title="ongeschat")

    r = client.get("/api/v1/projects/SOS/items?workload=heavy", headers=auth)
    refs = [i["title"] for i in r.json()]
    assert refs == ["zwaar ding"]


def test_workload_and_priority_coexist_in_phase_1(client, auth, project):
    """Fase 1 is additief: priority blijft bestaan naast workload."""
    r = _create(client, auth, priority="high", workload="light")
    body = r.json()
    assert body["priority"] == "high"
    assert body["workload"] == "light"
