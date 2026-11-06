"""Per-project agent-toegangsniveaus (BETON-123): resolutie-repo."""

from __future__ import annotations

import pytest

from betonning.repo import access
from betonning.repo import projects as projects_repo
from betonning.repo import users as users_repo


@pytest.fixture
def setup(conn, seed_cast):
    """Project + een coding-agent (claude), een hermes-agent (smid), een mens."""
    p = projects_repo.create(conn, key="BETON", name="Betonning")
    return {
        "project_id": p["id"],
        "claude": seed_cast["claude"],
        "smid": seed_cast["smid"],
        "human": seed_cast["person"],
    }


def test_default_is_assign(conn, setup):
    """Zonder enige rij: iedere agent (en mens) is volledig toewijsbaar."""
    for who in ("claude", "smid", "human"):
        assert access.effective_level(conn, setup["project_id"], setup[who]) == "assign"


def test_humans_always_assign_even_with_rows(conn, setup):
    """Mensen vallen buiten het model — een type/agent-rij raakt hen niet."""
    access.set_type_access(conn, setup["project_id"], "hermes", "none")
    conn.commit()
    assert access.effective_level(conn, setup["project_id"], setup["human"]) == "assign"


def test_type_default_applies_to_type(conn, setup):
    access.set_type_access(conn, setup["project_id"], "hermes", "none")
    conn.commit()
    pid = setup["project_id"]
    assert access.effective_level(conn, pid, setup["smid"]) == "none"
    assert access.effective_level(conn, pid, setup["claude"]) == "assign"


def test_agent_override_beats_type_default(conn, setup):
    """override ?? type-default ?? globale default."""
    pid = setup["project_id"]
    access.set_type_access(conn, pid, "hermes", "none")
    access.set_agent_access(conn, pid, setup["smid"]["id"], "respond")
    conn.commit()
    assert access.effective_level(conn, pid, setup["smid"]) == "respond"


def test_inherit_clears_override(conn, setup):
    pid = setup["project_id"]
    access.set_type_access(conn, pid, "hermes", "none")
    access.set_agent_access(conn, pid, setup["smid"]["id"], "assign")
    conn.commit()
    assert access.effective_level(conn, pid, setup["smid"]) == "assign"
    # inherit (None) → val terug op de type-default (none).
    access.set_agent_access(conn, pid, setup["smid"]["id"], None)
    conn.commit()
    assert access.effective_level(conn, pid, setup["smid"]) == "none"


def test_type_inherit_clears_default(conn, setup):
    pid = setup["project_id"]
    access.set_type_access(conn, pid, "hermes", "none")
    access.set_type_access(conn, pid, "hermes", None)
    conn.commit()
    assert access.effective_level(conn, pid, setup["smid"]) == "assign"


def test_assignable_agents_filtered_by_project(conn, setup):
    """BETON-123: alleen 'assign'-agents blijven in de toewijs-roster; 'none' én
    'respond' vallen eruit. Zonder project_id blijft het de globale roster."""
    pid = setup["project_id"]
    both = {a["handle"] for a in users_repo.assignable_agents(conn)}
    # BETON-207: de échte coding-agent (claude) staat niet meer in de roster; de
    # virtuele coding-queue `coding-agent` en de specifieke Hermes-agents wel.
    assert "claude" not in both
    assert {"coding-agent", "smid"} <= both  # globaal: geen filter

    access.set_type_access(conn, pid, "hermes", "none")
    conn.commit()
    handles = {a["handle"] for a in users_repo.assignable_agents(conn, pid)}
    assert "coding-agent" in handles and "smid" not in handles

    access.set_type_access(conn, pid, "hermes", "respond")
    conn.commit()
    handles = {a["handle"] for a in users_repo.assignable_agents(conn, pid)}
    assert "smid" not in handles  # respond mag reageren maar niet toegewezen worden


def test_list_access_shape(conn, setup):
    pid = setup["project_id"]
    access.set_type_access(conn, pid, "hermes", "none")
    access.set_agent_access(conn, pid, setup["claude"]["id"], "respond")
    conn.commit()
    result = access.list_access(conn, pid)
    assert result["type_defaults"] == {"hermes": "none"}
    by_handle = {a["handle"]: a for a in result["agents"]}
    # triage zit niet in het roster (niet aangemaakt in deze setup, maar de query
    # sluit 'm sowieso uit); claude heeft een override, smid erft de type-default.
    assert by_handle["claude"]["override"] == "respond"
    assert by_handle["claude"]["effective"] == "respond"
    assert by_handle["smid"]["override"] is None
    assert by_handle["smid"]["effective"] == "none"
