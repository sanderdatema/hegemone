"""SQLite-connectie, PRAGMA's en migratierunner.

Eén serverproces schrijft; WAL + busy_timeout zorgen dat lezers nooit blokkeren.
Migraties zijn genummerde .sql-bestanden in migrations/; de runner draait alles
met een hoger nummer dan de huidige PRAGMA user_version en zet die bij.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path


def today(conn: sqlite3.Connection) -> str:
    """Vandaag volgens de DATABASE (UTC, `date('now')`), niet de lokale hostklok.

    Eén klok voor "vandaag": guardrail-reviewdatums, de triage-finders, de
    deadline-entries in de inbox en de milestone-overdue gebruiken allemaal
    deze, anders schuift een deadline rond middernacht een dag t.o.v. de rest
    (BETON-484)."""
    return conn.execute("SELECT date('now') AS d").fetchone()["d"]


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Voer een blok atomair uit. Commit bij succes, rollback bij elke fout.

    We draaien met isolation_level=None (autocommit), dus een expliciete
    ``BEGIN IMMEDIATE`` pakt meteen de schrijf-lock — zo laat een fout halverwege
    (update + labels + event + fanout) nooit een halve mutatie achter.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open een connectie met de juiste PRAGMA's en Row-factory."""
    conn = sqlite3.connect(
        str(db_path),
        check_same_thread=False,
        isolation_level=None,  # autocommit; we beheren transacties expliciet
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _migration_files() -> list[tuple[int, str]]:
    """Alle migraties als (versienummer, sql), oplopend gesorteerd."""
    migrations: list[tuple[int, str]] = []
    files = resources.files("betonning.migrations")
    for entry in files.iterdir():
        name = entry.name
        if not name.endswith(".sql"):
            continue
        version = int(name.split("_", 1)[0])
        migrations.append((version, entry.read_text(encoding="utf-8")))
    migrations.sort(key=lambda m: m[0])
    return migrations


def migrate(conn: sqlite3.Connection) -> int:
    """Draai openstaande migraties. Geeft de nieuwe schema-versie terug."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    target = current
    for version, sql in _migration_files():
        if version <= current:
            continue
        conn.executescript(sql)
        conn.execute(f"PRAGMA user_version = {version}")
        target = version
    return target


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Open een connectie en draai migraties. Handig eenregelig startpunt."""
    conn = connect(db_path)
    migrate(conn)
    return conn
