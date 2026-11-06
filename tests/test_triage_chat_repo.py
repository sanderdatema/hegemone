"""Chat-met-triage-repository (BETON-120): sessie-scoping + berichten/acties."""

from __future__ import annotations

import pytest

from betonning.repo import projects as projects_repo
from betonning.repo import triage_chat


@pytest.fixture
def setup(conn, seed_cast):
    p = projects_repo.create(conn, key="SOS", name="SOS")
    return {
        "project_id": p["id"],
        "person_id": seed_cast["person"]["id"],
        "triage_id": seed_cast["triage"]["id"],
    }


# --- active_session / archive_session --------------------------------------


def test_active_session_creates_lazily(conn, setup):
    s = triage_chat.active_session(conn, None)
    assert s["project_id"] is None
    assert s["archived_at"] is None


def test_active_session_is_stable_until_archived(conn, setup):
    s1 = triage_chat.active_session(conn, None)
    s2 = triage_chat.active_session(conn, None)
    assert s1["id"] == s2["id"]


def test_active_session_scopes_global_and_project_separately(conn, setup):
    global_s = triage_chat.active_session(conn, None)
    project_s = triage_chat.active_session(conn, setup["project_id"])
    assert global_s["id"] != project_s["id"]
    assert project_s["project_id"] == setup["project_id"]


def test_archive_session_starts_fresh_session(conn, setup):
    s1 = triage_chat.active_session(conn, None)
    triage_chat.archive_session(conn, s1["id"])
    s2 = triage_chat.active_session(conn, None)
    assert s2["id"] != s1["id"]
    assert s2["archived_at"] is None
    # de oude sessie blijft bestaan (historie), maar is niet meer actief
    old = conn.execute(
        "SELECT * FROM triage_chat_sessions WHERE id = ?", (s1["id"],)
    ).fetchone()
    assert old["archived_at"] is not None


def test_two_projects_have_independent_sessions(conn, setup):
    other = projects_repo.create(conn, key="SKY", name="Sky")
    conn.commit()
    s_sos = triage_chat.active_session(conn, setup["project_id"])
    s_sky = triage_chat.active_session(conn, other["id"])
    assert s_sos["id"] != s_sky["id"]


# --- messages ---------------------------------------------------------------


def test_add_and_list_messages_in_order(conn, setup):
    session = triage_chat.active_session(conn, None)
    triage_chat.add_message(
        conn, session["id"], "user", setup["person_id"], "hoeveel open bugs?"
    )
    triage_chat.add_message(conn, session["id"], "assistant", None, "7 stuks.")
    msgs = triage_chat.list_messages(conn, session["id"])
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["body_md"] == "hoeveel open bugs?"


def test_list_messages_respects_limit_but_stays_chronological(conn, setup):
    session = triage_chat.active_session(conn, None)
    for i in range(5):
        triage_chat.add_message(conn, session["id"], "user", setup["person_id"], f"msg{i}")
    msgs = triage_chat.list_messages(conn, session["id"], limit=2)
    assert [m["body_md"] for m in msgs] == ["msg3", "msg4"]


def test_messages_are_scoped_to_their_session(conn, setup):
    s1 = triage_chat.active_session(conn, None)
    triage_chat.add_message(conn, s1["id"], "user", setup["person_id"], "in sessie 1")
    triage_chat.archive_session(conn, s1["id"])
    s2 = triage_chat.active_session(conn, None)
    triage_chat.add_message(conn, s2["id"], "user", setup["person_id"], "in sessie 2")
    assert [m["body_md"] for m in triage_chat.list_messages(conn, s1["id"])] == ["in sessie 1"]
    assert [m["body_md"] for m in triage_chat.list_messages(conn, s2["id"])] == ["in sessie 2"]


def test_add_message_with_proposal_serializes_json(conn, setup):
    session = triage_chat.active_session(conn, None)
    proposal = {"verb": "archive", "project": "SOS", "refs": ["SOS-1", "SOS-2"]}
    msg = triage_chat.add_message(
        conn, session["id"], "assistant", None, "voorstel",
        proposal=proposal, status="pending",
    )
    assert msg["status"] == "pending"
    fetched = triage_chat.serialize_message(msg)
    assert fetched["proposal"] == proposal


def test_message_without_proposal_serializes_to_none(conn, setup):
    session = triage_chat.active_session(conn, None)
    msg = triage_chat.add_message(conn, session["id"], "assistant", None, "gewoon antwoord")
    assert triage_chat.serialize_message(msg)["proposal"] is None


def test_set_message_status_and_get_pending(conn, setup):
    session = triage_chat.active_session(conn, None)
    msg = triage_chat.add_message(
        conn, session["id"], "assistant", None, "archiveer?",
        proposal={"verb": "archive"}, status="pending",
    )
    pending = triage_chat.get_pending(conn, session["id"])
    assert pending["id"] == msg["id"]

    triage_chat.set_message_status(conn, msg["id"], "confirmed")
    assert triage_chat.get_pending(conn, session["id"]) is None
    assert triage_chat.get_message(conn, msg["id"])["status"] == "confirmed"


def test_get_pending_ignores_other_sessions(conn, setup):
    s1 = triage_chat.active_session(conn, setup["project_id"])
    triage_chat.add_message(
        conn, s1["id"], "assistant", None, "archiveer?",
        proposal={"verb": "archive"}, status="pending",
    )
    s2 = triage_chat.active_session(conn, None)  # andere scope
    assert triage_chat.get_pending(conn, s2["id"]) is None


# --- actions (audit) --------------------------------------------------------


def test_record_action_roundtrip(conn, setup):
    session = triage_chat.active_session(conn, setup["project_id"])
    msg = triage_chat.add_message(conn, session["id"], "user", setup["person_id"], "archiveer >30d")
    action = triage_chat.record_action(
        conn,
        message_id=msg["id"],
        commanded_by=setup["person_id"],
        verb="archive",
        project_id=setup["project_id"],
        params={"updated_before_days": 30},
        target_refs=["SOS-1", "SOS-2"],
    )
    row = conn.execute(
        "SELECT * FROM triage_chat_actions WHERE id = ?", (action["id"],)
    ).fetchone()
    assert row["verb"] == "archive"
    assert row["commanded_by"] == setup["person_id"]
    import json
    assert json.loads(row["target_refs"]) == ["SOS-1", "SOS-2"]
    assert json.loads(row["params"]) == {"updated_before_days": 30}
