"""Veroudering van guardrails (BETON-420, fase 4).

Een guardrail kost elke agent tokens, elke ronde. Daarom een verplichte
reviewdatum: is die verstreken, dan legt triage de vaste vraag "geldt dit nog?"
voor via de vraagmodule. Géén LLM — vraag en opties liggen vast.
"""

from __future__ import annotations

import sqlite3

import pytest

from betonning import triage as triage_mod
from betonning import triage_worker
from betonning.repo import guardrails as guardrails_repo
from betonning.repo import items as items_repo
from betonning.repo import users as users_repo


# --- Stap 4.1: vraag en opties (pure functies) -----------------------------


def test_review_vraag_draagt_marker_tekst_en_datum():
    body = triage_mod.format_guardrail_review_question(
        "Houd prompts kort.", "2020-01-01", mention="person"
    )
    assert body.splitlines()[0] == triage_mod.GUARDRAIL_REVIEW_MARKER
    assert "@person" in body
    assert "Houd prompts kort." in body
    assert "2020-01-01" in body
    assert triage_mod.is_guardrail_review_question(body)


def test_alleen_de_reviewmarker_telt_als_reviewvraag():
    """BETON-422: de voorstel-vraagroute is weg, de reviewroute bleef. Een
    gewone comment (of een oude voorstel-body) is nooit een reviewvraag."""
    review = triage_mod.format_guardrail_review_question("t", "2020-01-01")
    assert triage_mod.is_guardrail_review_question(review) is True
    assert triage_mod.is_guardrail_review_question("[Guardrail-voorstel]\n\n> t") is False
    assert triage_mod.is_guardrail_review_question("zomaar een comment") is False
    assert triage_mod.is_guardrail_review_question(None) is False


def test_review_opties_zijn_een_contract():
    assert triage_mod.GUARDRAIL_REVIEW_OPTIONS == [
        "Blijft geldig — verleng de reviewdatum",
        "Vervalt — hef de guardrail op",
        "Aanpassen — ik pas de tekst zelf aan",
    ]


@pytest.fixture
def seeded(client, auth, conn: sqlite3.Connection):
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    client.put("/api/v1/projects/SOS/triage", json={"enabled": True}, headers=auth)
    for title in ("een", "twee"):
        client.post("/api/v1/projects/SOS/items", json={"title": title}, headers=auth)
    users_repo.create(conn, handle="triage", display_name="Triage", kind="agent")
    conn.commit()
    return conn


def _triage_id(conn):
    return users_repo.get_by_handle(conn, "triage")["id"]


def _set(conn, ref="SOS-1", text="Houd prompts kort.", review_by="2020-01-01"):
    item = items_repo.get_by_ref(conn, ref)
    guardrails_repo.set_guardrail(
        conn, item["id"], text=text, review_by=review_by, set_by=None
    )
    return items_repo.get_by_ref(conn, ref)


def test_optie_nul_verlengt_en_reset_de_marker(seeded):
    conn = seeded
    item = _set(conn)
    conn.execute(
        "UPDATE items SET guardrail_review_asked_at = '2020-02-02' WHERE id = ?",
        (item["id"],),
    )
    fields = triage_mod.apply_guardrail_review_answer(conn, item, 0)
    fresh = items_repo.get(conn, item["id"])
    assert fresh["guardrail_review_by"] > "2020-01-01"
    assert fresh["guardrail_review_asked_at"] is None
    assert fresh["guardrail_lifted_at"] is None
    assert "guardrail_review_by" in fields


def test_optie_een_heft_op_maar_laat_de_tekst_staan(seeded):
    conn = seeded
    item = _set(conn)
    triage_mod.apply_guardrail_review_answer(conn, item, 1)
    fresh = items_repo.get(conn, item["id"])
    assert fresh["guardrail_lifted_at"] is not None
    assert fresh["guardrail_md"] == "Houd prompts kort."


@pytest.mark.parametrize("index", [2, None])
def test_optie_twee_en_vrije_tekst_veranderen_niets(seeded, index):
    conn = seeded
    item = _set(conn)
    assert triage_mod.apply_guardrail_review_answer(conn, item, index) == {}
    fresh = items_repo.get(conn, item["id"])
    assert fresh["guardrail_review_by"] == "2020-01-01"
    assert fresh["guardrail_lifted_at"] is None
# --- Stap 4.2: de poll-query ----------------------------------------------


def _find(conn, limit=10):
    return triage_worker.find_guardrails_due_review(
        conn, triage_user_id=_triage_id(conn), limit=limit
    )


def test_verstreken_reviewdatum_wordt_gevonden(seeded):
    conn = seeded
    item = _set(conn)
    assert _find(conn) == [item["id"]]


def test_toekomstige_reviewdatum_wordt_niet_gevonden(seeded):
    conn = seeded
    _set(conn, review_by="2099-01-01")
    assert _find(conn) == []


def test_opgeheven_en_gearchiveerde_guardrails_vallen_af(seeded):
    conn = seeded
    a = _set(conn, "SOS-1")
    b = _set(conn, "SOS-2")
    guardrails_repo.lift(conn, a["id"])
    conn.execute("UPDATE items SET archived_at = '2021-01-01' WHERE id = ?", (b["id"],))
    assert _find(conn) == []


def test_gelockt_ticket_valt_af(seeded, client, auth):
    conn = seeded
    _set(conn)
    client.post("/api/v1/items/SOS-1/lock", headers=auth)
    assert _find(conn) == []


def test_lopende_state_is_geen_voorwaarde(seeded, client, auth):
    """Anders dan `find_stale`: een guardrail geldt in elke state."""
    conn = seeded
    item = _set(conn)
    client.patch("/api/v1/items/SOS-1", json={"state": "done"}, headers=auth)
    assert _find(conn) == [item["id"]]


def test_vraag_stellen_is_idempotent(seeded):
    conn = seeded
    item = _set(conn)
    triage_worker.ask_guardrail_review_once(conn, item["id"], triage_user_id=_triage_id(conn))
    assert items_repo.get(conn, item["id"])["guardrail_review_asked_at"] is not None
    assert _find(conn) == []


def test_openstaand_opheffingsvoorstel_houdt_de_reviewvraag_tegen(seeded):
    """BETON-422: "geldt hij nog?" ligt dan al bij de mens; een reviewvraag
    ernaast stelt dezelfde beslissing twee keer met twee gevolgen."""
    conn = seeded
    item = _set(conn)
    guardrails_repo.propose(
        conn, item["id"], kind="lift", reason="niet meer nodig", proposed_by=None
    )
    assert _find(conn) == []

    # Een `set`-concept is een ander voorstel en sluit de reviewvraag niet uit.
    guardrails_repo.propose(
        conn, item["id"], kind="set", text="andere tekst", proposed_by=None
    )
    assert _find(conn) == [item["id"]]


def test_open_review_vraag_houdt_een_tweede_tegen(seeded):
    conn = seeded
    item = _set(conn)
    triage_worker.ask_guardrail_review_once(conn, item["id"], triage_user_id=_triage_id(conn))
    # Marker terug op NULL (alsof er een nieuwe reviewdatum kwam), maar de eerste
    # vraag staat nog open → nog steeds geen tweede vraag.
    conn.execute(
        "UPDATE items SET guardrail_review_asked_at = NULL WHERE id = ?", (item["id"],)
    )
    assert _find(conn) == []


def test_de_vraag_is_een_vraagmodule_vraag_aan_de_mens(seeded, client, auth):
    conn = seeded
    item = _set(conn)
    triage_worker.ask_guardrail_review_once(conn, item["id"], triage_user_id=_triage_id(conn))
    detail = client.get("/api/v1/items/SOS-1", headers=auth).json()
    question = [c for c in detail["comments"] if c["kind"] == "question"][-1]
    assert question["author"] == "triage"
    assert question["question_options"] == triage_mod.GUARDRAIL_REVIEW_OPTIONS
    assert "@person" in question["body_md"]
    # Hij bereikt de mens via de mention (hij is geen assignee).
    open_qs = client.get("/api/v1/questions?open=true", headers=auth).json()
    assert [q["item"]["ref"] for q in open_qs] == ["SOS-1"]
# --- Stap 4.3: antwoordpad -------------------------------------------------


def _ask(conn, client, auth, ref="SOS-1"):
    item = items_repo.get_by_ref(conn, ref)
    triage_worker.ask_guardrail_review_once(conn, item["id"], triage_user_id=_triage_id(conn))
    detail = client.get(f"/api/v1/items/{ref}", headers=auth).json()
    return [c for c in detail["comments"] if c["kind"] == "question"][-1]["id"]


def _answer(client, headers, qid, option_index=None, text=None):
    payload = {"option_index": option_index} if text is None else {"text": text}
    return client.post(f"/api/v1/comments/{qid}/answer", json=payload, headers=headers)


def test_antwoord_blijft_geldig_verlengt(seeded, client, auth):
    conn = seeded
    _set(conn)
    qid = _ask(conn, client, auth)
    assert _answer(client, auth, qid, option_index=0).status_code == 200

    item = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert item["guardrail_review_by"] > "2020-01-01"
    assert item["has_guardrail"] is True
    row = conn.execute(
        "SELECT evaluated_at, answered_at FROM comments WHERE id = ?", (qid,)
    ).fetchone()
    assert row["evaluated_at"] >= row["answered_at"]
    types = [
        e["type"]
        for e in client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    ]
    assert "item.guardrail_set" in types


def test_antwoord_vervalt_heft_op(seeded, client, auth):
    conn = seeded
    _set(conn)
    qid = _ask(conn, client, auth)
    _answer(client, auth, qid, option_index=1)
    item = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert item["has_guardrail"] is False
    assert item["guardrail_md"] == "Houd prompts kort."
    types = [
        e["type"]
        for e in client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    ]
    assert "item.guardrail_lifted" in types


def test_vrije_tekst_verandert_niets_maar_zet_evaluated_at_vooruit(seeded, client, auth):
    conn = seeded
    _set(conn)
    qid = _ask(conn, client, auth)
    _answer(client, auth, qid, text="ik pas 'm zelf aan")
    item = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert item["guardrail_review_by"] == "2020-01-01"
    row = conn.execute(
        "SELECT evaluated_at, answered_at FROM comments WHERE id = ?", (qid,)
    ).fetchone()
    assert row["evaluated_at"] >= row["answered_at"]


def test_agent_mag_de_review_niet_beantwoorden(seeded, client, auth, conn):
    _set(conn)
    qid = _ask(conn, client, auth)
    _, key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent", agent_type="coding"
    )
    conn.commit()
    r = _answer(client, {"Authorization": f"Bearer {key}"}, qid, option_index=1)
    assert r.status_code == 403
    item = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert item["has_guardrail"] is True
    assert (
        conn.execute("SELECT answered_at FROM comments WHERE id = ?", (qid,)).fetchone()[
            "answered_at"
        ]
        is None
    )


def test_ticket_wordt_niet_aan_triage_toegewezen(seeded, client, auth):
    conn = seeded
    _set(conn)
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    qid = _ask(conn, client, auth)
    _answer(client, auth, qid, option_index=0)
    item = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert item["assignee"] == "person"


def test_na_verlengen_vindt_de_finder_hem_niet_meteen_opnieuw(seeded, client, auth):
    conn = seeded
    _set(conn)
    qid = _ask(conn, client, auth)
    _answer(client, auth, qid, option_index=0)
    assert _find(conn) == []

    # Maar wél zodra de nieuwe reviewdatum verstreken is.
    item = items_repo.get_by_ref(conn, "SOS-1")
    conn.execute(
        "UPDATE items SET guardrail_review_by = '2020-01-01' WHERE id = ?", (item["id"],)
    )
    assert _find(conn) == [item["id"]]


@pytest.fixture(autouse=True)
def legacy_dutch_system_text(monkeypatch):
    """Bestaande Nederlandse tekst-/optiecontracten worden expliciet getest."""
    monkeypatch.setenv('HEGEMONE_LANGUAGE', 'nl')
