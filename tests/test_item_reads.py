"""Per-item read-state (BETON-294).

Fundament voor BETON-281/286: naast de globale inbox-watermark
(`users.last_seen_event_id`) houdt `item_reads` per (user, item) bij tot welk
event-id die user het item gezien heeft. Getoetst gedrag:

- vreemde activiteit → `has_unread` voor de assignee;
- **je eigen activiteit maakt niets ongelezen**;
- `POST /items/{ref}/read` zet de vlag uit — en alléén voor dit item/deze user;
- read-state is per user gescheiden;
- de bestaande inbox-watermark blijft werken (regressie);
- de lijstweergave doet **geen** query per item (bewaakt de bulkvorm).
"""

from __future__ import annotations

import sqlite3

import pytest

from betonning import db as db_module
from betonning.repo import items as items_repo
from betonning.repo import users as users_repo


@pytest.fixture
def other_key(conn: sqlite3.Connection) -> str:
    """Een tweede user (agent) die activiteit kan veroorzaken."""
    _, key = users_repo.create(
        conn, handle="claude", display_name="Claude", kind="agent"
    )
    return key


@pytest.fixture
def other_auth(other_key: str) -> dict:
    return {"Authorization": f"Bearer {other_key}"}


@pytest.fixture
def project(project, client, auth) -> str:
    client.post("/api/v1/projects/SOS/items", json={"title": "x"}, headers=auth)
    # person is de assignee; claude veroorzaakt straks de vreemde activiteit.
    client.patch("/api/v1/items/SOS-1", json={"assignee": "person"}, headers=auth)
    return project


def _unread(client, auth, ref: str = "SOS-1") -> bool:
    return client.get(f"/api/v1/items/{ref}", headers=auth).json()["has_unread"]


def _unread_in_list(client, auth, ref: str = "SOS-1") -> bool:
    rows = client.get("/api/v1/projects/SOS/items", headers=auth).json()
    return next(r for r in rows if r["ref"] == ref)["has_unread"]


# --- Vreemde vs. eigen activiteit ----------------------------------------


def test_comment_from_someone_else_marks_unread(client, auth, other_auth, project):
    """Kern: een comment van een ander maakt het item ongelezen voor de assignee."""
    client.post(
        "/api/v1/items/SOS-1/read", headers=auth
    )  # eerst schoon: alles gezien
    assert _unread(client, auth) is False

    client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=other_auth
    )
    assert _unread(client, auth) is True
    assert _unread_in_list(client, auth) is True


def test_own_comment_does_not_mark_unread(client, auth, project):
    """Je eigen activiteit maakt een item nóóit ongelezen — anders is elk item dat
    je aanraakt meteen weer 'ongelezen'."""
    client.post("/api/v1/items/SOS-1/read", headers=auth)
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "eigen"}, headers=auth)
    assert _unread(client, auth) is False
    assert _unread_in_list(client, auth) is False


def test_own_activity_after_read_keeps_item_read(client, auth, other_auth, project):
    """Discriminerend: een eigen event ná het lezen (dus met een hóger event-id dan
    de watermark) laat de vlag uit — de vreemde max telt, niet de absolute max."""
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "a"}, headers=other_auth)
    client.post("/api/v1/items/SOS-1/read", headers=auth)
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "b"}, headers=auth)
    assert _unread(client, auth) is False


def test_item_without_foreign_activity_is_read(client, auth, project):
    """Een vers item dat je zelf maakte is niet ongelezen (geen vreemde events)."""
    assert _unread(client, auth) is False


def test_label_change_by_someone_else_does_not_mark_unread(
    client, auth, other_auth, project
):
    """BETON-281: Person koos expliciet voor alleen ongelezen *comments* — een
    label-wijziging door een ander is `item.updated`, geen comment-event, en
    mag de kaart niet markeren. Dit is de discriminerende test uit het plan."""
    client.post(
        "/api/v1/projects/SOS/labels", json={"name": "triage"}, headers=auth
    )
    client.post("/api/v1/items/SOS-1/read", headers=auth)
    assert _unread(client, auth) is False

    client.post("/api/v1/items/SOS-1/labels/triage", headers=other_auth)
    assert _unread(client, auth) is False
    assert _unread_in_list(client, auth) is False

    # Ter controle: een comment op datzelfde item markeert wél.
    client.post(
        "/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=other_auth
    )
    assert _unread(client, auth) is True


# --- Markeren als gelezen -------------------------------------------------


def test_read_endpoint_clears_flag(client, auth, other_auth, project):
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=other_auth)
    assert _unread(client, auth) is True

    resp = client.post("/api/v1/items/SOS-1/read", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["has_unread"] is False
    assert _unread(client, auth) is False
    assert _unread_in_list(client, auth) is False


def test_read_marks_only_this_item(client, auth, other_auth, project):
    """De kern van BETON-294: één ticket lezen markeert niet álles als gelezen
    (dat was precies het gebrek van de globale watermark)."""
    client.post("/api/v1/projects/SOS/items", json={"title": "y"}, headers=auth)
    client.patch("/api/v1/items/SOS-2", json={"assignee": "person"}, headers=auth)
    for ref in ("SOS-1", "SOS-2"):
        client.post(
            f"/api/v1/items/{ref}/comments", json={"body_md": "hoi"}, headers=other_auth
        )

    client.post("/api/v1/items/SOS-1/read", headers=auth)

    assert _unread(client, auth, "SOS-1") is False
    assert _unread(client, auth, "SOS-2") is True


def test_read_watermark_never_goes_down(client, auth, other_auth, conn, project):
    """Monotoon, net als inbox.mark_seen: een nieuwe vreemde comment ná het lezen
    maakt weer ongelezen, maar opnieuw lezen verlaagt de marker niet."""
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "1"}, headers=other_auth)
    first = client.post("/api/v1/items/SOS-1/read", headers=auth).json()[
        "last_seen_event_id"
    ]
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "2"}, headers=other_auth)
    assert _unread(client, auth) is True
    second = client.post("/api/v1/items/SOS-1/read", headers=auth).json()[
        "last_seen_event_id"
    ]
    assert second > first
    # Eén rij per (user, item) — geen duplicaten na herhaald lezen.
    assert (
        conn.execute("SELECT COUNT(*) AS n FROM item_reads").fetchone()["n"] == 1
    )


def test_read_writes_no_event(client, auth, other_auth, conn, project):
    """Lezen is geen activiteit: het schrijft geen event (anders zou het item voor
    ánderen ongelezen worden)."""
    before = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    client.post("/api/v1/items/SOS-1/read", headers=auth)
    after = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    assert after == before


def test_read_is_per_user(client, auth, other_auth, project):
    """A leest, B niet: read-state deelt niets tussen users."""
    # person veroorzaakt activiteit; het item is voor claude ongelezen.
    client.patch("/api/v1/items/SOS-1", json={"assignee": "claude"}, headers=auth)
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=auth)
    assert _unread(client, other_auth) is True

    client.post("/api/v1/items/SOS-1/read", headers=other_auth)
    assert _unread(client, other_auth) is False

    # Voor person verandert claude's leesactie niets: er is vreemde activiteit
    # (de toewijzing door claude bestaat niet, dus maak er expliciet één).
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "van claude"}, headers=other_auth)
    assert _unread(client, auth) is True
    assert _unread(client, other_auth) is False


def test_read_unknown_item_404(client, auth, project):
    assert client.post("/api/v1/items/SOS-999/read", headers=auth).status_code == 404


def test_read_requires_auth(client, project):
    assert client.post("/api/v1/items/SOS-1/read").status_code == 401


# --- Samenspel met de bestaande globale watermark -------------------------


def test_global_inbox_watermark_still_marks_items_read(client, auth, other_auth, project):
    """Regressie: de globale watermark (`users.last_seen_event_id`, migratie 019)
    blijft gelden — het per-item-gedrag komt eróverheen, niet ervoor in de plaats."""
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=other_auth)
    assert _unread(client, auth) is True

    inbox = client.get("/api/v1/inbox", headers=auth).json()
    latest = max(i["event_id"] for i in inbox["items"])
    client.post("/api/v1/inbox/seen", json={"event_id": latest}, headers=auth)

    assert _unread(client, auth) is False


def test_inbox_unread_count_drops_after_item_read(client, auth, other_auth, project):
    """Sinds BETON-286 koppelt de inbox mee: een item lezen telt zijn eigen
    notificaties niet langer mee in de globale teller. De globale watermark
    zelf (`last_seen_event_id`) blijft ongemoeid — dit is een aparte,
    per-item bijdrage aan diezelfde teller. Zie test_inbox.py voor de volle
    dekking (andere tickets blijven ongelezen, bulkvorm)."""
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=other_auth)
    before = client.get("/api/v1/inbox", headers=auth).json()["unread_count"]
    assert before > 0

    client.post("/api/v1/items/SOS-1/read", headers=auth)
    after = client.get("/api/v1/inbox", headers=auth).json()
    assert after["unread_count"] == before - 1
    assert after["last_seen_event_id"] == 0


# --- Bulk: geen N+1 -------------------------------------------------------


def test_list_does_not_query_per_item(db_path, client, auth, other_auth, conn, project):
    """Bewaakt de bulkvorm (`item_reads.unread_bulk`): het board haalt honderden
    items op, dus het aantal read-state-query's moet constant zijn — onafhankelijk
    van het aantal items. Een query per item is een echte performanceregressie.

    Meten op repo-niveau met een trace-callback; de query's van de request-
    connectie zijn via de TestClient niet te observeren.
    """
    for n in range(2, 12):
        client.post("/api/v1/projects/SOS/items", json={"title": f"t{n}"}, headers=auth)
        client.post(
            f"/api/v1/items/SOS-{n}/comments", json={"body_md": "hoi"}, headers=other_auth
        )
    project_id = conn.execute("SELECT id FROM projects WHERE key = 'SOS'").fetchone()["id"]
    viewer = conn.execute("SELECT id FROM users WHERE handle = 'person'").fetchone()["id"]

    def _count_queries(limit: int) -> tuple[int, int]:
        traced = db_module.connect(db_path)
        statements: list[str] = []
        traced.set_trace_callback(statements.append)
        rows = items_repo.list_items(traced, project_id, limit=limit, viewer_id=viewer)
        traced.close()
        assert len(rows) == limit  # écht zoveel items geserialiseerd
        return (
            sum(1 for s in statements if "FROM events" in s),
            sum(1 for s in statements if "FROM item_reads" in s),
        )

    assert _count_queries(2) == _count_queries(11)


def test_list_without_viewer_has_no_read_state(client, auth, other_auth, conn, project):
    """Zonder viewer (serialisatie buiten een request-context) is has_unread False
    en worden er geen read-state-query's gedaan."""
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=other_auth)
    project_id = conn.execute("SELECT id FROM projects WHERE key = 'SOS'").fetchone()["id"]
    rows = items_repo.list_items(conn, project_id)
    assert all(r["has_unread"] is False for r in rows)

    item = items_repo.get_by_ref(conn, "SOS-1")
    assert items_repo.serialize(conn, item)["has_unread"] is False


# --- _in_clause bulk-helper (BETON-326) -----------------------------------
#
# `watermarks_bulk` en `unread_bulk` gebruiken `_in_clause` voor hun
# `IN (...)`-placeholders. Lege id-lijst → geen query (guard blijft bij de
# caller); niet-lege lijst → dezelfde mapping/set als voorheen.


def test_watermarks_bulk_empty_and_non_empty(db_path, client, auth, conn, project):
    from betonning import db as db_module
    from betonning.repo import item_reads as item_reads_repo

    person = users_repo.get_by_handle(conn, "person")
    item = items_repo.get_by_ref(conn, "SOS-1")
    item_reads_repo.mark_read(conn, item["id"], person["id"], 1)
    conn.commit()

    traced = db_module.connect(db_path)
    statements: list[str] = []
    traced.set_trace_callback(statements.append)
    empty = item_reads_repo.watermarks_bulk(traced, [], person["id"])
    traced.close()
    assert empty == {}
    assert not any("SELECT" in s for s in statements)

    result = item_reads_repo.watermarks_bulk(conn, [item["id"]], person["id"])
    assert result[item["id"]] == 1


def test_unread_bulk_empty_and_non_empty(db_path, client, auth, other_auth, conn, project):
    from betonning import db as db_module
    from betonning.repo import item_reads as item_reads_repo

    person = users_repo.get_by_handle(conn, "person")
    item = items_repo.get_by_ref(conn, "SOS-1")
    client.post("/api/v1/items/SOS-1/comments", json={"body_md": "hoi"}, headers=other_auth)

    traced = db_module.connect(db_path)
    statements: list[str] = []
    traced.set_trace_callback(statements.append)
    empty = item_reads_repo.unread_bulk(traced, [], person["id"])
    traced.close()
    assert empty == set()
    assert not any("SELECT" in s for s in statements)

    result = item_reads_repo.unread_bulk(conn, [item["id"]], person["id"])
    assert result == {item["id"]}
