"""Portable configuratie: allowlist, preview en atomaire confirmatie."""

import copy

import pytest

from betonning import server
from betonning.repo import configuration, installation_settings, users

BASE = "/api/v1/settings/configuration"
SECRET = "synthetic-secret-not-for-portable-files"


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(server, "load_dotenv", lambda: None)
    for prefix in ["HEGEMONE_", "BETONNING_"]:
        for suffix in [
            "LLM_BASE_URL",
            "LLM_API_KEY",
            "LLM_MODEL",
            "EMBED_BASE_URL",
            "EMBED_API_KEY",
            "EMBED_MODEL",
            "TRIAGE_ENABLED",
            "WIKI_COMPILE_ENABLED",
        ]:
            monkeypatch.delenv(prefix + suffix, raising=False)
    monkeypatch.setenv(
        "HEGEMONE_SETTINGS_SECRET", "synthetic-transfer-encryption-000000000000000"
    )


def export(client, auth):
    response = client.get(BASE + "/export", headers=auth)
    assert response.status_code == 200
    return response.json()


def preview(client, auth, document):
    response = client.post(BASE + "/preview", headers=auth, json=document)
    assert response.status_code == 200
    return response.json()


def confirm(client, auth, token):
    return client.post(
        BASE + "/confirm",
        headers=auth,
        json={"preview_token": token, "confirmed": True},
    )


def test_export_has_only_public_fields_and_no_ticket_wiki_endpoint_or_credentials(
    client, auth, conn, project
):
    user, key = users.create(
        conn,
        handle="portable-agent",
        display_name="Portable agent",
        kind="agent",
        agent_type="coding",
        webhook_url="https://receiver.example/" + SECRET,
        webhook_secret=SECRET,
        description=SECRET,
    )
    client.post(
        f"/api/v1/projects/{project}/items",
        headers=auth,
        json={"title": SECRET, "description_md": SECRET},
    )
    client.patch(
        "/api/v1/settings/installation",
        headers=auth,
        json={
            "schema_version": 1,
            "expected_revision": 0,
            "settings": {"llm": {"api_key": SECRET}},
        },
    )
    response = client.get(BASE + "/export", headers=auth)
    assert (
        response.status_code == 200 and response.headers["cache-control"] == "no-store"
    )
    assert SECRET not in response.text and key not in response.text
    data = response.json()
    assert data["format"] == "hegemone.configuration" and data["version"] == 1
    assert set(data["agents"][0]) == {
        "handle",
        "display_name",
        "agent_type",
        "subscribe_all",
    }
    assert "api_key" not in data["installation"]["llm"]
    assert not any(agent["handle"] == "triage" for agent in data["agents"])


def test_preview_is_readonly_then_confirm_applies_once_and_creates_disabled_agent(
    client, auth, conn
):
    document = export(client, auth)
    document["installation"]["language"] = "nl"
    document["agents"] = [
        {
            "handle": "new-builder",
            "display_name": "Builder",
            "agent_type": "coding",
            "subscribe_all": True,
        }
    ]
    document["projects"] = [
        {
            "key": "NEW",
            "name": "New project",
            "triage_enabled": False,
            "wiki_compile_enabled": False,
            "type_defaults": {"coding": "respond"},
            "agent_overrides": {"new-builder": "assign"},
        }
    ]
    before = configuration.baseline(conn)
    plan = preview(client, auth, document)
    assert (
        plan["can_apply"]
        and plan["changes"]
        and plan["warnings"][0]["code"] == "new_agent_disabled"
    )
    assert configuration.baseline(conn) == before
    assert users.get_by_handle(conn, "new-builder") is None
    response = confirm(client, auth, plan["preview_token"])
    assert response.status_code == 200
    actor = users.get_by_handle(conn, "new-builder")
    assert not actor["active"] and actor["webhook_url"] is None
    assert export(client, auth)["installation"]["language"] == "nl"
    assert confirm(client, auth, plan["preview_token"]).status_code == 409
    assert client.get("/api/v1/projects", headers=auth).json()[0]["key"] == "NEW"


def test_roundtrip_preserves_existing_secrets_and_ticket_columns(
    client, auth, conn, project
):
    _, key = users.create(
        conn,
        handle="existing-builder",
        display_name="Existing",
        kind="agent",
        agent_type="coding",
        webhook_url="https://receiver.example/events",
        webhook_secret=SECRET,
    )
    document = export(client, auth)
    columns = client.get(f"/api/v1/projects/{project}/states", headers=auth).json()
    token = preview(client, auth, document)["preview_token"]
    assert confirm(client, auth, token).status_code == 200
    assert export(client, auth) == document
    existing = users.get_by_handle(conn, "existing-builder")
    assert (
        existing["webhook_secret"] == SECRET
        and existing["webhook_url"] == "https://receiver.example/events"
    )
    assert users.get_by_api_key(conn, key)["handle"] == "existing-builder"
    assert (
        client.get(f"/api/v1/projects/{project}/states", headers=auth).json() == columns
    )


def test_stale_baseline_and_wrong_actor_cannot_confirm(client, auth, conn):
    _, key = users.create(
        conn, handle="other-admin", display_name="Other", kind="human"
    )
    document = export(client, auth)
    token = preview(client, auth, document)["preview_token"]
    assert confirm(client, {"Authorization": f"Bearer {key}"}, token).status_code == 409
    assert confirm(client, auth, token).status_code == 200
    token = preview(client, auth, document)["preview_token"]
    response = client.patch(
        "/api/v1/settings/installation",
        headers=auth,
        json={
            "schema_version": 1,
            "expected_revision": 1,
            "settings": {"language": "nl"},
        },
    )
    assert response.status_code == 200
    assert confirm(client, auth, token).status_code == 409
    assert installation_settings.get(conn)["settings"]["language"] == "nl"


def test_unknown_version_secret_fields_and_confirm_false_are_safe(client, auth):
    document = export(client, auth)
    bad = copy.deepcopy(document)
    bad["version"] = 99
    response = client.post(BASE + "/preview", headers=auth, json=bad)
    assert response.status_code == 422
    bad = copy.deepcopy(document)
    bad["installation"]["llm"]["api_key"] = SECRET
    response = client.post(BASE + "/preview", headers=auth, json=bad)
    assert response.status_code == 422 and SECRET not in response.text
    token = preview(client, auth, document)["preview_token"]
    assert (
        client.post(
            BASE + "/confirm",
            headers=auth,
            json={"preview_token": token, "confirmed": False},
        ).status_code
        == 422
    )
    assert confirm(client, auth, token).status_code == 200


def test_credential_bound_endpoint_and_unknown_agent_are_preview_conflicts(
    client, auth, project
):
    client.patch(
        "/api/v1/settings/installation",
        headers=auth,
        json={
            "schema_version": 1,
            "expected_revision": 0,
            "settings": {
                "llm": {"base_url": "https://original.example", "api_key": SECRET}
            },
        },
    )
    document = export(client, auth)
    document["installation"]["llm"]["base_url"] = "https://different.example"
    document["projects"][0]["agent_overrides"] = {"missing": "assign"}
    plan = preview(client, auth, document)
    assert not plan["can_apply"]
    assert {conflict["code"] for conflict in plan["conflicts"]} == {
        "provider_endpoint_has_key",
        "unknown_agent",
    }
    assert confirm(client, auth, plan["preview_token"]).status_code == 409


def test_expired_preview_and_new_preview_invalidate_old_tokens(client, auth, conn):
    document = export(client, auth)
    first = preview(client, auth, document)["preview_token"]
    second = preview(client, auth, document)["preview_token"]
    assert confirm(client, auth, first).status_code == 409
    conn.execute(
        "UPDATE configuration_imports SET expires_at='2000-01-01T00:00:00.000Z'"
    )
    assert confirm(client, auth, second).status_code == 409
    assert installation_settings.get(conn) is None


def test_apply_failure_rolls_back_every_write_and_keeps_preview_retryable(
    client, auth, conn, monkeypatch
):
    from betonning import configuration_transfer

    document = export(client, auth)
    document["installation"]["language"] = "nl"
    token = preview(client, auth, document)["preview_token"]
    before = configuration.baseline(conn)
    original = configuration_transfer.project_template.replace

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic apply failure")

    monkeypatch.setattr(configuration_transfer.project_template, "replace", fail)
    with pytest.raises(RuntimeError, match="synthetic apply failure"):
        confirm(client, auth, token)
    assert configuration.baseline(conn) == before
    assert (
        conn.execute("SELECT consumed_at FROM configuration_imports").fetchone()[0]
        is None
    )
    monkeypatch.setattr(configuration_transfer.project_template, "replace", original)
    assert confirm(client, auth, token).status_code == 200


def test_admin_scope_agent_and_csrf_guards(client, auth, conn):
    document = export(client, auth)
    _, agent_key = users.create(
        conn, handle="transfer-agent", display_name="Agent", kind="agent"
    )
    agent = {"Authorization": f"Bearer {agent_key}"}
    assert client.get(BASE + "/export", headers=agent).status_code == 403
    assert (
        client.post(BASE + "/preview", headers=agent, json=document).status_code == 403
    )
    human, key = users.create(
        conn, handle="transfer-reader", display_name="Reader", kind="human"
    )
    users.admin_update(conn, human["id"], {"api_key_scopes": ["read", "write"]})
    assert (
        client.get(
            BASE + "/export", headers={"Authorization": f"Bearer {key}"}
        ).status_code
        == 403
    )
    session = client.post("/api/v1/session", headers=auth).json()
    assert client.post(BASE + "/preview", json=document).status_code == 403
    response = client.post(
        BASE + "/preview",
        headers={"X-CSRF-Token": session["csrf_token"]},
        json=document,
    )
    assert response.status_code == 200
    token = response.json()["preview_token"]
    assert (
        client.post(
            BASE + "/confirm", json={"preview_token": token, "confirmed": True}
        ).status_code
        == 403
    )


def test_environment_credential_cannot_be_retargeted_by_import(
    client, auth, monkeypatch
):
    monkeypatch.setenv("HEGEMONE_LLM_API_KEY", SECRET)
    document = export(client, auth)
    document["installation"]["llm"]["base_url"] = "https://different.example"
    plan = preview(client, auth, document)
    assert not plan["can_apply"]
    assert plan["conflicts"] == [{"code": "provider_endpoint_has_key", "target": "llm"}]


def test_preview_is_process_bound_and_requires_boolean_true(client, auth):
    token = preview(client, auth, export(client, auth))["preview_token"]
    response = client.post(
        BASE + "/confirm", headers=auth, json={"preview_token": token, "confirmed": 1}
    )
    assert response.status_code == 422 and token not in response.text
    client.app.state.configuration_instance = "synthetic-different-process"
    assert confirm(client, auth, token).status_code == 409


def test_duplicate_agents_and_delivery_credentials_are_rejected_without_echo(
    client, auth
):
    document = export(client, auth)
    agent = {
        "handle": "builder",
        "display_name": "Builder",
        "agent_type": "coding",
        "subscribe_all": False,
    }
    document["agents"] = [agent, agent]
    assert (
        client.post(BASE + "/preview", headers=auth, json=document).status_code == 422
    )
    document["agents"] = [
        {**agent, "webhook_url": "https://receiver.example/" + SECRET}
    ]
    response = client.post(BASE + "/preview", headers=auth, json=document)
    assert response.status_code == 422 and SECRET not in response.text


def test_existing_human_cannot_be_overwritten_as_agent(client, auth, conn):
    document = export(client, auth)
    document["agents"] = [
        {
            "handle": "person",
            "display_name": "Replace",
            "agent_type": "coding",
            "subscribe_all": True,
        }
    ]
    plan = preview(client, auth, document)
    assert plan["conflicts"] == [{"code": "identity_conflict", "target": "person"}]
    assert confirm(client, auth, plan["preview_token"]).status_code == 409
    assert users.get_by_handle(conn, "person")["kind"] == "human"
