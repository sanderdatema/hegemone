"""BETON-476: migratie 047 zet modellabels om naar werkklassen."""

from __future__ import annotations

from betonning import db as dbm


def _conn_at_46(tmp_path):
    conn = dbm.connect(tmp_path / "m.db")
    for version, sql in dbm._migration_files():
        if version <= 46:
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version = {version}")
    return conn


def _run_47(conn):
    for version, sql in dbm._migration_files():
        if version == 47:
            conn.executescript(sql)


def _label(conn, pid, name, color="#111111"):
    return conn.execute(
        "INSERT INTO labels (project_id, name, color) VALUES (?, ?, ?)", (pid, name, color)
    ).lastrowid


def _item(conn, pid, seq):
    return conn.execute(
        "INSERT INTO items (project_id, seq, title) VALUES (?, ?, 't')", (pid, seq)
    ).lastrowid


def _names(conn, item_id):
    return sorted(
        r[0]
        for r in conn.execute(
            "SELECT l.name FROM item_labels il JOIN labels l ON l.id = il.label_id "
            "WHERE il.item_id = ?",
            (item_id,),
        )
    )


def test_hernoemt_en_voegt_samen(tmp_path):
    conn = _conn_at_46(tmp_path)
    a = conn.execute("INSERT INTO projects (key, name) VALUES ('AAA', 'A')").lastrowid
    b = conn.execute("INSERT INTO projects (key, name) VALUES ('BBB', 'B')").lastrowid
    # Project A: geen doellabels -> hernoemen (kleur blijft).
    a_opus = _label(conn, a, "opus", "#abcdef")
    a_sonnet = _label(conn, a, "sonnet")
    i1, i2 = _item(conn, a, 1), _item(conn, a, 2)
    conn.execute("INSERT INTO item_labels VALUES (?, ?)", (i1, a_opus))
    conn.execute("INSERT INTO item_labels VALUES (?, ?)", (i1, a_sonnet))
    conn.execute("INSERT INTO item_labels VALUES (?, ?)", (i2, a_sonnet))
    # Project B: doellabels bestaan al, en een item draagt oud + nieuw.
    b_opus = _label(conn, b, "opus")
    b_gpt = _label(conn, b, "gpt-5.5")
    b_complex = _label(conn, b, "complex")
    j1, j2 = _item(conn, b, 1), _item(conn, b, 2)
    conn.execute("INSERT INTO item_labels VALUES (?, ?)", (j1, b_opus))
    conn.execute("INSERT INTO item_labels VALUES (?, ?)", (j1, b_complex))
    conn.execute("INSERT INTO item_labels VALUES (?, ?)", (j2, b_gpt))

    _run_47(conn)

    assert _names(conn, i1) == ["complex", "standaard"]
    assert _names(conn, i2) == ["standaard"]
    assert conn.execute(
        "SELECT color FROM labels WHERE project_id = ? AND name = 'complex'", (a,)
    ).fetchone()[0] == "#abcdef"
    assert _names(conn, j1) == ["complex"]
    assert _names(conn, j2) == ["complex"]
    names_b = [r[0] for r in conn.execute("SELECT name FROM labels WHERE project_id = ?", (b,))]
    assert names_b == ["complex"]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
