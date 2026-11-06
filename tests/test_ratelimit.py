"""Rate-limit en dagbudget rond de LLM-calls (BETON-387).

Twee poorten die elkaar niet mogen raken: de per-user token-bucket op de
HTTP-endpoints, en het dagbudget van de in-process triage-worker. De belangrijkste
test hieronder is dat de eerste de tweede NIET stillegt.
"""

from __future__ import annotations

from conftest import inject_llm

import json
from datetime import date

import pytest

from betonning import ratelimit
from betonning import triage_worker
from betonning.repo import projects as projects_repo
from betonning.repo import users as users_repo


class FakeLLM:
    def __init__(self, reply: str = "# Verrijkt") -> None:
        self.reply = reply
        self.calls = 0
        self.last_messages = None

    def complete(self, messages):
        self.calls += 1
        self.last_messages = messages
        return self.reply


# --- Token-bucket (puur) ---------------------------------------------------


def test_bucket_laat_burst_door_en_blokkeert_daarna():
    limiter = ratelimit.RateLimiter()
    for _ in range(3):
        assert limiter.check("u", rate_per_hour=3) == 0.0
    wachttijd = limiter.check("u", rate_per_hour=3)
    assert wachttijd > 0


def test_bucket_is_per_sleutel():
    limiter = ratelimit.RateLimiter()
    assert limiter.check("a", rate_per_hour=1) == 0.0
    assert limiter.check("a", rate_per_hour=1) > 0
    # Andere user heeft een eigen emmer.
    assert limiter.check("b", rate_per_hour=1) == 0.0


def test_bucket_zonder_limiet_laat_alles_door():
    limiter = ratelimit.RateLimiter()
    for _ in range(50):
        assert limiter.check("u", rate_per_hour=0) == 0.0


def test_bucket_vult_bij_met_de_tijd(monkeypatch):
    """De emmer loopt vol op `rate/3600` per seconde; na genoeg tijd mag het weer."""
    klok = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: klok[0])
    limiter = ratelimit.RateLimiter()
    # 1 token per seconde, emmer van 1: één call, dan wachten.
    assert limiter.check("u", rate_per_hour=3600, burst=1) == 0.0
    assert limiter.check("u", rate_per_hour=3600, burst=1) > 0
    klok[0] += 2.0
    assert limiter.check("u", rate_per_hour=3600, burst=1) == 0.0


def test_rate_uit_env(monkeypatch):
    monkeypatch.setenv("BETONNING_LLM_RATE", "7")
    assert ratelimit.llm_rate_per_hour() == 7
    monkeypatch.setenv("BETONNING_LLM_RATE", "onzin")
    assert ratelimit.llm_rate_per_hour() == ratelimit.DEFAULT_LLM_RATE_PER_HOUR


# --- Endpoints -------------------------------------------------------------


@pytest.fixture
def item(client, auth):
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    r = client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "Iets", "description_md": "kort"},
        headers=auth,
    )
    return r.json()["ref"]


@pytest.fixture
def agent_auth(conn):
    _, key = users_repo.create(
        conn, handle="codex", display_name="Codex", kind="agent", agent_type="coding"
    )
    conn.commit()
    return {"Authorization": f"Bearer {key}"}


def test_enrich_429_na_de_limiet(client, auth, item, agent_auth, monkeypatch):
    """De agent mag 1 call per uur; de tweede geeft 429 met Retry-After."""
    monkeypatch.setenv("BETONNING_LLM_RATE", "1")
    fake = FakeLLM()
    inject_llm(client, fake)

    assert client.post(f"/api/v1/items/{item}/enrich", headers=agent_auth).status_code == 200
    r = client.post(f"/api/v1/items/{item}/enrich", headers=agent_auth)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    assert "limiet" in r.json()["detail"].lower()
    # Geweigerd = geen LLM-call.
    assert fake.calls == 1


def test_mens_krijgt_een_hoger_plafond(client, auth, item, agent_auth, monkeypatch):
    """Mensen klikken zelf; zij krijgen HUMAN_FACTOR keer het agent-plafond."""
    monkeypatch.setenv("BETONNING_LLM_RATE", "1")
    inject_llm(client, FakeLLM())

    # Agent: 1 call, dan dicht.
    assert client.post(f"/api/v1/items/{item}/enrich", headers=agent_auth).status_code == 200
    assert client.post(f"/api/v1/items/{item}/enrich", headers=agent_auth).status_code == 429
    # Mens (person): 1 × HUMAN_FACTOR calls.
    for _ in range(ratelimit.HUMAN_FACTOR):
        assert client.post(f"/api/v1/items/{item}/enrich", headers=auth).status_code == 200
    assert client.post(f"/api/v1/items/{item}/enrich", headers=auth).status_code == 429


def test_decompose_deelt_de_emmer_met_enrich(client, item, agent_auth, monkeypatch):
    """Eén emmer per user over alle LLM-endpoints — anders is de limiet te omzeilen."""
    monkeypatch.setenv("BETONNING_LLM_RATE", "1")
    inject_llm(client, FakeLLM(json.dumps({"should_decompose": False})))
    assert client.post(f"/api/v1/items/{item}/enrich", headers=agent_auth).status_code == 200
    assert (
        client.post(f"/api/v1/items/{item}/decompose", headers=agent_auth).status_code
        == 429
    )


def test_decompose_apply_valt_niet_onder_de_limiet(client, auth, item, monkeypatch):
    """/decompose/apply doet geen LLM-call en hoort dus geen token te kosten."""
    monkeypatch.setenv("BETONNING_LLM_RATE", "1")
    inject_llm(client, FakeLLM(json.dumps({"should_decompose": False})))
    client.post(f"/api/v1/items/{item}/enrich", headers=auth)
    r = client.post(
        f"/api/v1/items/{item}/decompose/apply",
        json={"should_decompose": True, "subtasks": [{"title": "Sub"}]},
        headers=auth,
    )
    assert r.status_code == 201


def test_limiet_raakt_de_ingebouwde_triage_worker_niet(
    client, conn, auth, item, agent_auth, monkeypatch, db_path
):
    """DE kern van BETON-387: de bucket zit op de HTTP-dependency, de worker roept
    `llm.complete` rechtstreeks aan. Een dichtgeslagen emmer mag de bot dus niet
    stilleggen."""
    monkeypatch.setenv("BETONNING_LLM_RATE", "1")
    inject_llm(client, FakeLLM())
    assert client.post(f"/api/v1/items/{item}/enrich", headers=agent_auth).status_code == 200
    assert client.post(f"/api/v1/items/{item}/enrich", headers=agent_auth).status_code == 429

    # Zelfde app, zelfde db: triage draait gewoon door.
    project = projects_repo.get_by_key(conn, "SOS")
    projects_repo.set_triage_enabled(conn, project["id"], True)
    triage_user, _ = users_repo.create(
        conn, handle="triage", display_name="Triage", kind="agent"
    )
    conn.commit()
    worker_llm = FakeLLM(json.dumps({"type_label": "chore", "comment": "ok"}))
    triage_worker._run_batch(db_path, worker_llm, None, triage_user["id"], 0, 5)
    assert worker_llm.calls >= 1


# --- Dagbudget van de worker ----------------------------------------------


def test_dagbudget_telt_en_raakt_op():
    budget = ratelimit.DailyBudget(2)
    assert not budget.exhausted()
    budget.spend()
    assert not budget.exhausted()
    budget.spend()
    assert budget.exhausted()


def test_dagbudget_nul_of_negatief_is_ongelimiteerd():
    budget = ratelimit.DailyBudget(0)
    for _ in range(100):
        budget.spend()
    assert not budget.exhausted()


def test_dagbudget_rolt_om_bij_dagwissel():
    budget = ratelimit.DailyBudget(1)
    budget.spend()
    assert budget.exhausted()
    # Zet de teller-dag op gisteren: de eerstvolgende aanraking rolt om.
    budget._day = date(2020, 1, 1)
    assert budget.spent == 0
    assert not budget.exhausted()


def test_budgeted_llm_telt_elke_call():
    budget = ratelimit.DailyBudget(10)
    inner = FakeLLM("hoi")
    wrapped = ratelimit.BudgetedLLM(inner, budget)
    assert wrapped.complete([{"role": "user", "content": "x"}]) == "hoi"
    assert budget.spent == 1
    assert inner.calls == 1


def test_run_batch_slaat_over_als_het_budget_op_is(conn, db_path):
    """Op = geen finder, geen LLM-call. De poort staat vóór het werk, niet in de
    client — een exception daar zou het item in quarantaine duwen."""
    p = projects_repo.create(conn, key="SOS", name="SOS")
    projects_repo.set_triage_enabled(conn, p["id"], True)
    triage_user, _ = users_repo.create(
        conn, handle="triage", display_name="Triage", kind="agent"
    )
    seq = projects_repo.next_seq(conn, p["id"])
    conn.execute(
        "INSERT INTO items (project_id, seq, title, updated_at) "
        "VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-10 seconds'))",
        (p["id"], seq, "Nieuw item"),
    )
    conn.commit()

    op = ratelimit.DailyBudget(1)
    op.spend()
    llm = FakeLLM(json.dumps({"type_label": "chore"}))
    triage_worker._run_batch(db_path, llm, None, triage_user["id"], 0, 5, budget=op)
    assert llm.calls == 0

    # Met ruimte in het budget draait dezelfde batch wél.
    ruim = ratelimit.DailyBudget(10)
    triage_worker._run_batch(db_path, llm, None, triage_user["id"], 0, 5, budget=ruim)
    assert llm.calls >= 1


def test_dagbudget_en_rondebudget_zijn_losse_assen(conn, db_path):
    """Twee assen: het dagbudget (BETON-387) begrenst een UTC-dag over alle
    ronden, het rondebudget (BETON-392) verdeelt binnen één ronde over de
    finders. Een ruime dag mag het rondebudget dus niet omzeilen."""
    p = projects_repo.create(conn, key="SOS", name="SOS")
    projects_repo.set_triage_enabled(conn, p["id"], True)
    triage_user, _ = users_repo.create(
        conn, handle="triage", display_name="Triage", kind="agent"
    )
    for titel in ("Eerste", "Tweede"):
        seq = projects_repo.next_seq(conn, p["id"])
        conn.execute(
            "INSERT INTO items (project_id, seq, title, updated_at) "
            "VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-10 seconds'))",
            (p["id"], seq, titel),
        )
    conn.commit()

    ruim = ratelimit.DailyBudget(1000)
    llm = FakeLLM(json.dumps({"type_label": "chore"}))
    triage_worker._run_batch(
        db_path, llm, None, triage_user["id"], 0, 5, budget=ruim, llm_call_budget=1
    )
    assert llm.calls == 1


def test_dagbudget_uit_env(monkeypatch):
    monkeypatch.setenv("BETONNING_TRIAGE_DAILY_BUDGET", "42")
    assert ratelimit.triage_daily_budget() == 42
    monkeypatch.setenv("BETONNING_TRIAGE_DAILY_BUDGET", "onzin")
    assert ratelimit.triage_daily_budget() == ratelimit.DEFAULT_TRIAGE_DAILY_BUDGET
