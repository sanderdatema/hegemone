"""Pydantic request-modellen voor de API. Responses zijn plain dicts uit repo."""

from __future__ import annotations

import re

from typing import Literal, get_args

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

Priority = Literal["urgent", "high", "medium", "low", "none"]
# BETON-311: werklast (hoeveel tokens een ticket kost). Interne waarden Engels;
# de UI toont licht/middel/zwaar.
Workload = Literal["light", "medium", "heavy"]
StateGroup = Literal["backlog", "unstarted", "started", "completed", "cancelled"]

# BETON-327: enige bron voor de toegestane waarden — afgeleid uit de Literals
# hierboven i.p.v. los onderhouden tuples/frozensets elders (repo/items.py,
# triage_commands.py).
PRIORITIES: tuple[str, ...] = get_args(Priority)
WORKLOADS: tuple[str, ...] = get_args(Workload)


# --- Guardrails (BETON-420) ------------------------------------------------
#
# Een guardrail is kennis die niet in een regressietest past en die elke agent
# hierna moet naleven. Hij kost elke agent tokens, elke ronde — vandaar een
# harde tekencap, een plafond op het aantal projectbrede, en een verplichte
# reviewdatum.
#
# De rekensom achter de twee getallen: 5 projectbrede × 1000 tekens ≈ 5.000
# tekens plus koppen, tegen `wiki.DEFAULT_CONTEXT_BUDGET = 12000`. Guardrails
# claimen dan hooguit ~42% van het contextbudget en laten de wiki ruimte.
# 1000 tekens is ruim voor drie zinnen wat/waarom/wat-te-doen en te krap voor
# een verhandeling — de cap ÍS de drempel.
GUARDRAIL_MAX_CHARS = 1000
GUARDRAIL_PROJECT_WIDE_MAX = 5
# Horizon voor een reviewdatum die niet door een mens is meegegeven (activeren
# via een vraagmodule-antwoord kan er geen dragen).
GUARDRAIL_DEFAULT_REVIEW_DAYS = 90


class GuardrailIn(BaseModel):
    """Een guardrail zetten of wijzigen (mens-only)."""

    guardrail_md: str
    review_by: str  # ISO-datum YYYY-MM-DD
    scope_labels: list[str] = []  # lege lijst = projectbreed


# De twee soorten voorstel (BETON-422). Volgorde/spelling zijn contract: ze
# staan zo in de kolom-CHECK van migratie 042.
GUARDRAIL_PROPOSAL_KINDS = ("set", "lift")


class GuardrailProposalIn(BaseModel):
    """Een guardrail-wijziging VOORSTELLEN als concept (mag een agent).

    Een concept staat NAAST de actieve versie en bindt niets: tot een mens het
    goedkeurt blijft de actieve guardrail onverkort gelden. `kind="set"` stelt
    een nieuwe tekst/scope/reviewdatum voor (ook om een actieve te wijzigen),
    `kind="lift"` stelt voor de actieve guardrail op te heffen — dán is `reason`
    verplicht en wordt de rest genegeerd.
    """

    kind: str = "set"
    guardrail_md: str = ""
    scope_labels: list[str] = []  # lege lijst = projectbreed
    review_by: str | None = None  # ISO-datum; leeg = default-horizon bij goedkeuren
    reason: str = ""  # verplicht bij kind="lift"


class ProjectCreate(BaseModel):
    key: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=60000)

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        """Hetzelfde alfabet als de projectkiezer en ref-routes (BETON-502)."""
        key = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{1,20}", key):
            raise ValueError("Projectkey moet 1-20 letters of cijfers bevatten")
        return key



class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, max_length=60000)


class TriageOptIn(BaseModel):
    enabled: bool


class UnlockIn(BaseModel):
    """Ruimte die het gesprek na het ontgrendelen krijgt (BETON-338).

    Een whitelist van drie waarden, geen vrij getal: een typefout als 500 zou
    de noodstop effectief uitschakelen — precies de storing die het mechanisme
    moet voorkomen. Buiten de lijst → 422."""

    headroom: Literal[5, 10, 20] = 5


class AccessLevelUpdate(BaseModel):
    # None = "inherit": wis de override/default en val terug op de laag eronder
    # (BETON-123). 'none'/'respond'/'assign' zetten expliciet een niveau.
    level: Literal["none", "respond", "assign"] | None = None


class TriageChatMessage(BaseModel):
    message: str = Field(min_length=1, max_length=12000)


class TriageChatConfirm(BaseModel):
    # Boven de veiligheidsdrempel moet de mens het aantal typen (bulk-rem).
    typed_count: int | None = None


class WikiPageCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    body_md: str = Field(default="", max_length=60000)


class WikiPageUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    body_md: str | None = Field(default=None, max_length=60000)


class StateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    group: StateGroup
    color: str = "#95a5a6"
    sort_order: int = 0
    is_default: bool = False
    closed: bool = False
    blocks_work: bool = False


class StateUpdate(BaseModel):
    """Bewerkbare metadata van een bestaande state."""

    name: str | None = Field(default=None, min_length=1)
    color: str | None = None
    sort_order: int | None = None
    blocks_work: bool | None = None


class ItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description_md: str = Field(default="", max_length=60000)
    state: str | None = None  # state-naam
    priority: Priority = "none"
    # BETON-311: geschatte werklast (tokens), leeg = nog niet geschat.
    workload: Workload | None = Field(
        default=None,
        description=(
            "Geschatte werklast: light/medium/heavy. Een inschatting van de "
            "TOKENkosten om dit ticket uit te voeren — GEEN tijdsinschatting "
            "('een uur'/'een dag' is hier zinloos). Vul dit in bij elk ticket "
            "dat je aanmaakt, behalve mens-toewijzingen; leeg laten → triage "
            "schat het."
        ),
    )
    assignee: str | None = None  # user-handle
    parent: str | None = None  # ref, bv. "SOS-1"
    milestone: str | None = None  # milestone-naam
    due_date: str | None = None  # ISO-datum (YYYY-MM-DD), streefdatum
    deferred_until: str | None = None  # ISO-datum, uitstellen tot (BETON-212)
    labels: list[str] = []  # bestaande labelnamen (BETON-188)
    # Plan/handover (BETON-430): optioneel meegeven bij aanmaken, zodat een
    # ticket niet eerst zonder plan bestaat. Zelfde veld als bij PATCH.
    plan_md: str | None = Field(default=None, max_length=60000)


class CommentCreate(BaseModel):
    # BETON-426: een onbekend veld geeft 422 i.p.v. stil te verdwijnen.
    model_config = ConfigDict(extra="forbid")

    body_md: str = Field(min_length=1, max_length=60000)
    # Vraagmodule (BETON-219): kind='question' + optionele meerkeuze-opties.
    kind: Literal["comment", "question"] = "comment"
    # `question_options` is de naam in het antwoord; die mag hier ook (BETON-426).
    options: list[str] | None = Field(
        default=None, validation_alias=AliasChoices("options", "question_options")
    )


class CommentUpdate(BaseModel):
    body_md: str = Field(min_length=1, max_length=60000)


class AnswerCreate(BaseModel):
    """Antwoord op een vraag-comment (BETON-219): precies één van beide."""

    text: str | None = Field(default=None, min_length=1)
    option_index: int | None = None


class QuestionWithdraw(BaseModel):
    """Een vraag intrekken (BETON-454): de reden is verplicht."""

    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("reden mag niet leeg zijn")
        return v


class LabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    color: str = "#95a5a6"


class LabelUpdate(BaseModel):
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class ItemMove(BaseModel):
    project: str = Field(min_length=1)  # doel-project-key, bv. "SOS"


class MilestoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    due_date: str | None = None


class MilestoneUpdate(BaseModel):
    status: Literal["open", "completed"] | None = None
    due_date: str | None = None


RelationType = Literal[
    "blocks", "blocked_by", "duplicate_of", "duplicated_by", "relates_to"
]


class RelationCreate(BaseModel):
    type: RelationType
    target: str  # ref van het gerelateerde item, bv. "SOS-2"


class ItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description_md: str | None = Field(default=None, max_length=60000)
    state: str | None = None
    priority: Priority | None = None
    # BETON-311: werklast (tokenkosten, GEEN tijd); null → wis (nog niet geschat).
    workload: Workload | None = Field(
        default=None,
        description=(
            "Geschatte werklast light/medium/heavy — de TOKENkosten om dit "
            "ticket uit te voeren, geen tijdsinschatting. null wist (nog niet "
            "geschat)."
        ),
    )
    assignee: str | None = None  # "" of null → wis assignee
    # BETON-469: korte, verplichte aanleiding bij agent → mens.
    handover_md: str | None = Field(default=None, min_length=1, max_length=300)

    @field_validator("handover_md", mode="before")
    @classmethod
    def validate_handover(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if not value or "\n" in value or "\r" in value:
                raise ValueError("Schrijf handover_md als één korte alinea")
        return value

    parent: str | None = None
    milestone: str | None = None
    labels: list[str] | None = None  # volledige vervanging van de labelset
    # Uitstellen (BETON-39): ISO-datum → item naar de deferred-state; "" of null wist.
    deferred_until: str | None = None
    # Streefdatum (BETON-53): ISO-datum (YYYY-MM-DD); "" of null wist. Puur
    # informatief/filterbaar — géén state-flip (anders dan deferred_until).
    due_date: str | None = None
    # Plan/handover (BETON-218): markdown-werkplan, los van de omschrijving.
    # "" of null wist. Zit bewust niet in de item-serialisatie (alleen
    # `has_plan`); ophalen via GET /items/{ref}/plan.
    plan_md: str | None = Field(default=None, max_length=60000)
    # Optimistic concurrency (BETON-44): als gezet moet het gelijk zijn aan het
    # actuele updated_at, anders 409. Alternatief: de If-Match-header.
    expected_updated_at: str | None = None
