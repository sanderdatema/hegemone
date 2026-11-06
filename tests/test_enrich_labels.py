"""De verrijk-knop stelt ook labels voor (BETON-355).

Zelfde idioom als de omschrijving: het endpoint LEVERT een voorstel en slaat
niets op; de mens bevestigt. Twee regels die het voorstel bruikbaar houden —
alleen labels die op het project bestaan (de LLM munt er geen), en aanvullen in
plaats van vervangen (BETON-65).
"""

from __future__ import annotations

from conftest import inject_llm

import json

import pytest

from betonning import llm


class FakeLLM:
    def __init__(self, payload: dict) -> None:
        self.reply = json.dumps(payload)
        self.last_messages = None

    def complete(self, messages):
        self.last_messages = messages
        return self.reply


@pytest.fixture
def item(client, auth):
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    for naam in ("bug", "ui", "backend"):
        client.post("/api/v1/projects/SOS/labels", json={"name": naam}, headers=auth)
    r = client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "Knop doet niets", "description_md": "kort"},
        headers=auth,
    )
    return r.json()["ref"]


# --- Filteren (puur) -------------------------------------------------------


def test_resolve_houdt_alleen_bestaande_projectlabels():
    assert llm.resolve_label_suggestions(
        ["bug", "verzonnen"], ["bug", "ui"], []
    ) == ["bug"]


def test_resolve_matcht_case_insensitief_maar_geeft_de_canonieke_naam():
    assert llm.resolve_label_suggestions(["BUG"], ["bug"], []) == ["bug"]


def test_resolve_laat_labels_weg_die_er_al_op_staan():
    """Aanvullen, niet vervangen (BETON-65) — en geen dubbele toevoeg-poging."""
    assert llm.resolve_label_suggestions(["bug", "ui"], ["bug", "ui"], ["bug"]) == ["ui"]


def test_resolve_dedupliceert_met_behoud_van_volgorde():
    assert llm.resolve_label_suggestions(
        ["ui", "bug", "UI"], ["bug", "ui"], []
    ) == ["ui", "bug"]


def test_enrich_result_schoont_labels_op():
    res = llm.parse_enrich(
        json.dumps({"kind": "proposal", "description": "d", "labels": [" bug ", "", "bug"]})
    )
    assert res.labels == ["bug"]


def test_enrich_result_zonder_labels_is_leeg():
    res = llm.parse_enrich(json.dumps({"kind": "proposal", "description": "d"}))
    assert res.labels == []


# --- Prompt ----------------------------------------------------------------


def test_prompt_noemt_de_projectlabels_en_de_al_toegekende():
    msgs = llm.build_enrich_messages(
        "T", "D", [], project_labels=["bug", "ui"], item_labels=["ui"]
    )
    user = msgs[1]["content"]
    assert "Bestaande labels" in user and "bug, ui" in user
    assert "al op dit ticket" in user
    assert "labels" in msgs[0]["content"]


def test_prompt_zonder_projectlabels_noemt_geen_labellijst():
    msgs = llm.build_enrich_messages("T", "D", [])
    assert "Bestaande labels" not in msgs[1]["content"]


# --- Endpoint --------------------------------------------------------------


def test_voorstel_bevat_labels(client, auth, item):
    fake = FakeLLM({"kind": "proposal", "description": "Beter.", "labels": ["bug", "ui"]})
    inject_llm(client, fake)
    body = client.post(f"/api/v1/items/{item}/enrich", headers=auth).json()
    assert body["kind"] == "proposal"
    assert body["labels"] == ["bug", "ui"]
    assert body["current_labels"] == []
    # De projectlabels gingen de prompt in.
    assert "backend" in fake.last_messages[1]["content"]


def test_verzonnen_labels_vallen_af(client, auth, item):
    """De LLM mag geen nieuwe labels munten — dat sloopt de projecttaxonomie."""
    inject_llm(client, FakeLLM(
        {"kind": "proposal", "description": "Beter.", "labels": ["bugfix", "bug"]}
    ))
    body = client.post(f"/api/v1/items/{item}/enrich", headers=auth).json()
    assert body["labels"] == ["bug"]
    # En er is niets aangemaakt.
    namen = [
        label["name"]
        for label in client.get("/api/v1/projects/SOS/labels", headers=auth).json()
    ]
    assert "bugfix" not in namen


def test_voorstel_slaat_niets_op(client, auth, item):
    inject_llm(client, FakeLLM(
        {"kind": "proposal", "description": "Beter.", "labels": ["bug"]}
    ))
    client.post(f"/api/v1/items/{item}/enrich", headers=auth)
    vers = client.get(f"/api/v1/items/{item}", headers=auth).json()
    assert vers["labels"] == []
    assert vers["description_md"] == "kort"


def test_bevestigen_vult_de_labels_aan(client, auth, item):
    """Het bestaande label blijft staan; het voorstel komt erbij (BETON-65)."""
    client.post(f"/api/v1/items/{item}/labels/ui", headers=auth)
    inject_llm(client, FakeLLM(
        {"kind": "proposal", "description": "Beter.", "labels": ["bug", "ui"]}
    ))
    voorstel = client.post(f"/api/v1/items/{item}/enrich", headers=auth).json()
    # 'ui' zit er al op en hoort niet in het voorstel.
    assert voorstel["labels"] == ["bug"]
    assert voorstel["current_labels"] == ["ui"]

    # De bevestig-stap van de UI: omschrijving patchen + de voorgestelde labels toevoegen.
    client.patch(
        f"/api/v1/items/{item}",
        json={"description_md": voorstel["proposal"]},
        headers=auth,
    )
    for naam in voorstel["labels"]:
        client.post(f"/api/v1/items/{item}/labels/{naam}", headers=auth)

    vers = client.get(f"/api/v1/items/{item}", headers=auth).json()
    assert sorted(vers["labels"]) == ["bug", "ui"]
    assert vers["description_md"] == "Beter."


def test_labels_toevoegen_breekt_de_precondition_van_de_patch_niet(client, auth, item):
    """De bevestig-stap doet twee schrijfacties op hetzelfde item, en de PATCH
    draagt het `updated_at` van het drawer-load mee (BETON-44). Zou het
    label-endpoint `items.updated_at` bumpen, dan maakten die twee elkaars
    precondition kapot. Dat doet het niet — het schrijft alleen een event."""
    voor = client.get(f"/api/v1/items/{item}", headers=auth).json()
    client.post(f"/api/v1/items/{item}/labels/bug", headers=auth)
    r = client.patch(
        f"/api/v1/items/{item}",
        json={"description_md": "Beter.", "expected_updated_at": voor["updated_at"]},
        headers=auth,
    )
    assert r.status_code == 200
    vers = client.get(f"/api/v1/items/{item}", headers=auth).json()
    assert vers["description_md"] == "Beter."
    assert vers["labels"] == ["bug"]


def test_vragen_antwoord_draagt_geen_labels(client, auth, item):
    """Bij te magere input komt er geen voorstel, dus ook geen labels."""
    inject_llm(client, FakeLLM(
        {"kind": "questions", "questions": ["Wat moet het doen?"]}
    ))
    body = client.post(f"/api/v1/items/{item}/enrich", headers=auth).json()
    assert body["kind"] == "questions"
    assert "labels" not in body


def test_project_zonder_labels_geeft_een_leeg_voorstel(client, auth):
    client.post("/api/v1/projects", json={"key": "KAAL", "name": "Kaal"}, headers=auth)
    r = client.post(
        "/api/v1/projects/KAAL/items", json={"title": "Iets"}, headers=auth
    )
    ref = r.json()["ref"]
    inject_llm(client, FakeLLM(
        {"kind": "proposal", "description": "Beter.", "labels": ["bug"]}
    ))
    body = client.post(f"/api/v1/items/{ref}/enrich", headers=auth).json()
    assert body["labels"] == []
