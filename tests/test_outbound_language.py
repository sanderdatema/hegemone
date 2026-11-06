"""Uitvoer lokaliseren zonder acties, bronwaarden of payloadcontract te wijzigen."""

import copy
import json
import string

import pytest

from betonning import config, webhooks
from betonning.outbound import MESSAGES, outbound


@pytest.fixture(autouse=True)
def clean_language(monkeypatch):
    monkeypatch.delenv("HEGEMONE_LANGUAGE", raising=False)
    monkeypatch.delenv("BETONNING_LANGUAGE", raising=False)


def test_catalog_parameter_parity_and_fallback():
    fmt = string.Formatter()
    for key, entry in MESSAGES.items():
        assert {name for _, name, _, _ in fmt.parse(entry["en"]) if name} == {
            name for _, name, _, _ in fmt.parse(entry["nl"]) if name
        }, key
    assert (
        outbound("action_do.2", language="unknown", p0="EIGEN-{p0}")
        == "Respond substantively to EIGEN-{p0} in a comment, from your role."
    )
    assert config.installation_language() == "en"


@pytest.mark.parametrize(
    "action_case",
    ["assigned", "mention", "cancelled", "answered", "informational", "blocked"],
)
def test_instruction_actions_and_data_are_language_independent(
    monkeypatch, action_case
):
    item = {
        "ref": "OWN-12",
        "project": "OWN",
        "seq": 12,
        "state": "eigen-status",
        "assignee": "builder",
        "has_plan": True,
    }
    trigger = {
        "type": "assigned",
        "changed_fields": ["assignee"],
        "assignee_changed_to_me": True,
    }
    policy = {"state": "eigen-status", "work_allowed": True}
    event = "item.updated"
    if action_case == "mention":
        trigger = {"type": "mention", "mentioned_by": "eigen-actor"}
        event = "comment.created"
    if action_case == "cancelled":
        trigger = {
            "type": "assigned",
            "changed_fields": ["state"],
            "to_state_grp": "cancelled",
        }
    if action_case == "answered":
        event = "question.answered"
    if action_case == "informational":
        trigger = {"type": "subscribe_all"}
    if action_case == "blocked":
        policy["work_allowed"] = False
    before = copy.deepcopy((item, trigger, policy))
    outputs = {}
    for language in ["en", "nl"]:
        monkeypatch.setenv("HEGEMONE_LANGUAGE", language)
        outputs[language] = webhooks.build_instructions(
            {"handle": "builder"}, item, trigger, policy, event_type=event
        )
    en, nl = outputs["en"], outputs["nl"]
    expected = {
        "assigned": "pick_up",
        "mention": "respond",
        "cancelled": "stand_down",
        "answered": "answered",
        "informational": "none",
        "blocked": "acknowledge",
    }
    assert en["expected_action"] == nl["expected_action"] == expected[action_case]
    assert en["reply"]["ref"] == nl["reply"]["ref"] == "OWN-12"
    assert en["reply"]["url"] == nl["reply"]["url"]
    assert [entry["hoe"] for entry in en["read"]] == [
        entry["hoe"] for entry in nl["read"]
    ]
    assert len(en["do_not"]) == len(nl["do_not"])
    assert en["instructions"] != nl["instructions"]
    assert before == (item, trigger, policy)
    if en["expected_action"] == "stand_down":
        assert en["read"] == [] and "STOP" in en["instructions"]
        assert any("Do not post a comment" in text for text in en["do_not"])


def test_saved_context_and_deployment_priority(monkeypatch):
    with config.runtime_context({"BETONNING_LANGUAGE": "nl"}):
        assert config.installation_language() == "nl"
        assert outbound("telegram_headline.1").startswith("🔒 Op slot")
        monkeypatch.setenv("BETONNING_LANGUAGE", "en")
        assert config.installation_language() == "en"
        monkeypatch.setenv("HEGEMONE_LANGUAGE", "nl")
        assert config.installation_language() == "nl"


def test_telegram_preserves_title_and_escapes_html(
    client, auth, conn, project, monkeypatch
):
    item = client.post(
        f"/api/v1/projects/{project}/items",
        headers=auth,
        json={"title": "Mijn <titel> & inhoud"},
    ).json()
    client.post(f"/api/v1/items/{item['ref']}/lock", headers=auth)
    event = conn.execute(
        "SELECT * FROM events WHERE type='item.locked' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    monkeypatch.setenv("HEGEMONE_LANGUAGE", "en")
    text = webhooks._telegram_text(conn, event)
    assert (
        "Locked (emergency stop)" in text and "Mijn &lt;titel&gt; &amp; inhoud" in text
    )
    monkeypatch.setenv("HEGEMONE_LANGUAGE", "nl")
    assert "Op slot (noodstop)" in webhooks._telegram_text(conn, event)


def test_dispatcher_uses_saved_installation_language_with_fake_transport(
    client, auth, conn, db_path, monkeypatch
):
    import asyncio
    import httpx
    from betonning.repo import users

    monkeypatch.setenv("HEGEMONE_WEBHOOK_ALLOWED_HOSTS", "")
    monkeypatch.setenv("HEGEMONE_AI_LANGUAGE", "en")
    response = client.patch(
        "/api/v1/settings/installation",
        headers=auth,
        json={
            "schema_version": 1,
            "expected_revision": 0,
            "settings": {"language": "nl"},
        },
    )
    assert response.status_code == 200
    users.create(
        conn,
        handle="localized-receiver",
        display_name="Receiver",
        kind="agent",
        webhook_url="https://203.0.113.10/events",
    )
    assert (
        client.post(
            "/api/v1/users/localized-receiver/webhook-test", headers=auth
        ).status_code
        == 202
    )
    original = httpx.AsyncClient
    captured = []

    async def scenario():
        stop = asyncio.Event()

        def receive(request):
            captured.append(json.loads(request.content))
            stop.set()
            return httpx.Response(200)

        monkeypatch.setattr(
            webhooks.httpx,
            "AsyncClient",
            lambda **kwargs: original(transport=httpx.MockTransport(receive), **kwargs),
        )
        await asyncio.wait_for(
            webhooks.dispatcher_loop(db_path, stop, interval=0.01), timeout=2
        )

    asyncio.run(scenario())
    assert captured[0]["instructions"].startswith("Alleen een verbindingstest.")
    assert (
        captured[0]["expected_action"] == "stand_down" and captured[0]["item"] is None
    )


def test_invalid_installation_language_has_no_value_in_error(monkeypatch):
    monkeypatch.setenv("HEGEMONE_LANGUAGE", "synthetic-invalid-setting")
    with pytest.raises(ValueError) as error:
        config.installation_language()
    assert str(error.value) == "HEGEMONE_LANGUAGE moet en of nl zijn."


@pytest.mark.parametrize("language", ["en", "nl"])
def test_scripted_questions_preserve_markers_data_and_option_indices(
    monkeypatch, language
):
    from betonning import triage

    monkeypatch.setenv("HEGEMONE_LANGUAGE", language)
    questions = triage.format_enrich_questions(["Mijn eigen vraag {p0}?"])
    assert questions.startswith(triage.ENRICH_QUESTION_MARKER)
    assert "Mijn eigen vraag {p0}?" in questions
    assert triage.has_outstanding_enrich_questions(
        [{"author": "triage", "body_md": questions}]
    )
    proposal = triage.format_enrich_proposal("Mijn eigen voorstel {p1}")
    assert (
        proposal.startswith(triage.ENRICH_PROPOSAL_MARKER)
        and "Mijn eigen voorstel {p1}" in proposal
    )
    stale = triage.format_stale_question(7, mention="eigen-naam")
    assert triage.is_stale_question(stale) and "@eigen-naam" in stale and "7" in stale
    guard = triage.format_guardrail_review_question(
        "Mijn guardrail {p0}", "2026-11-01", mention="eigen-naam"
    )
    assert triage.is_guardrail_review_question(guard) and "Mijn guardrail {p0}" in guard
    assert len(triage.stale_options()) == len(triage.guardrail_options()) == 3
    if language == "en":
        assert "More information is needed" in questions
        assert triage.stale_options()[1] == "Back to todo"
        assert triage.guardrail_options()[1].startswith("No longer valid")
    else:
        assert triage.stale_options() == triage.STALE_OPTIONS
        assert triage.guardrail_options() == triage.GUARDRAIL_REVIEW_OPTIONS


def test_english_handover_keeps_original_human_request(
    client, auth, conn, project, monkeypatch
):
    from betonning.repo import users

    monkeypatch.setenv("HEGEMONE_LANGUAGE", "en")
    _, key = users.create(conn, handle="builder", display_name="Builder", kind="agent")
    item = client.post(
        f"/api/v1/projects/{project}/items",
        headers=auth,
        json={"title": "Eigen taak", "assignee": "builder"},
    ).json()
    response = client.patch(
        f"/api/v1/items/{item['ref']}",
        headers={"Authorization": f"Bearer {key}"},
        json={"assignee": "person", "handover_md": "Mijn eigen verzoek {body}."},
    )
    assert response.status_code == 200
    data = client.get(f"/api/v1/items/{item['ref']}", headers=auth).json()
    assert (
        data["comments"][0]["body_md"]
        == "**Needed from @person:** Mijn eigen verzoek {body}."
    )
