"""Guardrail-voorstel als concept naast de actieve versie (BETON-420/422).

Een agent zet nooit rechtstreeks een guardrail: hij stelt voor (`kind="set"` of
`kind="lift"`) en dat voorstel staat als CONCEPT naast de actieve versie. Tot een
mens goedkeurt verandert er niets aan wat er geldt. Goedkeuren en afwijzen zijn
mens-only.
"""

from __future__ import annotations

import sqlite3

import pytest

from betonning.repo import users as users_repo

FUTURE = "2099-06-01"


@pytest.fixture
def seeded(client, auth, conn: sqlite3.Connection):
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    for name in ("prompts", "ui"):
        client.post("/api/v1/projects/SOS/labels", json={"name": name}, headers=auth)
    for title in ("een", "twee"):
        client.post("/api/v1/projects/SOS/items", json={"title": title}, headers=auth)
    return conn


@pytest.fixture
def agent_auth(conn: sqlite3.Connection):
    _, key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent", agent_type="coding"
    )
    conn.commit()
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def agent2_auth(conn: sqlite3.Connection):
    _, key = users_repo.create(
        conn, handle="codex", display_name="Codex", kind="agent", agent_type="coding"
    )
    conn.commit()
    return {"Authorization": f"Bearer {key}"}


def _propose(client, headers, ref="SOS-1", **body):
    body.setdefault("guardrail_md", "Houd prompts voor model X kort.")
    return client.post(
        f"/api/v1/items/{ref}/guardrail/propose", json=body, headers=headers
    )


def _set_guardrail(client, auth, ref="SOS-1", **body):
    body.setdefault("guardrail_md", "Geldt nu.")
    body.setdefault("review_by", FUTURE)
    return client.post(f"/api/v1/items/{ref}/guardrail", json=body, headers=auth)


def _get(client, auth, ref="SOS-1"):
    return client.get(f"/api/v1/items/{ref}", headers=auth).json()


def _types(client, auth, ref="SOS-1"):
    return [
        e["type"] for e in client.get(f"/api/v1/items/{ref}/activity", headers=auth).json()
    ]


# --- Voorstellen -----------------------------------------------------------


def test_agent_stelt_voor_als_concept(seeded, client, auth, agent_auth):
    r = _propose(client, agent_auth, scope_labels=["prompts"], review_by=FUTURE)
    assert r.status_code == 200
    data = r.json()
    assert data["guardrail_proposal"]["kind"] == "set"
    assert data["guardrail_proposal"]["guardrail_md"] == "Houd prompts voor model X kort."
    assert data["guardrail_proposal"]["scope"] == ["prompts"]
    assert data["guardrail_proposal"]["review_by"] == FUTURE
    assert data["guardrail_proposal"]["proposed_by"] == "claude"
    # De actieve versie is onaangeroerd — een concept bindt niets.
    assert data["guardrail_md"] is None
    assert data["has_guardrail"] is False


def test_voorstel_maakt_geen_comment_en_geen_open_vraag(seeded, client, auth, agent_auth):
    _propose(client, agent_auth)
    item = _get(client, auth)
    assert item["comments"] == []
    assert client.get("/api/v1/questions?open=true", headers=auth).json() == []


def test_voorstel_schrijft_een_event_zonder_de_tekst(seeded, client, auth, agent_auth):
    _propose(client, agent_auth, scope_labels=["ui"], review_by=FUTURE)
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    ev = [e for e in events if e["type"] == "item.guardrail_proposed"][0]
    assert ev["payload"] == {
        "guardrail": {"proposal": "set", "scoped": True, "review_by": FUTURE}
    }


def test_voorstel_zonder_key_is_401(seeded, client):
    assert _propose(client, {}).status_code == 401


def test_voorstel_op_onbekende_ref_is_404(seeded, client, agent_auth):
    assert _propose(client, agent_auth, ref="SOS-99").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"guardrail_md": "   "},
        {"guardrail_md": "x" * 1001},
        {"scope_labels": ["bestaat-niet"]},
        {"review_by": "1 juni"},
        {"review_by": "2020-01-01"},
        {"kind": "onzin"},
    ],
)
def test_ongeldig_voorstel_is_422(seeded, client, agent_auth, body):
    assert _propose(client, agent_auth, **body).status_code == 422


def test_voorstel_op_een_gelockt_ticket_is_409(seeded, client, auth, agent_auth):
    client.post("/api/v1/items/SOS-1/lock", headers=auth)
    assert _propose(client, agent_auth).status_code == 409


def test_voorstel_mag_naast_een_actieve_guardrail(seeded, client, auth, agent_auth):
    """De kern van de aanvulling: wijzigen mag voorgesteld worden, en de actieve
    versie blijft ondertussen onverkort gelden."""
    from betonning.repo import guardrails as guardrails_repo
    from betonning.repo import wiki as wiki_repo

    conn = seeded
    _set_guardrail(client, auth)
    r = _propose(client, agent_auth, guardrail_md="Liever anders.")
    assert r.status_code == 200
    item = _get(client, auth)
    assert item["guardrail_md"] == "Geldt nu."
    assert item["has_guardrail"] is True
    assert item["guardrail_proposal"]["guardrail_md"] == "Liever anders."

    pid = conn.execute("SELECT id FROM projects WHERE key='SOS'").fetchone()["id"]
    assert guardrails_repo.project_wide_count(conn, pid) == 1
    blok = wiki_repo.guardrail_block(conn, pid)
    assert "Geldt nu." in blok
    assert "Liever anders." not in blok


def test_voorstel_telt_niet_mee_in_het_plafond(seeded, client, auth, agent_auth):
    for n in range(3, 8):
        client.post("/api/v1/projects/SOS/items", json={"title": f"g{n}"}, headers=auth)
        _set_guardrail(client, auth, ref=f"SOS-{n}", guardrail_md=f"regel {n}")
    assert _propose(client, agent_auth).status_code == 200


def test_tweede_agent_overschrijft_het_concept(seeded, client, auth, agent_auth, agent2_auth):
    _propose(client, agent_auth, guardrail_md="eerste", scope_labels=["prompts"])
    _propose(client, agent2_auth, guardrail_md="tweede")
    item = _get(client, auth)
    assert item["guardrail_proposal"]["guardrail_md"] == "tweede"
    assert item["guardrail_proposal"]["proposed_by"] == "codex"
    assert item["guardrail_proposal"]["scope"] == []
    assert _types(client, auth).count("item.guardrail_proposed") == 2


# --- Opheffing voorstellen -------------------------------------------------


def test_agent_stelt_opheffen_voor(seeded, client, auth, agent_auth):
    _set_guardrail(client, auth)
    r = _propose(client, agent_auth, kind="lift", reason="Model X bestaat niet meer.")
    assert r.status_code == 200
    data = r.json()
    assert data["guardrail_proposal"]["kind"] == "lift"
    assert data["guardrail_proposal"]["reason"] == "Model X bestaat niet meer."
    # Bindt niets: de guardrail geldt nog.
    assert data["has_guardrail"] is True
    assert data["guardrail_lifted_at"] is None


def test_opheffingsvoorstel_zonder_reden_is_422(seeded, client, auth, agent_auth):
    _set_guardrail(client, auth)
    assert _propose(client, agent_auth, kind="lift").status_code == 422
    assert _propose(client, agent_auth, kind="lift", reason="x" * 1001).status_code == 422


def test_opheffen_voorstellen_zonder_actieve_guardrail_is_409(seeded, client, agent_auth):
    assert _propose(client, agent_auth, kind="lift", reason="weg ermee").status_code == 409


# --- Goedkeuren ------------------------------------------------------------


def _approve(client, headers, ref="SOS-1"):
    return client.post(f"/api/v1/items/{ref}/guardrail/approve", headers=headers)


def _reject(client, headers, ref="SOS-1"):
    return client.post(f"/api/v1/items/{ref}/guardrail/reject", headers=headers)


def test_mens_keurt_goed(seeded, client, auth, agent_auth):
    _propose(client, agent_auth, scope_labels=["prompts"], review_by=FUTURE)
    r = _approve(client, auth)
    assert r.status_code == 200
    data = r.json()
    assert data["has_guardrail"] is True
    assert data["guardrail_md"] == "Houd prompts voor model X kort."
    assert data["guardrail_scope"] == ["prompts"]
    assert data["guardrail_review_by"] == FUTURE
    assert data["guardrail_set_by"] == "person"
    assert data["guardrail_set_at"] is not None
    assert data["guardrail_proposal"] is None
    assert _types(client, auth).count("item.guardrail_set") == 1


def test_goedkeuren_zonder_voorgestelde_datum_neemt_de_default_horizon(
    seeded, client, auth, agent_auth, conn
):
    from betonning import models

    _propose(client, agent_auth)
    _approve(client, auth)
    verwacht = conn.execute(
        "SELECT date('now', ?) AS d",
        (f"+{models.GUARDRAIL_DEFAULT_REVIEW_DAYS} days",),
    ).fetchone()["d"]
    assert _get(client, auth)["guardrail_review_by"] == verwacht


def test_verstreken_voorgestelde_datum_wordt_de_default_horizon(
    seeded, client, auth, agent_auth, conn
):
    """Een concept kan lang blijven liggen; activeren met een verstreken datum
    zou de guardrail meteen door de review-finder laten oppakken."""
    from betonning import models
    from betonning.repo import guardrails as guardrails_repo
    from betonning.repo import items as items_repo

    _propose(client, agent_auth)
    item_id = items_repo.get_by_ref(conn, "SOS-1")["id"]
    conn.execute(
        "UPDATE item_guardrail_proposals SET review_by = '2020-01-01' WHERE item_id = ?",
        (item_id,),
    )
    conn.commit()
    _approve(client, auth)
    verwacht = conn.execute(
        "SELECT date('now', ?) AS d",
        (f"+{models.GUARDRAIL_DEFAULT_REVIEW_DAYS} days",),
    ).fetchone()["d"]
    assert _get(client, auth)["guardrail_review_by"] == verwacht
    assert guardrails_repo.proposal(conn, item_id) is None


def test_goedkeuren_van_een_wijziging_vervangt_de_actieve_versie(
    seeded, client, auth, agent_auth
):
    _set_guardrail(client, auth, scope_labels=["ui"])
    _propose(client, agent_auth, guardrail_md="Nieuwe tekst.", scope_labels=["prompts"])
    _approve(client, auth)
    item = _get(client, auth)
    assert item["guardrail_md"] == "Nieuwe tekst."
    assert item["guardrail_scope"] == ["prompts"]
    assert item["guardrail_proposal"] is None


def test_goedkeuren_van_een_opheffing(seeded, client, auth, agent_auth):
    _set_guardrail(client, auth)
    _propose(client, agent_auth, kind="lift", reason="niet meer nodig")
    r = _approve(client, auth)
    assert r.status_code == 200
    item = r.json()
    assert item["has_guardrail"] is False
    assert item["guardrail_lifted_at"] is not None
    assert item["guardrail_md"] == "Geldt nu."  # tekst blijft voor de historie
    assert item["guardrail_proposal"] is None
    assert _types(client, auth).count("item.guardrail_lifted") == 1


def test_agent_mag_niet_goedkeuren_of_afwijzen(seeded, client, auth, agent_auth):
    _propose(client, agent_auth)
    assert _approve(client, agent_auth).status_code == 403
    assert _reject(client, agent_auth).status_code == 403
    assert _get(client, auth)["guardrail_proposal"] is not None


def test_goedkeuren_zonder_key_is_401(seeded, client, agent_auth):
    _propose(client, agent_auth)
    assert _approve(client, {}).status_code == 401
    assert _reject(client, {}).status_code == 401


def test_goedkeuren_op_onbekende_ref_is_404(seeded, client, auth):
    assert _approve(client, auth, ref="SOS-99").status_code == 404
    assert _reject(client, auth, ref="SOS-99").status_code == 404


def test_goedkeuren_zonder_concept_is_409(seeded, client, auth):
    assert _approve(client, auth).status_code == 409
    assert _reject(client, auth).status_code == 409


def test_tweede_afwijzing_is_409(seeded, client, auth, agent_auth):
    _propose(client, agent_auth)
    assert _reject(client, auth).status_code == 200
    assert _reject(client, auth).status_code == 409


def test_goedkeuren_bij_vol_plafond_is_409(seeded, client, auth, agent_auth):
    for n in range(3, 8):
        client.post("/api/v1/projects/SOS/items", json={"title": f"g{n}"}, headers=auth)
        _set_guardrail(client, auth, ref=f"SOS-{n}", guardrail_md=f"regel {n}")
    _propose(client, agent_auth)
    r = _approve(client, auth)
    assert r.status_code == 409
    assert "plafond" in r.json()["detail"].lower()
    # Het concept blijft liggen: de mens kan eerst een guardrail opheffen.
    assert _get(client, auth)["guardrail_proposal"] is not None

    client.post("/api/v1/items/SOS-3/guardrail/lift", headers=auth)
    assert _approve(client, auth).status_code == 200


def test_gescoped_concept_kent_geen_plafond(seeded, client, auth, agent_auth):
    for n in range(3, 8):
        client.post("/api/v1/projects/SOS/items", json={"title": f"g{n}"}, headers=auth)
        _set_guardrail(client, auth, ref=f"SOS-{n}", guardrail_md=f"regel {n}")
    _propose(client, agent_auth, scope_labels=["ui"])
    assert _approve(client, auth).status_code == 200


def test_wijziging_van_een_actieve_projectbrede_telt_niet_dubbel(
    seeded, client, auth, agent_auth
):
    """Het plafond wordt op de UITKOMST getoetst: deze guardrail was al een van
    de vijf, dus corrigeren moet kunnen ook als het plafond vol staat."""
    for n in range(3, 7):
        client.post("/api/v1/projects/SOS/items", json={"title": f"g{n}"}, headers=auth)
        _set_guardrail(client, auth, ref=f"SOS-{n}", guardrail_md=f"regel {n}")
    _set_guardrail(client, auth)  # de vijfde, op SOS-1
    _propose(client, agent_auth, guardrail_md="Scherper geformuleerd.")
    r = _approve(client, auth)
    assert r.status_code == 200
    assert r.json()["guardrail_md"] == "Scherper geformuleerd."


# --- Afwijzen --------------------------------------------------------------


def test_afwijzen_laat_de_actieve_versie_staan(seeded, client, auth, agent_auth):
    from betonning.repo import items as items_repo

    conn = seeded
    _set_guardrail(client, auth)
    _propose(client, agent_auth, guardrail_md="Liever anders.", scope_labels=["ui"])
    r = _reject(client, auth)
    assert r.status_code == 200
    item = r.json()
    assert item["guardrail_proposal"] is None
    assert item["guardrail_md"] == "Geldt nu."
    assert item["has_guardrail"] is True
    item_id = items_repo.get_by_ref(conn, "SOS-1")["id"]
    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM item_guardrail_proposal_labels WHERE item_id = ?",
            (item_id,),
        ).fetchone()["n"]
        == 0
    )
    assert _types(client, auth).count("item.guardrail_rejected") == 1


def test_afwijzen_van_een_opheffingsvoorstel_laat_de_guardrail_gelden(
    seeded, client, auth, agent_auth
):
    _set_guardrail(client, auth)
    _propose(client, agent_auth, kind="lift", reason="weg ermee")
    _reject(client, auth)
    item = _get(client, auth)
    assert item["has_guardrail"] is True
    assert item["guardrail_lifted_at"] is None


# --- Geen fanout, geen inbox-event -----------------------------------------


def test_voorstellen_goedkeuren_en_afwijzen_leveren_geen_deliveries_op(
    seeded, client, auth, agent_auth, conn
):
    client.patch("/api/v1/items/SOS-1", json={"assignee": "claude"}, headers=auth)
    before = conn.execute("SELECT COUNT(*) AS n FROM webhook_deliveries").fetchone()["n"]
    _propose(client, agent_auth)
    _approve(client, auth)
    _propose(client, agent_auth, kind="lift", reason="toch niet")
    _reject(client, auth)
    after = conn.execute("SELECT COUNT(*) AS n FROM webhook_deliveries").fetchone()["n"]
    assert after == before


# --- Een mens die zelf zet of opheft, is zelf de beslissing (BETON-422) -----


def test_zelf_zetten_wist_het_openstaande_concept(seeded, client, auth, agent_auth):
    """"Goedkeuren met wijzigingen" loopt via `POST /items/{ref}/guardrail`: de
    mens bewerkt het concept in de Drawer en slaat op. Het concept mag daarna
    niet blijven staan — dan bleef het conceptblok én de inbox-entry hangen voor
    een voorstel dat net verwerkt is."""
    _propose(client, agent_auth, guardrail_md="Voorstel van de agent.")
    r = _set_guardrail(client, auth, guardrail_md="Voorstel, iets scherper.")
    assert r.status_code == 200
    item = r.json()
    assert item["guardrail_proposal"] is None
    assert item["guardrail_md"] == "Voorstel, iets scherper."
    assert item["has_guardrail"] is True


def test_zelf_opheffen_wist_het_openstaande_concept(seeded, client, auth, agent_auth):
    _set_guardrail(client, auth)
    _propose(client, agent_auth, kind="lift", reason="niet meer nodig")
    r = client.post("/api/v1/items/SOS-1/guardrail/lift", headers=auth)
    assert r.status_code == 200
    item = r.json()
    assert item["guardrail_proposal"] is None
    assert item["has_guardrail"] is False


def test_zelf_zetten_wist_ook_een_openstaand_opheffingsvoorstel(
    seeded, client, auth, agent_auth
):
    """De mens raakt de guardrail zelf aan, dus het voorstel is beantwoord — ook
    als het een andere soort was dan wat hij doet. Anders bleef een
    opheffingsvoorstel staan naast een guardrail die net herschreven is."""
    _set_guardrail(client, auth)
    _propose(client, agent_auth, kind="lift", reason="achterhaald")
    r = _set_guardrail(client, auth, guardrail_md="Toch anders geformuleerd.")
    assert r.status_code == 200
    assert r.json()["guardrail_proposal"] is None
    assert r.json()["has_guardrail"] is True
