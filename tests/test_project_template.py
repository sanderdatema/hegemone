"""BETON-490: template werkt uitsluitend door naar nieuwe projecten."""

import pytest

URL = "/api/v1/settings/project-template"


def test_template_roundtrip_and_creation(client, auth):
    original = client.get(URL, headers=auth).json()["states"]
    assert len(original) == 6
    client.post("/api/v1/projects", json={"key": "OUD", "name": "Oud"}, headers=auth)
    states = [dict(name="Idee", group="backlog", color="#123456", is_default=True,
                   closed=False, blocks_work=True),
              dict(name="Klaar", group="completed", color="#abcdef", is_default=False,
                   closed=True, blocks_work=False)]
    assert client.put(URL, json={"states": states}, headers=auth).json()["states"] == states
    assert client.get(URL, headers=auth).json()["states"] == states
    assert client.post("/api/v1/projects", json={"key": "NIEUW", "name": "Nieuw"}, headers=auth).status_code == 201
    actual = client.get("/api/v1/projects/NIEUW/states", headers=auth).json()
    assert [s["name"] for s in actual] == ["Idee", "Klaar"]
    for result, expected in zip(actual, states):
        for key, value in expected.items():
            assert result[key] == value
    assert len(client.get("/api/v1/projects/OUD/states", headers=auth).json()) == 6
    item = client.post("/api/v1/projects/NIEUW/items", json={"title": "Eerste"}, headers=auth).json()
    assert item["state"] == "Idee"


@pytest.mark.parametrize("states", [[], [{}], [dict(name=" ", group="backlog", is_default=True)],
    [dict(name="A", group="unknown", is_default=True)],
    [dict(name="A", group="backlog", is_default=False)],
    [dict(name="A", group="backlog", is_default=True, color="rood")],
    [dict(name="A", group="backlog", is_default=True)] * 2])
def test_invalid_template_atomic(client, auth, states):
    before = client.get(URL, headers=auth).json()
    assert client.put(URL, json={"states": states}, headers=auth).status_code == 422
    assert client.get(URL, headers=auth).json() == before


def test_template_permissions(client, auth, conn):
    from betonning.repo import users
    _, key = users.create(conn, handle="bot", display_name="Bot", kind="agent")
    agent = {"Authorization": f"Bearer {key}"}
    assert client.get(URL).status_code == 401
    assert client.put(URL, json={"states": []}).status_code == 401
    states = client.get(URL, headers=agent).json()["states"]
    assert client.put(URL, json={"states": states}, headers=agent).status_code == 403
