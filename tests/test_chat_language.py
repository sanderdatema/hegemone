"""Tweetalige chatstatus/validatie zonder historische inhoud te herschrijven."""

import json

import pytest

from betonning import triage_chat_engine as engine, triage_commands as commands, server
from betonning.repo import items, projects, triage_chat as chat, users


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(server, "load_dotenv", lambda: None)
    monkeypatch.delenv("HEGEMONE_LANGUAGE", raising=False)
    monkeypatch.delenv("BETONNING_LANGUAGE", raising=False)


class Proposal:
    def __init__(self, ref, verb="archive", params=None):
        self.ref, self.verb, self.params = ref, verb, params or {}

    def complete(self, messages):
        return json.dumps(
            {
                "kind": "proposal",
                "summary": "Mijn eigen samenvatting {p0}",
                "commands": [
                    {
                        "verb": self.verb,
                        "selector": {"refs": [self.ref]},
                        "params": self.params,
                    }
                ],
            }
        )


def prepare(client, auth, project, conn):
    item = client.post(
        f"/api/v1/projects/{project}/items", headers=auth, json={"title": "Eigen taak"}
    ).json()
    human = users.get_by_handle(conn, "person")["id"]
    return item, human, projects.get_by_key(conn, project)["id"]


@pytest.mark.parametrize("language", ["en", "nl"])
def test_confirm_preserves_preview_and_user_data_and_recognizes_status(
    client, auth, project, conn, monkeypatch, language
):
    monkeypatch.setenv("HEGEMONE_LANGUAGE", language)
    item, human, pid = prepare(client, auth, project, conn)
    proposal = engine.run_turn(
        conn, Proposal(item["ref"]), "Mijn verzoek", human, project_id=pid
    )
    assert proposal["kind"] == "proposal"
    assert items.get_by_ref(conn, item["ref"])["archived_at"] is None
    result = engine.confirm(conn, proposal["message"]["id"], human)
    expected = "Executed on 1 item:" if language == "en" else "Uitgevoerd op 1 item(s):"
    assert result["message"]["body_md"].startswith(expected)
    assert item["ref"] in result["message"]["body_md"]
    assert (
        chat.get_message(conn, proposal["message"]["id"])["body_md"]
        == "Mijn eigen samenvatting {p0}"
    )
    assert engine._status_note(result["message"]["body_md"]) is not None
    assert items.get_by_ref(conn, item["ref"])["archived_at"] is not None


@pytest.mark.parametrize("language", ["en", "nl"])
def test_cancel_and_expiry_are_localized_without_execution(
    client, auth, project, conn, monkeypatch, language
):
    monkeypatch.setenv("HEGEMONE_LANGUAGE", language)
    item, human, pid = prepare(client, auth, project, conn)
    proposed = engine.run_turn(
        conn, Proposal(item["ref"]), "Cancel", human, project_id=pid
    )
    cancelled = engine.cancel(conn, proposed["message"]["id"])["message"]["body_md"]
    assert cancelled == (
        "Proposal cancelled." if language == "en" else "Voorstel geannuleerd."
    )
    proposed = engine.run_turn(
        conn,
        Proposal(item["ref"], "set_state", {"state": "todo"}),
        "Change",
        human,
        project_id=pid,
    )
    conn.execute("DELETE FROM states WHERE project_id=? AND name='todo'", (pid,))
    result = engine.confirm(conn, proposed["message"]["id"], human)
    assert result["executed"] == []
    assert result["message"]["body_md"].startswith(
        "Proposal expired:" if language == "en" else "Voorstel verlopen:"
    )
    assert (
        "Unknown state: todo" if language == "en" else "Onbekende state: todo"
    ) in result["message"]["body_md"]
    assert engine._status_note(result["message"]["body_md"]) is not None
    assert items.get_by_ref(conn, item["ref"])["archived_at"] is None


def test_bulk_count_gate_and_both_history_languages_remain_intact(
    client, auth, project, conn, monkeypatch
):
    monkeypatch.setenv("HEGEMONE_LANGUAGE", "en")
    monkeypatch.setattr(engine, "BULK_CONFIRM_THRESHOLD", 0)
    item, human, pid = prepare(client, auth, project, conn)
    proposed = engine.run_turn(
        conn, Proposal(item["ref"]), "Archive", human, project_id=pid
    )
    with pytest.raises(engine.ConfirmationRequired) as error:
        engine.confirm(conn, proposed["message"]["id"], human)
    assert error.value.total == 1 and "Type 1" in str(error.value)
    assert items.get_by_ref(conn, item["ref"])["archived_at"] is None
    assert (
        engine.confirm(conn, proposed["message"]["id"], human, typed_count=1)["kind"]
        == "done"
    )
    session = chat.active_session(conn, pid)
    source = [
        "Voorstel geannuleerd.",
        "Proposal cancelled.",
        "Voorstel verlopen: Eigen reden {rest}",
        "Proposal expired: Own reason {rest}",
        "Uitgevoerd op 2 item(s): OWN-1",
        "Executed on 1 item: OWN-2",
    ]
    for text in source:
        chat.add_message(conn, session["id"], "assistant", None, text)
    rows = chat.list_messages(conn, session["id"])
    messages = engine.build_chat_messages(conn, pid, rows)
    assert all(engine._status_note(text) is not None for text in source)
    assert any(
        message["role"] == "user"
        and message["content"].startswith("[status] The user cancelled")
        for message in messages
    )
    assert [row["body_md"] for row in chat.list_messages(conn, session["id"])][
        -len(source) :
    ] == source


def test_command_errors_use_language_without_changing_selector_rules(
    client, auth, project, conn, monkeypatch
):
    _, _, pid = prepare(client, auth, project, conn)
    command = commands.Command(
        "set_state", pid, selector={"refs": ["invalid {p0}"]}, params={"state": "todo"}
    )
    monkeypatch.setenv("HEGEMONE_LANGUAGE", "en")
    assert commands.validate(conn, command) == ["Invalid ref: 'invalid {p0}'"]
    monkeypatch.setenv("HEGEMONE_LANGUAGE", "nl")
    assert commands.validate(conn, command) == ["Ongeldige ref: 'invalid {p0}'"]


@pytest.mark.parametrize("language", ["en", "nl"])
def test_pending_wiki_response_preserves_proposal_content(
    client, auth, conn, monkeypatch, language
):
    monkeypatch.setenv("HEGEMONE_LANGUAGE", language)
    _, key = users.create(conn, handle="writer", display_name="Writer", kind="agent")
    response = client.post(
        "/api/v1/wiki",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "slug": "own-policy",
            "title": "Mijn titel",
            "body_md": "Mijn inhoud {message}",
        },
    )
    assert response.status_code == 201
    value = response.json()
    assert value["status"] == "pending" and value["body_md"] == "Mijn inhoud {message}"
    assert value["message"] == (
        "Awaiting human approval"
        if language == "en"
        else "Wacht op menselijke goedkeuring"
    )
    assert client.get("/api/v1/wiki/own-policy", headers=auth).status_code == 404
