"""DB-laag: migraties en PRAGMA's."""

from __future__ import annotations

from betonning import db as db_module


def test_migrate_sets_user_version(tmp_path):
    conn = db_module.connect(tmp_path / "x.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    version = db_module.migrate(conn)
    assert version >= 1
    assert conn.execute("PRAGMA user_version").fetchone()[0] == version


def test_migrate_is_idempotent(tmp_path):
    path = tmp_path / "x.db"
    db_module.init_db(path).close()
    conn = db_module.connect(path)
    # Tweede run mag niet crashen en houdt de laatste versie vast.
    latest = conn.execute("PRAGMA user_version").fetchone()[0]
    assert db_module.migrate(conn) == latest


def test_wal_mode_enabled(tmp_path):
    conn = db_module.connect(tmp_path / "x.db")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_expected_tables_exist(tmp_path):
    conn = db_module.init_db(tmp_path / "x.db")
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r["name"] for r in rows}
    for t in [
        "users", "projects", "states", "items", "labels", "item_labels",
        "milestones", "comments", "relations", "events", "webhook_deliveries",
    ]:
        assert t in names


_COMMENTS_FTS_VERSION = 38


def test_comments_fts_backfills_existing_comments(tmp_path):
    """BETON-370: migratie 038 indexeert comments die er al stonden.

    De triggers dekken alleen nieuwe/gewijzigde comments; de prod-db heeft er
    duizenden staan. Daarom de migratie tot vlak vóór 038 draaien, een comment
    schrijven, en dán de echte runner de rest laten doen — dat toetst de
    ``'rebuild'`` in de migratie zelf, niet een trigger.
    """
    conn = db_module.connect(tmp_path / "x.db")
    applied = 0
    for version, sql in db_module._migration_files():
        if version >= _COMMENTS_FTS_VERSION:
            continue
        conn.executescript(sql)
        applied = version
    conn.execute(f"PRAGMA user_version = {applied}")
    conn.execute("INSERT INTO projects (key, name) VALUES ('SOS', 'SOS')")
    conn.execute("INSERT INTO items (project_id, seq, title) VALUES (1, 1, 'Iets')")
    conn.execute("INSERT INTO comments (item_id, body_md) VALUES (1, 'kraakpeer hier')")
    conn.commit()
    assert "comments_fts" not in _table_names(conn)

    db_module.migrate(conn)

    assert "comments_fts" in _table_names(conn)
    hits = conn.execute(
        "SELECT rowid FROM comments_fts WHERE comments_fts MATCH ?", ('"kraakpeer"*',)
    ).fetchall()
    assert len(hits) == 1


def _table_names(conn) -> set[str]:
    return {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
