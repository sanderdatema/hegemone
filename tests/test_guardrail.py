"""Guardrail op een ticket (BETON-420): datamodel, repo, endpoints.

Een guardrail is kennis die niet in een regressietest past ("prompts voor model
X kort houden") en die elke agent hierna moet naleven. Hij is duur — hij kost
elke agent tokens, elke ronde — dus: harde tekencap, een plafond op het aantal
projectbrede, en een verplichte reviewdatum.
"""

from __future__ import annotations

import sqlite3

import pytest


# --- Stap 1.1: migratie ----------------------------------------------------


GUARDRAIL_COLUMNS = {
    "guardrail_md",
    "guardrail_review_by",
    "guardrail_set_by",
    "guardrail_set_at",
    "guardrail_lifted_at",
    "guardrail_review_asked_at",
}


def test_migratie_voegt_guardrail_kolommen_toe(conn: sqlite3.Connection):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
    assert GUARDRAIL_COLUMNS <= cols


def test_scope_tabel_cascadeert_op_item_en_label(conn: sqlite3.Connection):
    """Beide FK's cascaderen: `labels_repo.delete` is een kale DELETE FROM labels
    en zou zonder de cascade op `label_id` weesrijen achterlaten."""
    fks = conn.execute(
        "PRAGMA foreign_key_list(item_guardrail_labels)"
    ).fetchall()
    assert {(f["table"], f["on_delete"]) for f in fks} == {
        ("items", "CASCADE"),
        ("labels", "CASCADE"),
    }


def test_tekst_boven_de_cap_wordt_door_de_db_geweigerd(
    conn: sqlite3.Connection, client, auth, project
):
    """De CHECK in de migratie is het vangnet onder de 422 in de API."""
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    item_id = conn.execute("SELECT id FROM items").fetchone()["id"]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE items SET guardrail_md = ? WHERE id = ?", ("x" * 1001, item_id)
        )
    conn.execute("UPDATE items SET guardrail_md = ? WHERE id = ?", ("x" * 1000, item_id))


# --- Stap 1.2: constanten + het "actief"-fragment --------------------------


def test_actief_fragment_zet_de_alias_door():
    """Eén definitie van "actief", overal hergebruikt — inclusief de drie termen
    (tekst aanwezig, niet opgeheven, ticket niet gearchiveerd)."""
    from betonning.repo import items as items_repo

    sql = items_repo.guardrail_active_sql("i")
    assert sql == (
        "i.guardrail_md IS NOT NULL AND i.guardrail_lifted_at IS NULL "
        "AND i.archived_at IS NULL"
    )
    assert items_repo.guardrail_active_sql().startswith("items.guardrail_md")


def test_constanten_staan_in_models():
    from betonning import models

    assert models.GUARDRAIL_MAX_CHARS == 1000
    assert models.GUARDRAIL_PROJECT_WIDE_MAX == 5
    assert models.GUARDRAIL_DEFAULT_REVIEW_DAYS == 90


# --- Stap 1.3: repo/guardrails.py -----------------------------------------


@pytest.fixture
def seeded(client, auth, conn: sqlite3.Connection):
    """Twee projecten (SOS, AND) met elk wat items en labels."""
    for key in ("SOS", "AND"):
        client.post("/api/v1/projects", json={"key": key, "name": key}, headers=auth)
        for name in ("prompts", "ui"):
            client.post(
                f"/api/v1/projects/{key}/labels", json={"name": name}, headers=auth
            )
        for title in ("een", "twee", "drie"):
            client.post(
                f"/api/v1/projects/{key}/items", json={"title": title}, headers=auth
            )
    return conn


def _item(conn, ref):
    from betonning.repo import items as items_repo

    return items_repo.get_by_ref(conn, ref)


def _label_id(conn, key, name):
    return conn.execute(
        "SELECT l.id FROM labels l JOIN projects p ON p.id = l.project_id "
        "WHERE p.key = ? AND l.name = ?",
        (key, name),
    ).fetchone()["id"]


def _set(conn, ref, text="kort houden", review_by="2099-01-01", set_by=None):
    from betonning.repo import guardrails as guardrails_repo

    guardrails_repo.set_guardrail(
        conn, _item(conn, ref)["id"], text=text, review_by=review_by, set_by=set_by
    )


def test_set_en_lift(seeded):
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    person = conn.execute("SELECT id FROM users WHERE handle='person'").fetchone()["id"]
    _set(conn, "SOS-1", set_by=person)
    row = _item(conn, "SOS-1")
    assert row["guardrail_md"] == "kort houden"
    assert row["guardrail_review_by"] == "2099-01-01"
    assert row["guardrail_set_by"] == person
    assert row["guardrail_set_at"] is not None
    assert row["guardrail_lifted_at"] is None

    guardrails_repo.lift(conn, row["id"])
    lifted = _item(conn, "SOS-1")["guardrail_lifted_at"]
    assert lifted is not None
    # Opheffen wist de tekst niet (historie blijft leesbaar).
    assert _item(conn, "SOS-1")["guardrail_md"] == "kort houden"

    guardrails_repo.lift(conn, row["id"])  # idempotent
    assert _item(conn, "SOS-1")["guardrail_lifted_at"] == lifted


def test_opnieuw_zetten_wist_de_opheffing_en_de_reviewmarker(seeded):
    conn = seeded
    _set(conn, "SOS-1")
    item_id = _item(conn, "SOS-1")["id"]
    conn.execute(
        "UPDATE items SET guardrail_lifted_at = '2020-01-01', "
        "guardrail_review_asked_at = '2020-01-01' WHERE id = ?",
        (item_id,),
    )
    _set(conn, "SOS-1", text="opnieuw")
    row = _item(conn, "SOS-1")
    assert row["guardrail_lifted_at"] is None
    assert row["guardrail_review_asked_at"] is None


def test_zetten_raakt_updated_at_niet(seeded):
    """Een guardrail is metadata over hóé je met het ticket omgaat, geen
    inhoudelijke wijziging — anders springt het ticket naar de top van "Laatst
    gewijzigd". Zelfde keuze als `add_label`."""
    conn = seeded
    before = _item(conn, "SOS-1")["updated_at"]
    _set(conn, "SOS-1")
    assert _item(conn, "SOS-1")["updated_at"] == before


def test_scope_vervangt_volledig(seeded):
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    item_id = _item(conn, "SOS-1")["id"]
    guardrails_repo.set_scope(
        conn, item_id, [_label_id(conn, "SOS", "prompts"), _label_id(conn, "SOS", "ui")]
    )
    assert guardrails_repo.scope_labels(conn, item_id) == ["prompts", "ui"]

    guardrails_repo.set_scope(conn, item_id, [_label_id(conn, "SOS", "ui")])
    assert guardrails_repo.scope_labels(conn, item_id) == ["ui"]

    guardrails_repo.set_scope(conn, item_id, [])
    assert guardrails_repo.scope_labels(conn, item_id) == []
    # De scope raakt de labels van het ticket zélf niet aan.
    from betonning.repo import items as items_repo

    assert items_repo.serialize(conn, _item(conn, "SOS-1"))["labels"] == []


def test_project_wide_count_telt_alleen_actieve_ongescopede(seeded):
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    pid = conn.execute("SELECT id FROM projects WHERE key='SOS'").fetchone()["id"]
    assert guardrails_repo.project_wide_count(conn, pid) == 0

    _set(conn, "SOS-1")
    _set(conn, "SOS-2")
    assert guardrails_repo.project_wide_count(conn, pid) == 2

    # Gescoped telt niet mee in het plafond.
    guardrails_repo.set_scope(
        conn, _item(conn, "SOS-2")["id"], [_label_id(conn, "SOS", "prompts")]
    )
    assert guardrails_repo.project_wide_count(conn, pid) == 1

    # Opgeheven telt niet mee.
    _set(conn, "SOS-3")
    guardrails_repo.lift(conn, _item(conn, "SOS-3")["id"])
    assert guardrails_repo.project_wide_count(conn, pid) == 1

    # Gearchiveerd ticket geeft zijn plek in het plafond vrij.
    conn.execute(
        "UPDATE items SET archived_at = '2020-01-01' WHERE id = ?",
        (_item(conn, "SOS-1")["id"],),
    )
    assert guardrails_repo.project_wide_count(conn, pid) == 0


def test_project_wide_geeft_ref_titel_en_tekst(seeded):
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    pid = conn.execute("SELECT id FROM projects WHERE key='SOS'").fetchone()["id"]
    _set(conn, "SOS-2", text="tweede")
    conn.execute(
        "UPDATE items SET guardrail_set_at = '2020-01-01T00:00:00.000Z' WHERE id = ?",
        (_item(conn, "SOS-2")["id"],),
    )
    _set(conn, "SOS-1", text="eerste")
    rows = guardrails_repo.project_wide(conn, pid)
    # Gesorteerd op guardrail_set_at (oudste eerst, stabiel op id).
    assert [r["ref"] for r in rows] == ["SOS-2", "SOS-1"]
    assert rows[0]["title"] == "twee"
    assert rows[0]["guardrail_md"] == "tweede"
    assert rows[0]["review_by"] == "2099-01-01"


def _add_label(client, auth, ref, name):
    return client.post(f"/api/v1/items/{ref}/labels/{name}", headers=auth)


def test_applicable_for_item_snijdt_op_labels(seeded, client, auth):
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    _set(conn, "SOS-1", text="prompt-regel")
    guardrails_repo.set_scope(
        conn, _item(conn, "SOS-1")["id"], [_label_id(conn, "SOS", "prompts")]
    )

    # SOS-2 draagt het label niet → geen treffer.
    assert guardrails_repo.applicable_for_item(conn, _item(conn, "SOS-2")["id"]) == []

    _add_label(client, auth, "SOS-2", "prompts")
    hits = guardrails_repo.applicable_for_item(conn, _item(conn, "SOS-2")["id"])
    assert [h["ref"] for h in hits] == ["SOS-1"]
    assert hits[0]["guardrail_md"] == "prompt-regel"


def test_applicable_for_item_laat_projectbreed_en_zichzelf_weg(seeded, client, auth):
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    _add_label(client, auth, "SOS-1", "prompts")
    _set(conn, "SOS-1", text="eigen")
    guardrails_repo.set_scope(
        conn, _item(conn, "SOS-1")["id"], [_label_id(conn, "SOS", "prompts")]
    )
    _set(conn, "SOS-2", text="projectbreed")  # geen scope

    hits = guardrails_repo.applicable_for_item(conn, _item(conn, "SOS-1")["id"])
    assert hits == []


def test_applicable_for_item_lekt_niet_over_projecten(seeded, client, auth):
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    _set(conn, "AND-1", text="ander project")
    guardrails_repo.set_scope(
        conn, _item(conn, "AND-1")["id"], [_label_id(conn, "AND", "prompts")]
    )
    _add_label(client, auth, "SOS-2", "prompts")
    assert guardrails_repo.applicable_for_item(conn, _item(conn, "SOS-2")["id"]) == []


def test_applicable_for_item_laat_opgeheven_en_gearchiveerde_weg(seeded, client, auth):
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    _add_label(client, auth, "SOS-3", "prompts")
    for ref in ("SOS-1", "SOS-2"):
        _set(conn, ref, text=f"regel {ref}")
        guardrails_repo.set_scope(
            conn, _item(conn, ref)["id"], [_label_id(conn, "SOS", "prompts")]
        )
    assert len(guardrails_repo.applicable_for_item(conn, _item(conn, "SOS-3")["id"])) == 2

    guardrails_repo.lift(conn, _item(conn, "SOS-1")["id"])
    conn.execute(
        "UPDATE items SET archived_at = '2020-01-01' WHERE id = ?",
        (_item(conn, "SOS-2")["id"],),
    )
    assert guardrails_repo.applicable_for_item(conn, _item(conn, "SOS-3")["id"]) == []


# --- Stap 1.4: serialisatie ------------------------------------------------


def test_serialize_draagt_de_guardrail_volledig(seeded, client, auth):
    from betonning.repo import guardrails as guardrails_repo
    from betonning.repo import items as items_repo

    conn = seeded
    person = conn.execute("SELECT id FROM users WHERE handle='person'").fetchone()["id"]
    _set(conn, "SOS-1", text="kort houden", set_by=person)
    guardrails_repo.set_scope(
        conn, _item(conn, "SOS-1")["id"], [_label_id(conn, "SOS", "prompts")]
    )

    data = items_repo.serialize(conn, _item(conn, "SOS-1"))
    assert data["guardrail_md"] == "kort houden"
    assert data["guardrail_review_by"] == "2099-01-01"
    assert data["guardrail_set_by"] == "person"
    assert data["guardrail_set_at"] is not None
    assert data["guardrail_lifted_at"] is None
    assert data["guardrail_scope"] == ["prompts"]
    assert data["has_guardrail"] is True


def test_has_guardrail_volgt_alle_drie_de_termen(seeded):
    """Niet `bool(guardrail_md)`: opheffen én archiveren zetten hem uit."""
    from betonning.repo import guardrails as guardrails_repo
    from betonning.repo import items as items_repo

    conn = seeded
    _set(conn, "SOS-1")
    _set(conn, "SOS-2")
    guardrails_repo.lift(conn, _item(conn, "SOS-1")["id"])
    conn.execute(
        "UPDATE items SET archived_at = '2020-01-01' WHERE id = ?",
        (_item(conn, "SOS-2")["id"],),
    )
    for ref in ("SOS-1", "SOS-2"):
        data = items_repo.serialize(conn, _item(conn, ref))
        assert data["has_guardrail"] is False, ref
        assert data["guardrail_md"] == "kort houden", ref  # tekst blijft


def test_kaart_draagt_has_guardrail_maar_niet_de_tekst(seeded, client, auth):
    conn = seeded
    _set(conn, "SOS-1")
    rows = client.get("/api/v1/projects/SOS/items", headers=auth).json()
    by_ref = {r["ref"]: r for r in rows}
    assert by_ref["SOS-1"]["has_guardrail"] is True
    assert by_ref["SOS-2"]["has_guardrail"] is False
    assert "guardrail_md" not in by_ref["SOS-1"]


def test_kaart_valt_terug_na_opheffen(seeded, client, auth):
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    _set(conn, "SOS-1")
    guardrails_repo.lift(conn, _item(conn, "SOS-1")["id"])
    rows = client.get("/api/v1/projects/SOS/items", headers=auth).json()
    assert {r["ref"]: r["has_guardrail"] for r in rows}["SOS-1"] is False


def test_lijst_doet_geen_query_per_kaart_voor_de_guardrail(db_path, seeded):
    """`has_guardrail` komt uit de item-rij zelf — de scope-tabel wordt in het
    lijstpad niet aangeraakt, ongeacht het aantal items."""
    from betonning import db as db_module
    from betonning.repo import items as items_repo

    conn = seeded
    pid = conn.execute("SELECT id FROM projects WHERE key='SOS'").fetchone()["id"]

    traced = db_module.connect(db_path)
    statements: list[str] = []
    traced.set_trace_callback(statements.append)
    rows = items_repo.list_items(traced, pid)
    traced.close()
    assert len(rows) == 3
    assert [s for s in statements if "item_guardrail_labels" in s] == []


# --- Stap 1.5: endpoints zetten/opheffen (mens-only) -----------------------


FUTURE = "2099-06-01"


@pytest.fixture
def agent_auth(conn: sqlite3.Connection):
    from betonning.repo import users as users_repo

    _, key = users_repo.create(
        conn,
        handle="claude",
        display_name="Claude",
        kind="agent",
        agent_type="coding",
        webhook_url="http://example.invalid/hook",
    )
    conn.commit()
    return {"Authorization": f"Bearer {key}"}


def _post_guardrail(client, headers, ref="SOS-1", **body):
    body.setdefault("guardrail_md", "Houd prompts voor model X kort.")
    body.setdefault("review_by", FUTURE)
    return client.post(f"/api/v1/items/{ref}/guardrail", json=body, headers=headers)


def test_mens_zet_guardrail(seeded, client, auth):
    r = _post_guardrail(client, auth, scope_labels=["prompts"])
    assert r.status_code == 200
    data = r.json()
    assert data["has_guardrail"] is True
    assert data["guardrail_md"] == "Houd prompts voor model X kort."
    assert data["guardrail_review_by"] == FUTURE
    assert data["guardrail_set_by"] == "person"
    assert data["guardrail_scope"] == ["prompts"]


def test_guardrail_zonder_key_is_401(seeded, client):
    assert _post_guardrail(client, {}).status_code == 401


def test_agent_mag_niet_zetten_of_opheffen(seeded, client, auth, agent_auth):
    assert _post_guardrail(client, agent_auth).status_code == 403
    _post_guardrail(client, auth)
    r = client.post("/api/v1/items/SOS-1/guardrail/lift", headers=agent_auth)
    assert r.status_code == 403


def test_onbekende_ref_is_404(seeded, client, auth):
    assert _post_guardrail(client, auth, ref="SOS-99").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"guardrail_md": "   "},
        {"guardrail_md": "x" * 1001},
        {"review_by": ""},
        {"review_by": "1 juni"},
        {"review_by": "2020-01-01"},
        {"scope_labels": ["bestaat-niet"]},
    ],
)
def test_ongeldige_invoer_is_422(seeded, client, auth, body):
    assert _post_guardrail(client, auth, **body).status_code == 422


def test_te_lange_tekst_noemt_het_aantal_tekens(seeded, client, auth):
    r = _post_guardrail(client, auth, guardrail_md="x" * 1001)
    assert "1001" in r.json()["detail"]


def test_zesde_projectbrede_guardrail_is_409(seeded, client, auth):
    for n in range(1, 6):
        client.post("/api/v1/projects/SOS/items", json={"title": f"g{n}"}, headers=auth)
    # SOS-1..3 bestaan al; samen met g1..g5 zijn er genoeg tickets.
    refs = [f"SOS-{n}" for n in range(1, 7)]
    for ref in refs[:5]:
        assert _post_guardrail(client, auth, ref=ref).status_code == 200
    r = _post_guardrail(client, auth, ref=refs[5])
    assert r.status_code == 409
    assert "plafond" in r.json()["detail"].lower()


def test_bestaande_projectbrede_wijzigen_mag_bij_vol_plafond(seeded, client, auth):
    for n in range(1, 6):
        client.post("/api/v1/projects/SOS/items", json={"title": f"g{n}"}, headers=auth)
    for n in range(1, 6):
        _post_guardrail(client, auth, ref=f"SOS-{n}")
    r = _post_guardrail(client, auth, ref="SOS-3", guardrail_md="aangepaste tekst")
    assert r.status_code == 200
    assert r.json()["guardrail_md"] == "aangepaste tekst"


def test_gescopede_guardrail_kent_geen_plafond(seeded, client, auth):
    for n in range(1, 6):
        client.post("/api/v1/projects/SOS/items", json={"title": f"g{n}"}, headers=auth)
    for n in range(1, 6):
        _post_guardrail(client, auth, ref=f"SOS-{n}")
    r = _post_guardrail(client, auth, ref="SOS-6", scope_labels=["ui"])
    assert r.status_code == 200


def test_opheffen_is_idempotent_en_schrijft_een_event(seeded, client, auth):
    _post_guardrail(client, auth)
    assert client.post("/api/v1/items/SOS-1/guardrail/lift", headers=auth).status_code == 200
    first = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert first["has_guardrail"] is False
    assert first["guardrail_md"]  # tekst blijft staan
    assert client.post("/api/v1/items/SOS-1/guardrail/lift", headers=auth).status_code == 200
    second = client.get("/api/v1/items/SOS-1", headers=auth).json()
    assert second["guardrail_lifted_at"] == first["guardrail_lifted_at"]

    types = [
        e["type"]
        for e in client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    ]
    assert types.count("item.guardrail_lifted") == 1
    assert types.count("item.guardrail_set") == 1


def test_event_payload_draagt_de_tekst_niet(seeded, client, auth):
    _post_guardrail(client, auth, scope_labels=["prompts"])
    events = client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    ev = [e for e in events if e["type"] == "item.guardrail_set"][0]
    assert ev["payload"] == {
        "guardrail": {"active": True, "review_by": FUTURE, "scoped": True}
    }


def test_zetten_levert_geen_webhook_deliveries_op(seeded, client, auth, agent_auth, conn):
    """Geen fanout (beslissing 12): de guardrail bereikt de agent al via de
    wiki-context en `get_item`; een derde push is dubbel leveren."""
    client.patch("/api/v1/items/SOS-1", json={"assignee": "claude"}, headers=auth)
    before = conn.execute("SELECT COUNT(*) AS n FROM webhook_deliveries").fetchone()["n"]
    _post_guardrail(client, auth)
    client.post("/api/v1/items/SOS-1/guardrail/lift", headers=auth)
    after = conn.execute("SELECT COUNT(*) AS n FROM webhook_deliveries").fetchone()["n"]
    assert after == before


def test_zetten_levert_geen_inbox_entry_op(seeded, client, auth, agent_auth, conn):
    """De inbox leidt zijn redenen uit de events af, niet uit deliveries — dus
    dat is een derde kanaal dat ook stil moet blijven."""
    client.patch("/api/v1/items/SOS-1", json={"assignee": "claude"}, headers=auth)
    _post_guardrail(client, auth)
    client.post("/api/v1/items/SOS-1/guardrail/lift", headers=auth)
    guardrail_events = {
        r["id"]
        for r in conn.execute(
            "SELECT id FROM events WHERE type LIKE 'item.guardrail%'"
        ).fetchall()
    }
    assert guardrail_events
    inbox = client.get("/api/v1/inbox", headers=agent_auth).json()
    assert guardrail_events.isdisjoint({e["event_id"] for e in inbox["items"]})


# --- Stap 1.6: de PATCH-bypass blijft dicht --------------------------------


def test_patch_kan_geen_guardrail_zetten(seeded, client, auth, agent_auth):
    """De grendel onder de mens-poort: stond `guardrail_md` in `_PATCHABLE`, dan
    zette élke `current_user` hem alsnog via PATCH."""
    for headers in (auth, agent_auth):
        r = client.patch(
            "/api/v1/items/SOS-1", json={"guardrail_md": "stiekem"}, headers=headers
        )
        assert r.status_code in (200, 422)
        item = client.get("/api/v1/items/SOS-1", headers=auth).json()
        assert item["guardrail_md"] is None
        assert item["has_guardrail"] is False

    types = [
        e["type"]
        for e in client.get("/api/v1/items/SOS-1/activity", headers=auth).json()
    ]
    assert "item.guardrail_set" not in types
