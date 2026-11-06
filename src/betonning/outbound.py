"""Eigen uitvoerteksten lokaliseren; parameters en opgeslagen broninhoud blijven data."""
import json
from pathlib import Path

from .config import installation_language

MESSAGES = json.loads(Path(__file__).with_name('outbound_messages.json').read_text())


def outbound(key: str, *, language: str | None = None, **params) -> str:
    """Stabiele template, Engelse fallback; nooit vertaling van gerenderde invoer."""
    language = language or installation_language()
    entry = MESSAGES[key]
    return entry.get(language, entry['en']).format(**params)
