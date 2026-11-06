"""BETON-476: globale mapping klasse → model per harnas."""

import pytest

H = "/api/v1/settings/model-classes"


def test_get_seed_voor_iedereen(client, auth):
    r = client.get(H, headers=auth)
    assert r.status_code == 200
    d = r.json()
    assert d["classes"] == ["routine", "standaard", "complex"]
    assert d["mapping"]["claude"] == {
        "routine": "sonnet", "standaard": "sonnet", "complex": "opus"}
    assert d["mapping"]["codex"]["routine"] == "gpt-5.4-mini"


def test_get_zonder_key_401(client):
    assert client.get(H).status_code == 401


def test_put_door_mens(client, auth):
    r = client.put(H, json={"mapping": {"codex": {"complex": "astra"}}}, headers=auth)
    assert r.status_code == 200
    assert r.json()["mapping"] == {"codex": {"complex": "astra"}}
    assert client.get(H, headers=auth).json()["mapping"] == {"codex": {"complex": "astra"}}


def test_put_onbekende_klasse_422(client, auth):
    r = client.put(H, json={"mapping": {"claude": {"zwaar": "opus"}}}, headers=auth)
    assert r.status_code == 422


def test_put_lege_modelnaam_422(client, auth):
    r = client.put(H, json={"mapping": {"claude": {"complex": " "}}}, headers=auth)
    assert r.status_code == 422


def test_put_door_agent_403(client, auth, conn):
    from betonning.repo import users as users_repo

    _, key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent", agent_type="coding"
    )
    h = {"Authorization": f"Bearer {key}"}
    assert client.get(H, headers=h).status_code == 200
    r = client.put(H, json={"mapping": {"claude": {"complex": "x"}}}, headers=h)
    assert r.status_code == 403


def _assigned_trigger():
    return {"type": "assigned", "work_unblocked": False}


@pytest.mark.parametrize("language,expected", [
    ("en", "Work class: complex — your model: opus"),
    ("nl", "Werkklasse: complex — voor jou: opus"),
])
def test_pick_up_noemt_klasse_en_model(monkeypatch, language, expected):
    monkeypatch.setenv("HEGEMONE_LANGUAGE", language)
    from betonning import webhooks

    item = {"ref": "SOS-1", "project": "SOS", "seq": 1, "assignee": "claude"}
    r = webhooks.build_instructions(
        {"handle": "claude"}, item, {"type": "assigned"}, {"work_allowed": True},
        event_type="item.updated", model_hint={"class": "complex", "model": "opus"},
    )
    assert r["expected_action"] == "pick_up"
    assert expected in r["instructions"]


@pytest.mark.parametrize("language,prefix", [("en", "Work class"), ("nl", "Werkklasse")])
def test_pick_up_zonder_hint_ongewijzigd(monkeypatch, language, prefix):
    monkeypatch.setenv("HEGEMONE_LANGUAGE", language)
    from betonning import webhooks

    item = {"ref": "SOS-1", "project": "SOS", "seq": 1, "assignee": "claude"}
    r = webhooks.build_instructions(
        {"handle": "claude"}, item, {"type": "assigned"}, {"work_allowed": True},
        event_type="item.updated",
    )
    assert prefix not in r["instructions"]


def test_hint_for_per_harnas(conn, project, client, auth):
    from betonning.repo import model_classes as mc

    client.post("/api/v1/projects/SOS/labels", json={"name": "complex"}, headers=auth)
    client.post(
        "/api/v1/projects/SOS/items", json={"title": "x", "labels": ["complex"]}, headers=auth
    )
    item_id = conn.execute("SELECT id FROM items").fetchone()[0]
    assert mc.hint_for(conn, item_id, "claude") == {"class": "complex", "model": "opus"}
    assert mc.hint_for(conn, item_id, "codex") == {"class": "complex", "model": "gpt-5.5"}
    assert mc.hint_for(conn, item_id, "smid") is None
