"""Korte aanleiding verplicht bij agent → mens (BETON-469)."""
import pytest
from conftest import _create
from betonning.repo import users as users_repo


@pytest.fixture
def agent(conn, auth):
    _, key = users_repo.create(conn, handle="claude", display_name="Claude", kind="agent")
    conn.commit()
    return {"Authorization": f"Bearer {key}"}


def test_handover_verplicht_en_atomair(client, auth, project, agent, monkeypatch):
    monkeypatch.setenv("HEGEMONE_LANGUAGE", "nl")
    ref = _create(client, auth, project, assignee="claude").json()["ref"]
    response = client.patch(f"/api/v1/items/{ref}", headers=agent, json={"assignee": "person", "title": "Niet opslaan"})
    assert response.status_code == 422
    assert "handover_md" in response.json()["detail"]
    item = client.get(f"/api/v1/items/{ref}", headers=auth).json()
    assert item["assignee"] == "claude"
    assert item["title"] != "Niet opslaan"
    response = client.patch(f"/api/v1/items/{ref}", headers=agent, json={"assignee": "person", "handover_md": "Test de nieuwe knop."})
    assert response.status_code == 200
    item = client.get(f"/api/v1/items/{ref}", headers=auth).json()
    assert item["comments"][0]["body_md"] == "**Nodig van @person:** Test de nieuwe knop."
    assert item["comments"][0]["author"] == "claude"


@pytest.mark.parametrize("note", ["", "  ", "x" * 301, "Eerste regel\nTweede regel"])
def test_handover_validatie(client, auth, project, agent, note):
    ref = _create(client, auth, project).json()["ref"]
    assert client.patch(f"/api/v1/items/{ref}", headers=agent, json={"assignee": "person", "handover_md": note}).status_code == 422


def test_eigen_open_vraag_of_mens_heeft_geen_notitie_nodig(client, auth, project, agent):
    ref = _create(client, auth, project).json()["ref"]
    # Een mens mag zonder notitie overdragen.
    assert client.patch(f"/api/v1/items/{ref}", headers=auth, json={"assignee": "claude"}).status_code == 200
    assert client.post(f"/api/v1/items/{ref}/comments", headers=agent, json={"kind": "question", "body_md": "@person, wil je testen?"}).status_code == 201
    # De vraagmodule wijst zelf toe; een no-op-PATCH blijft toegestaan.
    assert client.patch(f"/api/v1/items/{ref}", headers=agent, json={"assignee": "person"}).status_code == 200


def test_agent_naar_agent_en_noop_ongewijzigd(client, auth, project, agent):
    ref = _create(client, auth, project).json()["ref"]
    assert client.patch(f"/api/v1/items/{ref}", headers=agent, json={"assignee": "claude"}).status_code == 200
    assert client.patch(f"/api/v1/items/{ref}", headers=agent, json={"assignee": "claude"}).status_code == 200


def test_handover_komt_in_inbox(client, auth, project, agent):
    ref = _create(client, auth, project, assignee="claude").json()["ref"]
    client.patch(f"/api/v1/items/{ref}", headers=agent, json={"assignee": "person", "handover_md": "Controleer de knop."}).raise_for_status()
    entries = client.get("/api/v1/inbox", headers=auth).json()["items"]
    assigned = next(e for e in entries if e["ref"] == ref and e["reason"] == "assigned")
    assert assigned["handover_md"] == "Controleer de knop."


def test_eigen_vraag_staat_echte_overdracht_toe(client, auth, project, agent):
    ref = _create(client, auth, project).json()["ref"]
    client.post(f"/api/v1/items/{ref}/comments", headers=agent, json={"kind": "question", "body_md": "@person, wil je testen?"}).raise_for_status()
    client.patch(f"/api/v1/items/{ref}", headers=auth, json={"assignee": "claude"}).raise_for_status()
    assert client.patch(f"/api/v1/items/{ref}", headers=agent, json={"assignee": "person"}).status_code == 200


def test_andermans_vraag_telt_niet(client, auth, project, agent):
    ref = _create(client, auth, project).json()["ref"]
    client.post(f"/api/v1/items/{ref}/comments", headers=auth, json={"kind": "question", "body_md": "Wil je testen?"}).raise_for_status()
    assert client.patch(f"/api/v1/items/{ref}", headers=agent, json={"assignee": "person"}).status_code == 422


def test_notitie_en_overdracht_rollen_samen_terug(client, auth, project, agent, monkeypatch):
    from betonning.repo import events as events_repo
    ref = _create(client, auth, project, assignee="claude").json()["ref"]
    record = events_repo.record
    def fail_update(conn, **kwargs):
        if kwargs["type"] == "item.updated":
            raise RuntimeError("Gesimuleerde eventfout")
        return record(conn, **kwargs)
    monkeypatch.setattr(events_repo, "record", fail_update)
    with pytest.raises(RuntimeError, match="eventfout"):
        client.patch(f"/api/v1/items/{ref}", headers=agent, json={"assignee": "person", "handover_md": "Test de knop."})
    item = client.get(f"/api/v1/items/{ref}", headers=auth).json()
    assert item["assignee"] == "claude"
    assert item["comments"] == []


def test_notitie_omzeilt_gesloten_ticket_niet(client, auth, project, agent):
    ref = _create(client, auth, project, assignee="claude", state="done").json()["ref"]
    response = client.patch(f"/api/v1/items/{ref}", headers=agent, json={"assignee": "person", "handover_md": "Test de knop."})
    assert response.status_code == 409
    item = client.get(f"/api/v1/items/{ref}", headers=auth).json()
    assert item["assignee"] == "claude"
    assert item["comments"] == []


def test_notitie_omzeilt_noodstop_niet(client, auth, project, agent):
    ref = _create(client, auth, project, assignee="claude").json()["ref"]
    client.post(f"/api/v1/items/{ref}/lock", headers=auth).raise_for_status()
    response = client.patch(f"/api/v1/items/{ref}", headers=agent, json={"assignee": "person", "handover_md": "Test de knop."})
    assert response.status_code == 409
    item = client.get(f"/api/v1/items/{ref}", headers=auth).json()
    assert item["assignee"] == "claude"
    assert item["comments"] == []


def test_overdrachtsnotitie_telt_mee_voor_commentdrempel(client, auth, project, agent, conn):
    ref = _create(client, auth, project, assignee="claude").json()["ref"]
    conn.execute("UPDATE items SET comment_limit = 1")
    conn.commit()
    response = client.patch(f"/api/v1/items/{ref}", headers=agent, json={"assignee": "person", "handover_md": "Test de knop."})
    assert response.status_code == 200
    assert response.json()["locked_at"] is not None
    assert response.json()["previous_assignee"] == "claude"
