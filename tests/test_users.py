"""Agent-/user-beheer (BETON-72): admin-CRUD achter current_human + rolonderscheid."""

from __future__ import annotations

import pytest

from betonning import db as db_module
from betonning.repo import users as users_repo
from betonning.security import hash_api_key


@pytest.fixture
def agent_key(conn) -> str:
    """Een agent-user (kind='agent') met eigen key — mag GEEN admin-CRUD doen."""
    _, key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent"
    )
    conn.commit()
    return key


@pytest.fixture
def agent_auth(agent_key) -> dict:
    return {"Authorization": f"Bearer {agent_key}"}


# --- Happy path (mens) -----------------------------------------------------


def test_human_creates_agent_with_description_and_gets_key_once(client, auth):
    r = client.post(
        "/api/v1/users",
        json={
            "handle": "lobke",
            "display_name": "Lobke",
            "kind": "agent",
            "description": "Documentatie en teksten",
        },
        headers=auth,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["handle"] == "lobke"
    assert body["description"] == "Documentatie en teksten"
    assert body["kind"] == "agent"
    # Ruwe key wordt exact één keer teruggegeven bij create.
    assert body.get("api_key")

    # GET /users bevat de nieuwe agent incl. description, maar NOOIT de ruwe key.
    users = client.get("/api/v1/users", headers=auth).json()
    lobke = next(u for u in users if u["handle"] == "lobke")
    assert lobke["description"] == "Documentatie en teksten"
    assert "api_key" not in lobke


def test_human_updates_description_and_active(client, auth):
    client.post(
        "/api/v1/users",
        json={"handle": "smid", "display_name": "Smid", "kind": "agent"},
        headers=auth,
    )
    r = client.patch(
        "/api/v1/users/smid",
        json={"description": "Backend-specialist", "display_name": "De Smid"},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["description"] == "Backend-specialist"
    assert r.json()["display_name"] == "De Smid"


def test_human_deactivates_agent(client, auth, conn):
    create = client.post(
        "/api/v1/users",
        json={"handle": "joop", "display_name": "Joop", "kind": "agent"},
        headers=auth,
    )
    raw_key = create.json()["api_key"]
    assert client.delete("/api/v1/users/joop", headers=auth).status_code == 204

    # Gedeactiveerd → active=0 en de key werkt niet meer (get_by_api_key filtert).
    row = users_repo.get_by_handle(conn, "joop")
    assert bool(row["active"]) is False
    assert (
        client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {raw_key}"}
        ).status_code
        == 401
    )


def test_human_rotates_user_api_key_once(client, auth, conn):
    create = client.post(
        "/api/v1/users",
        json={"handle": "codex", "display_name": "Codex", "kind": "agent"},
        headers=auth,
    )
    old_key = create.json()["api_key"]

    r = client.post("/api/v1/users/codex/api-key/rotate", headers=auth)
    assert r.status_code == 200
    body = r.json()
    new_key = body["api_key"]
    assert new_key.startswith("bt_")
    assert new_key != old_key
    assert body["handle"] == "codex"
    assert "api_key_hash" not in body

    assert (
        client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {old_key}"}
        ).status_code
        == 401
    )
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {new_key}"})
    assert me.status_code == 200
    assert me.json()["handle"] == "codex"

    row = users_repo.get_by_handle(conn, "codex")
    assert row["api_key_hash"] == hash_api_key(new_key)
    assert row["api_key_hash"] != new_key

    users = client.get("/api/v1/users", headers=auth).json()
    codex = next(u for u in users if u["handle"] == "codex")
    assert "api_key" not in codex
    assert "api_key_hash" not in codex


def test_agent_cannot_rotate_api_key(client, auth, agent_auth):
    client.post(
        "/api/v1/users",
        json={"handle": "codex", "display_name": "Codex", "kind": "agent"},
        headers=auth,
    )
    r = client.post("/api/v1/users/codex/api-key/rotate", headers=agent_auth)
    assert r.status_code == 403


def test_rotate_api_key_unknown_handle_404(client, auth):
    r = client.post("/api/v1/users/nietbestaand/api-key/rotate", headers=auth)
    assert r.status_code == 404


# --- Rolonderscheid: agent krijgt 403 --------------------------------------


def test_agent_cannot_create(client, agent_auth):
    r = client.post(
        "/api/v1/users",
        json={"handle": "x", "display_name": "X", "kind": "agent"},
        headers=agent_auth,
    )
    assert r.status_code == 403


def test_agent_cannot_update(client, auth, agent_auth):
    client.post(
        "/api/v1/users",
        json={"handle": "vic", "display_name": "Vic", "kind": "agent"},
        headers=auth,
    )
    assert (
        client.patch(
            "/api/v1/users/vic", json={"description": "hack"}, headers=agent_auth
        ).status_code
        == 403
    )


def test_agent_cannot_delete(client, auth, agent_auth):
    client.post(
        "/api/v1/users",
        json={"handle": "vic", "display_name": "Vic", "kind": "agent"},
        headers=auth,
    )
    assert client.delete("/api/v1/users/vic", headers=agent_auth).status_code == 403


# --- Validatie / randgevallen ---------------------------------------------


def test_duplicate_handle_409(client, auth):
    client.post(
        "/api/v1/users",
        json={"handle": "dup", "display_name": "Dup", "kind": "agent"},
        headers=auth,
    )
    r = client.post(
        "/api/v1/users",
        json={"handle": "dup", "display_name": "Dup2", "kind": "agent"},
        headers=auth,
    )
    assert r.status_code == 409


# --- Handle-validatie (BETON-385) ------------------------------------------


@pytest.mark.parametrize(
    "handle",
    ["a b", "a/b", "<x>", "_x", "a" * 33, ""],
)
def test_create_with_invalid_handle_422(client, auth, handle):
    r = client.post(
        "/api/v1/users",
        json={"handle": handle, "display_name": "X", "kind": "agent"},
        headers=auth,
    )
    assert r.status_code == 422


def test_create_with_valid_handle_containing_hyphen_and_digit_201(client, auth):
    r = client.post(
        "/api/v1/users",
        json={"handle": "Claude-2", "display_name": "Claude 2", "kind": "agent"},
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["handle"] == "Claude-2"


def test_create_strips_leading_at_from_handle(client, auth):
    r = client.post(
        "/api/v1/users",
        json={"handle": "@person2", "display_name": "Person 2", "kind": "agent"},
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["handle"] == "person2"


def test_update_unknown_handle_404(client, auth):
    assert (
        client.patch(
            "/api/v1/users/nietbestaand", json={"description": "x"}, headers=auth
        ).status_code
        == 404
    )


def test_delete_unknown_handle_404(client, auth):
    assert client.delete("/api/v1/users/nietbestaand", headers=auth).status_code == 404


def test_human_cannot_deactivate_self(client, auth):
    # De person-fixture (user_key) is de ingelogde mens → mag zichzelf niet uitsluiten.
    assert client.delete("/api/v1/users/person", headers=auth).status_code == 400


def test_create_requires_auth(client):
    assert (
        client.post(
            "/api/v1/users", json={"handle": "x", "display_name": "X"}
        ).status_code
        == 401
    )


# --- assignable_agents (BETON-67 helper) -----------------------------------


# --- agent_type (BETON-88 fundament, BETON-82) -----------------------------


def test_create_agent_with_coding_agent_type(client, auth):
    r = client.post(
        "/api/v1/users",
        json={
            "handle": "codex",
            "display_name": "Codex",
            "kind": "agent",
            "agent_type": "coding",
        },
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["agent_type"] == "coding"


def test_create_agent_with_hermes_agent_type(client, auth):
    r = client.post(
        "/api/v1/users",
        json={
            "handle": "smid",
            "display_name": "Smid",
            "kind": "agent",
            "agent_type": "hermes",
        },
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["agent_type"] == "hermes"


def test_create_human_with_agent_type_422(client, auth):
    r = client.post(
        "/api/v1/users",
        json={
            "handle": "mens",
            "display_name": "Mens",
            "kind": "human",
            "agent_type": "coding",
        },
        headers=auth,
    )
    assert r.status_code == 422


def test_create_with_invalid_agent_type_422(client, auth):
    r = client.post(
        "/api/v1/users",
        json={
            "handle": "x",
            "display_name": "X",
            "kind": "agent",
            "agent_type": "bogus",
        },
        headers=auth,
    )
    assert r.status_code == 422


def test_admin_update_sets_agent_type(client, auth):
    client.post(
        "/api/v1/users",
        json={"handle": "smid", "display_name": "Smid", "kind": "agent"},
        headers=auth,
    )
    r = client.patch("/api/v1/users/smid", json={"agent_type": "hermes"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["agent_type"] == "hermes"


def test_admin_update_agent_type_on_human_is_422(client, auth):
    client.post(
        "/api/v1/users",
        json={"handle": "mens", "display_name": "Mens", "kind": "human"},
        headers=auth,
    )
    r = client.patch("/api/v1/users/mens", json={"agent_type": "coding"}, headers=auth)
    assert r.status_code == 422


def test_new_agent_without_explicit_agent_type_is_null(conn):
    # create() zet geen agent_type automatisch — dat is de backfill-taak van
    # migratie 022 zelf (voor bestaande data uit vóór die migratie).
    users_repo.create(conn, handle="lobke", display_name="Lobke", kind="agent")
    conn.commit()
    row = users_repo.get_by_handle(conn, "lobke")
    assert row["agent_type"] is None


def test_migration_022_backfills_coding_and_hermes_agent_type(tmp_path):
    # Simuleert data van vóór migratie 022: users op het oude schema (zonder
    # agent_type-kolom), waaronder de twee bekende coding-harnasen en een
    # willekeurige Hermes-agent + de triage-bot + een mens.
    db_path = str(tmp_path / "backfill.db")
    conn = db_module.connect(db_path)
    migrations = db_module._migration_files()
    for version, sql in migrations:
        if version >= 22:
            continue
        conn.executescript(sql)
        conn.execute(f"PRAGMA user_version = {version}")

    for handle, kind in (
        ("claude", "agent"),
        ("codex", "agent"),
        ("smid", "agent"),
        ("triage", "agent"),
        ("person", "human"),
    ):
        conn.execute(
            "INSERT INTO users (handle, display_name, kind, api_key_hash) "
            "VALUES (?, ?, ?, ?)",
            (handle, handle, kind, f"hash-{handle}"),
        )
    conn.commit()

    body = next(sql for version, sql in migrations if version == 22)
    conn.executescript(body)
    conn.execute("PRAGMA user_version = 22")
    conn.commit()

    def agent_type(handle):
        return conn.execute(
            "SELECT agent_type FROM users WHERE handle = ?", (handle,)
        ).fetchone()["agent_type"]

    assert agent_type("claude") == "coding"
    assert agent_type("codex") == "coding"
    assert agent_type("smid") == "hermes"
    assert agent_type("triage") is None
    assert agent_type("person") is None
    conn.close()


# --- admin kan webhook_url zetten (BETON-83/84, BETON-82) ------------------


def test_admin_sets_webhook_url_on_agent(client, auth):
    client.post(
        "/api/v1/users",
        json={
            "handle": "smid",
            "display_name": "Smid",
            "kind": "agent",
            "agent_type": "hermes",
        },
        headers=auth,
    )
    r = client.patch(
        "/api/v1/users/smid",
        json={"webhook_url": "http://hermes.local/hook", "webhook_secret": "s3cret"},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["has_webhook"] is True


def test_create_agent_with_webhook_url_has_webhook_true(client, auth):
    r = client.post(
        "/api/v1/users",
        json={
            "handle": "hermesagent",
            "display_name": "Hermesagent",
            "kind": "agent",
            "agent_type": "hermes",
            "webhook_url": "http://hermes.local/hook",
            "webhook_secret": "s3cret",
        },
        headers=auth,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["has_webhook"] is True
    # BETON-113: de create-response is mens-only, dus de URL mag terugkomen
    # (geen geheim) — maar het secret nooit.
    assert body["webhook_url"] == "http://hermes.local/hook"
    assert "webhook_secret" not in body


def test_patch_webhook_url_null_clears_it(client, auth):
    client.post(
        "/api/v1/users",
        json={
            "handle": "wisagent",
            "display_name": "Wisagent",
            "kind": "agent",
            "agent_type": "hermes",
            "webhook_url": "http://hermes.local/hook",
        },
        headers=auth,
    )
    r = client.patch(
        "/api/v1/users/wisagent",
        json={"webhook_url": None, "webhook_secret": None},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["has_webhook"] is False


# --- GET /users/{handle} detail (BETON-113): webhook_url zichtbaar voor mens --


def test_get_user_detail_includes_webhook_url(client, auth):
    client.post(
        "/api/v1/users",
        json={
            "handle": "smid2",
            "display_name": "Smid2",
            "kind": "agent",
            "agent_type": "hermes",
            "webhook_url": "http://hermes.local/hook",
            "webhook_secret": "s3cret",
        },
        headers=auth,
    )
    r = client.get("/api/v1/users/smid2", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["webhook_url"] == "http://hermes.local/hook"
    # Het secret komt hier nooit in mee, ook niet voor een mens.
    assert "webhook_secret" not in body


def test_get_user_detail_forbidden_for_agent(client, auth):
    client.post(
        "/api/v1/users",
        json={"handle": "smid3", "display_name": "Smid3", "kind": "agent"},
        headers=auth,
    )
    r = client.post(
        "/api/v1/users",
        json={"handle": "otheragent", "display_name": "Other", "kind": "agent"},
        headers=auth,
    )
    agent_key = r.json()["api_key"]
    agent_auth = {"Authorization": f"Bearer {agent_key}"}
    r = client.get("/api/v1/users/smid3", headers=agent_auth)
    assert r.status_code == 403


def test_get_user_detail_404_for_unknown_handle(client, auth):
    r = client.get("/api/v1/users/nietbestaand", headers=auth)
    assert r.status_code == 404


def test_assignable_agents_excludes_triage_and_inactive(conn):
    users_repo.create(conn, handle="person", display_name="Person", kind="human")
    users_repo.create(
        conn,
        handle="claude",
        display_name="Claude",
        kind="agent",
        description="Generieke coder",
    )
    users_repo.create(conn, handle="triage", display_name="Triage", kind="agent")
    lobke, _ = users_repo.create(
        conn, handle="lobke", display_name="Lobke", kind="agent", description="Docs"
    )
    gone, _ = users_repo.create(conn, handle="weg", display_name="Weg", kind="agent")
    users_repo.deactivate(conn, gone["id"])
    conn.commit()

    agents = users_repo.assignable_agents(conn)
    handles = {a["handle"] for a in agents}
    assert "claude" in handles and "lobke" in handles
    assert "triage" not in handles  # de bot wijst niet aan zichzelf toe
    assert "person" not in handles  # geen agent
    assert "weg" not in handles  # inactief
    assert next(a for a in agents if a["handle"] == "lobke")["description"] == "Docs"


def test_migration_seeds_virtual_assignees(conn):
    """BETON-207: migratie 027 seedt de twee virtuele assignees, gemarkeerd als
    is_virtual, met een passende agent_type."""
    coding = users_repo.get_by_handle(conn, "coding-agent")
    hermes = users_repo.get_by_handle(conn, "hermes-agent")
    assert coding is not None and hermes is not None
    assert users_repo.serialize(coding)["is_virtual"] is True
    assert users_repo.serialize(hermes)["is_virtual"] is True
    assert coding["agent_type"] == "coding" and hermes["agent_type"] == "hermes"


def test_collapse_to_virtual_folds_only_concrete_coding_agents(conn):
    """BETON-207: concrete coding-agents (agent_type='coding', niet-virtueel) klappen
    naar de gedeelde queue; mensen, Hermes-agents en de virtuele assignees blijven."""
    users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent", agent_type="coding"
    )
    users_repo.create(
        conn, handle="lobke", display_name="Lobke", kind="agent", agent_type="hermes"
    )
    users_repo.create(conn, handle="person", display_name="Person", kind="human")
    conn.commit()
    assert users_repo.collapse_to_virtual(conn, "claude") == "coding-agent"
    assert users_repo.collapse_to_virtual(conn, "lobke") == "lobke"
    assert users_repo.collapse_to_virtual(conn, "person") == "person"
    # De virtuele coding-agent klapt niet naar zichzelf/oneindig.
    assert users_repo.collapse_to_virtual(conn, "coding-agent") == "coding-agent"
    # Onbekende handle blijft ongemoeid (val terug, geen crash).
    assert users_repo.collapse_to_virtual(conn, "nietbestaand") == "nietbestaand"
    assert users_repo.collapse_to_virtual(conn, None) is None


def test_visible_queue_ids_includes_matching_virtual_queue(conn):
    """BETON-207: een coding-agent ziet z'n eigen id + de coding-agent-queue;
    een Hermes-agent + de hermes-agent-queue; mensen alleen zichzelf."""
    coding = users_repo.get_by_handle(conn, "coding-agent")
    hermesq = users_repo.get_by_handle(conn, "hermes-agent")
    claude, _ = users_repo.create(
        conn, handle="claude", display_name="C", kind="agent", agent_type="coding"
    )
    smid, _ = users_repo.create(
        conn, handle="smid", display_name="S", kind="agent", agent_type="hermes"
    )
    person, _ = users_repo.create(conn, handle="person", display_name="S", kind="human")
    conn.commit()
    assert set(users_repo.visible_queue_ids(conn, claude)) == {
        claude["id"],
        coding["id"],
    }
    assert set(users_repo.visible_queue_ids(conn, smid)) == {smid["id"], hermesq["id"]}
    assert users_repo.visible_queue_ids(conn, person) == [person["id"]]
    # De virtuele queue zelf breidt niet verder uit.
    assert users_repo.visible_queue_ids(conn, coding) == [coding["id"]]


def test_is_hermes_agent(conn):
    """BETON-213: agent_type-helpers onderscheiden Hermes- van coding-agents."""
    lobke, _ = users_repo.create(
        conn, handle="lobke", display_name="Lobke", kind="agent", agent_type="hermes"
    )
    claude, _ = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent", agent_type="coding"
    )
    person, _ = users_repo.create(conn, handle="person", display_name="S", kind="human")
    conn.commit()
    assert users_repo.is_hermes_agent(lobke)
    assert not users_repo.is_hermes_agent(claude)
    assert not users_repo.is_hermes_agent(person)


# --- Webhook-URL van een agent: mensenwerk, maar begrensd (BETON-378) ------


def test_human_sets_agent_webhook(client, auth):
    """De BETON-83/84-route blijft werken: een Hermes-agent heeft geen eigen key,
    dus de mens zet zijn webhook hier."""
    client.post(
        "/api/v1/users",
        json={"handle": "smid", "display_name": "Smid", "kind": "agent"},
        headers=auth,
    )
    r = client.patch(
        "/api/v1/users/smid",
        json={"webhook_url": "https://hermes.example/hook", "webhook_secret": "s3cret"},
        headers=auth,
    )
    assert r.status_code == 200
    assert client.get("/api/v1/users/smid", headers=auth).json()["webhook_url"] == (
        "https://hermes.example/hook"
    )


def test_human_cannot_point_agent_webhook_at_loopback(client, auth):
    client.post(
        "/api/v1/users",
        json={"handle": "smid", "display_name": "Smid", "kind": "agent"},
        headers=auth,
    )
    r = client.patch(
        "/api/v1/users/smid",
        json={"webhook_url": "http://127.0.0.1:8000/hook"},
        headers=auth,
    )
    assert r.status_code == 422
    assert client.get("/api/v1/users/smid", headers=auth).json()["webhook_url"] is None


def test_create_user_validates_webhook_url(client, auth):
    r = client.post(
        "/api/v1/users",
        json={
            "handle": "smid",
            "display_name": "Smid",
            "kind": "agent",
            "webhook_url": "http://169.254.169.254/latest",
        },
        headers=auth,
    )
    assert r.status_code == 422


def test_clearing_agent_webhook_still_allowed(client, auth):
    client.post(
        "/api/v1/users",
        json={
            "handle": "smid",
            "display_name": "Smid",
            "kind": "agent",
            "webhook_url": "https://hermes.example/hook",
        },
        headers=auth,
    )
    r = client.patch("/api/v1/users/smid", json={"webhook_url": None}, headers=auth)
    assert r.status_code == 200
    assert r.json()["webhook_url"] is None
