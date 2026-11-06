"""Wachtrij voor geblokkeerde comments (BETON-338), repo-laag.

De API-integratie (409 bewaart, unlock plaatst) zit in `test_item_lock.py`;
hier alleen het datagedrag: één plek per item, de race, en de release.
"""

from __future__ import annotations

import sqlite3

import pytest

from betonning.repo import held_comments as held_repo
from betonning.repo import users as users_repo


@pytest.fixture
def item_id(conn, project, client, auth):
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    return conn.execute("SELECT id FROM items WHERE seq = 1").fetchone()["id"]


@pytest.fixture
def author_id(conn):
    user, _ = users_repo.create(
        conn, handle="lobke", display_name="lobke", kind="agent"
    )
    conn.commit()
    return user["id"]


def test_hold_stores_the_body(conn, item_id, author_id):
    held_repo.hold(conn, item_id, author_id, "ik wilde nog dit zeggen")
    assert held_repo.get(conn, item_id)["body_md"] == "ik wilde nog dit zeggen"


def test_empty_queue_reads_as_none(conn, item_id):
    assert held_repo.get(conn, item_id) is None


def test_second_hold_is_refused(conn, item_id, author_id):
    held_repo.hold(conn, item_id, author_id, "eerste")
    assert held_repo.hold(conn, item_id, author_id, "tweede") is None
    # De eerste blijft staan — een tweede poging overschrijft niet.
    assert held_repo.get(conn, item_id)["body_md"] == "eerste"


def test_second_hold_by_other_author_is_refused(conn, item_id, author_id):
    """De wachtrij is per item, niet per auteur: één plek, wie er ook klopt."""
    other, _ = users_repo.create(conn, handle="smid", display_name="smid", kind="agent")
    held_repo.hold(conn, item_id, author_id, "eerste")
    assert held_repo.hold(conn, item_id, other["id"], "tweede") is None
    assert held_repo.get(conn, item_id)["body_md"] == "eerste"


def test_hold_does_not_raise_on_race(conn, item_id, author_id):
    """De UNIQUE-constraint mag geen IntegrityError naar buiten laten lekken —
    de aanroeper krijgt None en geeft daarop een nette 409, geen 500."""
    held_repo.hold(conn, item_id, author_id, "eerste")
    try:
        assert held_repo.hold(conn, item_id, author_id, "tweede") is None
    except sqlite3.IntegrityError:  # pragma: no cover - dit is de regressie
        pytest.fail("IntegrityError lekte uit hold() naar de aanroeper")


def test_release_returns_and_clears(conn, item_id, author_id):
    held_repo.hold(conn, item_id, author_id, "inhaalwerk")
    released = held_repo.release(conn, item_id)
    assert released["body_md"] == "inhaalwerk"
    assert held_repo.get(conn, item_id) is None


def test_release_on_empty_queue_is_none(conn, item_id):
    assert held_repo.release(conn, item_id) is None


def test_queue_frees_up_after_release(conn, item_id, author_id):
    """Na vrijgeven kan er weer iets in de wacht — anders zou een item na één
    slot nooit meer een geblokkeerde comment bewaren."""
    held_repo.hold(conn, item_id, author_id, "eerste")
    held_repo.release(conn, item_id)
    assert held_repo.hold(conn, item_id, author_id, "tweede") is not None


def test_serialize_uses_handle_not_id(conn, item_id, author_id):
    held_repo.hold(conn, item_id, author_id, "tekst")
    out = held_repo.serialize(conn, held_repo.get(conn, item_id))
    assert out["author"] == "lobke"
    assert out["body_md"] == "tekst"


def test_serialize_of_none_is_none(conn):
    assert held_repo.serialize(conn, None) is None


def test_deleting_item_clears_the_queue(conn, item_id, author_id):
    """ON DELETE CASCADE: een verwijderd item laat geen verweesde wachtrij achter
    (de fout uit BETON-336, maar dan voor deze tabel)."""
    held_repo.hold(conn, item_id, author_id, "tekst")
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    assert (
        conn.execute(
            "SELECT COUNT(*) c FROM held_comments WHERE item_id = ?", (item_id,)
        ).fetchone()["c"]
        == 0
    )
