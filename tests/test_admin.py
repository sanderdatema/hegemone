"""Admin-CLI: user aanmaken en Telegram koppelen (out-of-band beheer)."""

from __future__ import annotations

from betonning import admin
from betonning import db as db_module
from betonning.repo import users as users_repo


def test_create_user_prints_key(tmp_path, capsys):
    db = str(tmp_path / "a.db")
    rc = admin.main(["create-user", "--db", db, "--handle", "claude", "--name", "Claude"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "bt_" in out


def test_rotate_key_prints_new_key_and_invalidates_old(tmp_path, capsys):
    db = str(tmp_path / "rotate.db")
    admin.main(["create-user", "--db", db, "--handle", "codex", "--name", "Codex"])
    old_out = capsys.readouterr().out
    old_key = next(part for part in old_out.split() if part.startswith("bt_"))

    rc = admin.main(["rotate-key", "--db", db, "--handle", "codex"])
    assert rc == 0
    out = capsys.readouterr().out
    new_key = next(part for part in out.split() if part.startswith("bt_"))
    assert new_key != old_key

    conn = db_module.connect(db)
    assert users_repo.get_by_api_key(conn, old_key) is None
    assert users_repo.get_by_api_key(conn, new_key)["handle"] == "codex"
    conn.close()


def test_create_user_with_invalid_handle_exits_nonzero_without_creating_row(
    tmp_path, capsys
):
    db = str(tmp_path / "invalid-handle.db")
    rc = admin.main(
        ["create-user", "--db", db, "--handle", "a b", "--name", "Ongeldig"]
    )
    assert rc != 0
    out = capsys.readouterr().out
    assert "Ongeldige handle" in out

    conn = db_module.init_db(db)
    assert users_repo.get_by_handle(conn, "a b") is None
    conn.close()


def test_rotate_key_unknown_user(tmp_path):
    db = str(tmp_path / "rotate-unknown.db")
    db_module.init_db(db).close()
    rc = admin.main(["rotate-key", "--db", db, "--handle", "ghost"])
    assert rc == 1


def test_set_telegram_links_chat(tmp_path, capsys):
    db = str(tmp_path / "b.db")
    admin.main(["create-user", "--db", db, "--handle", "person", "--name", "Person"])
    rc = admin.main(["set-telegram", "--db", db, "--handle", "person", "42424"])
    assert rc == 0

    conn = db_module.connect(db)
    row = users_repo.get_by_handle(conn, "person")
    assert row["telegram_chat_id"] == "42424"
    assert users_repo.serialize(row)["has_telegram"] is True
    conn.close()


def test_set_telegram_unknown_user(tmp_path):
    db = str(tmp_path / "c.db")
    db_module.init_db(db).close()
    rc = admin.main(["set-telegram", "--db", db, "--handle", "ghost", "1"])
    assert rc == 1


def test_set_webhook_sets_url_and_secret(tmp_path, capsys):
    db = str(tmp_path / "e.db")
    admin.main(["create-user", "--db", db, "--handle", "smid", "--name", "Smid",
                "--kind", "agent"])
    rc = admin.main(
        ["set-webhook", "--db", db, "smid", "--url", "http://hermes.local/hook",
         "--secret", "s3cret"]
    )
    assert rc == 0

    conn = db_module.connect(db)
    row = users_repo.get_by_handle(conn, "smid")
    assert row["webhook_url"] == "http://hermes.local/hook"
    assert row["webhook_secret"] == "s3cret"
    assert users_repo.serialize(row)["has_webhook"] is True
    conn.close()


def test_set_webhook_unknown_user(tmp_path):
    db = str(tmp_path / "f.db")
    db_module.init_db(db).close()
    rc = admin.main(["set-webhook", "--db", db, "ghost", "--url", "http://x/hook"])
    assert rc == 1


def test_set_telegram_unlink(tmp_path):
    db = str(tmp_path / "d.db")
    admin.main(["create-user", "--db", db, "--handle", "person", "--name", "Person"])
    admin.main(["set-telegram", "--db", db, "--handle", "person", "42424"])
    admin.main(["set-telegram", "--db", db, "--handle", "person", ""])  # leeg → ontkoppelen
    conn = db_module.connect(db)
    assert users_repo.get_by_handle(conn, "person")["telegram_chat_id"] is None
    conn.close()


def test_set_webhook_rejects_loopback(tmp_path):
    """Ook out-of-band geldt de webhook-poort (BETON-378)."""
    db = str(tmp_path / "g.db")
    admin.main(["create-user", "--db", db, "--handle", "smid", "--name", "Smid",
                "--kind", "agent"])
    rc = admin.main(
        ["set-webhook", "--db", db, "smid", "--url", "http://127.0.0.1:8000/hook"]
    )
    assert rc == 1

    conn = db_module.connect(db)
    assert users_repo.get_by_handle(conn, "smid")["webhook_url"] is None
    conn.close()
