"""Guardrail-concepten in de inbox (BETON-422).

Persons enige echte kanaal is de UI-inbox: hij heeft geen `webhook_url` en geen
`telegram_chat_id`, dus een fanout naar hem levert nul deliveries. `_reason`
matcht alleen mention / toewijzing / eigen item / gevolgd item — een wachtend
voorstel valt daar buiten. Vandaar een eigen reden, AFGELEID bij het opvragen
(zoals `due_entries`): er is een entry zolang er een concept ligt, en hij
verdwijnt vanzelf zodra het goedgekeurd of afgewezen is.
"""

from __future__ import annotations

import sqlite3

import pytest

from betonning.repo import users as users_repo


@pytest.fixture
def seeded(client, auth, conn: sqlite3.Connection):
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    for title in ("een", "twee"):
        client.post("/api/v1/projects/SOS/items", json={"title": title}, headers=auth)
    return conn


@pytest.fixture
def agent_auth(conn: sqlite3.Connection):
    _, key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent", agent_type="coding"
    )
    conn.commit()
    return {"Authorization": f"Bearer {key}"}


def _propose(client, headers, ref="SOS-1", **body):
    body.setdefault("guardrail_md", "Houd prompts kort.")
    return client.post(
        f"/api/v1/items/{ref}/guardrail/propose", json=body, headers=headers
    )


def _inbox(client, headers):
    return client.get("/api/v1/inbox", headers=headers).json()


def _entries(client, headers):
    return [e for e in _inbox(client, headers)["items"] if e["reason"] == "guardrail"]


def test_concept_geeft_de_mens_een_inbox_entry(seeded, client, auth, agent_auth):
    _propose(client, agent_auth)
    entries = _entries(client, auth)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["ref"] == "SOS-1"
    assert entry["title"] == "een"
    assert entry["type"] == "item.guardrail_proposed"
    assert entry["actor"] == "claude"
    assert entry["event_id"] == 0
    assert entry["read"] is False


def test_concept_telt_mee_in_unread_count(seeded, client, auth, agent_auth):
    before = _inbox(client, auth)["unread_count"]
    _propose(client, agent_auth)
    assert _inbox(client, auth)["unread_count"] == before + 1


def test_entry_verdwijnt_na_goedkeuren(seeded, client, auth, agent_auth):
    _propose(client, agent_auth)
    client.post("/api/v1/items/SOS-1/guardrail/approve", headers=auth)
    assert _entries(client, auth) == []


def test_entry_verdwijnt_na_afwijzen(seeded, client, auth, agent_auth):
    _propose(client, agent_auth)
    client.post("/api/v1/items/SOS-1/guardrail/reject", headers=auth)
    assert _entries(client, auth) == []


def test_agent_krijgt_de_entry_niet(seeded, client, auth, agent_auth):
    """Alleen een mens keurt goed, dus voor een agent is dit geen signaal."""
    _propose(client, agent_auth)
    assert _entries(client, agent_auth) == []


def test_ook_een_opheffingsvoorstel_geeft_een_entry(seeded, client, auth, agent_auth):
    client.post(
        "/api/v1/items/SOS-1/guardrail",
        json={"guardrail_md": "Geldt nu.", "review_by": "2099-01-01"},
        headers=auth,
    )
    _propose(client, agent_auth, kind="lift", reason="niet meer nodig")
    assert len(_entries(client, auth)) == 1


def test_actieve_guardrail_zonder_concept_geeft_geen_entry(seeded, client, auth):
    client.post(
        "/api/v1/items/SOS-1/guardrail",
        json={"guardrail_md": "Geldt nu.", "review_by": "2099-01-01"},
        headers=auth,
    )
    assert _entries(client, auth) == []


def test_gelezen_volgt_uit_het_openen_van_het_ticket(seeded, client, auth, agent_auth):
    _propose(client, agent_auth)
    client.post("/api/v1/items/SOS-1/read", headers=auth)
    entries = _entries(client, auth)
    assert len(entries) == 1
    assert entries[0]["read"] is True


def test_gearchiveerd_ticket_geeft_geen_entry(seeded, client, auth, agent_auth):
    _propose(client, agent_auth)
    client.delete("/api/v1/items/SOS-1", headers=auth)
    assert _entries(client, auth) == []


def test_concept_op_meerdere_tickets_staat_op_volgorde_van_voorstellen(
    seeded, client, auth, agent_auth
):
    _propose(client, agent_auth, ref="SOS-2")
    _propose(client, agent_auth, ref="SOS-1")
    assert [e["ref"] for e in _entries(client, auth)] == ["SOS-2", "SOS-1"]
