"""Verrijk-endpoint: voorstel terug zonder op te slaan, met gefakete LLM (BETON-13)."""

from __future__ import annotations

from conftest import inject_llm

import json

import pytest

from betonning import llm
from betonning import triage as triage_mod
from betonning.repo import users as users_repo


class FakeLLM:
    """Legt de messages vast en geeft een vast antwoord terug."""

    def __init__(self, reply: str = "# Verrijkt\n\nInhoud.") -> None:
        self.reply = reply
        self.last_messages: list[dict] | None = None

    def complete(self, messages: list[dict]) -> str:
        self.last_messages = messages
        return self.reply


class BoomLLM:
    def complete(self, messages: list[dict]) -> str:
        raise RuntimeError("upstream 500")


@pytest.fixture
def item(client, auth):
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    r = client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "Vage titel", "description_md": "iets kort"},
        headers=auth,
    )
    return r.json()["ref"]


def test_enrich_returns_proposal_without_saving(client, auth, item):
    fake = FakeLLM("# Verrijkt\n\nBeter.")
    inject_llm(client, fake)
    r = client.post(f"/api/v1/items/{item}/enrich", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["proposal"] == "# Verrijkt\n\nBeter."
    assert body["current"] == "iets kort"
    # Prompt bevat titel + huidige omschrijving.
    user_msg = fake.last_messages[-1]["content"]
    assert "Vage titel" in user_msg
    assert "iets kort" in user_msg
    # Niet opgeslagen: de omschrijving is ongewijzigd.
    fresh = client.get(f"/api/v1/items/{item}", headers=auth).json()
    assert fresh["description_md"] == "iets kort"


def test_enrich_503_when_not_configured(client, auth, item):
    inject_llm(client, None)
    assert client.post(f"/api/v1/items/{item}/enrich", headers=auth).status_code == 503


def test_enrich_502_on_llm_error(client, auth, item):
    inject_llm(client, BoomLLM())
    assert client.post(f"/api/v1/items/{item}/enrich", headers=auth).status_code == 502


def test_enrich_requires_auth(client, item):
    inject_llm(client, FakeLLM())
    assert client.post(f"/api/v1/items/{item}/enrich").status_code == 401


def test_enrich_unknown_item_404(client, auth):
    inject_llm(client, FakeLLM())
    assert client.post("/api/v1/items/SOS-999/enrich", headers=auth).status_code == 404


def test_build_enrich_messages_structure():
    msgs = llm.build_enrich_messages("T", "D", [{"author": "person", "body_md": "hoi"}])
    assert msgs[0]["role"] == "system"
    assert "Acceptatie" in msgs[0]["content"]
    assert "T" in msgs[1]["content"] and "D" in msgs[1]["content"]
    assert "@person: hoi" in msgs[1]["content"]


def test_client_from_env_none_without_config(monkeypatch):
    for var in ("BETONNING_LLM_BASE_URL", "BETONNING_LLM_API_KEY", "BETONNING_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    assert llm.client_from_env() is None


# --- Getypeerde output: proposal vs questions (BETON-163) -------------------


def test_enrich_json_proposal_returns_description_text(client, auth, item):
    """JSON-proposal → response bevat de omschrijvingstekst, niet de ruwe JSON."""
    fake = FakeLLM(json.dumps({"kind": "proposal", "description": "# Verrijkt\n\nBeter."}))
    inject_llm(client, fake)
    r = client.post(f"/api/v1/items/{item}/enrich", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "proposal"
    assert body["proposal"] == "# Verrijkt\n\nBeter."
    assert body["current"] == "iets kort"


def test_enrich_questions_posts_comment_and_keeps_description(client, auth, conn, item):
    """Te magere input → vragen als comment onder triage; omschrijving ongemoeid."""
    users_repo.create(conn, handle="triage", display_name="Triage", kind="agent")
    conn.commit()
    fake = FakeLLM(json.dumps({"kind": "questions", "questions": ["Wat is het doel?", "Waar?"]}))
    inject_llm(client, fake)
    r = client.post(f"/api/v1/items/{item}/enrich", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "questions"
    assert body["questions"] == ["Wat is het doel?", "Waar?"]
    assert body["comment_posted"] is True
    # Er is GEEN proposal en de omschrijving is niet gewijzigd.
    assert "proposal" not in body
    fresh = client.get(f"/api/v1/items/{item}", headers=auth).json()
    assert fresh["description_md"] == "iets kort"
    # De vragen staan als triage-comment met de vraag-marker.
    bodies = [c["body_md"] for c in fresh["comments"]]
    assert any(triage_mod.ENRICH_QUESTION_MARKER in b for b in bodies)
    assert any("Wat is het doel?" in b for b in bodies)


def test_enrich_questions_without_triage_user_reports_not_posted(client, auth, item):
    """Zonder triage-user kan de comment niet geplaatst worden → comment_posted False."""
    fake = FakeLLM(json.dumps({"kind": "questions", "questions": ["Wat?"]}))
    inject_llm(client, fake)
    r = client.post(f"/api/v1/items/{item}/enrich", headers=auth)
    body = r.json()
    assert body["kind"] == "questions"
    assert body["comment_posted"] is False


# --- parse_enrich / thread-detectie (pure) ---------------------------------


def test_parse_enrich_plain_markdown_is_proposal():
    res = llm.parse_enrich("# Kop\n\nTekst zonder JSON.")
    assert res.kind == "proposal"
    assert res.description == "# Kop\n\nTekst zonder JSON."


def test_parse_enrich_questions_without_items_falls_back_to_proposal():
    res = llm.parse_enrich(json.dumps({"kind": "questions", "questions": []}))
    assert res.kind == "proposal"


def test_parse_json_result_fallback_receives_raw_dict_and_error():
    # Gedeelde helper (BETON-322): bij een ValidationError krijgt de fallback de
    # ruwe geëxtraheerde dict + de exception mee, zodat een aanroeper (zoals
    # triage's partial-salvage) daaruit kan putten.
    from pydantic import ValidationError

    class M(llm.BaseModel):
        n: int

    seen = {}

    def fallback(raw, exc):
        seen["raw"] = raw
        seen["exc"] = exc
        return "fallback-default"

    result = llm.parse_json_result('{"n": "niet-een-getal"}', M, fallback=fallback)
    assert result == "fallback-default"
    assert seen["raw"] == {"n": "niet-een-getal"}
    assert isinstance(seen["exc"], ValidationError)


def test_parse_json_result_fallback_on_missing_json_gets_empty_raw():
    seen = {}

    def fallback(raw, exc):
        seen["raw"] = raw
        return "no-json-default"

    result = llm.parse_json_result(
        "geen json hier", llm.EnrichResult, fallback=fallback
    )
    assert result == "no-json-default"
    assert seen["raw"] == {}


def test_parse_enrich_expected_fallback_produces_no_warning(caplog):
    # BETON-322: het "geen JSON, plat Markdown"-pad is verwacht/gedocumenteerd
    # backward-compat gedrag, geen fout — apply_re_enrich draait in de
    # triage-lus, dus dit mag geen WARNING-ruis worden in productie.
    with caplog.at_level("DEBUG", logger="betonning.llm"):
        res = llm.parse_enrich("# Kop\n\nTekst zonder JSON.")
    assert res.kind == "proposal"
    assert not any(r.levelno >= llm.logging.WARNING for r in caplog.records)
    # Het gebeurt nog steeds wél, alleen stiller (debug), zodat het spoor niet
    # helemaal verdwijnt.
    assert any(r.levelno == llm.logging.DEBUG for r in caplog.records)


def test_parse_triage_invalid_output_still_produces_warning(caplog):
    # De andere vier parsers houden WARNING: daar ís een fallback een échte
    # afwijking (BETON-322) — dit bewaakt dat de instelbare `level` het
    # bestaande gedrag van de niet-aangepaste parsers niet stilzwijgend meesleept.
    with caplog.at_level("DEBUG", logger="betonning.triage"):
        result = triage_mod.parse_triage("geen json hier, kapotte output")
    assert result.type_label == "chore"
    assert any(r.levelno == llm.logging.WARNING for r in caplog.records)


def test_parse_enrich_invalid_field_falls_back_to_proposal_with_raw_text():
    # Wél JSON, maar description is geen scalar → ValidationError (i.p.v. de
    # ValueError-tak voor "helemaal geen JSON") — zelfde veilige default:
    # proposal met de ruwe tekst als omschrijving (BETON-322).
    text = json.dumps({"kind": "proposal", "description": [1, 2, 3]})
    res = llm.parse_enrich(text)
    assert res.kind == "proposal"
    assert res.description == text


def test_has_outstanding_enrich_questions_latest_wins():
    q = triage_mod.ENRICH_QUESTION_MARKER + "\n\nWat?"
    p = triage_mod.ENRICH_PROPOSAL_MARKER + "\n\nVoorstel."
    # Laatste triage-enrich-comment is een vraag → open.
    assert triage_mod.has_outstanding_enrich_questions(
        [{"author": "triage", "body_md": q}]
    )
    # Vraag gevolgd door voorstel → niet meer open (lus termineert).
    assert not triage_mod.has_outstanding_enrich_questions(
        [{"author": "triage", "body_md": q}, {"author": "triage", "body_md": p}]
    )
    # Geen enrich-comment van triage → niet open.
    assert not triage_mod.has_outstanding_enrich_questions(
        [{"author": "person", "body_md": "gewone reactie"}]
    )
