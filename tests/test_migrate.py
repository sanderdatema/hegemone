"""Migratie uit Plane — mapping-logica getest met gemockte Plane-responses."""

from __future__ import annotations

import httpx
import pytest

from betonning import db as db_module
from betonning.migrate import RELATION_MAP, PlaneClient, run_migration
from betonning.repo import comments as comments_repo
from betonning.repo import items as items_repo
from betonning.repo import projects as projects_repo
from betonning.repo import relations as relations_repo
from betonning.repo import users as users_repo

STATES = [
    {"id": "st-backlog", "name": "backlog", "group": "backlog"},
    {"id": "st-todo", "name": "todo", "group": "unstarted"},
    {"id": "st-done", "name": "done", "group": "completed"},
]
LABELS = [
    {"id": "lb-bug", "name": "bug", "color": "#e74c3c"},
    {"id": "lb-opus", "name": "opus"},
]
ISSUES = [
    {
        "id": "i1", "name": "Parent ticket", "sequence_id": 1, "state": "st-todo",
        "priority": "high", "assignees": ["u-person"], "parent": None,
        "label_ids": ["lb-bug"], "created_by": "u-person",
        "description_stripped": "doe dit",
        "created_at": "2026-01-01T10:00:00.000Z",
        "updated_at": "2026-01-02T10:00:00.000Z", "completed_at": None,
    },
    {
        "id": "i2", "name": "Child ticket", "sequence_id": 2, "state": "st-backlog",
        "priority": "none", "assignees": [], "parent": "i1", "label_ids": [],
        "created_at": "2026-01-03T10:00:00.000Z",
    },
    {
        "id": "i5", "name": "Afgerond ding", "sequence_id": 5, "state": "st-done",
        "priority": "low", "assignees": ["u-claude"], "parent": None,
        "label_ids": ["lb-opus"], "completed_at": "2026-02-01T00:00:00.000Z",
        "created_at": "2026-01-20T10:00:00.000Z",
    },
]
COMMENTS = {
    "i1": [
        {"id": "c1", "comment_stripped": "eerste @claude", "actor": "u-person",
         "created_at": "2026-01-05T09:00:00.000Z"},
    ]
}
RELATIONS = {"i1": [{"relation_type": "blocking", "related_issue": "i2"}]}
USER_MAP = {"u-person": "person", "u-claude": "claude"}
PROJECTS_CONFIG = {"SOS": {"workspace": "ws", "project_id": "pid", "name": "SOS"}}


class FakePlane:
    def __init__(self, states=STATES, labels=LABELS, issues=ISSUES,
                 comments=COMMENTS, relations=RELATIONS):
        self._states, self._labels, self._issues = states, labels, issues
        self._comments, self._relations = comments, relations

    def states(self, ws, pid):
        return self._states

    def labels(self, ws, pid):
        return self._labels

    def issues(self, ws, pid):
        return self._issues

    def comments(self, ws, pid, issue_id):
        return self._comments.get(issue_id, [])

    def relations(self, ws, pid, issue_id):
        return self._relations.get(issue_id, [])


@pytest.fixture
def mdb(tmp_path):
    conn = db_module.init_db(str(tmp_path / "m.db"))
    users_repo.create(conn, handle="person", display_name="Person", kind="human")
    users_repo.create(conn, handle="claude", display_name="Claude", kind="agent")
    yield conn
    conn.close()


def _migrate(conn, **kw):
    return run_migration(conn, FakePlane(), PROJECTS_CONFIG, USER_MAP, **kw)


def test_creates_project_and_items(mdb):
    _migrate(mdb)
    assert projects_repo.get_by_key(mdb, "SOS") is not None
    for seq in (1, 2, 5):
        assert items_repo.get_by_ref(mdb, f"SOS-{seq}") is not None


def test_sequence_numbers_preserved(mdb):
    _migrate(mdb)
    row = items_repo.get_by_plane_id(mdb, "i5")
    assert row["seq"] == 5
    project = projects_repo.get_by_key(mdb, "SOS")
    assert project["next_seq"] == 6  # max(seq)+1


def test_fields_mapped(mdb):
    _migrate(mdb)
    data = items_repo.serialize(mdb, items_repo.get_by_ref(mdb, "SOS-1"))
    assert data["state"] == "todo"
    assert data["priority"] == "high"
    assert data["assignee"] == "person"
    assert data["labels"] == ["bug"]
    assert data["description_md"] == "doe dit"


def test_parent_relation(mdb):
    _migrate(mdb)
    data = items_repo.serialize(mdb, items_repo.get_by_ref(mdb, "SOS-2"))
    assert data["parent"] == "SOS-1"


def test_timestamps_preserved(mdb):
    _migrate(mdb)
    one = items_repo.get_by_plane_id(mdb, "i1")
    assert one["created_at"] == "2026-01-01T10:00:00.000Z"
    five = items_repo.get_by_plane_id(mdb, "i5")
    assert five["completed_at"] == "2026-02-01T00:00:00.000Z"


def test_comments_migrated(mdb):
    _migrate(mdb)
    item = items_repo.get_by_ref(mdb, "SOS-1")
    cs = [comments_repo.serialize(mdb, c) for c in comments_repo.list_for_item(mdb, item["id"])]
    assert len(cs) == 1
    assert cs[0]["author"] == "person"
    assert cs[0]["body_md"] == "eerste @claude"
    assert cs[0]["created_at"] == "2026-01-05T09:00:00.000Z"


def test_relations_directional(mdb):
    _migrate(mdb)
    one = items_repo.get_by_ref(mdb, "SOS-1")
    two = items_repo.get_by_ref(mdb, "SOS-2")
    assert relations_repo.for_item(mdb, one["id"])["blocks"] == ["SOS-2"]
    assert relations_repo.for_item(mdb, two["id"])["blocked_by"] == ["SOS-1"]


def test_idempotent(mdb):
    first = _migrate(mdb)
    assert first["projects"]["SOS"]["items_created"] == 3
    second = _migrate(mdb)
    assert second["projects"]["SOS"]["items_created"] == 0
    assert second["projects"]["SOS"]["items_skipped"] == 3
    # Geen duplicaten.
    n = mdb.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"]
    assert n == 3


def test_admin_migrate_plane_dry_run(tmp_path, monkeypatch, capsys):
    from betonning import admin
    from betonning import migrate as migrate_mod

    dbp = str(tmp_path / "c.db")
    conn = db_module.init_db(dbp)
    users_repo.create(conn, handle="person", display_name="S", kind="human")
    users_repo.create(conn, handle="claude", display_name="C", kind="agent")
    conn.close()

    monkeypatch.setattr(
        migrate_mod,
        "load_plane_config",
        lambda *a, **k: {"base_url": "x", "api_key": "y", "projects": PROJECTS_CONFIG},
    )
    monkeypatch.setattr(migrate_mod, "load_user_mapping", lambda *a, **k: USER_MAP)
    monkeypatch.setattr(migrate_mod, "PlaneClient", lambda *a, **k: FakePlane())

    rc = admin.main(["migrate-plane", "--from-plane", "--dry-run", "--db", dbp])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"items_created": 3' in out


def test_admin_migrate_plane_requires_from_plane(tmp_path, capsys):
    from betonning import admin

    rc = admin.main(["migrate-plane", "--db", str(tmp_path / "x.db")])
    assert rc == 1
    assert "--from-plane" in capsys.readouterr().out


def test_normalize_relations_uuid_lists():
    """Echte Plane-vorm: {relatietype: [uuid, ...]} met kale strings."""
    from betonning.migrate import _normalize_relations

    data = {
        "blocking": [],
        "blocked_by": ["u-b"],
        "relates_to": ["u-r1", "u-r2"],
        "duplicate": ["u-d"],
        "start_after": ["u-ignore"],  # niet in RELATION_MAP → genegeerd
    }
    out = _normalize_relations(data)
    assert {"relation_type": "blocked_by", "related_issue": "u-b"} in out
    assert {"relation_type": "relates_to", "related_issue": "u-r1"} in out
    assert {"relation_type": "relates_to", "related_issue": "u-r2"} in out
    assert {"relation_type": "duplicate", "related_issue": "u-d"} in out
    assert all(r["relation_type"] in RELATION_MAP for r in out)
    assert len(out) == 4


def test_planeclient_relations_endpoint(monkeypatch):
    """Lock het juiste endpoint (/relations/) + string-parsing end-to-end."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200, json={"blocking": [], "blocked_by": [], "relates_to": ["r1"], "duplicate": []}
        )

    client = PlaneClient("http://plane", "key")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    out = client.relations("ws", "pid", "iss1")
    assert seen["url"].endswith("/issues/iss1/relations/")
    assert out == [{"relation_type": "relates_to", "related_issue": "r1"}]


def test_planeclient_retries_on_429(monkeypatch):
    """429 → wachten (Retry-After) en opnieuw; daarna gewone response."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"results": [{"id": "x"}], "next_cursor": None})

    slept: list[float] = []
    monkeypatch.setattr("betonning.migrate.time.sleep", lambda d: slept.append(d))

    client = PlaneClient("http://plane", "key")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    out = client.issues("ws", "pid")
    assert out == [{"id": "x"}]
    assert calls["n"] == 3  # twee keer 429, derde keer 200
    assert slept == [0.0, 0.0]  # Retry-After gehonoreerd


def test_planeclient_gives_up_after_max_retries(monkeypatch):
    """Blijvende 429 → uiteindelijk raise_for_status."""
    monkeypatch.setattr("betonning.migrate.time.sleep", lambda d: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    client = PlaneClient("http://plane", "key")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        client.issues("ws", "pid")


def test_dry_run_writes_nothing_but_counts(mdb):
    report = _migrate(mdb, dry_run=True)
    assert report["dry_run"] is True
    counts = report["projects"]["SOS"]
    assert counts["items_created"] == 3
    assert counts["comments"] == 1
    assert counts["relations"] == 1
    assert counts["states"] == 3
    assert counts["labels"] == 2
    # Niets geschreven.
    assert projects_repo.get_by_key(mdb, "SOS") is None
    assert mdb.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"] == 0
