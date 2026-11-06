"""Guardrail-voorstel als CONCEPT naast de actieve versie (BETON-422).

Een agent zet nooit rechtstreeks een guardrail: elke wijziging (nieuw zetten,
een actieve wijzigen, hem opheffen) staat eerst als concept naast de actieve
versie. Tot een mens goedkeurt blijft de actieve versie de geldende — een
concept raakt bezorging, plafond en kaartmarkering nooit. De vraag-comment-route
voor een voorstel is verdwenen; de REVIEW-vraag (`[Guardrail-review]`) blijft.
"""

from __future__ import annotations

import sqlite3

import pytest

from betonning import db as db_module

_CONCEPT_VERSION = 42


def _migrate_until(path, version: int) -> sqlite3.Connection:
    """Een DB op de schemaversie vlak vóór `version`, zodat die migratie los
    getoetst kan worden. Zelfde patroon als `tests/test_db.py`."""
    conn = db_module.connect(path)
    applied = 0
    for v, sql in db_module._migration_files():
        if v >= version:
            continue
        conn.executescript(sql)
        applied = v
    conn.execute(f"PRAGMA user_version = {applied}")
    conn.commit()
    return conn


# --- Stap 1.1: migratie ----------------------------------------------------


def test_migratie_maakt_de_voorstel_tabellen(conn: sqlite3.Connection):
    cols = {
        r["name"]
        for r in conn.execute("PRAGMA table_info(item_guardrail_proposals)").fetchall()
    }
    assert cols == {
        "item_id",
        "kind",
        "guardrail_md",
        "review_by",
        "reason",
        "proposed_by",
        "proposed_at",
    }
    scope = {
        r["name"]
        for r in conn.execute(
            "PRAGMA table_info(item_guardrail_proposal_labels)"
        ).fetchall()
    }
    assert scope == {"item_id", "label_id"}


def test_actieve_guardrail_kolommen_blijven_ongemoeid(conn: sqlite3.Connection):
    """De actieve versie houdt exact de kolommen van 041 — er komt geen
    statuskolom bij, want concept en actief bestaan naast elkaar."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
    assert "guardrail_status" not in cols
    assert {"guardrail_md", "guardrail_set_by", "guardrail_lifted_at"} <= cols


def test_onbekende_soort_wordt_geweigerd(conn: sqlite3.Connection, client, auth):
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    item_id = conn.execute("SELECT id FROM items").fetchone()["id"]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO item_guardrail_proposals (item_id, kind, proposed_at) "
            "VALUES (?, 'onzin', '2026-01-01')",
            (item_id,),
        )


def test_voorstel_neemt_zijn_scope_mee_bij_verwijderen(
    conn: sqlite3.Connection, client, auth
):
    """Cascade op het VOORSTEL: een afgewezen concept laat geen spookscope
    achter waarmee een volgend concept stil de verkeerde labels erft."""
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    client.post("/api/v1/projects/SOS/labels", json={"name": "ui"}, headers=auth)
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    item_id = conn.execute("SELECT id FROM items").fetchone()["id"]
    label_id = conn.execute("SELECT id FROM labels").fetchone()["id"]
    conn.execute(
        "INSERT INTO item_guardrail_proposals (item_id, kind, guardrail_md, "
        "proposed_at) VALUES (?, 'set', 'kort houden', '2026-01-01')",
        (item_id,),
    )
    conn.execute(
        "INSERT INTO item_guardrail_proposal_labels (item_id, label_id) VALUES (?, ?)",
        (item_id, label_id),
    )
    conn.execute("DELETE FROM item_guardrail_proposals WHERE item_id = ?", (item_id,))
    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM item_guardrail_proposal_labels"
        ).fetchone()["n"]
        == 0
    )


def test_backfill_sluit_openstaande_voorstel_vragen(tmp_path):
    """De afhandelaar verdwijnt in fase 2; een open voorstel-vraag zou dood
    blijven hangen in `GET /questions?open=true`. Gewone vragen blijven open."""
    conn = _migrate_until(tmp_path / "x.db", _CONCEPT_VERSION)
    conn.execute("INSERT INTO projects (key, name) VALUES ('SOS', 'SOS')")
    conn.execute("INSERT INTO items (project_id, seq, title) VALUES (1, 1, 'Iets')")
    conn.execute(
        "INSERT INTO comments (item_id, body_md, kind) VALUES "
        "(1, '[Guardrail-voorstel]\n\nVoorstel\n\n> kort houden', 'question')"
    )
    conn.execute(
        "INSERT INTO comments (item_id, body_md, kind) VALUES "
        "(1, 'Gewone vraag?', 'question')"
    )
    conn.execute(
        "INSERT INTO comments (item_id, body_md, kind, answered_at) VALUES "
        "(1, '[Guardrail-voorstel] al beantwoord', 'question', '2020-01-01')"
    )
    conn.commit()

    db_module.migrate(conn)

    rows = {r["id"]: r for r in conn.execute("SELECT * FROM comments").fetchall()}
    assert rows[1]["answered_at"] is not None
    assert rows[1]["evaluated_at"] is not None
    assert "BETON-422" in rows[1]["answer_text"]
    assert rows[1]["answered_by"] is None
    assert rows[2]["answered_at"] is None
    # Een al beantwoorde voorstel-vraag blijft precies zoals hij was.
    assert rows[3]["answered_at"] == "2020-01-01"


# --- Stap 1.2: repo-functies voor het concept ------------------------------


@pytest.fixture
def seeded(client, auth, conn: sqlite3.Connection):
    """Eén project met labels en drie items."""
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    for name in ("prompts", "ui"):
        client.post("/api/v1/projects/SOS/labels", json={"name": name}, headers=auth)
    for title in ("een", "twee", "drie"):
        client.post(
            "/api/v1/projects/SOS/items", json={"title": title}, headers=auth
        )
    return conn


def _item(conn, ref):
    from betonning.repo import items as items_repo

    return items_repo.get_by_ref(conn, ref)


def _label_id(conn, name):
    return conn.execute("SELECT id FROM labels WHERE name = ?", (name,)).fetchone()["id"]


def test_propose_legt_het_concept_vast(seeded):
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    person = conn.execute("SELECT id FROM users WHERE handle='person'").fetchone()["id"]
    item_id = _item(conn, "SOS-1")["id"]
    guardrails_repo.propose(
        conn,
        item_id,
        kind="set",
        text="kort houden",
        review_by="2099-01-01",
        proposed_by=person,
        label_ids=[_label_id(conn, "prompts")],
    )
    row = guardrails_repo.proposal(conn, item_id)
    assert row["kind"] == "set"
    assert row["guardrail_md"] == "kort houden"
    assert row["review_by"] == "2099-01-01"
    assert row["proposed_by"] == person
    assert row["proposed_at"] is not None
    assert guardrails_repo.proposal_scope_labels(conn, item_id) == ["prompts"]


def test_propose_raakt_de_actieve_versie_en_updated_at_niet(seeded):
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    item_id = _item(conn, "SOS-1")["id"]
    guardrails_repo.set_guardrail(
        conn, item_id, text="geldt nu", review_by="2099-01-01", set_by=None
    )
    before = _item(conn, "SOS-1")["updated_at"]
    guardrails_repo.propose(
        conn, item_id, kind="set", text="voorstel", proposed_by=None
    )
    row = _item(conn, "SOS-1")
    assert row["guardrail_md"] == "geldt nu"
    assert row["updated_at"] == before


def test_tweede_voorstel_overschrijft_het_slot_inclusief_scope(seeded):
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    item_id = _item(conn, "SOS-1")["id"]
    guardrails_repo.propose(
        conn,
        item_id,
        kind="set",
        text="eerste",
        proposed_by=None,
        label_ids=[_label_id(conn, "prompts")],
    )
    guardrails_repo.propose(conn, item_id, kind="set", text="tweede", proposed_by=None)
    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM item_guardrail_proposals"
        ).fetchone()["n"]
        == 1
    )
    assert guardrails_repo.proposal(conn, item_id)["guardrail_md"] == "tweede"
    assert guardrails_repo.proposal_scope_labels(conn, item_id) == []


def test_delete_proposal_is_idempotent(seeded):
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    item_id = _item(conn, "SOS-1")["id"]
    guardrails_repo.propose(conn, item_id, kind="lift", reason="klaar", proposed_by=None)
    guardrails_repo.delete_proposal(conn, item_id)
    guardrails_repo.delete_proposal(conn, item_id)
    assert guardrails_repo.proposal(conn, item_id) is None


def test_concept_telt_niet_mee_in_het_plafond_en_wordt_niet_geleverd(seeded, client, auth):
    """De kern van de aanvulling: een concept raakt bezorging en plafond nooit."""
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    pid = conn.execute("SELECT id FROM projects WHERE key='SOS'").fetchone()["id"]
    guardrails_repo.propose(
        conn, _item(conn, "SOS-1")["id"], kind="set", text="voorstel", proposed_by=None
    )
    assert guardrails_repo.project_wide_count(conn, pid) == 0
    assert guardrails_repo.project_wide(conn, pid) == []
    client.post("/api/v1/items/SOS-2/labels/prompts", headers=auth)
    guardrails_repo.propose(
        conn,
        _item(conn, "SOS-1")["id"],
        kind="set",
        text="voorstel",
        proposed_by=None,
        label_ids=[_label_id(conn, "prompts")],
    )
    assert guardrails_repo.applicable_for_item(conn, _item(conn, "SOS-2")["id"]) == []


# --- Stap 1.3: serialisatie ------------------------------------------------


def test_serialize_draagt_concept_en_actieve_versie_los_van_elkaar(seeded):
    from betonning.repo import guardrails as guardrails_repo
    from betonning.repo import items as items_repo

    conn = seeded
    person = conn.execute("SELECT id FROM users WHERE handle='person'").fetchone()["id"]
    item_id = _item(conn, "SOS-1")["id"]
    guardrails_repo.set_guardrail(
        conn, item_id, text="geldt nu", review_by="2099-01-01", set_by=person
    )
    guardrails_repo.propose(
        conn,
        item_id,
        kind="set",
        text="voorstel",
        review_by="2098-01-01",
        proposed_by=person,
        label_ids=[_label_id(conn, "ui")],
    )

    data = items_repo.serialize(conn, _item(conn, "SOS-1"))
    assert data["guardrail_md"] == "geldt nu"
    assert data["has_guardrail"] is True
    assert data["guardrail_proposal"] == {
        "kind": "set",
        "guardrail_md": "voorstel",
        "review_by": "2098-01-01",
        "reason": None,
        "scope": ["ui"],
        "proposed_by": "person",
        "proposed_at": data["guardrail_proposal"]["proposed_at"],
    }
    assert data["guardrail_proposal"]["proposed_at"] is not None


def test_serialize_zonder_concept_draagt_none(seeded):
    from betonning.repo import items as items_repo

    conn = seeded
    assert items_repo.serialize(conn, _item(conn, "SOS-1"))["guardrail_proposal"] is None


def test_kaart_draagt_alleen_de_boolean(seeded, client, auth):
    from betonning.repo import guardrails as guardrails_repo

    conn = seeded
    guardrails_repo.propose(
        conn, _item(conn, "SOS-1")["id"], kind="lift", reason="klaar", proposed_by=None
    )
    rows = client.get("/api/v1/projects/SOS/items", headers=auth).json()
    by_ref = {r["ref"]: r for r in rows}
    assert by_ref["SOS-1"]["has_guardrail_proposal"] is True
    assert by_ref["SOS-1"]["has_guardrail"] is False
    assert by_ref["SOS-2"]["has_guardrail_proposal"] is False
    assert "guardrail_proposal" not in by_ref["SOS-1"]


def test_single_item_pad_draagt_de_boolean_ook(seeded):
    """`compact(serialize(...))` is het pad van de SSE-snapshot: zonder deze
    afleiding zou een live event de vlag wissen die het lijstpad net zette."""
    from betonning.repo import guardrails as guardrails_repo
    from betonning.repo import items as items_repo

    conn = seeded
    guardrails_repo.propose(
        conn, _item(conn, "SOS-1")["id"], kind="set", text="x", proposed_by=None
    )
    card = items_repo.compact(items_repo.serialize(conn, _item(conn, "SOS-1")))
    assert card["has_guardrail_proposal"] is True
    other = items_repo.compact(items_repo.serialize(conn, _item(conn, "SOS-2")))
    assert other["has_guardrail_proposal"] is False


def test_lijst_doet_geen_query_per_kaart_voor_het_concept(db_path, seeded):
    """De boolean komt uit een EXISTS in dezelfde SELECT — het aantal statements
    hangt niet van het aantal kaarten af."""
    from betonning import db as db_mod
    from betonning.repo import guardrails as guardrails_repo
    from betonning.repo import items as items_repo

    conn = seeded
    pid = conn.execute("SELECT id FROM projects WHERE key='SOS'").fetchone()["id"]
    guardrails_repo.propose(
        conn, _item(conn, "SOS-1")["id"], kind="set", text="x", proposed_by=None
    )
    conn.commit()

    def count(limit_refs: int) -> int:
        traced = db_mod.connect(db_path)
        statements: list[str] = []
        traced.set_trace_callback(statements.append)
        items_repo.list_items(traced, pid)
        traced.close()
        return len(statements)

    before = count(3)
    for n in range(4, 24):
        conn.execute(
            "INSERT INTO items (project_id, seq, title) VALUES (?, ?, ?)",
            (pid, n, f"item {n}"),
        )
    conn.commit()
    assert count(23) == before


def test_bestaande_actieve_guardrail_blijft_na_de_migratie(tmp_path):
    """Concepten bestonden nog nergens; een actieve guardrail verandert niet."""
    from betonning.repo import items as items_repo

    conn = _migrate_until(tmp_path / "x.db", _CONCEPT_VERSION)
    conn.execute("INSERT INTO projects (key, name) VALUES ('SOS', 'SOS')")
    conn.execute("INSERT INTO items (project_id, seq, title) VALUES (1, 1, 'Iets')")
    conn.execute(
        "UPDATE items SET guardrail_md = 'kort houden', "
        "guardrail_review_by = '2099-01-01' WHERE id = 1"
    )
    conn.commit()

    db_module.migrate(conn)

    row = conn.execute("SELECT * FROM items WHERE id = 1").fetchone()
    assert row["guardrail_md"] == "kort houden"
    assert items_repo.serialize(conn, row)["has_guardrail"] is True
