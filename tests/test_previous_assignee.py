"""Vorige toewijzing in de detailvorm, zonder extra werk in lijsten (BETON-470)."""
from conftest import _create


def test_previous_assignee_na_overdracht(client, auth, project):
    client.post("/api/v1/users", headers=auth, json={"handle": "claude", "display_name": "Claude", "kind": "agent"})
    ref = _create(client, auth, project, assignee="claude").json()["ref"]
    assert client.get(f"/api/v1/items/{ref}", headers=auth).json()["previous_assignee"] is None
    updated = client.patch(f"/api/v1/items/{ref}", headers=auth, json={"assignee": "person"})
    updated.raise_for_status()
    assert updated.json()["previous_assignee"] == "claude"
    # Een latere wijziging aan een ander veld wist de historie niet.
    client.patch(f"/api/v1/items/{ref}", headers=auth, json={"title": "Review"}).raise_for_status()
    assert client.get(f"/api/v1/items/{ref}", headers=auth).json()["previous_assignee"] == "claude"
    rows = client.get(f"/api/v1/projects/{project}/items", headers=auth).json()
    assert "previous_assignee" not in rows[0]


def test_previous_assignee_zonder_historie_of_na_wissen(client, auth, project):
    ref = _create(client, auth, project, assignee="person").json()["ref"]
    assert client.get(f"/api/v1/items/{ref}", headers=auth).json()["previous_assignee"] is None
    client.patch(f"/api/v1/items/{ref}", headers=auth, json={"title": "Andere titel"}).raise_for_status()
    assert client.get(f"/api/v1/items/{ref}", headers=auth).json()["previous_assignee"] is None
    client.patch(f"/api/v1/items/{ref}", headers=auth, json={"assignee": ""}).raise_for_status()
    assert client.get(f"/api/v1/items/{ref}", headers=auth).json()["previous_assignee"] is None


def test_previous_assignee_laatste_overdracht_wint(client, auth, project):
    client.post("/api/v1/users", headers=auth, json={"handle": "claude", "display_name": "Claude", "kind": "agent"})
    ref = _create(client, auth, project).json()["ref"]
    for handle in ["claude", "person", "", "person"]:
        client.patch(f"/api/v1/items/{ref}", headers=auth, json={"assignee": handle}).raise_for_status()
    assert client.get(f"/api/v1/items/{ref}", headers=auth).json()["previous_assignee"] is None
