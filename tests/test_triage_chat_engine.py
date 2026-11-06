"""Chat-motor voor chat-met-triage (BETON-120): query-lus, voorstel/bevestig, scope."""

from __future__ import annotations

import json

import pytest

from betonning import triage_chat_engine as engine
from betonning.repo import items as items_repo
from betonning.repo import projects as projects_repo
from betonning.repo import triage_chat as chat_repo
from betonning.repo import users as users_repo


class ScriptedLLM:
    """Geeft achtereenvolgens de vooraf-bepaalde replies terug (dicts → JSON).
    Zo kunnen we de query-lus (meerdere calls per beurt) sturen."""

    def __init__(self, replies: list) -> None:
        self._replies = list(replies)
        self.calls: list[list[dict]] = []

    def complete(self, messages):
        self.calls.append(messages)
        reply = self._replies.pop(0)
        return reply if isinstance(reply, str) else json.dumps(reply)


@pytest.fixture
def setup(conn):
    p = projects_repo.create(conn, key="SOS", name="SOS")
    person, _ = users_repo.create(conn, handle="person", display_name="Person", kind="human")
    users_repo.create(conn, handle="triage", display_name="Triage", kind="agent")
    conn.commit()
    return {"project_id": p["id"], "person_id": person["id"], "key": "SOS"}


def _make_item(conn, project_id, title, *, state=None, days_old=None):
    seq = projects_repo.next_seq(conn, project_id)
    conn.execute(
        "INSERT INTO items (project_id, seq, title) VALUES (?, ?, ?)",
        (project_id, seq, title),
    )
    key = conn.execute("SELECT key FROM projects WHERE id = ?", (project_id,)).fetchone()["key"]
    item = items_repo.get_by_ref(conn, f"{key}-{seq}")
    if state is not None:
        st = conn.execute(
            "SELECT id FROM states WHERE project_id = ? AND name = ?", (project_id, state)
        ).fetchone()
        items_repo.update(conn, item["id"], {"state_id": st["id"]})
    if days_old is not None:
        conn.execute(
            "UPDATE items SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now',?) WHERE id = ?",
            (f"-{days_old} days", item["id"]),
        )
    conn.commit()
    return items_repo.get(conn, item["id"])


# --- parse_chat_output ------------------------------------------------------


def test_parse_valid_kinds():
    assert engine.parse_chat_output('{"kind":"reply","text":"hoi"}')["kind"] == "reply"
    assert engine.parse_chat_output('{"kind":"query","query":{}}')["kind"] == "query"


def test_parse_invalid_json_falls_back_to_reply():
    out = engine.parse_chat_output("gewoon wat tekst zonder json")
    assert out["kind"] == "reply"
    assert "gewoon wat tekst" in out["text"]


def test_parse_unknown_kind_falls_back_to_reply():
    out = engine.parse_chat_output('{"kind":"explode"}')
    assert out["kind"] == "reply"


def test_parse_tolerates_literal_newline_in_string(conn):
    # LLM's produceren soms een letterlijke newline in een JSON-stringwaarde
    # ondanks instructies (BETON-179) — extract_json (strict=False) moet dat
    # nog steeds parsen i.p.v. terugvallen op reply.
    raw = '{"kind":"reply","text":"regel een\nregel twee"}'
    out = engine.parse_chat_output(raw)
    assert out["kind"] == "reply"
    assert out["text"] == "regel een\nregel twee"


# --- build_chat_messages: historie-hygiëne (BETON-181) ----------------------


def test_build_chat_messages_proposal_row_becomes_protocol_json(conn, setup):
    session = chat_repo.active_session(conn, setup["project_id"])
    chat_repo.add_message(conn, session["id"], "user", setup["person_id"], "archiveer oud")
    chat_repo.add_message(
        conn, session["id"], "assistant", None, "Ik ga 1 item archiveren",
        proposal={"summary": "Ik ga 1 item archiveren", "commands": [], "preview": [],
                  "total_count": 1, "threshold": 10},
        status="pending",
    )
    history = chat_repo.list_messages(conn, session["id"])
    messages = engine.build_chat_messages(conn, setup["project_id"], history)
    assistant = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant) == 1
    payload = json.loads(assistant[0]["content"])
    assert payload == {"kind": "proposal", "summary": "Ik ga 1 item archiveren"}


def test_build_chat_messages_plain_reply_becomes_protocol_json(conn, setup):
    session = chat_repo.active_session(conn, setup["project_id"])
    chat_repo.add_message(conn, session["id"], "user", setup["person_id"], "hoi")
    chat_repo.add_message(conn, session["id"], "assistant", None, "Hallo!")
    history = chat_repo.list_messages(conn, session["id"])
    messages = engine.build_chat_messages(conn, setup["project_id"], history)
    assistant = [m for m in messages if m["role"] == "assistant"]
    assert json.loads(assistant[0]["content"]) == {"kind": "reply", "text": "Hallo!"}


def test_build_chat_messages_cancellation_note_becomes_status_line_not_assistant(
    conn, setup
):
    session = chat_repo.active_session(conn, setup["project_id"])
    chat_repo.add_message(conn, session["id"], "user", setup["person_id"], "archiveer oud")
    chat_repo.add_message(
        conn, session["id"], "assistant", None, "Voorstel geannuleerd.",
    )
    history = chat_repo.list_messages(conn, session["id"])
    messages = engine.build_chat_messages(conn, setup["project_id"], history)
    # de annuleringsnotitie komt NIET als platte-tekst assistant-beurt terug —
    # anders papegaait het model "Voorstel geannuleerd." (BETON-181).
    assert not any(m["role"] == "assistant" for m in messages)
    status_lines = [m for m in messages if m["role"] == "user"
                     and m["content"].startswith("[status]")]
    assert len(status_lines) == 1
    assert "annuleerde" in status_lines[0]["content"]


# --- run_turn: reply + query-lus --------------------------------------------


def test_run_turn_plain_reply(conn, setup):
    llm = ScriptedLLM([{"kind": "reply", "text": "Hallo!"}])
    result = engine.run_turn(conn, llm, "hoi", setup["person_id"], project_id=setup["project_id"])
    assert result["kind"] == "reply"
    assert result["message"]["body_md"] == "Hallo!"
    # user + assistant beide opgeslagen
    session = chat_repo.active_session(conn, setup["project_id"])
    assert len(chat_repo.list_messages(conn, session["id"])) == 2


def test_run_turn_query_loop_answers_count(conn, setup):
    _make_item(conn, setup["project_id"], "Bug 1", state="todo")
    _make_item(conn, setup["project_id"], "Bug 2", state="todo")
    llm = ScriptedLLM([
        {"kind": "query", "query": {"filter": {"state_open": True}}},
        {"kind": "reply", "text": "Er zijn 2 open items."},
    ])
    result = engine.run_turn(conn, llm, "hoeveel open?", setup["person_id"],
                             project_id=setup["project_id"])
    assert result["kind"] == "reply"
    assert "2 open" in result["message"]["body_md"]
    # de query-ronde voerde daadwerkelijk een tweede LLM-call uit met resultaat
    assert len(llm.calls) == 2
    assert "Query-resultaat" in llm.calls[1][-1]["content"]


def test_run_turn_query_respects_max_rounds(conn, setup):
    # LLM blijft queries sturen; met max_query_rounds=1 mag er hooguit één query
    # zijn, daarna valt de motor terug op reply.
    llm = ScriptedLLM([
        {"kind": "query", "query": {"filter": {}}},
        {"kind": "query", "query": {"filter": {}}},
        {"kind": "reply", "text": "klaar"},
    ])
    result = engine.run_turn(conn, llm, "tel", setup["person_id"],
                             project_id=setup["project_id"], max_query_rounds=1)
    # ronde 0 = query (uitgevoerd), ronde 1 = tweede antwoord; dat is een query maar
    # de limiet is bereikt → val terug op reply-fallback.
    assert result["kind"] == "reply"
    assert len(llm.calls) == 2


# --- run_turn: proposal → pending (niets gemuteerd) -------------------------


def test_run_turn_proposal_stores_pending_without_mutating(conn, setup):
    item = _make_item(conn, setup["project_id"], "Oud", state="done", days_old=40)
    llm = ScriptedLLM([{
        "kind": "proposal",
        "summary": "Ik ga 1 item archiveren",
        "commands": [{"verb": "archive",
                      "selector": {"filter": {"state_closed": True, "updated_before_days": 30}}}],
    }])
    result = engine.run_turn(conn, llm, "archiveer gesloten >30d", setup["person_id"],
                             project_id=setup["project_id"])
    assert result["kind"] == "proposal"
    msg = result["message"]
    assert msg["status"] == "pending"
    assert msg["proposal"]["total_count"] == 1
    assert msg["proposal"]["preview"][0]["refs"] == [f"SOS-{item['seq']}"]
    # nog NIETS gemuteerd
    assert items_repo.get(conn, item["id"])["archived_at"] is None


def test_run_turn_proposal_with_validation_error_becomes_reply(conn, setup):
    llm = ScriptedLLM([{
        "kind": "proposal",
        "summary": "iets",
        "commands": [{"verb": "set_state",
                      "selector": {"refs": ["SOS-999"]}, "params": {"state": "done"}}],
    }])
    result = engine.run_turn(conn, llm, "doe iets", setup["person_id"],
                             project_id=setup["project_id"])
    assert result["kind"] == "reply"  # geen pending voorstel


def test_global_scope_requires_named_project(conn, setup):
    llm = ScriptedLLM([{
        "kind": "proposal", "summary": "archiveer",
        "commands": [{"verb": "archive", "selector": {"filter": {"state_closed": True}}}],
    }])
    # globale thread (project_id=None), geen project genoemd → wordt reply met fout
    result = engine.run_turn(conn, llm, "archiveer gesloten", setup["person_id"], project_id=None)
    assert result["kind"] == "reply"
    assert "project" in result["message"]["body_md"].lower()


def test_global_scope_resolves_named_project(conn, setup):
    item = _make_item(conn, setup["project_id"], "Oud", state="done", days_old=40)
    llm = ScriptedLLM([{
        "kind": "proposal", "summary": "archiveer",
        "commands": [{"verb": "archive", "project": "SOS",
                      "selector": {"filter": {"state_closed": True}}}],
    }])
    result = engine.run_turn(conn, llm, "archiveer gesloten in SOS", setup["person_id"],
                             project_id=None)
    assert result["kind"] == "proposal"
    assert f"SOS-{item['seq']}" in result["message"]["proposal"]["preview"][0]["refs"]


# --- confirm ----------------------------------------------------------------


def _pending_archive(conn, setup, item):
    llm = ScriptedLLM([{
        "kind": "proposal", "summary": "archiveer 1",
        "commands": [{"verb": "archive", "selector": {"refs": [f"SOS-{item['seq']}"]}}],
    }])
    result = engine.run_turn(conn, llm, "archiveer", setup["person_id"],
                             project_id=setup["project_id"])
    return result["message"]["id"]


def test_confirm_executes_and_logs_action_as_triage(conn, setup):
    item = _make_item(conn, setup["project_id"], "Item")
    msg_id = _pending_archive(conn, setup, item)

    result = engine.confirm(conn, msg_id, setup["person_id"])
    assert result["kind"] == "done"
    assert items_repo.get(conn, item["id"])["archived_at"] is not None
    # bericht is confirmed
    assert chat_repo.get_message(conn, msg_id)["status"] == "confirmed"
    # audit: actie geboekt met de mens als opdrachtgever
    action = conn.execute("SELECT * FROM triage_chat_actions").fetchone()
    assert action["commanded_by"] == setup["person_id"]
    assert action["verb"] == "archive"
    # event geboekt op naam van triage
    triage = users_repo.get_by_handle(conn, "triage")
    ev = conn.execute(
        "SELECT * FROM events WHERE type='item.archived' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert ev["actor_id"] == triage["id"]


def test_confirm_twice_raises_not_pending(conn, setup):
    item = _make_item(conn, setup["project_id"], "Item")
    msg_id = _pending_archive(conn, setup, item)
    engine.confirm(conn, msg_id, setup["person_id"])
    with pytest.raises(engine.ProposalNotPending):
        engine.confirm(conn, msg_id, setup["person_id"])


def test_confirm_bulk_over_threshold_requires_typed_count(conn, setup, monkeypatch):
    monkeypatch.setattr(engine, "BULK_CONFIRM_THRESHOLD", 2)
    for i in range(3):
        _make_item(conn, setup["project_id"], f"Oud {i}", state="done", days_old=40)
    llm = ScriptedLLM([{
        "kind": "proposal", "summary": "archiveer 3",
        "commands": [{"verb": "archive",
                      "selector": {"filter": {"state_closed": True, "updated_before_days": 30}}}],
    }])
    result = engine.run_turn(conn, llm, "archiveer oude", setup["person_id"],
                             project_id=setup["project_id"])
    msg_id = result["message"]["id"]
    assert result["message"]["proposal"]["total_count"] == 3

    with pytest.raises(engine.ConfirmationRequired):
        engine.confirm(conn, msg_id, setup["person_id"])  # geen typed_count
    # met het juiste aantal wél
    done = engine.confirm(conn, msg_id, setup["person_id"], typed_count=3)
    assert done["kind"] == "done"
    assert len(done["executed"]) == 3


def test_confirm_bulk_suppresses_fanout(conn, setup):
    # twee items met een webhook-user als assignee → zónder onderdrukking zou
    # elk een delivery geven. Bulk (>1) mag dat niet.
    _, key = users_repo.create(
        conn, handle="hermes", display_name="Hermes", kind="agent",
        webhook_url="http://example.invalid/hook", webhook_secret="s",
    )
    hermes = users_repo.get_by_handle(conn, "hermes")
    a = _make_item(conn, setup["project_id"], "A")
    b = _make_item(conn, setup["project_id"], "B")
    items_repo.update(conn, a["id"], {"assignee_id": hermes["id"]})
    items_repo.update(conn, b["id"], {"assignee_id": hermes["id"]})
    conn.commit()

    llm = ScriptedLLM([{
        "kind": "proposal", "summary": "archiveer beide",
        "commands": [{"verb": "archive",
                      "selector": {"refs": [f"SOS-{a['seq']}", f"SOS-{b['seq']}"]}}],
    }])
    result = engine.run_turn(conn, llm, "archiveer A en B", setup["person_id"],
                             project_id=setup["project_id"])
    engine.confirm(conn, result["message"]["id"], setup["person_id"])
    deliveries = conn.execute("SELECT COUNT(*) AS n FROM webhook_deliveries").fetchone()["n"]
    assert deliveries == 0


def test_confirm_executes_frozen_preview_not_refiltered(conn, setup):
    # Voorstel met een FILTER-selector. Tussen voorstel en bevestiging wordt een
    # tweede item óók passend gemaakt. Bevestigen mag alléén het gepreviewde item
    # raken (bevroren refs), niet de nieuwe match — anders klopt de veiligheidsrem-
    # telling niet en muteert er meer dan de mens zag.
    seen = _make_item(conn, setup["project_id"], "Gezien", state="done", days_old=40)
    llm = ScriptedLLM([{
        "kind": "proposal", "summary": "archiveer gesloten >30d",
        "commands": [{"verb": "archive",
                      "selector": {"filter": {"state_closed": True, "updated_before_days": 30}}}],
    }])
    result = engine.run_turn(conn, llm, "archiveer gesloten >30d", setup["person_id"],
                             project_id=setup["project_id"])
    msg_id = result["message"]["id"]
    assert result["message"]["proposal"]["preview"][0]["refs"] == [f"SOS-{seen['seq']}"]

    # nu matcht een TWEEDE item de filter ook
    late = _make_item(conn, setup["project_id"], "Later", state="done", days_old=40)

    done = engine.confirm(conn, msg_id, setup["person_id"])
    assert done["executed"] == [f"SOS-{seen['seq']}"]
    assert items_repo.get(conn, seen["id"])["archived_at"] is not None
    assert items_repo.get(conn, late["id"])["archived_at"] is None


def test_cancel_marks_cancelled(conn, setup):
    item = _make_item(conn, setup["project_id"], "Item")
    msg_id = _pending_archive(conn, setup, item)
    engine.cancel(conn, msg_id)
    assert chat_repo.get_message(conn, msg_id)["status"] == "cancelled"
    assert items_repo.get(conn, item["id"])["archived_at"] is None


def test_cancel_then_correction_produces_new_proposal(conn, setup):
    # Gediagnosticeerd prod-probleem (BETON-181): na annuleren + een correctie van
    # de mens moet het model een NIEUW proposal maken i.p.v. platte tekst die het
    # gesprekspatroon papegaait. Met de historie-hygiëne ziet het model de
    # annulering als "[status]"-regel (geen imiteerbare assistant-tekst), dus een
    # FakeLLM die hier keurig JSON teruggeeft simuleert het gewenste gedrag —
    # en dat nieuwe voorstel komt daadwerkelijk als pending bericht terug.
    item = _make_item(conn, setup["project_id"], "Item")
    msg_id = _pending_archive(conn, setup, item)
    engine.cancel(conn, msg_id)

    llm = ScriptedLLM([{
        "kind": "proposal", "summary": "archiveer toch, gecorrigeerd",
        "commands": [{"verb": "archive", "selector": {"refs": [f"SOS-{item['seq']}"]}}],
    }])
    result = engine.run_turn(
        conn, llm, "sorry, archiveer 'm toch wel", setup["person_id"],
        project_id=setup["project_id"],
    )
    assert result["kind"] == "proposal"
    assert result["message"]["status"] == "pending"
    assert result["message"]["proposal"]["summary"] == "archiveer toch, gecorrigeerd"
    # de call naar de LLM bevatte de annulering als statusregel, niet als
    # letterlijke assistant-tekst "Voorstel geannuleerd."
    sent = llm.calls[0]
    assert not any(
        m["role"] == "assistant" and "Voorstel geannuleerd." in m["content"]
        for m in sent
    )
    assert any(
        m["role"] == "user" and m["content"].startswith("[status]") for m in sent
    )


# --- history-bounding + sessie-reset ----------------------------------------


def test_history_window_capped(conn, setup, monkeypatch):
    monkeypatch.setattr(engine, "MAX_HISTORY", 4)
    session = chat_repo.active_session(conn, setup["project_id"])
    for i in range(10):
        chat_repo.add_message(conn, session["id"], "user", setup["person_id"], f"m{i}")
    llm = ScriptedLLM([{"kind": "reply", "text": "ok"}])
    engine.run_turn(conn, llm, "nieuw bericht", setup["person_id"],
                    project_id=setup["project_id"])
    # de messages naar de LLM: system + exact 4 history (die eindigt met het
    # huidige bericht — niet dubbel toegevoegd).
    non_system = [m for m in llm.calls[0] if m["role"] != "system"]
    assert len(non_system) == 4
    assert non_system[-1]["content"] == "nieuw bericht"
    assert [m["content"] for m in non_system].count("nieuw bericht") == 1


def test_new_session_resets_context(conn, setup):
    session = chat_repo.active_session(conn, setup["project_id"])
    chat_repo.add_message(conn, session["id"], "user", setup["person_id"], "oud")
    chat_repo.archive_session(conn, session["id"])
    llm = ScriptedLLM([{"kind": "reply", "text": "ok"}])
    engine.run_turn(conn, llm, "vers", setup["person_id"], project_id=setup["project_id"])
    # de nieuwe sessie bevat alleen het verse bericht + antwoord, niet 'oud'
    fresh = chat_repo.active_session(conn, setup["project_id"])
    bodies = [m["body_md"] for m in chat_repo.list_messages(conn, fresh["id"])]
    assert "oud" not in bodies
    assert "vers" in bodies


def test_scopes_do_not_share_history(conn, setup):
    gs = chat_repo.active_session(conn, None)
    chat_repo.add_message(conn, gs["id"], "user", setup["person_id"], "globaal bericht")
    llm = ScriptedLLM([{"kind": "reply", "text": "ok"}])
    engine.run_turn(conn, llm, "project bericht", setup["person_id"],
                    project_id=setup["project_id"])
    ps = chat_repo.active_session(conn, setup["project_id"])
    bodies = [m["body_md"] for m in chat_repo.list_messages(conn, ps["id"])]
    assert "globaal bericht" not in bodies


@pytest.fixture(autouse=True)
def legacy_dutch_chat_contract(monkeypatch):
    """De bestaande Nederlandstalige chat-/validatiecontracten blijven expliciet."""
    monkeypatch.setenv('HEGEMONE_LANGUAGE', 'nl')


def test_run_turn_rejects_negative_round_limit_without_storing_message(conn, setup):
    llm = ScriptedLLM([])
    with pytest.raises(ValueError, match="max_query_rounds"):
        engine.run_turn(conn, llm, "hoi", setup["person_id"], max_query_rounds=-1)
    assert conn.execute("SELECT COUNT(*) FROM triage_chat_messages").fetchone()[0] == 0
