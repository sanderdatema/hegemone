"""Runtime-instellingen met publieke namen en compatibele legacy-aliassen.

Er worden uitsluitend expliciet gevraagde waarden gelezen. Deze module kopieert
of logt geen omgevingsvariabelen en wijzigt de procesomgeving niet.
"""
from __future__ import annotations
import os
from contextvars import ContextVar
from contextlib import contextmanager

_runtime: ContextVar[dict[str, str]] = ContextVar("hegemone_runtime", default={})
_MISSING = object()


def raw_env(name: str, default=None):
    """HEGEMONE_* gaat voor BETONNING_*; expliciet leeg blijft leeg.

    Aanroepers houden hun bestaande parsing/validatie. Leeg kan daardoor een
    optionele integratie uitschakelen zonder een legacycredential te gebruiken.
    Andere namen worden zonder alias opgezocht.
    """
    if name.startswith('BETONNING_'):
        public_name = 'HEGEMONE_' + name.removeprefix('BETONNING_')
        if public_name in os.environ:
            return os.environ[public_name]
    return os.environ.get(name, default)


def env(name: str, default=None):
    """Deploymentwaarden blijven leidend; opgeslagen defaults zijn contextlokaal."""
    value = raw_env(name, _MISSING)
    return _runtime.get().get(name, default) if value is _MISSING else value


@contextmanager
def runtime_context(values):
    token = _runtime.set(values)
    try:
        yield
    finally:
        _runtime.reset(token)


def ai_language() -> str:
    """Uitvoertaal voor nieuw gegenereerde tekst; geen browser- of datamutatie."""
    language = env("BETONNING_AI_LANGUAGE", "en").strip().lower()
    if language not in {"en", "nl"}:
        raise ValueError("HEGEMONE_AI_LANGUAGE moet en of nl zijn.")
    return language


def installation_language() -> str:
    """Servergegenereerde tekst volgt installatieconfiguratie, niet browsertaal."""
    language = env("BETONNING_LANGUAGE", "en").strip().lower()
    if language not in {"en", "nl"}:
        raise ValueError("HEGEMONE_LANGUAGE moet en of nl zijn.")
    return language
