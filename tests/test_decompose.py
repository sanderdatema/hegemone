"""Decompose: pure prompt/parse + de voorstel/apply-endpoints (BETON-31)."""

from __future__ import annotations

from conftest import inject_llm

import json

import pytest

from betonning import decompose
from betonning.repo import items as items_repo
from betonning.repo import projects as projects_repo
from betonning.repo import users as users_repo


class FakeLLM:
    """Geeft een vast (JSON-)antwoord terug en legt de messages vast."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.last_messages = None

    def complete(self, messages):
        self.last_messages = messages
        return self.reply


class BoomLLM:
    """Simuleert een upstream-fout (→ 502, BETON-324)."""

    def complete(self, messages):
        raise RuntimeError("upstream 500")


VALID = json.dumps(
    {
        "should_decompose": True,
        "reason": "Bestaat uit losse stappen.",
        "subtasks": [
            {"title": "Ontwerp API", "description_md": "endpoints", "priority": "high"},
            {"title": "Bouw UI", "description_md": "knop"},
        ],
        "blocks": [[0, 1]],
    }
)


# --- Pure delen -----------------------------------------------------------


def test_build_messages_contains_item():
    msgs = decompose.build_decompose_messages(
        {"ref": "SOS-2", "title": "Groot", "description_md": "veel"},
        {"project_name": "SOS"},
    )
    assert msgs[0]["role"] == "system"
    assert "SOS-2" in msgs[1]["content"] and "Groot" in msgs[1]["content"]


def test_parse_valid():
    r = decompose.parse_decompose(VALID)
    assert r.should_decompose is True
    assert [s.title for s in r.subtasks] == ["Ontwerp API", "Bouw UI"]
    assert r.subtasks[0].priority == "high"
    assert r.blocks == [(0, 1)]


def test_parse_invalid_json_is_safe_noop():
    r = decompose.parse_decompose("geen json hier")
    assert r.should_decompose is False and r.subtasks == []


def test_parse_empty_subtasks_forces_false():
    r = decompose.parse_decompose('{"should_decompose": true, "subtasks": []}')
    assert r.should_decompose is False


def test_parse_false_clears_subtasks_and_blocks():
    # Nee is bindend: een nee-voorstel mét subtaken houdt geen half voorstel over.
    raw = json.dumps(
        {
            "should_decompose": False,
            "reason": "In één sessie klaar.",
            "subtasks": [{"title": "toch iets"}, {"title": "nog iets"}],
            "blocks": [[0, 1]],
        }
    )
    r = decompose.parse_decompose(raw)
    assert r.should_decompose is False
    assert r.subtasks == []
    assert r.blocks == []


def test_parse_caps_subtasks():
    many = {
        "should_decompose": True,
        "subtasks": [{"title": f"t{i}"} for i in range(20)],
        "blocks": [[0, 15], [0, 1]],
    }
    r = decompose.parse_decompose(json.dumps(many))
    assert len(r.subtasks) == decompose.MAX_SUBTASKS
    # Blocks die buiten de cap wijzen zijn weggefilterd.
    assert all(a < decompose.MAX_SUBTASKS and b < decompose.MAX_SUBTASKS for a, b in r.blocks)


# --- BETON-257: advies en proces hanteren dezelfde opknip-lat ---------------


def test_advice_and_process_share_one_rubric():
    """Triage's opknip-ADVIES (decompose_suggestion) en het opknip-PROCES
    (decompose) redeneren vanaf exact dezelfde rubriek. Vroeger adviseerde triage
    al bij 'meerdere zelfstandige stappen' terwijl decompose ≥3 zelfstandige
    stappen + te-groot-voor-één-sessie eiste → triage beloofde een opknipsel dat
    het proces vervolgens weigerde. Beide beslispaden embedden nu dezelfde
    DECOMPOSE_CRITERIA-constante, zodat de lat niet meer uit elkaar kan lopen."""
    from betonning import triage as triage_mod

    item = {"ref": "SOS-1", "title": "Groot", "description_md": "veel stappen"}
    ctx = {"project_name": "SOS"}
    triage_system = triage_mod.build_triage_messages(item, ctx, [])[0]["content"]
    decompose_system = decompose.build_decompose_messages(item, ctx)[0]["content"]
    # Dezelfde rubriek in beide prompts → structureel consistent (BETON-257).
    assert triage_mod.DECOMPOSE_CRITERIA in triage_system
    assert triage_mod.DECOMPOSE_CRITERIA in decompose_system
    # De rubriek is de strengere decompose-lat, niet de oude losse triage-tekst.
    assert "minstens 3 werkelijk zelfstandige stappen" in triage_mod.DECOMPOSE_CRITERIA


# --- BETON-67: expertise-routering per subtaak ----------------------------


def _make_item(conn, project_id, title, assignee_id=None):
    seq = projects_repo.next_seq(conn, project_id)
    conn.execute(
        "INSERT INTO items (project_id, seq, title, assignee_id) VALUES (?, ?, ?, ?)",
        (project_id, seq, title, assignee_id),
    )
    conn.commit()
    return items_repo.get_by_ref(conn, f"SOS-{seq}")


def test_build_messages_includes_agent_roster():
    msgs = decompose.build_decompose_messages(
        {"ref": "SOS-2", "title": "Groot", "description_md": "veel"},
        {"project_name": "SOS", "agents": [
            {"handle": "lobke", "description": "Docs en teksten"},
        ]},
    )
    u = msgs[1]["content"]
    assert "@lobke" in u and "Docs en teksten" in u and "Beschikbare agents" in u


def test_parse_subtask_assignee():
    raw = json.dumps({
        "should_decompose": True,
        "subtasks": [
            {"title": "Docs", "assignee": "@Lobke"},
            {"title": "Code"},
        ],
        "blocks": [],
    })
    r = decompose.parse_decompose(raw)
    assert r.subtasks[0].assignee == "lobke"  # genormaliseerd (@ weg, lowercase)
    assert r.subtasks[1].assignee is None


def test_apply_routes_subtasks_to_suggested_agents(conn):
    p = projects_repo.create(conn, key="SOS", name="SOS")
    users_repo.create(conn, handle="claude", display_name="Claude", kind="agent")
    users_repo.create(conn, handle="lobke", display_name="Lobke", kind="agent",
                      description="Docs")
    actor, _ = users_repo.create(conn, handle="triage", display_name="Triage", kind="agent")
    conn.commit()
    parent = _make_item(conn, p["id"], "Groot")  # geen parent-assignee
    result = decompose.DecomposeResult(
        should_decompose=True,
        subtasks=[
            decompose.DecomposeSubtask(title="Docs schrijven", assignee="lobke"),
            decompose.DecomposeSubtask(title="Onbekende agent", assignee="nietbestaand"),
            decompose.DecomposeSubtask(title="Geen suggestie"),
        ],
    )
    refs = decompose.apply_decompose(conn, parent, result, actor["id"])
    assignees = [
        items_repo.serialize(conn, items_repo.get_by_ref(conn, r))["assignee"] for r in refs
    ]
    # Gesuggereerde specialist krijgt de subtaak.
    assert assignees[0] == "lobke"
    # BETON-207: onbekende/lege handle → parent (None) → fallback coding-queue.
    assert assignees[1] == "coding-agent"
    assert assignees[2] == "coding-agent"


def test_apply_unknown_handle_falls_back_to_parent_assignee(conn):
    p = projects_repo.create(conn, key="SOS", name="SOS")
    users_repo.create(conn, handle="claude", display_name="Claude", kind="agent")
    smid, _ = users_repo.create(conn, handle="smid", display_name="Smid", kind="agent")
    actor, _ = users_repo.create(conn, handle="triage", display_name="Triage", kind="agent")
    conn.commit()
    parent = _make_item(conn, p["id"], "Groot", assignee_id=smid["id"])
    result = decompose.DecomposeResult(
        should_decompose=True,
        subtasks=[decompose.DecomposeSubtask(title="X", assignee="nietbestaand")],
    )
    refs = decompose.apply_decompose(conn, parent, result, actor["id"])
    data = items_repo.serialize(conn, items_repo.get_by_ref(conn, refs[0]))
    # Onbekende handle → val terug op de parent-assignee (niet claude).
    assert data["assignee"] == "smid"


# --- Endpoints ------------------------------------------------------------


@pytest.fixture
def item(client, auth):
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    r = client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "Grote taak", "description_md": "meerdere stappen"},
        headers=auth,
    )
    return r.json()["ref"]


def test_proposal_returns_without_saving(client, auth, item):
    inject_llm(client, FakeLLM(VALID))
    r = client.post(f"/api/v1/items/{item}/decompose", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["should_decompose"] is True
    assert len(body["subtasks"]) == 2
    # Niets opgeslagen: geen children.
    fresh = client.get(f"/api/v1/items/{item}", headers=auth).json()
    assert fresh["children"] == []


def test_proposal_503_without_llm(client, auth, item):
    inject_llm(client, None)
    assert client.post(f"/api/v1/items/{item}/decompose", headers=auth).status_code == 503


def test_proposal_502_on_llm_error(client, auth, item):
    inject_llm(client, BoomLLM())
    assert client.post(f"/api/v1/items/{item}/decompose", headers=auth).status_code == 502


def test_apply_creates_children_blocks_and_marker(client, auth, item):
    result = json.loads(VALID)
    r = client.post(f"/api/v1/items/{item}/decompose/apply", json=result, headers=auth)
    assert r.status_code == 201
    created = r.json()["created"]
    assert len(created) == 2

    parent = client.get(f"/api/v1/items/{item}", headers=auth).json()
    assert set(parent["children"]) == set(created)

    # Blocks-keten: subtask 0 blokkeert subtask 1.
    blocker = client.get(f"/api/v1/items/{created[0]}", headers=auth).json()
    assert created[1] in blocker["relations"]["blocks"]

    # [Decompose]-comment op het ouder-item.
    assert any("[Decompose]" in c["body_md"] for c in parent["comments"])


def test_apply_subtask_blocks_parent(client, auth, item):
    """BETON-137: elke subtaak blokkeert de parent, zodat de parent pas 'klaar'
    kan zijn als alle subtaken af zijn. Hergebruikt de bestaande blocks-relatie."""
    result = json.loads(VALID)
    r = client.post(f"/api/v1/items/{item}/decompose/apply", json=result, headers=auth)
    assert r.status_code == 201
    created = r.json()["created"]

    parent = client.get(f"/api/v1/items/{item}", headers=auth).json()
    # De parent is geblokkeerd door al zijn subtaken.
    assert set(parent["relations"]["blocked_by"]) == set(created)
    # En andersom: elke subtaak blokkeert de parent (uitgaande blocks-relatie).
    for ref in created:
        sub = client.get(f"/api/v1/items/{ref}", headers=auth).json()
        assert parent["ref"] in sub["relations"]["blocks"]


def test_apply_is_idempotent(client, auth, item):
    result = json.loads(VALID)
    assert client.post(
        f"/api/v1/items/{item}/decompose/apply", json=result, headers=auth
    ).status_code == 201
    # Tweede poging → 409 (al opgeknipt).
    assert client.post(
        f"/api/v1/items/{item}/decompose/apply", json=result, headers=auth
    ).status_code == 409


def test_proposal_409_when_already_decomposed(client, auth, item):
    inject_llm(client, FakeLLM(VALID))
    client.post(f"/api/v1/items/{item}/decompose/apply", json=json.loads(VALID), headers=auth)
    assert client.post(f"/api/v1/items/{item}/decompose", headers=auth).status_code == 409


def test_apply_422_without_subtasks(client, auth, item):
    assert client.post(
        f"/api/v1/items/{item}/decompose/apply",
        json={"should_decompose": True, "subtasks": []},
        headers=auth,
    ).status_code == 422


def test_apply_422_on_no_proposal(client, auth, item):
    # Nee is bindend via de API: een voorstel met should_decompose=false mét
    # subtaken wordt geweigerd en er wordt niets aangemaakt.
    r = client.post(
        f"/api/v1/items/{item}/decompose/apply",
        json={
            "should_decompose": False,
            "subtasks": [{"title": "toch iets"}, {"title": "nog iets"}],
        },
        headers=auth,
    )
    assert r.status_code == 422
    fresh = client.get(f"/api/v1/items/{item}", headers=auth).json()
    assert fresh["children"] == []


def test_no_path_end_to_end(client, auth, item):
    # LLM zegt nee → voorstel is leeg → apply weigert (422).
    reply = json.dumps(
        {
            "should_decompose": False,
            "reason": "In één sessie klaar.",
            "subtasks": [{"title": "kunstmatig"}],
            "blocks": [],
        }
    )
    inject_llm(client, FakeLLM(reply))
    proposal = client.post(f"/api/v1/items/{item}/decompose", headers=auth).json()
    assert proposal["should_decompose"] is False
    assert proposal["subtasks"] == []
    r = client.post(
        f"/api/v1/items/{item}/decompose/apply", json=proposal, headers=auth
    )
    assert r.status_code == 422


def test_proposal_with_subtasks_applies_without_refusal(client, auth, item):
    """Happy-path-tegenpool van test_no_path_end_to_end: zodra het voorstel
    subtaken bevat (should_decompose=true), gaat het schoon door apply (201) —
    geen 422-weigering. NB: dit oefent de opknip-lat zélf niet (FakeLLM negeert
    de prompt); de rubriek-consistentie van BETON-257 wordt geborgd door
    test_advice_and_process_share_one_rubric."""
    inject_llm(client, FakeLLM(VALID))
    proposal = client.post(f"/api/v1/items/{item}/decompose", headers=auth).json()
    assert proposal["should_decompose"] is True
    assert proposal["subtasks"]  # niet leeg → wordt niet geweigerd
    r = client.post(
        f"/api/v1/items/{item}/decompose/apply", json=proposal, headers=auth
    )
    assert r.status_code == 201
    assert len(r.json()["created"]) == 2


def test_decompose_requires_auth(client, item):
    assert client.post(f"/api/v1/items/{item}/decompose").status_code == 401
    assert client.post(f"/api/v1/items/{item}/decompose/apply", json={}).status_code == 401


def test_decompose_unknown_item_404(client, auth):
    inject_llm(client, FakeLLM(VALID))
    assert client.post("/api/v1/items/SOS-999/decompose", headers=auth).status_code == 404


def test_redecompose_after_children_archived(client, auth, item):
    """BETON-51: her-opknippen mag zodra alle eerdere subtaken gearchiveerd zijn."""
    result = json.loads(VALID)
    r = client.post(f"/api/v1/items/{item}/decompose/apply", json=result, headers=auth)
    assert r.status_code == 201
    created = r.json()["created"]

    # Met levende children → 409 blijft.
    assert client.post(
        f"/api/v1/items/{item}/decompose/apply", json=result, headers=auth
    ).status_code == 409

    # Archiveer alle subtaken → geen levende children meer.
    for ref in created:
        assert client.delete(f"/api/v1/items/{ref}", headers=auth).status_code == 204

    # Opnieuw opknippen lukt.
    again = client.post(f"/api/v1/items/{item}/decompose/apply", json=result, headers=auth)
    assert again.status_code == 201
    assert len(again.json()["created"]) == 2


# --- Vision / afbeeldingen (BETON-139) ------------------------------------

def test_build_decompose_messages_string_zonder_images():
    """Backward-compat: zonder images is user-content een string."""
    msgs = decompose.build_decompose_messages(
        {"ref": "SOS-1", "title": "Groot", "description_md": "stappen"},
        {"project_name": "SOS"},
    )
    assert isinstance(msgs[1]["content"], str)
    assert "SOS-1" in msgs[1]["content"]


def test_build_decompose_messages_list_met_images():
    """Met images wordt user-content een lijst [text-block, *image-blocks]."""
    img = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
    msgs = decompose.build_decompose_messages(
        {"ref": "SOS-1", "title": "Groot", "description_md": "stappen"},
        {"project_name": "SOS"},
        images=[img],
    )
    content = msgs[1]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert "SOS-1" in content[0]["text"]
    assert content[1] is img


PNG = b"\x89PNG\r\n\x1a\n fake-image-bytes"


def test_decompose_stuurt_afbeeldingen_mee_bij_vision(client, auth, item, monkeypatch):
    """End-to-end: vision aan + attachment → de FakeLLM ziet een image-block (BETON-139)."""
    monkeypatch.setenv("BETONNING_LLM_VISION", "1")
    # Upload een echte afbeelding via de API (bytes komen op disk via app.state.attachments_dir).
    up = client.post(
        f"/api/v1/items/{item}/attachments",
        files={"file": ("scherm.png", PNG, "image/png")},
        headers=auth,
    )
    assert up.status_code == 201

    inject_llm(client, FakeLLM(VALID))
    r = client.post(f"/api/v1/items/{item}/decompose", headers=auth)
    assert r.status_code == 200
    content = client.app.state.llm_client.last_messages[1]["content"]
    assert isinstance(content, list)  # multimodaal
    assert any(b.get("type") == "image_url" for b in content)
    assert any(b.get("type") == "text" and "Grote taak" in b["text"] for b in content)


def test_decompose_zonder_vision_blijft_tekst_content(client, auth, item, monkeypatch):
    """Vision uit → zelfs met attachment blijft user-content een string (backward-compat)."""
    monkeypatch.delenv("BETONNING_LLM_VISION", raising=False)
    up = client.post(
        f"/api/v1/items/{item}/attachments",
        files={"file": ("scherm.png", PNG, "image/png")},
        headers=auth,
    )
    assert up.status_code == 201

    inject_llm(client, FakeLLM(VALID))
    r = client.post(f"/api/v1/items/{item}/decompose", headers=auth)
    assert r.status_code == 200
    assert isinstance(client.app.state.llm_client.last_messages[1]["content"], str)
