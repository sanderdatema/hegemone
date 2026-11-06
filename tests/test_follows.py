"""Ticket volgen/ontvolgen als mens (BETON-369).

Spiegelbeeld van de per-item mute (BETON-245): een mute haalt je uit de
afgeleide fanout-doelgroep, een follow zet je erin. Deze tests pinnen wie erin
komt, wanneer niet (gericht event, mute) en welke inbox-reden eruit volgt.
"""

from __future__ import annotations

import pytest

from betonning.repo import users as users_repo

from conftest import _create


@pytest.fixture
def claude_auth(conn):
    """Agent met webhook-url zodat een fanout ook echt een delivery oplevert."""
    _, key = users_repo.create(
        conn,
        handle="claude",
        display_name="Claude",
        kind="agent",
        webhook_url="http://127.0.0.1:9/hook",
    )
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def lobke_auth(conn):
    _, key = users_repo.create(
        conn,
        handle="lobke",
        display_name="Lobke",
        kind="agent",
        webhook_url="http://127.0.0.1:9/hook",
    )
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def mens_auth(conn):
    """Tweede mens: volgt tickets die niet van hem zijn."""
    _, key = users_repo.create(conn, handle="mies", display_name="Mies", kind="human")
    return {"Authorization": f"Bearer {key}"}


def _deliveries_for(conn, handle: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM webhook_deliveries d "
        "JOIN users u ON u.id = d.user_id WHERE u.handle = ?",
        (handle,),
    ).fetchone()
    return row["n"]


def _inbox_reasons(client, auth, ref: str) -> list[str]:
    r = client.get("/api/v1/inbox", headers=auth)
    assert r.status_code == 200
    return [e["reason"] for e in r.json()["items"] if e["ref"] == ref]


# --- Endpoints ------------------------------------------------------------


def test_volgen_en_ontvolgen_is_idempotent(client, auth, mens_auth, project):
    ref = _create(client, auth, project, title="Iets").json()["ref"]
    assert client.post(f"/api/v1/items/{ref}/follow", headers=mens_auth).status_code == 204
    assert client.post(f"/api/v1/items/{ref}/follow", headers=mens_auth).status_code == 204
    r = client.get(f"/api/v1/items/{ref}", headers=mens_auth)
    assert r.json()["is_following"] is True

    assert client.delete(f"/api/v1/items/{ref}/follow", headers=mens_auth).status_code == 204
    assert client.delete(f"/api/v1/items/{ref}/follow", headers=mens_auth).status_code == 204
    assert client.get(f"/api/v1/items/{ref}", headers=mens_auth).json()["is_following"] is False


def test_agent_mag_niet_volgen(client, auth, claude_auth, project):
    ref = _create(client, auth, project, title="Iets").json()["ref"]
    assert client.post(f"/api/v1/items/{ref}/follow", headers=claude_auth).status_code == 403
    assert client.delete(f"/api/v1/items/{ref}/follow", headers=claude_auth).status_code == 403


def test_volgen_zonder_key_is_401(client, auth, project):
    ref = _create(client, auth, project, title="Iets").json()["ref"]
    assert client.post(f"/api/v1/items/{ref}/follow").status_code == 401


def test_volgen_van_onbekend_item_is_404(client, mens_auth, project):
    assert client.post("/api/v1/items/SOS-999/follow", headers=mens_auth).status_code == 404


def test_volger_staat_in_het_subscribers_overzicht(client, auth, mens_auth, project):
    ref = _create(client, auth, project, title="Iets").json()["ref"]
    client.post(f"/api/v1/items/{ref}/follow", headers=mens_auth)
    subs = client.get(f"/api/v1/items/{ref}/subscribers", headers=auth).json()["subscribers"]
    mies = [s for s in subs if s["handle"] == "mies"]
    assert len(mies) == 1
    assert mies[0]["following"] is True
    assert mies[0]["muted"] is False


# --- Fanout ---------------------------------------------------------------


def test_zonder_follow_geen_delivery(client, conn, auth, claude_auth, lobke_auth, project):
    """Referentiepunt: zonder mention, toewijzing of follow krijgt lobke niets."""
    ref = _create(client, auth, project, title="Iets").json()["ref"]
    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "hoi"}, headers=claude_auth)
    assert _deliveries_for(conn, "lobke") == 0


def test_volgen_schrijft_zelf_geen_event(client, conn, auth, mens_auth, project):
    """Volgen is geen activiteit op het ticket — het mag niemand notificeren."""
    ref = _create(client, auth, project, title="Iets").json()["ref"]
    before = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    client.post(f"/api/v1/items/{ref}/follow", headers=mens_auth)
    client.delete(f"/api/v1/items/{ref}/follow", headers=mens_auth)
    assert conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"] == before


def test_agent_volger_via_repo_krijgt_delivery(
    client, conn, auth, claude_auth, lobke_auth, project
):
    """De fanout-kant los getest: een volger-rij levert een delivery op.

    Volgen loopt normaal via het mens-only endpoint; hier zetten we de rij
    rechtstreeks zodat we kunnen zien dat `fanout` de volger óók zonder mention,
    toewijzing of eerdere betrokkenheid meeneemt.
    """
    from betonning.repo import follows as follows_repo
    from betonning.repo import items as items_repo

    ref = _create(client, auth, project, title="Iets").json()["ref"]
    item = items_repo.get_by_ref(conn, ref)
    lobke = users_repo.get_by_handle(conn, "lobke")
    follows_repo.follow(conn, item["id"], lobke["id"])
    conn.commit()

    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "hoi"}, headers=claude_auth)
    assert _deliveries_for(conn, "lobke") == 1


def test_gerichte_comment_gaat_niet_naar_een_volger(
    client, conn, auth, claude_auth, lobke_auth, project
):
    """BETON-216-lijn: een comment mét mentions is aan die handles gericht."""
    from betonning.repo import follows as follows_repo
    from betonning.repo import items as items_repo

    ref = _create(client, auth, project, title="Iets").json()["ref"]
    item = items_repo.get_by_ref(conn, ref)
    lobke = users_repo.get_by_handle(conn, "lobke")
    follows_repo.follow(conn, item["id"], lobke["id"])
    conn.commit()

    client.post(
        f"/api/v1/items/{ref}/comments", json={"body_md": "@person kijk jij?"}, headers=claude_auth
    )
    assert _deliveries_for(conn, "lobke") == 0


def test_mute_wint_van_follow(client, conn, auth, claude_auth, lobke_auth, project):
    from betonning.repo import follows as follows_repo
    from betonning.repo import items as items_repo

    ref = _create(client, auth, project, title="Iets").json()["ref"]
    item = items_repo.get_by_ref(conn, ref)
    lobke = users_repo.get_by_handle(conn, "lobke")
    follows_repo.follow(conn, item["id"], lobke["id"])
    conn.commit()
    client.post(f"/api/v1/items/{ref}/subscribers/lobke/mute", headers=auth)

    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "hoi"}, headers=claude_auth)
    assert _deliveries_for(conn, "lobke") == 0


def test_none_agent_blijft_buiten_schot_ondanks_follow(
    client, conn, auth, claude_auth, lobke_auth, project
):
    """De access-poort geldt onverkort: volgen omzeilt hem niet."""
    from betonning.repo import follows as follows_repo
    from betonning.repo import items as items_repo

    ref = _create(client, auth, project, title="Iets").json()["ref"]
    item = items_repo.get_by_ref(conn, ref)
    lobke = users_repo.get_by_handle(conn, "lobke")
    follows_repo.follow(conn, item["id"], lobke["id"])
    conn.commit()
    r = client.put(
        f"/api/v1/projects/{project}/access/agent/lobke",
        json={"level": "none"},
        headers=auth,
    )
    assert r.status_code == 200

    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "hoi"}, headers=claude_auth)
    assert _deliveries_for(conn, "lobke") == 0


# --- Inbox-reden ----------------------------------------------------------


def test_inbox_reden_following_bij_comment_op_gevolgd_item(
    client, auth, claude_auth, mens_auth, project
):
    ref = _create(client, auth, project, title="Iets").json()["ref"]
    client.post(f"/api/v1/items/{ref}/follow", headers=mens_auth)
    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "hoi"}, headers=claude_auth)
    assert "following" in _inbox_reasons(client, mens_auth, ref)


def test_zonder_follow_geen_inbox_entry(client, auth, claude_auth, mens_auth, project):
    ref = _create(client, auth, project, title="Iets").json()["ref"]
    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "hoi"}, headers=claude_auth)
    assert _inbox_reasons(client, mens_auth, ref) == []


def test_following_is_de_zwakste_reden(client, auth, claude_auth, mens_auth, project):
    """Wie het item volgt én de assignee is, ziet de specifiekere reden."""
    ref = _create(client, auth, project, title="Iets", assignee="mies").json()["ref"]
    client.post(f"/api/v1/items/{ref}/follow", headers=mens_auth)
    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "hoi"}, headers=claude_auth)
    assert _inbox_reasons(client, mens_auth, ref) == ["comment"]


def test_gearchiveerd_gevolgd_item_geeft_geen_inbox_entry(
    client, auth, mens_auth, project
):
    """De event-whitelist van regel 5 is bewust smal — `item.archived` valt erbuiten.

    Pin dat, zodat een latere verbreding van de whitelist een test breekt in
    plaats van stilletjes elke volger te gaan spammen.
    """
    ref = _create(client, auth, project, title="Iets").json()["ref"]
    client.post(f"/api/v1/items/{ref}/follow", headers=mens_auth)
    client.delete(f"/api/v1/items/{ref}", headers=auth)
    assert _inbox_reasons(client, mens_auth, ref) == []


def test_ontvolgen_haalt_de_inbox_reden_weg(client, auth, claude_auth, mens_auth, project):
    ref = _create(client, auth, project, title="Iets").json()["ref"]
    client.post(f"/api/v1/items/{ref}/follow", headers=mens_auth)
    client.post(f"/api/v1/items/{ref}/comments", json={"body_md": "hoi"}, headers=claude_auth)
    assert "following" in _inbox_reasons(client, mens_auth, ref)
    client.delete(f"/api/v1/items/{ref}/follow", headers=mens_auth)
    assert _inbox_reasons(client, mens_auth, ref) == []


def test_gedempte_niet_participant_staat_met_muted_in_overzicht(client, auth, mens_auth, project):
    ref = _create(client, auth, project, title="Iets").json()["ref"]
    client.post(f"/api/v1/items/{ref}/subscribers/mies/mute", headers=mens_auth)
    subs = client.get(f"/api/v1/items/{ref}/subscribers", headers=auth).json()["subscribers"]
    mies = [s for s in subs if s["handle"] == "mies"]
    assert len(mies) == 1 and mies[0]["muted"] is True
