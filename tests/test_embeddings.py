"""Embeddings: serialisatie, cosine, store + find_similar (BETON-22)."""

from __future__ import annotations

from betonning import embeddings as emb
from betonning.repo import projects as projects_repo


def test_pack_unpack_roundtrip():
    vec = [0.1, -0.2, 0.3, 1.5]
    back = emb.unpack_vector(emb.pack_vector(vec))
    assert len(back) == len(vec)
    assert all(abs(a - b) < 1e-6 for a, b in zip(vec, back))


def test_cosine():
    assert abs(emb.cosine([1, 0], [1, 0]) - 1.0) < 1e-9
    assert abs(emb.cosine([1, 0], [0, 1])) < 1e-9
    assert emb.cosine([1, 0], []) == 0.0


def test_find_similar_ranks_and_excludes(conn):
    p = projects_repo.create(conn, key="SOS", name="SOS")
    pid = p["id"]

    def _item(seq, title):
        cur = conn.execute(
            "INSERT INTO items (project_id, seq, title) VALUES (?, ?, ?)",
            (pid, seq, title),
        )
        return cur.lastrowid

    a = _item(1, "a")
    b = _item(2, "b")
    c = _item(3, "c")
    emb.upsert(conn, a, "m", [1.0, 0.0])
    emb.upsert(conn, b, "m", [0.9, 0.1])  # dichtbij query
    emb.upsert(conn, c, "m", [0.0, 1.0])  # ver van query
    conn.commit()

    result = emb.find_similar(conn, pid, [1.0, 0.0], top_k=10, exclude_item_id=a)
    ids = [i for i, _ in result]
    assert ids[0] == b  # meest gelijkend bovenaan
    assert a not in ids  # zichzelf uitgesloten
    assert ids[-1] == c


def test_find_similar_scopes_to_project(conn):
    p1 = projects_repo.create(conn, key="SOS", name="SOS")["id"]
    p2 = projects_repo.create(conn, key="BRAND", name="Brand")["id"]
    conn.execute("INSERT INTO items (project_id, seq, title) VALUES (?, 1, 'x')", (p1,))
    a = conn.execute("SELECT id FROM items WHERE project_id = ?", (p1,)).fetchone()["id"]
    conn.execute("INSERT INTO items (project_id, seq, title) VALUES (?, 1, 'y')", (p2,))
    b = conn.execute("SELECT id FROM items WHERE project_id = ?", (p2,)).fetchone()["id"]
    emb.upsert(conn, a, "m", [1.0, 0.0])
    emb.upsert(conn, b, "m", [1.0, 0.0])
    conn.commit()
    result = emb.find_similar(conn, p1, [1.0, 0.0], top_k=10)
    assert [i for i, _ in result] == [a]  # ander project niet meegenomen


def test_client_from_env_none_without_config(monkeypatch):
    for var in (
        "BETONNING_EMBED_BASE_URL",
        "BETONNING_EMBED_API_KEY",
        "BETONNING_EMBED_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    assert emb.client_from_env() is None
