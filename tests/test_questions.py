"""Vraagmodule (BETON-219): vraag-comments, antwoord-flow, open-vragen, fanout."""

from __future__ import annotations

import pytest

from betonning.repo import users as users_repo


@pytest.fixture
def project(project, client, auth):
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    return project


def _webhook_user(conn, handle, *, agent_type=None, subscribe_all=False):
    _, key = users_repo.create(
        conn,
        handle=handle,
        display_name=handle,
        kind="agent",
        agent_type=agent_type,
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
        subscribe_all=subscribe_all,
    )
    conn.commit()
    return key


def _deliveries_for(conn, handle):
    return conn.execute(
        "SELECT wd.* FROM webhook_deliveries wd JOIN users u ON u.id = wd.user_id "
        "WHERE u.handle = ? ORDER BY wd.id",
        (handle,),
    ).fetchall()


# --- Vraag-comment aanmaken ------------------------------------------------


def test_create_question_with_options(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={
            "body_md": "Rood of blauw?",
            "kind": "question",
            "options": ["rood", "blauw"],
        },
        headers=auth,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "question"
    assert body["question_options"] == ["rood", "blauw"]
    assert body["answered_at"] is None
    assert body["answered_by"] is None
    assert body["answer_comment_id"] is None


def test_question_options_is_accepted_as_alias(client, auth, project):
    # BETON-426: het antwoord noemt het veld `question_options`; wie die naam
    # bij het aanmaken overneemt, verloor de opties stil (201 zonder knoppen).
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={
            "body_md": "Rood of blauw?",
            "kind": "question",
            "question_options": ["rood", "blauw"],
        },
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["question_options"] == ["rood", "blauw"]


def test_unknown_comment_field_is_422(client, auth, project):
    # BETON-426: een onbekend veld verdwijnt niet meer stil.
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "x", "foo": 1},
        headers=auth,
    )
    assert r.status_code == 422


def test_create_free_text_question_without_options(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Wat vind je?", "kind": "question"},
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["kind"] == "question"
    assert r.json()["question_options"] is None


def test_options_without_question_kind_is_422(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "gewoon", "options": ["a", "b"]},
        headers=auth,
    )
    assert r.status_code == 422


def test_empty_option_is_422(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "?", "kind": "question", "options": ["a", "  "]},
        headers=auth,
    )
    assert r.status_code == 422


def test_duplicate_option_is_422(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "?", "kind": "question", "options": ["a", "a"]},
        headers=auth,
    )
    assert r.status_code == 422


def test_too_many_options_is_422(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={
            "body_md": "?",
            "kind": "question",
            "options": [str(i) for i in range(7)],
        },
        headers=auth,
    )
    assert r.status_code == 422


# --- BETON-304: één vraag per vraagmodule -----------------------------------


def test_count_questions_pure_helper():
    """Pure unit-tests op de tellogica, los van de HTTP-laag."""
    from betonning.api.items import _count_questions

    assert _count_questions("Rood of blauw?") == 1
    assert _count_questions("Rood, groen of blauw of paars?") == 1
    body = (
        "- Bedoel je X én Y?\n"
        "- Is de limiet per ticket, per gebruiker of globaal?\n"
        "- Moet de notificatie alleen naar jou gaan?"
    )
    assert _count_questions(body) == 3
    assert _count_questions("Kies een optie: `a ? b : c`") == 0
    assert _count_questions("Zie ```py\nx = 1 if a else 2  # a?\n``` — wat kies je?") == 1
    assert _count_questions("Weet je het zeker??") == 1
    assert _count_questions("Serieus?!") == 1
    assert _count_questions("Kies één van de opties:") == 0
    assert _count_questions("Moet ik X doen? Zo ja, ook Y?") == 2
    # Een reeks van uitsluitend '!' is geen vraag — geen vals-positief bij een
    # emfatische agent (bv. "Dit is urgent!! Beslis nu!!").
    assert _count_questions("Dit is urgent!! Beslis nu!! Rood of blauw?") == 1
    assert _count_questions("Doe dit nu!!") == 0


def test_multiple_questions_with_options_is_422(client, auth, project):
    """De echte casus (BETON-302): drie vragen + gemengde opties in één
    vraagmodule."""
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={
            "body_md": (
                "Bedoel je dat een ticket handmatig op slot gezet kan worden "
                "én automatisch na 10 comments? Is de limiet per ticket, per "
                "gebruiker of globaal? Moet de notificatie alleen naar jou "
                "gaan?"
            ),
            "kind": "question",
            "options": [
                "Handmatig + automatisch",
                "Alleen handmatig",
                "Per ticket",
                "Per gebruiker",
                "Globaal",
            ],
        },
        headers=auth,
    )
    assert r.status_code == 422


def test_single_question_with_options_allowed(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={
            "body_md": "Rood of blauw?",
            "kind": "question",
            "options": ["rood", "blauw"],
        },
        headers=auth,
    )
    assert r.status_code == 201


def test_multiple_questions_without_options_allowed(client, auth, project):
    """Het vangnet grijpt alleen als er óók opties zijn — een meervoudige
    vrije-tekstvraag heeft het gemengde-opties-probleem niet."""
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={
            "body_md": "Bedoel je X? En hoe zit het met Y? En Z?",
            "kind": "question",
        },
        headers=auth,
    )
    assert r.status_code == 201


def test_question_with_followup_clause_and_options_allowed(client, auth, project):
    """Geen vals-positief: een enkele vraag met een vervolgclausule ('Zo ja,
    ook Y?') heeft twee vraagtekens maar is één vraag."""
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={
            "body_md": "Moet ik dit nu doen? Zo ja, ook de rest?",
            "kind": "question",
            "options": ["ja", "nee"],
        },
        headers=auth,
    )
    assert r.status_code == 201


def test_plain_comment_with_multiple_questions_unaffected(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Vraag 1? Vraag 2? Vraag 3?"},
        headers=auth,
    )
    assert r.status_code == 201


def test_bad_kind_is_422(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "x", "kind": "banana"},
        headers=auth,
    )
    assert r.status_code == 422


def test_plain_comment_serializes_with_defaults(client, auth, project):
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=auth)
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    c = detail["comments"][0]
    assert c["kind"] == "comment"
    assert c["question_options"] is None
    assert c["answered_at"] is None
    assert c["answered_by"] is None
    assert c["answer_comment_id"] is None


# --- BETON-307: de vraagmodule is alleen voor vragen aan een mens ----------


def test_agent_question_mentioning_human_allowed(client, auth, conn, project):
    key = _webhook_user(conn, "lobke")
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Hoe wil je dit, @person?", "kind": "question"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 201


def test_agent_question_mentioning_only_agent_rejected(client, auth, conn, project):
    """BRAND-257: een agent stelt een vraag aan een andere agent via de
    vraagmodule — dat mag niet meer."""
    key = _webhook_user(conn, "lobke")
    _webhook_user(conn, "joop")
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Wat denk jij, @joop?", "kind": "question"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 422


def test_question_without_mention_assigned_to_human_allowed(client, auth, conn, project):
    key = _webhook_user(conn, "lobke")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Rood of blauw?", "kind": "question"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 201


def test_question_without_mention_assigned_to_agent_rejected(client, auth, conn, project):
    key = _webhook_user(conn, "lobke")
    _webhook_user(conn, "joop")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Rood of blauw?", "kind": "question"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 422


def test_question_without_mention_or_assignee_allowed(client, auth, conn, project):
    """Afwijking van het oorspronkelijke plan: een vraag zonder énige
    bepaalbare geadresseerde (geen mention, geen assignee) blijft toegestaan.
    Weigeren op afwezigheid van bewijs zou de gangbare vrije-tekstvraag breken
    (zie de vele bestaande tests die precies dit doen) — dat is niet het
    gerapporteerde misbruik uit BRAND-257 (een agent die expliciet een andere
    agent aanspreekt)."""
    key = _webhook_user(conn, "lobke")
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Rood of blauw?", "kind": "question"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 201


def test_human_question_without_mention_or_assignee_allowed(client, auth, project):
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Rood of blauw?", "kind": "question"},
        headers=auth,
    )
    assert r.status_code == 201


def test_human_question_on_agent_assigned_item_allowed(client, auth, conn, project):
    """De guard geldt alleen voor een AGENT-caller (BETON-307): een mens die
    een vraag stelt blijft altijd ongemoeid, ook op een aan-agent-toegewezen
    item zonder mention — anders zou een mens hier ten onrechte de
    agent-naar-agent-foutmelding krijgen."""
    _webhook_user(conn, "joop")
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Rood of blauw?", "kind": "question"},
        headers=auth,
    )
    assert r.status_code == 201


def test_plain_comment_mentioning_agent_unaffected(client, auth, conn, project):
    """De guard geldt alleen voor kind='question' — een gewone comment mag
    gewoon een agent aanspreken."""
    key = _webhook_user(conn, "lobke")
    _webhook_user(conn, "joop")
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "@joop kun jij dit oppakken?"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 201


def test_mention_of_unknown_handle_falls_back_allowed(client, auth, conn, project):
    """Een @mention die naar niemand resolvet is geen bewijs van een
    agent-adressering — sta toe (dezelfde geen-bewijs-logica als zonder
    mention)."""
    key = _webhook_user(conn, "lobke")
    r = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Wat vind @niemandbestaat hiervan?", "kind": "question"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 201


# --- Antwoord-flow ---------------------------------------------------------


def _ask(client, auth, options=None, body="Rood of blauw?"):
    payload = {"body_md": body, "kind": "question"}
    if options is not None:
        payload["options"] = options
    return client.post(
        "/api/v1/items/SOS-1/comments", json=payload, headers=auth
    ).json()


def test_answer_stored_inline_not_as_comment(client, auth, project):
    """BETON-265: het antwoord staat inline op de vraag, niet als los comment."""
    q = _ask(client, auth)
    r = client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"text": "groen"}, headers=auth
    )
    assert r.status_code == 200
    # De respons is de (beantwoorde) vraag zelf.
    assert r.json()["id"] == q["id"]
    assert r.json()["answer_text"] == "groen"

    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    # Géén extra antwoord-comment: alleen de vraag staat er.
    assert len(detail["comments"]) == 1
    question = detail["comments"][0]
    assert question["answered_at"] is not None
    assert question["answered_by"] == "person"
    assert question["answer_text"] == "groen"
    assert question["answer_comment_id"] is None


def test_answer_with_option_index(client, auth, project):
    q = _ask(client, auth, options=["rood", "blauw"])
    r = client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"option_index": 1}, headers=auth
    )
    assert r.status_code == 200
    assert r.json()["answer_text"] == "blauw"
    assert r.json()["answer_option_index"] == 1
    # Geen los antwoord-comment.
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert len(detail["comments"]) == 1


def test_answer_twice_is_409(client, auth, project):
    q = _ask(client, auth)
    client.post(f"/api/v1/comments/{q['id']}/answer", json={"text": "a"}, headers=auth)
    r = client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"text": "b"}, headers=auth
    )
    assert r.status_code == 409


def test_answer_bad_index_is_422(client, auth, project):
    q = _ask(client, auth, options=["rood", "blauw"])
    r = client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"option_index": 5}, headers=auth
    )
    assert r.status_code == 422


def test_answer_both_text_and_index_is_422(client, auth, project):
    q = _ask(client, auth, options=["rood"])
    r = client.post(
        f"/api/v1/comments/{q['id']}/answer",
        json={"text": "x", "option_index": 0},
        headers=auth,
    )
    assert r.status_code == 422


def test_answer_neither_is_422(client, auth, project):
    q = _ask(client, auth)
    r = client.post(f"/api/v1/comments/{q['id']}/answer", json={}, headers=auth)
    assert r.status_code == 422


def test_answer_non_question_is_422(client, auth, project):
    c = client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "gewoon"}, headers=auth
    ).json()
    r = client.post(
        f"/api/v1/comments/{c['id']}/answer", json={"text": "x"}, headers=auth
    )
    assert r.status_code == 422


def test_answer_unknown_comment_is_404(client, auth, project):
    r = client.post("/api/v1/comments/9999/answer", json={"text": "x"}, headers=auth)
    assert r.status_code == 404


def test_answer_requires_auth(client, project):
    r = client.post("/api/v1/comments/1/answer", json={"text": "x"})
    assert r.status_code == 401


def test_bad_index_leaves_no_partial_state(client, auth, project):
    """Een geweigerd antwoord (bad index) wordt vóór de transactie afgekapt: geen
    antwoord-comment, vraag blijft onbeantwoord."""
    q = _ask(client, auth, options=["rood"])
    client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"option_index": 9}, headers=auth
    )
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    # Alleen de vraag zelf staat er; geen antwoord-comment.
    assert len(detail["comments"]) == 1
    assert detail["comments"][0]["answered_at"] is None


def test_answer_rolls_back_on_mid_transaction_failure(
    client, auth, project, monkeypatch
):
    """Als het markeren van de vraag faalt, rolt de hele transactie terug: de
    vraag blijft onbeantwoord en er is geen event/notificatie blijven hangen."""
    from betonning.api import items as items_api

    def boom(*args, **kwargs):
        raise RuntimeError("kapot")

    q = _ask(client, auth)
    monkeypatch.setattr(items_api.comments_repo, "mark_answered", boom)
    # TestClient laat de server-exception door; de transactie moet dán al
    # teruggerold zijn.
    with pytest.raises(RuntimeError, match="kapot"):
        client.post(
            f"/api/v1/comments/{q['id']}/answer", json={"text": "groen"}, headers=auth
        )
    monkeypatch.undo()
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    # De antwoord-comment (create ván vóór mark_answered) mag niet blijven staan.
    assert len(detail["comments"]) == 1
    assert detail["comments"][0]["answered_at"] is None


# --- Open-vraag-markering op kaart/lijst (BETON-275) -----------------------


def test_has_open_question_flag_on_item_and_list(client, auth, project):
    # Zonder vraag: geen markering (detail + list).
    assert (
        client.get("/api/v1/items/SOS-1", headers=auth).json()["has_open_question"]
        is False
    )
    rows = client.get("/api/v1/projects/SOS/items", headers=auth).json()
    assert next(r for r in rows if r["ref"] == "SOS-1")["has_open_question"] is False

    q = _ask(client, auth)
    # Met open vraag: markering aan (detail + list).
    assert (
        client.get("/api/v1/items/SOS-1", headers=auth).json()["has_open_question"]
        is True
    )
    rows = client.get("/api/v1/projects/SOS/items", headers=auth).json()
    assert next(r for r in rows if r["ref"] == "SOS-1")["has_open_question"] is True

    # Beantwoord → markering weg.
    client.post(f"/api/v1/comments/{q['id']}/answer", json={"text": "x"}, headers=auth)
    assert (
        client.get("/api/v1/items/SOS-1", headers=auth).json()["has_open_question"]
        is False
    )


# --- Open-vragen-filter ----------------------------------------------------


def test_open_questions_for_creator(client, auth, project):
    _ask(client, auth)
    r = client.get("/api/v1/questions?open=true", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["item"]["ref"] == "SOS-1"
    assert data[0]["kind"] == "question"


def test_answered_question_not_in_open(client, auth, project):
    q = _ask(client, auth)
    client.post(f"/api/v1/comments/{q['id']}/answer", json={"text": "x"}, headers=auth)
    data = client.get("/api/v1/questions?open=true", headers=auth).json()
    assert data == []


def test_open_questions_only_directed(client, auth, conn, project):
    """Een vraag op een item waar de user geen assignee/maker/mentioned is,
    verschijnt niet in zijn open-vragen."""
    key = _webhook_user(conn, "lobke")
    lobke_auth = {"Authorization": f"Bearer {key}"}
    # person (maker van SOS-1) stelt een vraag zonder @mention.
    _ask(client, auth)
    # lobke is niet betrokken bij SOS-1 → ziet de vraag niet.
    assert client.get("/api/v1/questions?open=true", headers=lobke_auth).json() == []


def test_open_questions_for_mentioned(client, auth, conn, project):
    key = _webhook_user(conn, "lobke")
    lobke_auth = {"Authorization": f"Bearer {key}"}
    # BETON-307: de vraagmodule vereist een menselijke geadresseerde — @person
    # erbij mentionen maakt dit een geldige vraag; lobke blijft "directed" via
    # zijn eigen mention en ziet hem dus nog steeds als open question.
    _ask(client, auth, body="Wat denk jij @lobke, @person?")
    data = client.get("/api/v1/questions?open=true", headers=lobke_auth).json()
    assert len(data) == 1
    assert data[0]["item"]["ref"] == "SOS-1"


def test_open_questions_for_assignee(client, auth, conn, project):
    """BETON-307: een onbeantwoorde vraag zonder mention valt terug op de
    assignee — die moet dan een mens zijn, dus hier een mens ipv een agent."""
    _, key = users_repo.create(conn, handle="joris", display_name="Joris", kind="human")
    conn.commit()
    joris_auth = {"Authorization": f"Bearer {key}"}
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joris"}, headers=auth)
    _ask(client, auth)
    data = client.get("/api/v1/questions?open=true", headers=joris_auth).json()
    assert len(data) == 1


# --- Fanout-gerichtheid ----------------------------------------------------


def test_answer_notifies_asker(client, auth, conn, project):
    """De vragensteller krijgt het antwoord-event; de antwoorder niet zijn eigen."""
    key = _webhook_user(conn, "lobke")
    lobke_auth = {"Authorization": f"Bearer {key}"}
    # lobke (webhook-user) stelt de vraag; person beantwoordt.
    q = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Rood of blauw?", "kind": "question"},
        headers=lobke_auth,
    ).json()
    client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"text": "groen"}, headers=auth
    )
    assert len(_deliveries_for(conn, "lobke")) == 1


def test_answer_does_not_notify_answerer(client, auth, conn, project):
    """De actor (antwoorder) krijgt nooit zijn eigen antwoord-event."""
    key = _webhook_user(conn, "lobke")
    lobke_auth = {"Authorization": f"Bearer {key}"}
    # person stelt de vraag; lobke beantwoordt → lobke krijgt geen eigen event.
    q = _ask(client, auth)
    client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"text": "groen"}, headers=lobke_auth
    )
    assert _deliveries_for(conn, "lobke") == []


def test_answer_does_not_notify_uninvolved_assignee(client, auth, conn, project):
    """Het antwoord is gericht aan de vragensteller, niet automatisch aan de
    assignee van het item."""
    asker_key = _webhook_user(conn, "lobke")
    lobke_auth = {"Authorization": f"Bearer {asker_key}"}
    # BETON-307: assignee moet een mens zijn wil een onaangesproken vraag
    # daarop mogen terugvallen — joop is hier dus mens, niet agent.
    users_repo.create(
        conn,
        handle="joop",
        display_name="Joop",
        kind="human",
        webhook_url="http://example.invalid/hook",
        webhook_secret="s",
    )
    conn.commit()
    # joop is assignee; lobke stelt de vraag; person beantwoordt.
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    q = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Rood of blauw?", "kind": "question"},
        headers=lobke_auth,
    ).json()
    # reset deliveries van de assignee-patch
    conn.execute("DELETE FROM webhook_deliveries")
    conn.commit()
    client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"text": "groen"}, headers=auth
    )
    assert len(_deliveries_for(conn, "lobke")) == 1
    assert _deliveries_for(conn, "joop") == []


# --- Notificatie inhouden tot alle vragen beantwoord (BETON-262) -----------


def test_notification_held_until_all_questions_answered(client, auth, conn, project):
    """Zolang er nog een open vraag op het item is, wordt de vragensteller nog
    niet genotificeerd; pas als álle vragen beantwoord zijn gaan de deliveries los."""
    key = _webhook_user(conn, "lobke")
    lobke_auth = {"Authorization": f"Bearer {key}"}
    q1 = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Vraag 1?", "kind": "question"},
        headers=lobke_auth,
    ).json()
    q2 = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Vraag 2?", "kind": "question"},
        headers=lobke_auth,
    ).json()

    # Eerste antwoord: nog een open vraag → niets ingehouden vrijgegeven.
    client.post(f"/api/v1/comments/{q1['id']}/answer", json={"text": "a"}, headers=auth)
    assert _deliveries_for(conn, "lobke") == []

    # Tweede antwoord: alle vragen beantwoord → beide notificaties los.
    client.post(f"/api/v1/comments/{q2['id']}/answer", json={"text": "b"}, headers=auth)
    assert len(_deliveries_for(conn, "lobke")) == 2


def test_held_deliveries_use_answer_grace_window(client, auth, conn, project):
    """De vrijgegeven answer-delivery krijgt een not_before in de toekomst
    (grace-venster), niet direct verzendbaar."""
    key = _webhook_user(conn, "lobke")
    lobke_auth = {"Authorization": f"Bearer {key}"}
    q = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Vraag?", "kind": "question"},
        headers=lobke_auth,
    ).json()
    client.post(f"/api/v1/comments/{q['id']}/answer", json={"text": "a"}, headers=auth)
    d = _deliveries_for(conn, "lobke")
    assert len(d) == 1
    assert d[0]["not_before"] is not None


# --- Antwoord wijzigen tot verstuurd (BETON-263) ---------------------------


def test_edit_answer_before_notified(client, auth, conn, project):
    """Zolang de notificatie nog niet afgeleverd is, kan het antwoord gewijzigd."""
    key = _webhook_user(conn, "lobke")
    lobke_auth = {"Authorization": f"Bearer {key}"}
    q = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Vraag?", "kind": "question"},
        headers=lobke_auth,
    ).json()
    client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"text": "eerst"}, headers=auth
    )
    r = client.patch(
        f"/api/v1/comments/{q['id']}/answer", json={"text": "bijgesteld"}, headers=auth
    )
    assert r.status_code == 200
    assert r.json()["answer_text"] == "bijgesteld"
    assert r.json()["answer_locked"] is False


def test_edit_answer_after_delivered_is_409(client, auth, conn, project):
    """Zodra de antwoord-delivery is afgeleverd, is het antwoord gelockt (409)."""
    key = _webhook_user(conn, "lobke")
    lobke_auth = {"Authorization": f"Bearer {key}"}
    q = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Vraag?", "kind": "question"},
        headers=lobke_auth,
    ).json()
    client.post(f"/api/v1/comments/{q['id']}/answer", json={"text": "a"}, headers=auth)
    # Simuleer dat de delivery daadwerkelijk is afgeleverd.
    conn.execute("UPDATE webhook_deliveries SET status = 'delivered'")
    conn.commit()
    r = client.patch(
        f"/api/v1/comments/{q['id']}/answer", json={"text": "b"}, headers=auth
    )
    assert r.status_code == 409
    # En de serialisatie markeert 'm als locked.
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert detail["comments"][0]["answer_locked"] is True


def test_edit_unanswered_question_is_422(client, auth, project):
    q = _ask(client, auth)
    r = client.patch(
        f"/api/v1/comments/{q['id']}/answer", json={"text": "x"}, headers=auth
    )
    assert r.status_code == 422


def test_edit_non_question_is_422(client, auth, project):
    c = client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "gewoon"}, headers=auth
    ).json()
    r = client.patch(
        f"/api/v1/comments/{c['id']}/answer", json={"text": "x"}, headers=auth
    )
    assert r.status_code == 422


# --- Toewijzing terug naar vraagsteller (BETON-285) ------------------------


def test_answer_reassigns_to_asker_when_assignee_answered(client, auth, conn, project):
    """Laatste (enige) vraag beantwoord, person is assignee → de toewijzing
    gaat terug naar de vraagsteller."""
    key = _webhook_user(conn, "lobke")
    lobke_auth = {"Authorization": f"Bearer {key}"}
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    q = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Rood of blauw?", "kind": "question"},
        headers=lobke_auth,
    ).json()
    client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"text": "rood"}, headers=auth
    )
    item = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert item["assignee"] == "lobke"


def test_answer_does_not_reassign_while_questions_open(client, auth, conn, project):
    """Nog een open vraag op het item → geen reassign, ook al is person assignee."""
    key = _webhook_user(conn, "lobke")
    lobke_auth = {"Authorization": f"Bearer {key}"}
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    q1 = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Vraag 1?", "kind": "question"},
        headers=lobke_auth,
    ).json()
    client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Vraag 2?", "kind": "question"},
        headers=lobke_auth,
    )
    client.post(f"/api/v1/comments/{q1['id']}/answer", json={"text": "a"}, headers=auth)
    item = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert item["assignee"] == "person"


def test_answer_does_not_reassign_when_assignee_is_not_answerer(
    client, auth, conn, project
):
    """De assignee is iemand anders dan de antwoorder → geen reassign.

    BETON-307: assignee moet een mens zijn wil een onaangesproken vraag
    daarop mogen terugvallen — joop is hier dus mens, niet agent."""
    key = _webhook_user(conn, "lobke")
    lobke_auth = {"Authorization": f"Bearer {key}"}
    users_repo.create(conn, handle="joop", display_name="Joop", kind="human")
    conn.commit()
    client.patch("/api/v1/items/SOS-1", json={"assignee": "joop"}, headers=auth)
    q = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Rood of blauw?", "kind": "question"},
        headers=lobke_auth,
    ).json()
    client.post(f"/api/v1/comments/{q['id']}/answer", json={"text": "a"}, headers=auth)
    item = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert item["assignee"] == "joop"


def test_answer_does_not_reassign_when_asker_is_answerer(client, auth, project):
    """Person stelde de vraag zelf en beantwoordt hem ook → geen reassign."""
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    q = _ask(client, auth)
    client.post(f"/api/v1/comments/{q['id']}/answer", json={"text": "a"}, headers=auth)
    item = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert item["assignee"] == "person"


def test_answer_reassigns_to_last_asker_when_multiple_askers(client, auth, conn, project):
    """Vragen van verschillende agents → de laatst gestelde vraag wint."""
    lobke_key = _webhook_user(conn, "lobke")
    joop_key = _webhook_user(conn, "joop")
    lobke_auth = {"Authorization": f"Bearer {lobke_key}"}
    joop_auth = {"Authorization": f"Bearer {joop_key}"}
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    q1 = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Vraag van lobke?", "kind": "question"},
        headers=lobke_auth,
    ).json()
    q2 = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Vraag van joop?", "kind": "question"},
        headers=joop_auth,
    ).json()
    client.post(f"/api/v1/comments/{q1['id']}/answer", json={"text": "a"}, headers=auth)
    client.post(f"/api/v1/comments/{q2['id']}/answer", json={"text": "b"}, headers=auth)
    item = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert item["assignee"] == "joop"


def test_answer_reassign_does_not_double_notify_asker(client, auth, conn, project):
    """Regressietest: de reassign mag géén tweede notificatie naar de
    vraagsteller sturen bovenop de gerichte question.answered-fanout."""
    key = _webhook_user(conn, "lobke")
    lobke_auth = {"Authorization": f"Bearer {key}"}
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    q = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Rood of blauw?", "kind": "question"},
        headers=lobke_auth,
    ).json()
    # reset deliveries van de assignee-patch/comment hierboven
    conn.execute("DELETE FROM webhook_deliveries")
    conn.commit()
    client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"text": "rood"}, headers=auth
    )
    assert len(_deliveries_for(conn, "lobke")) == 1


def test_answer_does_not_reassign_when_answerer_is_agent(client, auth, conn, project):
    """De reassign is een mens-conventie: als de agent-assignee zijn eigen
    ticket beantwoordt, blijft hij gewoon assignee (geen reassign naar de
    vraagsteller).

    BETON-307: de vraag moet aan een mens gericht zijn — @person erbij
    mentionen maakt dit geldig. BETON-431: de vraag verhuist het ticket naar
    person; een agent die antwoordt triggert geen teruggave, dus het blijft
    bij person."""
    joop_key = _webhook_user(conn, "joop")
    lobke_key = _webhook_user(conn, "lobke")
    joop_auth = {"Authorization": f"Bearer {joop_key}"}
    lobke_auth = {"Authorization": f"Bearer {lobke_key}"}
    client.patch("/api/v1/items/SOS-1", json={"assignee": "lobke"}, headers=auth)
    q = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Rood of blauw, @person?", "kind": "question"},
        headers=joop_auth,
    ).json()
    client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"text": "rood"}, headers=lobke_auth
    )
    item = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert item["assignee"] == "person"


def test_answer_reassign_records_item_updated_event(client, auth, conn, project):
    """De reassign legt wél een item.updated-event vast (voor SSE/activiteit)."""
    key = _webhook_user(conn, "lobke")
    lobke_auth = {"Authorization": f"Bearer {key}"}
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    q = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Rood of blauw?", "kind": "question"},
        headers=lobke_auth,
    ).json()
    client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"text": "rood"}, headers=auth
    )
    item_id = conn.execute(
        "SELECT id FROM items WHERE seq = 1"
    ).fetchone()["id"]
    events = conn.execute(
        "SELECT * FROM events WHERE item_id = ? AND type = 'item.updated' "
        "ORDER BY id",
        (item_id,),
    ).fetchall()
    import json as json_mod

    payloads = [json_mod.loads(e["payload"]) for e in events]
    reassign_payloads = [p for p in payloads if p.get("assignee", {}).get("to") == "lobke"]
    assert len(reassign_payloads) == 1


# --- Antwoord op een stale-vraag (BETON-375) --------------------------------


def _stale_question(client, conn, headers, *, ref="SOS-1"):
    """Plaats een stale-vraag van triage op `ref` en geef het comment-id terug."""
    from betonning import triage as triage_mod

    triage, key = users_repo.create(
        conn, handle="triage", display_name="Triage", kind="agent"
    )
    conn.commit()
    r = client.post(
        f"/api/v1/items/{ref}/comments",
        json={
            "body_md": triage_mod.format_stale_question(3),
            "kind": "question",
            "options": triage_mod.STALE_OPTIONS,
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 201
    return r.json()["id"]


def _state_of(client, headers, ref="SOS-1"):
    return client.get(f"/api/v1/items/{ref}", headers=headers).json()


def test_stale_answer_back_to_todo(client, auth, conn, project):
    """Optie 1 zet het item terug naar todo — deterministisch, geen LLM."""
    client.patch("/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=auth)
    qid = _stale_question(client, conn, auth)

    r = client.post(
        f"/api/v1/comments/{qid}/answer", json={"option_index": 1}, headers=auth
    )
    assert r.status_code == 200
    assert _state_of(client, auth)["state"] == "todo"


def test_stale_answer_releases_to_coding_queue(client, auth, conn, project):
    """Optie 2 zet het item op todo én legt het bij de coding-queue neer."""
    client.patch("/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=auth)
    qid = _stale_question(client, conn, auth)

    client.post(
        f"/api/v1/comments/{qid}/answer", json={"option_index": 2}, headers=auth
    )
    fresh = _state_of(client, auth)
    assert fresh["state"] == "todo"
    assert fresh["assignee"] == "coding-agent"


def test_stale_answer_still_busy_changes_nothing(client, auth, conn, project):
    """Optie 0 laat het item staan — inclusief de toewijzing.

    De valkuil zit in BETON-285: alle vragen beantwoord én de assignee is de
    antwoorder → het item gaat naar de vragensteller. Dat is hier `triage`, en een
    lopend ticket bij de bot parkeren is precies het tegenovergestelde van wat de
    stale-vraag wil."""
    client.patch(
        "/api/v1/items/SOS-1",
        json={"state": "in-progress", "assignee": "person"},
        headers=auth,
    )
    qid = _stale_question(client, conn, auth)

    client.post(
        f"/api/v1/comments/{qid}/answer", json={"option_index": 0}, headers=auth
    )
    fresh = _state_of(client, auth)
    assert fresh["state"] == "in-progress"
    assert fresh["assignee"] == "person"


def test_stale_answer_marks_question_evaluated(client, auth, conn, project):
    """De vraag is hier al afgehandeld; `find_answered_questions` (BETON-389) mag
    er dus géén tweede, LLM-gestuurde ronde overheen doen."""
    from betonning import triage_worker

    client.patch("/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=auth)
    qid = _stale_question(client, conn, auth)
    client.post(
        f"/api/v1/comments/{qid}/answer", json={"option_index": 1}, headers=auth
    )

    triage_id = users_repo.get_by_handle(conn, "triage")["id"]
    assert (
        triage_worker.find_answered_questions(
            conn, triage_user_id=triage_id, debounce_seconds=0, limit=5
        )
        == []
    )


def test_ordinary_question_is_untouched_by_the_stale_hook(client, auth, conn, project):
    """Een gewone vraag zonder de marker verandert niets aan state/assignee."""
    client.patch("/api/v1/items/SOS-1", json={"state": "in-progress"}, headers=auth)
    q = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Rood of blauw?", "kind": "question", "options": ["a", "b"]},
        headers=auth,
    ).json()

    client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"option_index": 1}, headers=auth
    )
    assert _state_of(client, auth)["state"] == "in-progress"


def test_open_questions_no_query_per_question(client, auth, db_path, project):
    """`GET /questions` haalt item-context in dezelfde query op als de vragen,
    niet per vraag een `items_repo.get` + volledige `serialize`."""
    from betonning import db as db_module
    from betonning.api.items import list_questions

    for n in range(2, 6):
        client.post("/api/v1/projects/SOS/items", json={"title": f"t{n}"}, headers=auth)
        client.post(
            f"/api/v1/items/SOS-{n}/comments",
            json={"body_md": "Rood of blauw?", "kind": "question"},
            headers=auth,
        )

    traced = db_module.connect(db_path)
    statements: list[str] = []
    user = users_repo.get_by_handle(traced, "person")
    traced.set_trace_callback(statements.append)
    result = list_questions(open=True, conn=traced, user=user)
    traced.close()

    assert [q["item"]["ref"] for q in result] == [f"SOS-{n}" for n in range(2, 6)]
    assert all(q["item"]["state"] and q["item"]["title"] for q in result)
    assert sum(1 for s in statements if "FROM items WHERE id" in s) == 0


def test_only_answerer_or_human_edits_answer(client, auth, conn, project):
    """Binnen het grace-venster mag de antwoorder (of een mens) het antwoord
    nog wijzigen, een andere agent niet: die zou Persons antwoord herschrijven
    vóór het de vraagsteller bereikt."""
    lobke = {"Authorization": f"Bearer {_webhook_user(conn, 'lobke')}"}
    joop = {"Authorization": f"Bearer {_webhook_user(conn, 'joop')}"}
    q = _ask(client, auth)
    client.post(f"/api/v1/comments/{q['id']}/answer", json={"text": "rood"}, headers=auth)
    r = client.patch(f"/api/v1/comments/{q['id']}/answer", json={"text": "blauw"},
                     headers=lobke)
    assert r.status_code == 403

    q2 = _ask(client, auth, body="Groen of geel?")
    client.post(f"/api/v1/comments/{q2['id']}/answer", json={"text": "groen"}, headers=joop)
    assert client.patch(f"/api/v1/comments/{q2['id']}/answer", json={"text": "geel"},
                        headers=joop).status_code == 200
    assert client.patch(f"/api/v1/comments/{q2['id']}/answer", json={"text": "geel!"},
                        headers=auth).status_code == 200
