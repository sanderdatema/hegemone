"""Deadline-notificaties in de inbox (BETON-367).

De reden is AFGELEID uit de datum, niet uit een event — er is geen event als een
datum verstrijkt. Deze tests pinnen dat gedrag: welke items een deadline-entry
opleveren, voor wie, en wanneer hij als gelezen geldt.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from betonning.repo import users as users_repo

from conftest import _create


def _day(offset: int) -> str:
    # SQLite date('now') gebruikt UTC, onafhankelijk van de lokale tijdzone.
    return (datetime.now(UTC).date() + timedelta(days=offset)).isoformat()


@pytest.fixture
def claude_auth(conn):
    _, key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent"
    )
    return {"Authorization": f"Bearer {key}"}


def _due_entries(client, auth):
    r = client.get("/api/v1/inbox", headers=auth)
    assert r.status_code == 200
    return [e for e in r.json()["items"] if e["reason"] == "due"]


def test_deadline_vandaag_geeft_inbox_entry(client, auth, project):
    _create(client, auth, project, title="Vandaag", assignee="person", due_date=_day(0))
    entries = _due_entries(client, auth)
    assert len(entries) == 1
    assert entries[0]["ref"] == "SOS-1"
    assert entries[0]["overdue"] is False
    assert entries[0]["due_date"] == _day(0)
    assert entries[0]["event_id"] == 0
    assert entries[0]["actor"] is None


def test_verstreken_deadline_is_overdue(client, auth, project):
    _create(client, auth, project, title="Te laat", assignee="person", due_date=_day(-3))
    entries = _due_entries(client, auth)
    assert len(entries) == 1
    assert entries[0]["overdue"] is True


def test_toekomstige_deadline_geeft_geen_entry(client, auth, project):
    _create(client, auth, project, title="Later", assignee="person", due_date=_day(3))
    assert _due_entries(client, auth) == []


def test_deadline_op_eigen_gemaakt_item_zonder_toewijzing(client, auth, claude_auth, project):
    """Ook zonder toewijzing: wie het item maakte krijgt de deadline te zien."""
    _create(client, auth, project, title="Van mij", due_date=_day(-1))
    assert len(_due_entries(client, auth)) == 1
    # Een derde krijgt hem niet.
    assert _due_entries(client, claude_auth) == []


def test_afgerond_item_geeft_geen_deadline(client, auth, project):
    r = _create(client, auth, project, title="Klaar", assignee="person", due_date=_day(-2))
    ref = r.json()["ref"]
    client.patch(f"/api/v1/items/{ref}", json={"state": "Done"}, headers=auth)
    assert _due_entries(client, auth) == []


def test_gearchiveerd_item_geeft_geen_deadline(client, auth, project):
    r = _create(client, auth, project, title="Weg", assignee="person", due_date=_day(-2))
    ref = r.json()["ref"]
    client.delete(f"/api/v1/items/{ref}", headers=auth)
    assert _due_entries(client, auth) == []


def test_item_zonder_deadline_geeft_geen_entry(client, auth, project):
    _create(client, auth, project, title="Geen datum", assignee="person")
    assert _due_entries(client, auth) == []


def test_deadline_telt_mee_in_unread_count_en_klaart_op_na_openen(client, auth, project):
    r = _create(client, auth, project, title="Te laat", assignee="person", due_date=_day(-1))
    ref = r.json()["ref"]
    before = client.get("/api/v1/inbox", headers=auth).json()
    assert before["unread_count"] >= 1
    assert _due_entries(client, auth)[0]["read"] is False

    # Ticket openen (per-item read-state, BETON-294) = deadline gezien.
    assert client.post(f"/api/v1/items/{ref}/read", headers=auth).status_code == 200
    entries = _due_entries(client, auth)
    assert entries[0]["read"] is True
    after = client.get("/api/v1/inbox", headers=auth).json()
    assert after["unread_count"] == before["unread_count"] - 1


def test_deadline_entry_krijgt_geen_instructieblok(client, auth, project):
    """`?instructions=true` mag niet omvallen op een entry zonder event."""
    _create(client, auth, project, title="Te laat", assignee="person", due_date=_day(-1))
    r = client.get("/api/v1/inbox?instructions=true", headers=auth)
    assert r.status_code == 200
    due = [e for e in r.json()["items"] if e["reason"] == "due"]
    assert len(due) == 1
    assert due[0]["instruction"] is None

def test_vandaag_komt_van_de_database_klok_niet_van_de_host(
    client, auth, conn, project, monkeypatch
):
    """BETON-484: één klok. De host zegt 'over 5 dagen', de database is leidend."""
    import datetime as dt

    from betonning.repo import milestones as milestones_mod

    class VerdwaaldeHost(dt.date):
        @classmethod
        def today(cls):
            return dt.date.today() + dt.timedelta(days=5)

    monkeypatch.setattr(dt, "date", VerdwaaldeHost)
    monkeypatch.setattr(milestones_mod, "date", VerdwaaldeHost, raising=False)

    db_vandaag = conn.execute("SELECT date('now') AS d").fetchone()["d"]
    _create(client, auth, project, title="Vandaag", assignee="person", due_date=db_vandaag)
    entries = _due_entries(client, auth)
    assert len(entries) == 1
    assert entries[0]["overdue"] is False

    client.post(
        "/api/v1/projects/SOS/milestones",
        json={"name": "v9.9.9", "due_date": db_vandaag},
        headers=auth,
    )
    rows = {
        m["name"]: m
        for m in client.get("/api/v1/projects/SOS/milestones", headers=auth).json()
    }
    assert rows["v9.9.9"]["overdue"] is False
