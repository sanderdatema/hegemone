"""Characterization-matrix over `webhooks.build_instructions` (BETON-333).

Dit is een **oracle**, geen specificatie: het legt het HUIDIGE gedrag vast van de
actie-berekening (`_ownership_action` → `only_reading` → triggertype →
`_field_based_action`), zodat een representatie-refactor bit-identiek moet
blijven. Elke case is gepind aan een regressie-ticket (BRAND-150, BETON-282,
BETON-291, BETON-292, BETON-293, BETON-299); geen enkele tak mag stilletjes
verdwijnen of samenvallen.

De sleutel is bewust NIET het viertal `(trigger_type, event_type, is_assignee,
dominant_field)` — de berekening leest méér signalen, en juist die extra
dimensies zijn waar een refactor kan glippen:

- `only_reading` is afgeleid (`addressed_to` + eigen handle), geen event-veld;
- de assignee-richting (`to_me`/`from_me`) en de state-richting
  (`completed`/`cancelled` vs `work_unblocked`) zijn sub-signalen ván een veld,
  niet het veld zelf;
- `relation_type` is richtinggevoelig: `blocked_by`/`duplicate_of` geven een
  stopsein, `blocks`/`duplicated_by` juist niet;
- `work_allowed` moduleert **niet uniform** — `mention → respond` is
  onvoorwaardelijk, maar `assigned` + comment-event is wél work-gated.

We snapshotten de VOLLEDIGE outputdict (`instructions`/`expected_action`/`do`/
`do_not`/`read`/`reply`), niet alleen `expected_action`: strikt sterker en even
goedkoop. De verwachte waarden staan in `test_webhooks_action_matrix.json`,
gegenereerd uit de code van vóór de refactor (`python -m tests.
test_webhooks_action_matrix` vanuit de repo-root herschrijft het bestand —
alleen doen als een gedragswijziging BEWUST is).

De Hegemone-taalmigratie heeft de presentatie bewust op Engels en een vaste
publieke voorbeeld-URL gepind. Bij regeneratie worden de actieprefixen van alle
bestaande combinaties vergeleken voordat hashes worden vervangen. Een aparte
controle bewaakt actie-/protocolpariteit tussen Engels en Nederlands.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest
from pathlib import Path

from betonning import webhooks

GOLDEN = Path(__file__).with_suffix(".json")


@pytest.fixture(autouse=True)
def stable_presentation(monkeypatch):
    """De oracle gebruikt de publieke default, zonder deployment-afhankelijkheid."""
    monkeypatch.setenv("HEGEMONE_LANGUAGE", "en")
    monkeypatch.setenv("HEGEMONE_PUBLIC_URL", "https://tickets.example.org")

HANDLE = "smid"

TTYPES = ("mention", "assigned", "participant", "subscribe_all")

# Alle event-types die de berekening onderscheidt, plus een "gewoon" event en
# `None` (handmatig samengestelde trigger, zoals in de pure unit-tests).
EVENT_TYPES = (
    None,
    "comment.created",
    "comment.updated",
    "question.answered",
    "item.locked",
    "item.archived",
    "item.moved",
    "item.updated",
    "relation.created",
    "relation.deleted",
)

# None = geen adressering (niet-comment-event), [] = ongerichte comment,
# [HANDLE] = aan mij gericht, ["ander"] = aan iemand anders (only_reading).
ADDRESSED = (None, [], [HANDLE], ["ander"])

RELATION_TYPES = (None, "blocked_by", "duplicate_of", "blocks", "duplicated_by")

# `changed_fields`-varianten mét de bijbehorende richtingsignalen. De sleutel is
# een label voor de leesbaarheid van de golden-file.
CHANGED_VARIANTS: tuple[tuple[str, dict], ...] = (
    ("no_changed_fields", {}),
    ("changed_empty", {"changed_fields": []}),
    ("assignee_to_me", {"changed_fields": ["assignee"], "assignee_changed_to_me": True}),
    (
        "assignee_from_me",
        {"changed_fields": ["assignee"], "assignee_changed_from_me": True},
    ),
    ("assignee_other", {"changed_fields": ["assignee"]}),
    ("state_completed", {"changed_fields": ["state"], "to_state_grp": "completed"}),
    ("state_cancelled", {"changed_fields": ["state"], "to_state_grp": "cancelled"}),
    (
        "state_unblocked",
        {"changed_fields": ["state"], "to_state_grp": "todo", "work_unblocked": True},
    ),
    ("state_plain", {"changed_fields": ["state"], "to_state_grp": "todo"}),
    ("labels_only", {"changed_fields": ["labels"]}),
    # De DOORVAL: `assignee` wijzigde wél, maar niet naar/van mij — dan doet de
    # veldladder `continue` en beslist alsnog op `state`. De assignee-rij
    # TERMINEERT dus niet. Dit is precies het gedrag dat een sleutel op een
    # enkel "dominant veld" niet kan uitdrukken: welk veld domineert hangt af
    # van de UITKOMST van de sub-conditie, niet van de aanwezigheid van het veld.
    (
        "assignee_other_state_completed",
        {"changed_fields": ["assignee", "state"], "to_state_grp": "completed"},
    ),
    (
        "assignee_other_state_unblocked",
        {
            "changed_fields": ["assignee", "state"],
            "to_state_grp": "todo",
            "work_unblocked": True,
        },
    ),
    # BETON-291: rangorde bij meerdere velden in één event — assignee wint.
    (
        "assignee_and_state",
        {
            "changed_fields": ["assignee", "state"],
            "assignee_changed_to_me": True,
            "to_state_grp": "completed",
        },
    ),
)

# `work_unblocked` op trigger-niveau zonder `changed_fields` (de vrijgave-fanout
# van `api/items.py`, die ook niet-assignees notificeert).
TOPLEVEL_UNBLOCKED = (False, True)

ACCESS_LEVELS = (None, "respond", "assign")


def _item(is_assignee: bool, has_plan: bool) -> dict:
    return {
        "ref": "BETON-1",
        "project": "BETON",
        "seq": 1,
        "assignee": HANDLE if is_assignee else "iemand-anders",
        "has_plan": has_plan,
    }


def _relevant_relation_types(event_type: str | None) -> tuple[str | None, ...]:
    if event_type in ("relation.created", "relation.deleted"):
        return RELATION_TYPES[1:]
    return (None,)


def _relevant_changed(event_type: str | None) -> tuple[tuple[str, dict], ...]:
    # `changed_fields` wordt alleen door `_changed_fields_signal` gezet bij
    # item.updated; andere events dragen het nooit.
    if event_type == "item.updated":
        return CHANGED_VARIANTS
    return (CHANGED_VARIANTS[0],)


def iter_cases():
    """Yield `(case_id, kwargs)` voor elke bereikbare combinatie."""
    for ttype in TTYPES:
        for event_type in EVENT_TYPES:
            for addressed in ADDRESSED:
                is_comment = event_type in ("comment.created", "comment.updated")
                if is_comment:
                    # Bij comment-events zet `build_trigger` altijd een lijst.
                    if addressed is None:
                        continue
                elif addressed is not None and addressed != ["ander"]:
                    # `build_trigger` zet `addressed_to` alleen bij comment-
                    # events, dus in productie is `only_reading` bij een ander
                    # event-type onbereikbaar. We pinnen die combinatie tóch
                    # (alleen de only_reading-variant), want juist DAAR ligt de
                    # precedentievraag "ownership vóór only_reading?" — zonder
                    # deze rijen kan een refactor die volgorde stilzwijgend
                    # omdraaien zonder dat één test omvalt. `build_instructions`
                    # is een pure functie; wat onbereikbaar is via de huidige
                    # caller kan het morgen zijn.
                    continue
                for relation_type in _relevant_relation_types(event_type):
                    for changed_label, changed in _relevant_changed(event_type):
                        for unblocked in TOPLEVEL_UNBLOCKED:
                            # `work_unblocked` zit al in de changed-variant;
                            # niet dubbel zetten.
                            if unblocked and "work_unblocked" in changed:
                                continue
                            for is_assignee in (False, True):
                                # `type == "assigned"` betekent per constructie
                                # dat de ontvanger de assignee is.
                                if ttype == "assigned" and not is_assignee:
                                    continue
                                for work_allowed in (True, False):
                                    for access_level in ACCESS_LEVELS:
                                        for has_plan in (False, True):
                                            trigger = {
                                                "type": ttype,
                                                "addressed_to": addressed,
                                                "relation_type": relation_type,
                                                "mentioned_in": (
                                                    "comment"
                                                    if addressed is not None
                                                    else None
                                                ),
                                            }
                                            trigger.update(changed)
                                            if unblocked:
                                                trigger["work_unblocked"] = True
                                            case_id = "|".join(
                                                [
                                                    ttype,
                                                    str(event_type),
                                                    f"addr={addressed}",
                                                    f"rel={relation_type}",
                                                    changed_label,
                                                    f"unblocked={unblocked}",
                                                    f"assignee={is_assignee}",
                                                    f"work={work_allowed}",
                                                    f"access={access_level}",
                                                    f"plan={has_plan}",
                                                ]
                                            )
                                            yield case_id, {
                                                "trigger": trigger,
                                                "item": _item(is_assignee, has_plan),
                                                "event_type": event_type,
                                                "work_allowed": work_allowed,
                                                "access_level": access_level,
                                            }


def run_case(kwargs: dict) -> dict | None:
    user = {"handle": HANDLE}
    agent_policy = {"work_allowed": kwargs["work_allowed"], "state": "todo"}
    return webhooks.build_instructions(
        user,
        kwargs["item"],
        kwargs["trigger"],
        agent_policy,
        event_type=kwargs["event_type"],
        access_level=kwargs["access_level"],
    )


def fingerprint(out: dict | None) -> str:
    """`expected_action` leesbaar + een hash over de VOLLEDIGE outputdict.

    De ruwe dicts opslaan zou een golden-file van ~7 MB opleveren (de
    `instructions`/`reply`-teksten zijn lang en zeer repetitief). De hash dekt
    álle velden — `instructions`, `do`, `do_not`, `read`, `reply` — dus de
    oracle is even streng, terwijl de leesbare actie ervoor zorgt dat een diff
    in code-review meteen laat zien wélke tak van gedrag veranderde.
    """
    blob = json.dumps(out, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(blob.encode()).hexdigest()[:16]
    action = out["expected_action"] if out else "None"
    return f"{action}:{digest}"


def build_snapshot() -> dict:
    return {case_id: fingerprint(run_case(kwargs)) for case_id, kwargs in iter_cases()}


def test_matrix_matches_golden():
    """Bit-identieke Engelse presentatie met de gereviewde publieke voorbeeld-URL."""
    expected = json.loads(GOLDEN.read_text())
    actual = build_snapshot()
    assert set(actual) == set(expected), "de set combinaties is gewijzigd"
    diffs = [k for k in expected if actual[k] != expected[k]]
    assert not diffs, f"{len(diffs)} combinaties wijken af, bv.: {diffs[:5]}"


def test_matrix_is_substantial():
    """Vangnet: als de enumeratie stilletjes leegloopt is de oracle waardeloos."""
    cases = list(iter_cases())
    assert len(cases) > 1000
    actions = {run_case(kw)["expected_action"] for _, kw in cases}
    # Alle zes actiewaarden moeten bereikt worden — anders dekt de matrix een
    # tak niet af (BETON-293 voegde `stand_down` toe, BETON-280 `answered`).
    assert actions == {
        "none",
        "respond",
        "pick_up",
        "acknowledge",
        "answered",
        "stand_down",
    }


def test_mention_respond_is_not_work_gated():
    """BETON-292/BRAND-150-val: `work_allowed` moduleert NIET uniform.

    `mention → respond` is onvoorwaardelijk, maar `assigned` + comment-event is
    wél work-gated. Een refactor die één generieke `respond → acknowledge`-
    downgrade aan het eind toepast, breekt precies deze asymmetrie stil.
    """
    base = {
        "item": _item(is_assignee=True, has_plan=False),
        "event_type": "comment.created",
        "access_level": None,
    }
    mention = run_case(
        {
            **base,
            "trigger": {"type": "mention", "addressed_to": [HANDLE]},
            "work_allowed": False,
        }
    )
    assert mention["expected_action"] == "respond"

    assigned = run_case(
        {
            **base,
            "trigger": {"type": "assigned", "addressed_to": []},
            "work_allowed": False,
        }
    )
    assert assigned["expected_action"] == "acknowledge"


def test_language_preserves_every_matrix_action_and_protocol(monkeypatch):
    """Taal mag geen opdracht, verbodsomvang of concrete tool-/replyroute wijzigen."""
    for case_id, kwargs in iter_cases():
        monkeypatch.setenv("HEGEMONE_LANGUAGE", "en")
        english = run_case(kwargs)
        monkeypatch.setenv("HEGEMONE_LANGUAGE", "nl")
        dutch = run_case(kwargs)
        assert english.keys() == dutch.keys(), case_id
        assert english["expected_action"] == dutch["expected_action"], case_id
        assert len(english["do_not"]) == len(dutch["do_not"]), case_id
        assert [step["hoe"] for step in english["read"]] == [step["hoe"] for step in dutch["read"]], case_id
        for key in ("ref", "url", "item_url", "item_api_url"):
            assert english["reply"].get(key) == dutch["reply"].get(key), case_id


if __name__ == "__main__":  # pragma: no cover - handmatige regeneratie
    os.environ["HEGEMONE_LANGUAGE"] = "en"
    os.environ["HEGEMONE_PUBLIC_URL"] = "https://tickets.example.org"
    snapshot = build_snapshot()
    previous = json.loads(GOLDEN.read_text())
    if set(snapshot) != set(previous) or any(
        snapshot[key].split(":", 1)[0] != previous[key].split(":", 1)[0] for key in previous
    ):
        raise SystemExit("Actiecontract gewijzigd; aparte review nodig vóór regeneratie")
    GOLDEN.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(snapshot)} combinaties bijgewerkt; alle actie-uitkomsten behouden")
