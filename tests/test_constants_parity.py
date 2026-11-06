"""Backend↔UI-pariteit voor de gedeelde enums (BETON-327).

`models.py` is de enige bron voor `PRIORITIES`/`WORKLOADS` (afgeleid via
`typing.get_args` uit de `Literal`s); `repo/items.py` en `triage_commands.py`
importeren die nu i.p.v. eigen losse tuples/frozensets te onderhouden. Deze
test bewaakt dat de UI (`ui/src/lib/labels.js`, JS — kan de Python-Literal
niet importeren) niet uit de pas gaat lopen met de backend-waarden.

We parsen `labels.js` als tekst (geen JS-runtime hier) en vergelijken de
waarden-sets. Alleen constanten die daadwerkelijk in `labels.js` bestaan
worden getest — `PRIORITY_VALUES` is met BETON-330 als dode code verwijderd,
dus priority-pariteit loopt via de sleutels van `PRIO_LABELS` (dat blijft
bestaan voor de weergave van historische activiteit).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from betonning.models import (
    GUARDRAIL_MAX_CHARS,
    PRIORITIES,
    Priority,
    StateGroup,
    Workload,
    WORKLOADS,
)
from betonning.repo.items import PRIORITIES as ITEMS_PRIORITIES
from betonning.repo.items import WORKLOADS as ITEMS_WORKLOADS
from betonning.triage_commands import _PRIORITIES as TRIAGE_PRIORITIES

UI_LIB = Path(__file__).resolve().parent.parent / "ui" / "src" / "lib"
LABELS_JS = UI_LIB / "labels.js"
GUARDRAIL_JS = UI_LIB / "guardrail.js"


def _js_array_values(source: str, const_name: str) -> set[str]:
    """Parse de stringwaarden uit `export const <const_name> = [...]`."""
    m = re.search(rf"{const_name}\s*=\s*\[(.*?)\]", source, re.DOTALL)
    assert m, f"{const_name} niet gevonden in labels.js"
    return set(re.findall(r'["\']([\w-]+)["\']', m.group(1)))


def _js_object_keys(source: str, const_name: str) -> set[str]:
    """Parse de sleutels uit `const <const_name> = { key: "...", ... }`."""
    m = re.search(rf"{const_name}\s*=\s*\{{(.*?)\}}", source, re.DOTALL)
    assert m, f"{const_name} niet gevonden in labels.js"
    return set(re.findall(r"^\s*(\w[\w-]*)\s*:", m.group(1), re.MULTILINE))


def test_models_is_the_single_source_for_priorities_and_workloads():
    """`PRIORITIES`/`WORKLOADS` zijn afgeleid uit de Literals, niet los onderhouden."""
    assert PRIORITIES == get_args(Priority)
    assert WORKLOADS == get_args(Workload)


def test_repo_items_reexports_models_constants():
    assert ITEMS_PRIORITIES is PRIORITIES
    assert ITEMS_WORKLOADS is WORKLOADS


def test_triage_commands_priorities_derived_from_models():
    assert TRIAGE_PRIORITIES == frozenset(PRIORITIES)


def test_priority_parity_with_ui_prio_labels():
    source = LABELS_JS.read_text(encoding="utf-8")
    ui_values = _js_object_keys(source, "PRIO_LABELS")
    assert set(PRIORITIES) == ui_values


def test_workload_parity_with_ui_workload_values():
    source = LABELS_JS.read_text(encoding="utf-8")
    ui_values = _js_array_values(source, "WORKLOAD_VALUES")
    assert set(WORKLOADS) == ui_values


def test_guardrail_max_chars_parity_with_ui():
    """De tekencap (BETON-420) staat in `models.py` én in `guardrail.js`.

    De UI valideert lokaal zodat de gebruiker de 422 niet hoeft op te halen;
    lopen de twee uit elkaar, dan weigert de server wat de UI toestaat (of
    andersom). Een scalar, dus een eigen regex — de helpers hierboven parsen
    arrays en objecten.
    """
    source = GUARDRAIL_JS.read_text(encoding="utf-8")
    m = re.search(r"GUARDRAIL_MAX_CHARS\s*=\s*(\d+)", source)
    assert m, "GUARDRAIL_MAX_CHARS niet gevonden in guardrail.js"
    assert int(m.group(1)) == GUARDRAIL_MAX_CHARS


def test_state_group_parity_with_ui_state_group_labels():
    source = LABELS_JS.read_text(encoding="utf-8")
    ui_values = _js_object_keys(source, "STATE_GROUP_LABELS")
    assert set(get_args(StateGroup)) == ui_values
