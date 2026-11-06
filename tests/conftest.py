"""Pytest-fixtures: geïsoleerde temp-db, TestClient en geseede users."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# MCP-mount standaard uit in de testsuite: tests draaien de app-lifespan vaak
# opnieuw op (elke TestClient), en de FastMCP-session-manager mag maar één keer
# run()'en. In productie draait de lifespan één keer, dus daar staat hij aan.
# De mount zelf wordt gericht getest met create_app(..., enable_mcp=True).
os.environ["BETONNING_MCP_MOUNT"] = "0"

from betonning import db as db_module
from betonning.repo import users as users_repo
from betonning.server import create_app


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path: str) -> TestClient:
    # Dispatcher uit: bezorging wordt in de webhook-tests deterministisch getest.
    app = create_app(db_path, enable_dispatcher=False, enable_api_limits=False)
    with TestClient(app) as c:  # context manager draait lifespan → migraties
        yield c


@pytest.fixture
def conn(db_path: str, client: TestClient) -> sqlite3.Connection:
    """Directe connectie naar dezelfde db (na migratie via client-lifespan)."""
    c = db_module.connect(db_path)
    yield c
    c.close()


@pytest.fixture
def user_key(conn: sqlite3.Connection) -> str:
    """Een user aanmaken en de ruwe API-key teruggeven."""
    _, key = users_repo.create(
        conn, handle="person", display_name="Person", kind="human"
    )
    return key


@pytest.fixture
def auth(user_key: str) -> dict:
    return {"Authorization": f"Bearer {user_key}"}


@pytest.fixture
def project(client: TestClient, auth: dict) -> str:
    """Kaal project 'SOS', geen items/labels. Testfiles die meer seeding nodig
    hebben (items/labels) overriden deze fixture lokaal en nemen 'm als param
    (pytest-idioom voor fixture-override), zodat de aanmaak niet dubbel gebeurt.
    """
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    return "SOS"


def _create(client: TestClient, auth: dict, project: str, **body):
    """Gedeelde API-helper (was 3x byte-identiek gekopieerd: test_activity.py,
    test_inbox.py, test_items.py). Losse functie i.p.v. fixture zodat de
    honderden bestaande callsites (`_create(client, auth, project, **body)`)
    ongewijzigd blijven — alleen `from conftest import _create` toevoegen."""
    body.setdefault("title", "Iets")
    return client.post(f"/api/v1/projects/{project}/items", json=body, headers=auth)


@pytest.fixture
def seed_cast(conn: sqlite3.Connection) -> dict:
    """Seedt de vaste testcast — claude (coding-agent), smid (hermes-agent),
    person (mens), triage (agent) — en geeft de id-dict (serialized user-rows)
    terug. Was 5x met kleine variaties gekopieerd (welke subset, welk
    project-type); bestaande lokale `setup`/`seeded`-fixtures nemen deze als
    param en plukken er alleen de handles uit die ze nodig hebben."""
    claude, _ = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent", agent_type="coding"
    )
    smid, _ = users_repo.create(
        conn, handle="smid", display_name="Smid", kind="agent", agent_type="hermes"
    )
    person, _ = users_repo.create(
        conn, handle="person", display_name="Person", kind="human"
    )
    triage, _ = users_repo.create(
        conn, handle="triage", display_name="Triage", kind="agent"
    )
    conn.commit()
    return {"claude": claude, "smid": smid, "person": person, "triage": triage}


def inject_llm(client: TestClient, value) -> None:
    """Vervang een testprovider via dezelfde snapshotpublicatie als de runtime.

    Rechtstreeks app.state.llm_client overschrijven verandert het reeds
    vastgelegde request-snapshot niet. Dit hulppad blijft uitsluitend in tests.
    """
    from betonning import installation_runtime
    from betonning.repo import installation_settings

    app = client.app
    conn = db_module.connect(app.state.db_path)
    try:
        with app.state.runtime_lock:
            app.state.runtime_overrides["llm_client"] = value
            snapshot = installation_runtime.prepare(app, installation_settings.get(conn))
            installation_runtime.publish(app, snapshot)
    finally:
        conn.close()
