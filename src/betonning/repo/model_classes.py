"""Werkklassen → model per harnas (BETON-476)."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

CLASSES = ("routine", "standaard", "complex")
LEGACY_LABELS = {
    "opus": "complex", "gpt-5.5": "complex", "sol": "complex",
    "sonnet": "standaard",
    "gpt-5.4-mini": "routine", "terra": "routine", "haiku": "routine",
}


def get_all(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """``{harness: {class: model}}`` — alleen klassen die een rij hebben."""
    out: dict[str, dict[str, str]] = {}
    rows = conn.execute(
        "SELECT harness, class, model FROM model_classes ORDER BY harness"
    ).fetchall()
    for r in rows:
        out.setdefault(r["harness"], {})[r["class"]] = r["model"]
    return out


def replace_all(conn: sqlite3.Connection, mapping: Mapping[str, Mapping[str, str]]) -> None:
    """Vervang de hele mapping. Aanroeper zorgt voor de transactie."""
    conn.execute("DELETE FROM model_classes")
    for harness, classes in mapping.items():
        for cls, model in classes.items():
            conn.execute(
                "INSERT INTO model_classes (harness, class, model) VALUES (?, ?, ?)",
                (harness, cls, model),
            )


def model_for(conn: sqlite3.Connection, harness: str | None, cls: str | None) -> str | None:
    """Het model van ``harness`` voor klasse ``cls``; onbekend harnas/klasse → None."""
    if not harness or not cls:
        return None
    row = conn.execute(
        "SELECT model FROM model_classes WHERE harness = ? AND class = ?",
        (harness, cls),
    ).fetchone()
    return row["model"] if row else None


def class_of_item(conn: sqlite3.Connection, item_id: int) -> str | None:
    """De werkklasse van een item (via zijn labels). Zijn er meer, dan wint de
    zwaarste — beter te veel model dan te weinig."""
    names = {
        r[0]
        for r in conn.execute(
            "SELECT l.name FROM item_labels il JOIN labels l ON l.id = il.label_id "
            "WHERE il.item_id = ?",
            (item_id,),
        )
    }
    for cls in reversed(CLASSES):
        if cls in names:
            return cls
    return None


def hint_for(conn: sqlite3.Connection, item_id: int | None, handle: str) -> dict | None:
    """``{"class", "model"}`` voor deze agent op dit item, of None als het item
    geen klasse heeft of de agent geen harnas met een mapping is."""
    if item_id is None:
        return None
    cls = class_of_item(conn, item_id)
    model = model_for(conn, handle, cls)
    if cls is None or model is None:
        return None
    return {"class": cls, "model": model}
