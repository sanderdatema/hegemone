"""Noodstop op tickets (BETON-302): slot, drempel, ontgrendelen, notificatie.

Aanleiding is BRAND-222: een comment-lus tussen twee agents (lies ↔ smid) die
35 comments lang doorging terwijl Person erin riep dat ze moesten stoppen. De
tests hieronder toetsen dat gedrag, niet de implementatie: kán een agent nog
praten, ziet de mens het slot, en verschuift de drempel na ontgrendelen.
"""

from __future__ import annotations

import pytest

from betonning.repo import users as users_repo


@pytest.fixture
def project(project, client, auth):
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    return project


def _agent_headers(conn, handle="lobke"):
    _, key = users_repo.create(conn, handle=handle, display_name=handle, kind="agent")
    conn.commit()
    return {"Authorization": f"Bearer {key}"}


def _comment(client, headers, body, ref="SOS-1"):
    return client.post(
        f"/api/v1/items/{ref}/comments", json={"body_md": body}, headers=headers
    )


def _fill_comments(client, headers, n, start=0):
    """n comments plaatsen met unieke tekst (de dedup-vangnet van BETON-217
    zou identieke bodies binnen 10s samenvouwen)."""
    for i in range(start, start + n):
        _comment(client, headers, f"comment {i}")


# --- Automatisch slot bij de drempel ---------------------------------------


def test_item_locks_at_comment_limit(client, auth, project):
    _fill_comments(client, auth, 9)
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["locked_at"] is None

    _fill_comments(client, auth, 1, start=9)
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["locked_at"] is not None


def test_tenth_comment_is_still_stored(client, auth, project):
    """De comment die de drempel raakt gaat er nog in — het slot valt erná."""
    _fill_comments(client, auth, 9)
    r = _comment(client, auth, "de tiende")
    assert r.status_code == 201
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert len(detail["comments"]) == 10
    assert detail["locked_at"] is not None


def test_lock_writes_event(client, auth, project):
    _fill_comments(client, auth, 10)
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert [e["type"] for e in events if e["type"] == "item.locked"] == ["item.locked"]


def _seed_triage(conn):
    """De triage-user los seeden. Niet via de `seed_cast`-fixture: die maakt óók
    'person' aan, en die bestaat hier al via `auth`/`user_key`."""
    user, _ = users_repo.create(
        conn, handle="triage", display_name="Triage", kind="agent"
    )
    conn.commit()
    return user


def _lock_actor(conn):
    return conn.execute(
        "SELECT actor_id FROM events WHERE type = 'item.locked'"
    ).fetchone()["actor_id"]


def test_auto_lock_actor_is_triage(client, auth, conn, project):
    """Triage zet het slot, niet de agent die toevallig de tiende plaatste
    (BETON-338) — hij is de hoeder van Betonning en dus de juiste afzender.

    Vóór BETON-338 was dit `None`, wat in de tijdlijn als `@?` verscheen."""
    triage = _seed_triage(conn)
    _fill_comments(client, _agent_headers(conn), 10)
    assert _lock_actor(conn) == triage["id"]


def test_auto_lock_actor_is_never_the_commenting_agent(client, auth, conn, project):
    """De kern van het oude `actor_id=None`: `fanout` slaat de actor over, dus
    een agent als actor zou zichzelf uit zijn eigen stop-notificatie filteren.
    Triage mag die rol overnemen, de plaatsende agent nooit."""
    _seed_triage(conn)
    _fill_comments(client, _agent_headers(conn), 10)
    lobke = conn.execute("SELECT id FROM users WHERE handle = 'lobke'").fetchone()
    assert _lock_actor(conn) != lobke["id"]


def test_auto_lock_without_triage_user_falls_back_to_no_actor(
    client, auth, conn, project
):
    """Zonder geseede triage (kale db) blijft het BETON-302-gedrag: geen actor,
    geen crash."""
    _fill_comments(client, _agent_headers(conn), 10)
    assert _lock_actor(conn) is None


def test_manual_lock_keeps_human_actor(client, auth, conn, project):
    """Een handmatige noodstop is wél van de mens die hem zette, niet van triage."""
    triage = _seed_triage(conn)
    client.post("/api/v1/items/SOS-1/lock", headers=auth)
    person = conn.execute("SELECT id FROM users WHERE handle = 'person'").fetchone()
    assert _lock_actor(conn) == person["id"]
    assert _lock_actor(conn) != triage["id"]


# --- Wat een slot blokkeert -------------------------------------------------


def test_agent_cannot_comment_on_locked_item(client, auth, conn, project):
    _fill_comments(client, auth, 10)
    r = _comment(client, _agent_headers(conn), "toch nog even iets")
    assert r.status_code == 409
    assert "op slot" in r.json()["detail"]["message"]
    assert r.json()["error_code"] == "ticket_locked_queued"


def test_human_can_still_comment_on_locked_item(client, auth, project):
    """Person moet op een gelockt ticket kunnen blijven schrijven — hij is juist
    degene die de lus doorbreekt."""
    _fill_comments(client, auth, 10)
    r = _comment(client, auth, "ik mag wel")
    assert r.status_code == 201


def test_agent_cannot_edit_comment_on_locked_item(client, auth, conn, project):
    """Een edit fant opnieuw uit — anders is dat de achterdeur uit het slot."""
    headers = _agent_headers(conn)
    r = _comment(client, headers, "van de agent")
    cid = r.json()["id"]
    client.post("/api/v1/items/SOS-1/lock", headers=auth)
    r = client.patch(
        f"/api/v1/items/SOS-1/comments/{cid}",
        json={"body_md": "@person alsnog"},
        headers=headers,
    )
    assert r.status_code == 409


def test_locked_item_error_differs_from_closed_item_error(client, auth, conn, project):
    """Een agent moet weten of hij tegen een slot of tegen een gesloten ticket
    aanloopt — dat vraagt om een andere actie."""
    client.post("/api/v1/items/SOS-1/lock", headers=auth)
    locked_msg = _comment(client, _agent_headers(conn), "x").json()["detail"]["message"]

    client.post("/api/v1/projects/SOS/items", json={"title": "y"}, headers=auth)
    client.patch("/api/v1/items/SOS-2", json={"state": "done"}, headers=auth)
    closed_msg = _comment(
        client, _agent_headers(conn, "joop"), "x", ref="SOS-2"
    ).json()["detail"]["message"]

    assert locked_msg != closed_msg


# --- Handmatig slot: mens-only ---------------------------------------------


def test_human_can_lock_item(client, auth, project):
    r = client.post("/api/v1/items/SOS-1/lock", headers=auth)
    assert r.status_code == 200
    assert r.json()["locked_at"] is not None


def test_agent_cannot_lock_item(client, auth, conn, project):
    """Een agent mag de noodstop niet bedienen — hij zou een collega muilkorven."""
    r = client.post("/api/v1/items/SOS-1/lock", headers=_agent_headers(conn))
    assert r.status_code == 403


def test_agent_cannot_unlock_item(client, auth, conn, project):
    client.post("/api/v1/items/SOS-1/lock", headers=auth)
    r = client.post("/api/v1/items/SOS-1/unlock", headers=_agent_headers(conn))
    assert r.status_code == 403
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["locked_at"] is not None


def test_lock_is_idempotent(client, auth, project):
    client.post("/api/v1/items/SOS-1/lock", headers=auth)
    client.post("/api/v1/items/SOS-1/lock", headers=auth)
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    assert len([e for e in events if e["type"] == "item.locked"]) == 1


# --- Ontgrendelen en de verschuivende drempel ------------------------------


def test_unlock_reopens_and_shifts_limit(client, auth, project):
    _fill_comments(client, auth, 10)
    r = client.post("/api/v1/items/SOS-1/unlock", headers=auth)
    assert r.status_code == 200
    assert r.json()["locked_at"] is None
    assert r.json()["comment_limit"] == 15


def test_agent_may_comment_again_after_unlock(client, auth, conn, project):
    _fill_comments(client, auth, 10)
    client.post("/api/v1/items/SOS-1/unlock", headers=auth)
    assert _comment(client, _agent_headers(conn), "weer aan de slag").status_code == 201


def test_relocks_after_five_more_comments(client, auth, project):
    """De kern van het model: een vaste drempel van 10 zou na ontgrendelen bij 10
    meteen weer dichtklappen. Na unlock is er precies 5 comments ruimte."""
    _fill_comments(client, auth, 10)
    client.post("/api/v1/items/SOS-1/unlock", headers=auth)

    _fill_comments(client, auth, 4, start=10)
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["locked_at"] is None

    _fill_comments(client, auth, 1, start=14)
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["locked_at"] is not None


def test_unlock_of_open_item_does_not_raise_limit(client, auth, project):
    """Een ontgrendeling van een open item mag de drempel niet stiekem ophogen —
    dat zou een noodstop weg-klikken die nooit geklapt heeft."""
    _fill_comments(client, auth, 3)
    r = client.post("/api/v1/items/SOS-1/unlock", headers=auth)
    assert r.status_code == 200
    assert r.json()["comment_limit"] == 10
    assert not [
        e
        for e in client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
        if e["type"] == "item.unlocked"
    ]


# --- Notificatie: de mens moet het slot zien -------------------------------


def test_lock_appears_in_human_inbox(client, auth, conn, project):
    """De kern van "daarna krijg ik een notificatie".

    Het item staat op naam van agents (zoals BRAND-222: assignee smid, maker
    claude), dus geen mention, geen toewijzing, geen "eigen item" — zonder een
    eigen inbox-reden zou Person het slot nooit zien. Hij heeft bovendien geen
    webhook_url en geen telegram_chat_id, dus de inbox is zijn enige kanaal."""
    agent = _agent_headers(conn)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    _fill_comments(client, agent, 10)

    inbox = client.get("/api/v1/inbox", headers=auth).json()
    locked = [e for e in inbox["items"] if e["type"] == "item.locked"]
    assert len(locked) == 1
    assert locked[0]["reason"] == "locked"
    assert locked[0]["ref"] == "SOS-1"
    assert inbox["unread_count"] >= 1


def test_lock_not_in_agent_inbox(client, auth, conn, project):
    """Het slot is gericht aan de mensen; een agent hoeft het niet als opdracht
    in zijn inbox te krijgen."""
    agent = _agent_headers(conn)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    _fill_comments(client, auth, 10)

    inbox = client.get("/api/v1/inbox", headers=agent).json()
    assert not [e for e in inbox["items"] if e["type"] == "item.locked"]


def test_lock_does_not_notify_agents(client, auth, conn, project):
    """Het slot mag geen delivery naar de assignee-agent opleveren — dat is
    precies de reactie die de noodstop moet voorkomen (BETON-282)."""
    _agent_headers(conn)
    conn.execute(
        "UPDATE users SET webhook_url = 'http://x' WHERE handle = 'lobke'"
    )
    conn.commit()
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    _fill_comments(client, auth, 10)

    rows = conn.execute(
        """SELECT u.handle FROM webhook_deliveries d
           JOIN events e ON e.id = d.event_id
           JOIN users u ON u.id = d.user_id
           WHERE e.type = 'item.locked'"""
    ).fetchall()
    assert [r["handle"] for r in rows] == []


def test_lock_notifies_human_with_a_channel(client, auth, conn, project):
    """Zodra Person wél een kanaal heeft (webhook/Telegram) moet het slot daar
    landen — de fanout is nu een dood kanaal, maar mag niet stilletjes de
    verkeerde doelgroep hebben."""
    conn.execute("UPDATE users SET webhook_url = 'http://x' WHERE handle = 'person'")
    conn.commit()
    agent = _agent_headers(conn)
    _fill_comments(client, agent, 10)

    rows = conn.execute(
        """SELECT u.handle FROM webhook_deliveries d
           JOIN events e ON e.id = d.event_id
           JOIN users u ON u.id = d.user_id
           WHERE e.type = 'item.locked'"""
    ).fetchall()
    assert [r["handle"] for r in rows] == ["person"]


def test_locked_event_tells_agent_to_stand_down(client, auth, conn, project):
    """Een agent die het event tóch ziet (subscribe_all) krijgt een stopsein,
    geen "ter info" — anders praat hij alsnog door."""
    from betonning import webhooks

    _agent_headers(conn)
    conn.execute(
        "UPDATE users SET webhook_url = 'http://x', subscribe_all = 1 "
        "WHERE handle = 'lobke'"
    )
    conn.commit()
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    _fill_comments(client, auth, 10)

    event = conn.execute("SELECT * FROM events WHERE type = 'item.locked'").fetchone()
    agent = users_repo.get_by_handle(conn, "lobke")
    instructions = webhooks.build_agent_instructions(conn, event, agent)
    assert instructions["expected_action"] == "stand_down"


# --- Serialisatie -----------------------------------------------------------


def test_list_shows_locked_flag(client, auth, project):
    _fill_comments(client, auth, 10)
    items = client.get("/api/v1/projects/SOS/items", headers=auth).json()
    assert items[0]["locked"] is True


def test_open_item_is_not_locked(client, auth, project):
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert detail["locked_at"] is None
    assert detail["comment_limit"] == 10
    items = client.get("/api/v1/projects/SOS/items", headers=auth).json()
    assert items[0]["locked"] is False


# --- Wachtrij: de geblokkeerde comment bewaren en vrijgeven (BETON-338) -----


def _held(client, auth, ref="SOS-1"):
    return client.get(f"/api/v1/items/{ref}", headers=auth).json()["held_comment"]


def test_blocked_comment_is_held(client, auth, conn, project):
    """De comment die de tiende triggerde gaat er al in; de ELFDE liep tegen het
    slot en was voorheen weg. Die bewaren we nu."""
    _fill_comments(client, auth, 10)
    r = _comment(client, _agent_headers(conn), "dit wilde ik nog zeggen")
    assert r.status_code == 409
    held = _held(client, auth)
    assert held["body_md"] == "dit wilde ik nog zeggen"
    assert held["author"] == "lobke"


def test_held_comment_message_tells_agent_it_was_saved(client, auth, conn, project):
    _fill_comments(client, auth, 10)
    msg = _comment(client, _agent_headers(conn), "x").json()["detail"]["message"]
    assert "bewaard" in msg


def test_second_blocked_comment_is_not_held(client, auth, conn, project):
    """Eén plek per item: de tweede die aanklopt wordt geweigerd zónder opslag,
    anders blijft de lus tijdens het slot gewoon doorproduceren."""
    _fill_comments(client, auth, 10)
    _comment(client, _agent_headers(conn, "lobke"), "eerste")
    r = _comment(client, _agent_headers(conn, "joop"), "tweede")
    assert r.status_code == 409
    assert "al een bericht" in r.json()["detail"]["message"]
    assert _held(client, auth)["body_md"] == "eerste"


def test_held_comment_is_not_counted_as_comment(client, auth, conn, project):
    """Een wachtende comment is nog géén comment: hij mag niet meetellen voor de
    drempel die hem tegenhoudt, en niet in de tijdlijn opduiken."""
    _fill_comments(client, auth, 10)
    before = len(client.get("/api/v1/items/SOS-1", headers=auth).json()["comments"])
    _comment(client, _agent_headers(conn), "in de wacht")
    after = client.get("/api/v1/items/SOS-1", headers=auth).json()["comments"]
    assert len(after) == before
    assert all("in de wacht" not in c["body_md"] for c in after)


def test_unlock_publishes_held_comment_as_author(client, auth, conn, project):
    _fill_comments(client, auth, 10)
    _comment(client, _agent_headers(conn), "inhaalwerk")
    client.post("/api/v1/items/SOS-1/unlock", headers=auth)

    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    last = detail["comments"][-1]
    assert last["body_md"] == "inhaalwerk"
    assert last["author"] == "lobke"
    assert detail["held_comment"] is None


def test_released_comment_does_not_eat_the_new_headroom(client, auth, conn, project):
    """Persons keuze (BETON-338): de vrijgegeven comment is inhaalwerk van vóór
    het slot en telt NIET mee in de nieuwe ruimte — vrijgegeven + 5 nieuwe, niet
    + 4. Codificeert de bedoeling, niet het toevallige rekengedrag."""
    _fill_comments(client, auth, 10)
    _comment(client, _agent_headers(conn), "inhaalwerk")
    r = client.post("/api/v1/items/SOS-1/unlock", headers=auth)
    # 10 + de vrijgegeven = 11 comments; ruimte 5 → drempel 16.
    assert r.json()["comment_limit"] == 16


def test_relock_after_release_plus_five(client, auth, conn, project):
    _fill_comments(client, auth, 10)
    _comment(client, _agent_headers(conn), "inhaalwerk")
    client.post("/api/v1/items/SOS-1/unlock", headers=auth)
    _fill_comments(client, auth, 4, start=20)
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["locked_at"] is None
    _fill_comments(client, auth, 1, start=30)
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["locked_at"] is not None


def test_unlock_without_held_comment_keeps_beton_302_arithmetic(client, auth, project):
    """Regressie: zonder wachtende comment blijft de telling exact als vóór
    BETON-338 (10 comments → drempel 15)."""
    _fill_comments(client, auth, 10)
    r = client.post("/api/v1/items/SOS-1/unlock", headers=auth)
    assert r.json()["comment_limit"] == 15


def test_edit_on_locked_item_is_not_held(client, auth, conn, project):
    """Een bewerking van een bestaande comment is geen nieuw bericht — die
    blijft 409 zónder opslag."""
    headers = _agent_headers(conn)
    _fill_comments(client, headers, 5)
    cid = client.get("/api/v1/items/SOS-1", headers=auth).json()["comments"][0]["id"]
    _fill_comments(client, auth, 5, start=50)
    r = client.patch(
        f"/api/v1/items/SOS-1/comments/{cid}", json={"body_md": "bewerkt"}, headers=headers
    )
    assert r.status_code == 409
    assert _held(client, auth) is None


def test_queue_frees_up_for_the_next_lock(client, auth, conn, project):
    """Na vrijgeven kan een volgende ronde weer iets bewaren."""
    agent = _agent_headers(conn)
    _fill_comments(client, auth, 10)
    _comment(client, agent, "eerste ronde")
    client.post("/api/v1/items/SOS-1/unlock", headers=auth)
    _fill_comments(client, auth, 5, start=60)
    _comment(client, agent, "tweede ronde")
    assert _held(client, auth)["body_md"] == "tweede ronde"


# --- Kiesbare ruimte bij ontgrendelen (BETON-338) ---------------------------


def test_unlock_headroom_choice_applies(client, auth, project):
    _fill_comments(client, auth, 10)
    r = client.post("/api/v1/items/SOS-1/unlock", json={"headroom": 20}, headers=auth)
    assert r.json()["comment_limit"] == 30


def test_unlock_defaults_to_five_without_body(client, auth, project):
    _fill_comments(client, auth, 10)
    assert (
        client.post("/api/v1/items/SOS-1/unlock", headers=auth).json()["comment_limit"]
        == 15
    )


def test_unlock_rejects_headroom_outside_the_whitelist(client, auth, project):
    """Geen vrij getal: 500 zou de noodstop effectief uitschakelen."""
    _fill_comments(client, auth, 10)
    r = client.post("/api/v1/items/SOS-1/unlock", json={"headroom": 500}, headers=auth)
    assert r.status_code == 422
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["locked_at"] is not None


def test_agent_cannot_choose_headroom(client, auth, conn, project):
    _fill_comments(client, auth, 10)
    r = client.post(
        "/api/v1/items/SOS-1/unlock", json={"headroom": 20}, headers=_agent_headers(conn)
    )
    assert r.status_code == 403


# --- Vraagmodule staat los van de noodstop (BETON-339) ----------------------


def _ask(client, headers, body, ref="SOS-1", options=None):
    payload = {"body_md": body, "kind": "question"}
    if options:
        payload["options"] = options
    return client.post(f"/api/v1/items/{ref}/comments", json=payload, headers=headers)


def test_questions_do_not_count_toward_the_lock_threshold(client, auth, conn, project):
    """Een vraag aan een mens mag het ticket niet richting het slot duwen — dat
    is de nooduitgang, geen geklets."""
    headers = _agent_headers(conn)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    for i in range(10):
        _ask(client, headers, f"@person vraag {i}?")
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["locked_at"] is None


def test_agent_may_still_ask_a_question_on_a_locked_item(client, auth, conn, project):
    """Het slot legt geklets stil, niet het enige kanaal waarlangs een agent om
    ingrijpen kan vragen."""
    headers = _agent_headers(conn)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    _fill_comments(client, auth, 10)
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["locked_at"] is not None

    r = _ask(client, headers, "@person moet ik hiermee stoppen?")
    assert r.status_code == 201
    assert r.json()["kind"] == "question"


def test_question_on_locked_item_is_never_held(client, auth, conn, project):
    """Omdat vragen doorgaan, komen ze nooit in de wachtrij — en dus bestaat de
    stille kind-downgrade (de aanleiding van BETON-339) niet meer."""
    headers = _agent_headers(conn)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    _fill_comments(client, auth, 10)
    _ask(client, headers, "@person mag dit nog?")
    assert client.get("/api/v1/items/SOS-1", headers=auth).json()["held_comment"] is None


def test_question_keeps_its_options_on_a_locked_item(client, auth, conn, project):
    """De meerkeuze-opties overleven — juist wat vóór BETON-339 wegviel."""
    headers = _agent_headers(conn)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    _fill_comments(client, auth, 10)
    r = _ask(client, headers, "@person doorgaan?", options=["ja", "nee"])
    assert r.status_code == 201
    assert r.json()["question_options"] == ["ja", "nee"]


def test_plain_comment_on_locked_item_is_still_blocked(client, auth, conn, project):
    """Regressie: de uitzondering geldt ALLEEN voor vragen — gewoon geklets
    blijft geblokkeerd, anders is de noodstop stuk."""
    headers = _agent_headers(conn)
    _fill_comments(client, auth, 10)
    assert _comment(client, headers, "gewoon iets").status_code == 409


def test_questions_still_freeze_description(client, auth, conn, project):
    """Regressie op BETON-301: voor de bevriezing van omschrijving/plan tellen
    vragen wél mee. `count_chatter` mag die poort niet meeverzetten."""
    headers = _agent_headers(conn)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    _ask(client, headers, "@person een vraag?")
    r = client.patch(
        "/api/v1/items/SOS-1", json={"description_md": "herschreven"}, headers=headers
    )
    assert r.status_code == 409
