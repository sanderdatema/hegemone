"""Betonning MCP-server: exposeert de LLM-wiki (memory-provider) aan MCP-native
agents zoals Claude Code en de Hermes-agents (BETON-24).

De server praat via de REST-API met Betonning. Twee transports uit één codebase:

- **stdio** (lokaal, bv. Claude Code op de MacBook): de key komt uit de env
  (`BETONNING_API_KEY`) of het `bt`-configbestand.
- **streamable-http** (service op de LXC): elke agent stuurt z'n *eigen*
  `Authorization: Bearer <key>` mee; die wordt per request doorgegeven aan de
  REST-API, zodat Betonning ziet wélke agent de call deed (attributie).

Config: `BETONNING_BASE_URL` (+ evt. `BETONNING_API_KEY`) via env, of
`~/.config/betonning/config.json`. Transport via `BETONNING_MCP_TRANSPORT`
(`stdio`|`streamable-http`) + `BETONNING_MCP_HOST`/`BETONNING_MCP_PORT`.

De tool-docstrings zijn bewust beschrijvend: dát is wat de agent te zien krijgt en
hoe hij leert dat Betonning zijn geheugen is.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import httpx
from pydantic import Field
from mcp.server.fastmcp import Context

from .outbound import outbound

# Gepubliceerde protocolvolgorde; pariteit met de API wordt in tests bewaakt.
_WORK_CLASS_ORDER = ("routine", "standaard", "complex")
# Transportbudget voor inline base64; de HTTP-API valideert ook per MIME-type.
MAX_INLINE_ATTACHMENT_BYTES = 10 * 1024 * 1024

DEFAULT_CONFIG_PATH = "~/.config/betonning/config.json"


def _config() -> dict:
    """base_url + (optionele) api_key uit env of het bt-configbestand.

    Bij de http-service is er géén vaste key (die komt per request binnen); dan
    volstaat `BETONNING_BASE_URL`. api_key mag dus None zijn."""
    base = os.environ.get("BETONNING_BASE_URL")
    key = os.environ.get("BETONNING_API_KEY")
    cfg: dict = {}
    if not base or not key:
        # Het configbestand is optioneel: bij de HTTP-service komt base_url uit de
        # env en de key per request, en staat het (onleesbare) home onder
        # ProtectHome. Een lees-/permissiefout mag de tool dus niet breken.
        path = Path(
            os.environ.get("BETONNING_CONFIG", DEFAULT_CONFIG_PATH)
        ).expanduser()
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            cfg = {}
    return {
        "base_url": base or cfg.get("base_url") or "http://127.0.0.1",
        "api_key": key or cfg.get("api_key"),
    }


def _incoming_key(ctx: Context | None) -> str | None:
    """De per-request Bearer-key uit de inkomende HTTP-Authorization-header (of
    None bij stdio / geen header)."""
    if ctx is None:
        return None
    try:
        request = ctx.request_context.request  # Starlette Request bij http-transport
        auth = request.headers.get("authorization") if request is not None else None
    except Exception:  # noqa: BLE001 — geen request-context (stdio) → geen header
        auth = None
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _is_http(ctx: Context | None) -> bool:
    """Draait deze call op het http-transport (er is een inkomende request)?"""
    if ctx is None:
        return False
    try:
        return ctx.request_context.request is not None
    except Exception:  # noqa: BLE001 — geen request-context → stdio
        return False


def _resolve_key(ctx: Context | None = None) -> str:
    """De API-key voor deze call.

    Op het **http**-transport is de per-request header de enige bron (BETON-381):
    de service-key uit `_config()` mag daar nooit invallen, want dan zou een
    request zónder header stilletjes als de service-user handelen — verkeerde
    attributie en een gat in de auth. Op **stdio** (lokale Claude Code) is er per
    definitie geen header en blijft de geconfigureerde key de bron.

    Dit is de tweede laag: de mount in `server.py` weigert een header-loze
    HTTP-request al met 401, dus hier komt er in de praktijk geen langs.
    """
    if _is_http(ctx):
        key = _incoming_key(ctx)
        if not key:
            raise RuntimeError(
                "Geen Authorization: Bearer-header. De MCP-server over http "
                "gebruikt uitsluitend de key van de aanroepende agent."
            )
        return key
    key = _config().get("api_key")
    if not key:
        raise RuntimeError(
            "Geen API-key: stuur een Authorization: Bearer <key> mee of zet "
            "BETONNING_API_KEY / het bt-configbestand."
        )
    return key


def _client(key: str) -> httpx.AsyncClient:
    """Async HTTP-client naar de Betonning-API met de opgegeven key. Test-seam.

    Async is bewust: bij de in-de-app-gemounte MCP draait de tool in dezelfde
    event-loop als de API; een sync (blokkerende) call zou de loopback naar de
    eigen app laten deadlocken. Async laat de loop de zelf-call concurrent bedienen.
    """
    return httpx.AsyncClient(
        base_url=_config()["base_url"].rstrip("/"),
        headers={"Authorization": f"Bearer {key}"},
        timeout=15.0,
    )


def _wiki_base(project: str | None) -> str:
    return "/api/v1/wiki" if not project else f"/api/v1/projects/{project}/wiki"


def _nice_http_error(exc: httpx.HTTPStatusError) -> RuntimeError:
    """Vertaal een REST-fout naar een leesbare RuntimeError met de server-detail,
    zodat de agent een nette boodschap ziet i.p.v. een kale stacktrace."""
    detail: object
    try:
        detail = exc.response.json().get("detail")
    except Exception:  # noqa: BLE001 — geen JSON-body → val terug op de ruwe tekst
        detail = exc.response.text
    return RuntimeError(f"Betonning API {exc.response.status_code}: {detail}")


async def _api(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    resp = await client.request(method, path, **kwargs)
    resp.raise_for_status()
    return resp.json() if resp.content else None


async def _call(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    """`_api` met foutvertaling: onbekende ref/validatie → nette RuntimeError."""
    try:
        return await _api(client, method, path, **kwargs)
    except httpx.HTTPStatusError as exc:
        raise _nice_http_error(exc) from exc


# --- Tool-implementaties (async thin wrappers om de REST-API) --------------


async def load_memory(project: str | None = None, ctx: Context | None = None) -> str:
    """Laad je persistente geheugen (wiki) als markdown, aan het begin van een taak.
    Zonder ``project``: globaal; met project-key: globaal + project. Bovenaan
    kunnen bindende GUARDRAILS van het project staan: lees ze vóór je werkt.
    """
    async with _client(_resolve_key(ctx)) as client:
        resp = await client.get(f"{_wiki_base(project)}/context")
        resp.raise_for_status()
        return resp.text


async def list_memory_pages(
    project: str | None = None, ctx: Context | None = None
) -> list[dict]:
    """Lijst de wiki-pagina's (slug + titel) — globaal of van een project."""
    async with _client(_resolve_key(ctx)) as client:
        return await _api(client, "GET", _wiki_base(project))


async def get_memory_page(
    slug: str, project: str | None = None, ctx: Context | None = None
) -> dict:
    """Haal één wiki-pagina op (volledige inhoud)."""
    async with _client(_resolve_key(ctx)) as client:
        return await _api(client, "GET", f"{_wiki_base(project)}/{slug}")


async def set_memory(
    slug: str,
    title: str,
    body_md: str = "",
    project: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Sla iets DUURZAAMS op in je geheugen (upsert van een wiki-pagina).
    Globale/beschermde wijzigingen worden voorstellen en gelden pas na menselijke
    goedkeuring; de respons vermeldt status=pending. Projectkennis blijft direct
    bewerkbaar tenzij beschermd. ``slug`` is kebab-case; ``project`` leeg = globaal.
    Verwijderen is mens-only:
    leeg de body of markeer als verouderd.
    """
    base = _wiki_base(project)
    async with _client(_resolve_key(ctx)) as client:
        exists = (await client.get(f"{base}/{slug}")).status_code == 200
        if exists:
            return await _api(
                client,
                "PATCH",
                f"{base}/{slug}",
                json={"title": title, "body_md": body_md},
            )
        return await _api(
            client,
            "POST",
            base,
            json={"slug": slug, "title": title, "body_md": body_md},
        )


async def list_projects(ctx: Context | None = None) -> list[dict]:
    """Lijst de Betonning-projecten (key + naam) — handig om de scope te kiezen."""
    async with _client(_resolve_key(ctx)) as client:
        return await _api(client, "GET", "/api/v1/projects")


async def search_tickets(
    query: str, limit: int = 10, ctx: Context | None = None
) -> list[dict]:
    """Zoek in de tickets (full-text, cross-project) — bredere werkgeheugen-context.

    Zoekt in titel, omschrijving én comments. Een treffer die alleen in een
    reactie zit draagt `matched_in="comment"` plus het `comment_id`.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _api(
            client, "GET", "/api/v1/search", params={"q": query, "limit": limit}
        )


# --- Ticket-tools (thin wrappers om de items-REST-API, BETON-45) -----------


async def list_items(
    project: str,
    state: str | None = None,
    assignee: str | None = None,
    label: str | None = None,
    query: str | None = None,
    limit: int | None = None,
    ctx: Context | None = None,
) -> list[dict]:
    """Lijst de tickets van een project (compact), gefilterd op ``state``,
    ``assignee`` (handle), ``label`` en/of vrije ``query``. ``todo`` = vrij.
    ``has_plan`` true: plan via ``get_item`` (``get_plan`` voor een lang plan).
    """
    params: dict = {}
    if state is not None:
        params["state"] = state
    if assignee is not None:
        params["assignee"] = assignee
    if label is not None:
        params["label"] = label
    if query is not None:
        params["q"] = query
    if limit is not None:
        params["limit"] = limit
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client, "GET", f"/api/v1/projects/{project}/items", params=params
        )


PLAN_INLINE_MAX = 20_000  # BETON-430: tekens plan_md die get_item inline meegeeft


async def get_item(ref: str, ctx: Context | None = None) -> dict:
    """Haal één ticket volledig op (comments, relaties, subtaken, plan).

    ``ref`` is bv. ``SOS-42``. Bij ``has_plan`` komt het plan inline als
    ``plan_md`` (afgekapt op 20.000 tekens; ``get_plan`` geeft de rest): lees het
    vóór je begint. ``guardrail_md`` en ``applicable_guardrails`` zijn BINDEND;
    projectbrede guardrails komen via ``load_memory``. ``model_for_you`` is de
    werkklasse van het ticket (routine/standaard/complex) vertaald naar het model
    dat bij jouw harnas hoort; ``null`` als er geen klasse of geen mapping is.
    """
    async with _client(_resolve_key(ctx)) as client:
        item = await _call(client, "GET", f"/api/v1/items/{ref}")
        if item.get("has_plan"):
            plan = (await _call(client, "GET", f"/api/v1/items/{ref}/plan")).get(
                "plan_md"
            )
            if plan:
                if len(plan) > PLAN_INLINE_MAX:
                    plan = (
                        plan[:PLAN_INLINE_MAX]
                        + f"\n\n[… plan afgekapt na {PLAN_INLINE_MAX} van "
                        f"{len(plan)} tekens — volledige tekst: get_plan(\"{ref}\")]"
                    )
                item["plan_md"] = plan
        item["model_for_you"] = await _model_for_you(client, item)
        return item


async def _model_for_you(client: httpx.AsyncClient, item: dict) -> dict | None:
    """Werkklasse van het ticket vertaald naar het model van de aanroepende
    harnas (BETON-476): ``{"class", "model"}``, of ``None`` als het ticket geen
    klasse heeft of de aanroeper geen harnas met een mapping is (bv. een mens
    of een Hermes-agent). Harnas = de handle (claude, codex)."""
    me = await _me(client)
    if me.get("kind") == "human":
        return None
    # Zwaarste klasse wint, zoals `model_classes.class_of_item` server-side.
    labels = item.get("labels") or []
    cls = next((c for c in reversed(_WORK_CLASS_ORDER) if c in labels), None)
    if cls is None:
        return None
    settings = await _call(client, "GET", "/api/v1/settings/model-classes")
    model = settings.get("mapping", {}).get(me.get("handle"), {}).get(cls)
    return {"class": cls, "model": model} if model else None


async def get_plan(ref: str, ctx: Context | None = None) -> dict:
    """Haal het volledige plan/handover van een ticket op (BETON-218).

    Een zwaarder model kan een gedetailleerd werkplan op een ticket zetten
    (via ``create_item`` of ``update_item`` met ``plan_md``). ``get_item``
    levert het plan al inline mee (tot 20.000 tekens); gebruik ``get_plan``
    alleen voor de volledige tekst van een langer plan, of om het plan zonder
    de rest van het ticket op te halen. ``plan_md`` is ``null`` als er geen
    plan is (zie ``has_plan`` in ``get_item``)."""
    async with _client(_resolve_key(ctx)) as client:
        return await _call(client, "GET", f"/api/v1/items/{ref}/plan")


_NO_PLAN_NEXT_STEP = (
    "Dit ticket heeft nog GEEN plan. Zet het nu: update_item(\"{ref}\", "
    "plan_md=...) met stappen, te wijzigen bestanden, tests, verificatie en "
    "commit-granulariteit. Doe het vóór de eerste comment: daarna ligt plan_md "
    "vast (BETON-301)."
)

_NO_PLAN_COMMENT_WARNING = (
    "Dit is de eerste comment op een ticket dat jij aanmaakte zonder plan. "
    "plan_md ligt nu vast (BETON-301) en kan door een agent niet meer gezet "
    "worden; laat een mens het plan aanvullen als het nodig is. "
    "Maak een volgend ticket mét plan_md in de create_item-call zelf."
)


_ME_TTL = 300.0  # BETON-467: seconden dat GET /me per key onthouden wordt
_ME_CACHE: dict[str, tuple[float, dict]] = {}


async def _me(client: httpx.AsyncClient) -> dict:
    """Wie ben ik? Per key gecachet (kind/handle veranderen praktisch nooit),
    zodat create_item/comment_item niet elke keer een extra GET /me doen."""
    key = client.headers.get("Authorization", "")
    now = time.monotonic()
    hit = _ME_CACHE.get(key)
    if hit is not None and now - hit[0] < _ME_TTL:
        return hit[1]
    me = await _call(client, "GET", "/api/v1/me")
    if len(_ME_CACHE) > 256:
        _ME_CACHE.clear()
    _ME_CACHE[key] = (now, me)
    return me


async def _is_human(client: httpx.AsyncClient) -> bool:
    return (await _me(client)).get("kind") == "human"


async def create_item(
    project: str,
    title: str,
    description_md: str = "",
    state: str | None = None,
    priority: str | None = None,
    workload: str | None = None,
    assignee: str | None = None,
    parent: str | None = None,
    milestone: str | None = None,
    due_date: str | None = None,
    labels: list[str] | None = None,
    plan_md: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Maak een nieuw ticket in een project aan.

    ``project`` is de key (bv. ``SOS``). ``assignee`` = handle, ``parent`` = ref,
    ``due_date`` = ``YYYY-MM-DD``, ``labels`` = labelnamen. Kies voor agentwerk
    precies één werkklasse: ``routine``, ``standaard`` of ``complex``; geen modelnamen.

    ``workload``: ``light``/``medium``/``heavy`` = geschatte **tokenkosten** van
    het uitvoeren, NIET tijd (geen uren/dagen/weken). Vul in, behalve bij
    toewijzing aan een mens. ``priority`` wordt uitgefaseerd.

    ``plan_md``: geef het plan (stappen, bestanden, tests, verificatie, commits)
    mee in deze call; zonder plan bevat het antwoord een ``next_step``. De
    omschrijving is wat/waarom, het plan is hoe (BETON-301: daarna ligt het vast).
    """
    body: dict = {"title": title, "description_md": description_md}
    if state is not None:
        body["state"] = state
    if priority is not None:
        body["priority"] = priority
    if workload is not None:
        body["workload"] = workload
    if assignee is not None:
        body["assignee"] = assignee
    if parent is not None:
        body["parent"] = parent
    if milestone is not None:
        body["milestone"] = milestone
    if due_date is not None:
        body["due_date"] = due_date
    if plan_md is not None:
        body["plan_md"] = plan_md
    async with _client(_resolve_key(ctx)) as client:
        item = await _call(
            client, "POST", f"/api/v1/projects/{project}/items", json=body
        )
        if labels is not None:
            item = await _call(
                client, "PATCH", f"/api/v1/items/{item['ref']}", json={"labels": labels}
            )
        if not await _is_human(client):
            steps = []
            if not item.get("has_plan"):
                steps.append(_NO_PLAN_NEXT_STEP.format(ref=item["ref"]))
            classes = {name.lower() for name in item.get("labels", [])} & {"routine", "standaard", "complex"}
            if len(classes) != 1:
                steps.append("Kies precies één werkklasselabel: routine, standaard of complex. "
                             "Gebruik geen modelnamen als labels; de modelkeuze volgt uit de harnasmapping.")
            if steps:
                item["next_step"] = "\n\n".join(steps)
        return item


async def update_item(
    ref: str,
    title: str | None = None,
    description_md: str | None = None,
    state: str | None = None,
    priority: str | None = None,
    workload: str | None = None,
    assignee: str | None = None,
    parent: str | None = None,
    milestone: str | None = None,
    labels: list[str] | None = None,
    deferred_until: str | None = None,
    due_date: str | None = None,
    plan_md: str | None = None,
    handover_md: Annotated[str, Field(min_length=1, max_length=300)] | None = None,
    ctx: Context | None = None,
) -> dict:
    """Werk velden van een ticket bij; alleen meegegeven velden wijzigen.

    ``labels`` vervangt de hele set (voor één label: ``add_label``/
    ``remove_label``). ``workload`` = tokenkosten, geen tijd. ``deferred_until``
    en ``due_date`` zijn ISO-datums. ``plan_md`` = plan/handover (lezen: ``get_plan``). Een lege string
    wist ``state``/``assignee``/``parent``/``milestone``/``deferred_until``/
    ``due_date``/``plan_md``.

    Agent → mens: geef ``handover_md`` mee (één alinea, max 300 tekens) of stel
    eerst een ``ask_question`` met een expliciete ``@handle`` van die mens.
    Zonder zo’n mention richt de vraag zich op de huidige assignee.
    Na de eerste comment liggen ``description_md`` en
    ``plan_md`` vast voor agents (409, BETON-301).
    """
    body: dict = {}
    for key, value in (
        ("title", title),
        ("description_md", description_md),
        ("state", state),
        ("priority", priority),
        ("workload", workload),
        ("assignee", assignee),
        ("parent", parent),
        ("milestone", milestone),
        ("labels", labels),
        ("deferred_until", deferred_until),
        ("due_date", due_date),
        ("plan_md", plan_md),
        ("handover_md", handover_md),
    ):
        if value is not None:
            body[key] = value
    async with _client(_resolve_key(ctx)) as client:
        return await _call(client, "PATCH", f"/api/v1/items/{ref}", json=body)


async def _set_state(ref: str, state: str, ctx: Context | None = None) -> dict:
    """Gedeelde implementatie voor ``set_state``/``move_item``: wissel de state
    (kolom) van een ticket."""
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client, "PATCH", f"/api/v1/items/{ref}", json={"state": state}
        )


async def set_state(ref: str, state: str, ctx: Context | None = None) -> dict:
    """Zet een ticket op een andere state/kolom (bv. ``in-progress`` of ``done``).

    Kortere weg dan ``update_item`` als je alleen de state wilt zetten. Zet een taak
    die je oppakt meteen op ``in-progress``, en op ``done`` als 'ie klaar is. Let op
    het onderscheid met ``transfer_item``: die verplaatst een ticket naar een ANDER
    project (BETON-183) — dit hier verandert alleen de kolom binnen hetzelfde project.
    """
    return await _set_state(ref, state, ctx)


async def move_item(ref: str, state: str, ctx: Context | None = None) -> dict:
    """DEPRECATED alias van ``set_state`` (wisselt de state, verplaatst niet naar
    een ander project; zie ``transfer_item``).
    """
    return await _set_state(ref, state, ctx)


async def comment_item(ref: str, body_md: str, ctx: Context | None = None) -> dict:
    """Plaats een comment (markdown) onder een ticket, bv. een afsluit-comment bij
    ``done`` (wat, welke bestanden, tests). ``@handle`` notificeert die persoon.
    Mensen zien comment-ID’s niet: verwijs naar auteur, datum of een kort citaat,
    zo nodig met de ticketref; gebruik interne ID’s alleen in toolargumenten.

    De antwoord kan een ``warning`` bevatten (eerste comment zonder plan,
    BETON-301) of een samenvattingshint (BETON-469); de comment wordt altijd
    geplaatst.
    """
    async with _client(_resolve_key(ctx)) as client:
        # BETON-430: de eerste comment van een agent op een eigen ticket zonder
        # plan legt plan_md vast (BETON-301) — dat melden we in het antwoord.
        # Triage-comments tellen niet mee (zelfde regel als count_for_item).
        no_plan_first = False
        me = await _me(client)
        if me.get("kind") != "human":
            item = await _call(client, "GET", f"/api/v1/items/{ref}")
            no_plan_first = (
                not item.get("has_plan")
                and item.get("created_by") == me.get("handle")
                and not any(
                    c.get("author") != "triage" for c in item.get("comments") or []
                )
            )
        comment = await _call(
            client, "POST", f"/api/v1/items/{ref}/comments", json={"body_md": body_md}
        )
        warnings = []
        if no_plan_first:
            warnings.append(_NO_PLAN_COMMENT_WARNING)
        if me.get("kind") != "human" and len(body_md) > 800:
            first = re.split(r"\n\s*\n", body_md.strip(), maxsplit=1)[0]
            if len(first) > 300:
                warnings.append("Begin met een samenvatting van 1–3 zinnen; details daaronder of in `<details>`.")
        if warnings:
            comment["warning"] = "\n".join(warnings)
        return comment


async def relate_items(
    ref: str, relation: str, target: str, ctx: Context | None = None
) -> dict:
    """Leg een relatie tussen twee tickets.

    ``relation`` is één van ``blocks``, ``blocked_by``, ``duplicate_of``,
    ``duplicated_by`` of ``relates_to``. ``ref`` is het bron-item, ``target`` het
    gerelateerde item (bv. ``SOS-9``). Leg na het aanmaken van een ticket de juiste
    relatie zodat volgorde/duplicaten expliciet zijn.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client,
            "POST",
            f"/api/v1/items/{ref}/relations",
            json={"type": relation, "target": target},
        )


async def transfer_item(ref: str, project: str, ctx: Context | None = None) -> dict:
    """Verplaats een ticket naar een ANDER project (niet te verwarren met
    ``set_state``, dat alleen de kolom wisselt).

    Het ticket krijgt een nieuwe ref; comments, relaties en bijlagen gaan mee,
    labels worden geremapt, de milestone wordt gewist en de default-state van het
    doelproject geldt. Subtaken blijven in het bronproject. 400 als het al in het
    doelproject staat.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client, "POST", f"/api/v1/items/{ref}/move", json={"project": project}
        )


# --- P1-ticket-tools (BETON-146: archive/unrelate/comments/activity) -------


async def archive_item(ref: str, ctx: Context | None = None) -> dict:
    """Archiveer een ticket (verdwijnt uit board/list/search, blijft opvraagbaar).

    ``ref`` is een item-ref zoals ``SOS-42``. Onherroepelijk verwijderen kan alleen
    een mens, via de UI (BETON-377) — deze tool archiveert altijd, nooit hard-delete.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(client, "DELETE", f"/api/v1/items/{ref}")


async def unrelate_items(
    ref: str, relation: str, target: str, ctx: Context | None = None
) -> dict:
    """Verwijder een relatie tussen twee tickets.

    ``relation`` en ``target`` zijn hetzelfde als bij ``relate_items``: geef dezelfde
    combinatie mee als bij aanmaken. ``ref`` is het bron-item.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client,
            "DELETE",
            f"/api/v1/items/{ref}/relations",
            json={"type": relation, "target": target},
        )


async def edit_comment(
    ref: str, comment_id: int, body_md: str, ctx: Context | None = None
) -> dict:
    """Bewerk een bestaand comment (alleen de eigen auteur mag dat; anders 403).

    ``ref`` is het item-ref, ``comment_id`` de id van het comment, ``body_md`` de
    nieuwe markdown-body.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client,
            "PATCH",
            f"/api/v1/items/{ref}/comments/{comment_id}",
            json={"body_md": body_md},
        )


async def delete_comment(ref: str, comment_id: int, ctx: Context | None = None) -> dict:
    """Verwijder een comment (alleen de eigen auteur mag dat; anders 403).

    ``ref`` is het item-ref, ``comment_id`` de id van het comment.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client, "DELETE", f"/api/v1/items/{ref}/comments/{comment_id}"
        )


async def list_item_activity(ref: str, ctx: Context | None = None) -> list[dict]:
    """Toon de activiteit (event-log) van een ticket — wie deed wat en wanneer.

    Handig om te begrijpen wat er al met een ticket is gebeurd vóór je het oppakt:
    statuswijzigingen, comments, relaties, mentions. ``ref`` is een item-ref.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(client, "GET", f"/api/v1/items/{ref}/activity")


async def list_project_activity(
    project: str,
    since_id: int | None = None,
    limit: int = 50,
    ctx: Context | None = None,
) -> list[dict]:
    """Activiteitenfeed van een heel project, nieuwste eerst. ``since_id`` = hoogste
    event-id dat je al zag, voor alleen nieuwere events.
    """
    params: dict = {"limit": limit}
    if since_id is not None:
        params["since"] = since_id
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client, "GET", f"/api/v1/projects/{project}/activity", params=params
        )


# Hoeveel tekens van een tekst-attachment de MCP-tool teruggeeft. Een logbestand
# mag 5 MB zijn (BETON-374); dat hoort niet ongevraagd in een contextvenster.
ATTACHMENT_TEXT_LIMIT = 50_000

# Bewust een letterlijke set en geen import uit `repo.attachments`: dit module is
# een kale HTTP-client zonder app-imports (het draait ook als losse stdio-server).
ATTACHMENT_TEXT_TYPES = {"text/plain", "application/json"}


async def get_attachment(sha256: str, ctx: Context | None = None):
    """Haal een attachment op en bekijk 'm (screenshot, logbestand, JSON).

    ``sha256`` is de content-hash uit de attachment-lijst van een ticket (het
    ``sha256``-veld, of de laatste segment van de attachment-``url``
    ``/api/v1/attachments/<sha256>``). Een afbeelding krijg je als afbeelding
    terug; tekst en JSON als tekst (afgekapt op ~50.000 tekens). Een PDF kun je
    hier niet lezen — die haal je desnoods zelf op via de REST-API. De bytes
    worden met jouw eigen Betonning-key opgehaald (dezelfde attributie als je
    andere calls).
    """
    from mcp.server.fastmcp import Image

    async with _client(_resolve_key(ctx)) as client:
        try:
            resp = await client.get(f"/api/v1/attachments/{sha256}")
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _nice_http_error(exc) from exc
    content_type = resp.headers.get("content-type", "application/octet-stream")
    base_type = content_type.split(";")[0].strip().lower()
    # Niet-afbeeldingen zijn geen `Image`: die tak maakte er `format="plain"` van
    # met tekstbytes erin (BETON-374).
    if base_type in ATTACHMENT_TEXT_TYPES:
        text = resp.content.decode("utf-8", errors="replace")
        if len(text) > ATTACHMENT_TEXT_LIMIT:
            rest = len(text) - ATTACHMENT_TEXT_LIMIT
            text = text[:ATTACHMENT_TEXT_LIMIT] + f"\n\n[afgekapt: nog {rest} tekens]"
        return text
    if not base_type.startswith("image/"):
        return (
            f"Attachment {sha256} is van het type {base_type} en kan hier niet "
            "getoond worden; haal 'm zo nodig op via "
            f"GET /api/v1/attachments/{sha256}."
        )
    # image/png → "png", image/jpeg → "jpeg"; val terug op "png" bij twijfel.
    fmt = base_type.split("/")[-1] or "png"
    return Image(data=resp.content, format=fmt)


# --- P1-config-tools (BETON-146: milestones + states) ---------------------


async def list_milestones(project: str, ctx: Context | None = None) -> list[dict]:
    """Haal een attachment op via ``sha256`` (uit de attachment-lijst van een
    ticket). Afbeeldingen komen als afbeelding, tekst/JSON als tekst (afgekapt op
    ~50.000 tekens); PDF niet leesbaar hier.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(client, "GET", f"/api/v1/projects/{project}/milestones")


async def create_milestone(
    project: str, name: str, due_date: str | None = None, ctx: Context | None = None
) -> dict:
    """Maak een nieuwe milestone aan in een project.

    ``project`` is de key, ``name`` de milestone-naam (vaak een versie zoals
    ``v1.4.0``). Optioneel ``due_date`` (ISO-datum zoals ``2026-08-01``).
    """
    body: dict = {"name": name}
    if due_date is not None:
        body["due_date"] = due_date
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client, "POST", f"/api/v1/projects/{project}/milestones", json=body
        )


async def update_milestone(
    project: str,
    name: str,
    status: str | None = None,
    due_date: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Werk een milestone bij (status en/of due_date).

    ``project`` is de key, ``name`` de milestone-naam. ``status`` is ``open`` of
    ``completed``; ``due_date`` een ISO-datum. Geef alleen de velden mee die je
    wilt wijzigen.
    """
    body: dict = {}
    if status is not None:
        body["status"] = status
    if due_date is not None:
        body["due_date"] = due_date
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client, "PATCH", f"/api/v1/projects/{project}/milestones/{name}", json=body
        )


async def list_states(project: str, ctx: Context | None = None) -> list[dict]:
    """Lijst de states (kolommen) van een project — naam, group, kleur, volgorde.

    ``project`` is de project-key (bv. ``SOS``). States bepalen de board-kolommen;
    de group (``backlog``/``unstarted``/``started``/``completed``/``cancelled``)
    stuurt de kleur en het kanban-gedrag.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(client, "GET", f"/api/v1/projects/{project}/states")


async def create_state(
    project: str,
    name: str,
    group: str,
    color: str | None = None,
    sort_order: int | None = None,
    is_default: bool = False,
    closed: bool = False,
    blocks_work: bool = False,
    ctx: Context | None = None,
) -> dict:
    """Maak een state (board-kolom) aan. ``group`` is ``backlog``/``unstarted``/
    ``started``/``completed``/``cancelled``. Optioneel: ``color`` (hex),
    ``sort_order``, ``is_default``, ``closed``, ``blocks_work``.
    """
    body: dict = {"name": name, "group": group}
    if color is not None:
        body["color"] = color
    if sort_order is not None:
        body["sort_order"] = sort_order
    if is_default:
        body["is_default"] = True
    if closed:
        body["closed"] = True
    if blocks_work:
        body["blocks_work"] = True
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client, "POST", f"/api/v1/projects/{project}/states", json=body
        )


async def update_state(
    project: str,
    name: str,
    new_name: str | None = None,
    color: str | None = None,
    sort_order: int | None = None,
    blocks_work: bool | None = None,
    ctx: Context | None = None,
) -> dict:
    """Werk een bestaande state bij: ``new_name`` (uniek, anders 409), ``color``,
    ``sort_order`` en/of ``blocks_work`` (agents mogen dan alleen reageren).
    ``name`` identificeert de state.
    """
    body: dict = {}
    if new_name is not None:
        body["name"] = new_name
    if color is not None:
        body["color"] = color
    if sort_order is not None:
        body["sort_order"] = sort_order
    if blocks_work is not None:
        body["blocks_work"] = blocks_work
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client,
            "PATCH",
            f"/api/v1/projects/{project}/states/{name}",
            json=body,
        )


async def delete_state(project: str, name: str, ctx: Context | None = None) -> str:
    """Verwijder een state (kolom) uit een project.

    ``project`` is de key, ``name`` de state-naam. 409 als het de laatste kolom
    van het project is, of als er nog items in staan — verplaats die eerst
    naar een andere kolom (``update_item``/``set_state``).
    """
    async with _client(_resolve_key(ctx)) as client:
        await _call(client, "DELETE", f"/api/v1/projects/{project}/states/{name}")
    return f"Verwijderd: {project}/{name}"


# --- P2-config-tools (BETON-147: project-CRUD + labels + triage-toggle) ----


async def create_project(
    key: str, name: str, description: str = "", ctx: Context | None = None
) -> dict:
    """Maak een nieuw Betonning-project aan.

    ``key`` is de korte project-key (bv. ``SOS``, max 20 tekens), ``name`` de
    volledige naam. Optioneel ``description``. 409 als de key al bestaat.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client,
            "POST",
            "/api/v1/projects",
            json={"key": key, "name": name, "description": description},
        )


async def update_project(
    key: str,
    name: str | None = None,
    description: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Werk naam en/of omschrijving van een project bij (partiële update).

    ``key`` is de project-key. Alleen de meegegeven (niet-``None``) velden
    wijzigen.
    """
    body: dict = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    async with _client(_resolve_key(ctx)) as client:
        return await _call(client, "PATCH", f"/api/v1/projects/{key}", json=body)


async def archive_project(key: str, ctx: Context | None = None) -> str:
    """Archiveer een project (soft-delete; blijft herstelbaar).

    ``key`` is de project-key. Het project verdwijnt uit de default-lijst maar
    kan met ``restore_project`` teruggehaald worden. Alleen voor mensen: een
    agent krijgt 403 (BETON-482).
    """
    async with _client(_resolve_key(ctx)) as client:
        await _call(client, "DELETE", f"/api/v1/projects/{key}")
    return f"Gearchiveerd: {key}"


async def restore_project(key: str, ctx: Context | None = None) -> dict:
    """Herstel een gearchiveerd project. Alleen voor mensen (BETON-482)."""
    async with _client(_resolve_key(ctx)) as client:
        return await _call(client, "POST", f"/api/v1/projects/{key}/restore")


async def list_labels(project: str, ctx: Context | None = None) -> list[dict]:
    """Lijst de labels van een project (naam + kleur).

    ``project`` is de project-key (bv. ``SOS``).
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(client, "GET", f"/api/v1/projects/{project}/labels")


async def create_label(
    project: str, name: str, color: str | None = None, ctx: Context | None = None
) -> dict:
    """Maak een nieuw label aan in een project.

    ``project`` is de key, ``name`` de label-naam. Optioneel ``color`` (hex,
    bv. ``#e74c3c``). 409 als het label al bestaat.
    """
    body: dict = {"name": name}
    if color is not None:
        body["color"] = color
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client, "POST", f"/api/v1/projects/{project}/labels", json=body
        )


async def delete_label(project: str, name: str, ctx: Context | None = None) -> str:
    """Verwijder een label uit een project.

    ``project`` is de key, ``name`` de label-naam. Het label wordt van alle
    items losgekoppeld.
    """
    async with _client(_resolve_key(ctx)) as client:
        await _call(client, "DELETE", f"/api/v1/projects/{project}/labels/{quote(name, safe='')}")
    return f"Verwijderd: {project}/{name}"


async def set_triage_enabled(
    project: str, enabled: bool, ctx: Context | None = None
) -> dict:
    """Zet de per-project triage-opt-in aan of uit.

    ``project`` is de key. ``enabled=True`` activeert de automatische triage-bot
    voor nieuwe items in dit project; ``False`` zet 'm uit.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client,
            "PUT",
            f"/api/v1/projects/{project}/triage",
            json={"enabled": enabled},
        )


async def backfill_triage(project: str, ctx: Context | None = None) -> dict:
    """Plan alle bestaande items van een (opt-in) project opnieuw voor triage in.

    De triage-loop pikt ze in zijn eigen tempo op. 400 als triage uit staat voor
    dit project (zet 'm eerst aan met ``set_triage_enabled``). Geeft ``{"queued":
    <aantal>}`` terug.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client, "POST", f"/api/v1/projects/{project}/triage/backfill"
        )


# --- P3-session-tools (BETON-150: my-issues + inbox) ----------------------


async def get_my_issues(ctx: Context | None = None) -> list[dict]:
    """Mijn openstaande tickets (cross-project) — het startpunt van een sessie.

    Lijst de open items die aan jóu (de ingelogde agent/mens) toegewezen zijn,
    over alle projecten heen. Gebruik dit om te zien wat er voor je klaarligt
    vóór je een taak oppakt.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(client, "GET", "/api/v1/me/issues")


async def get_inbox(
    limit: int = 50, instructions: bool = False, ctx: Context | None = None
) -> dict:
    """Mijn inbox: verse mentions, toewijzingen en reacties, nieuwste eerst, met
    ``unread_count``. ``limit`` 1–200 (default 50). ``instructions=True`` voegt
    per entry een ``instruction``-blok toe (zoals een webhook-delivery).
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client,
            "GET",
            "/api/v1/inbox",
            params={"limit": limit, "instructions": instructions},
        )


# --- Vraagmodule (BETON-219) ----------------------------------------------


async def ask_question(
    ref: str,
    question_md: str,
    options: list[str] | None = None,
    ctx: Context | None = None,
) -> dict:
    """Stel EEN vraag aan een mens onder een ticket.

    Alleen voor mensen; voor een agent gebruik je ``comment_item`` met
    ``@handle``. ``question_md`` is de vraag (``@handle`` richt hem aan een
    mens). Staat het ticket nog bij een agent, noem de mens expliciet met
    ``@handle``. Je kunt ook eerst ``update_item(assignee=..., handover_md=...)``
    doen en daarna een vraag aan de menselijke assignee stellen.
    ``options`` zijn optionele meerkeuze-antwoorden (max 6, uniek) die bij
    deze ene vraag horen. Precies ÉÉN vraag per aanroep: meerdere vragen = meerdere
    aanroepen (BETON-304).

    Het ticket wordt aan de aangesproken mens toegewezen en komt na het antwoord
    terug; zet de toewijzing niet zelf terug (409). Kwam het antwoord elders,
    trek de vraag in met ``withdraw_question`` vóór je het ticket afsluit.
    """
    payload: dict = {"body_md": question_md, "kind": "question"}
    if options is not None:
        payload["options"] = options
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client, "POST", f"/api/v1/items/{ref}/comments", json=payload
        )


async def propose_guardrail(
    ref: str,
    guardrail_md: str = "",
    labels: list[str] | None = None,
    review_by: str | None = None,
    kind: str = "set",
    reason: str = "",
    ctx: Context | None = None,
) -> dict:
    """Stel een GUARDRAIL voor: kennis die niet in een regressietest past en die
    elke agent moet naleven (bv. "prompts voor model X kort houden").

    De drempel is hoog: kun je er een test voor schrijven, schrijf die test.
    Dit zet een CONCEPT (één slot per ticket); alleen een mens keurt goed, een
    actieve guardrail blijft tot dan gelden.

    ``kind="set"``: ``guardrail_md`` verplicht, max 1000 tekens (wat, waarom, wat
    te doen). ``labels`` scopet tot tickets met die labels; zonder labels geldt
    hij projectbreed (plafond vijf). ``review_by``: YYYY-MM-DD, niet in het
    verleden (default 90 dagen). ``kind="lift"``: stel opheffen voor; ``reason``
    verplicht.
    """
    payload: dict = {"kind": kind}
    if kind == "lift":
        payload["reason"] = reason
    else:
        payload["guardrail_md"] = guardrail_md
        payload["scope_labels"] = labels or []
        if review_by:
            payload["review_by"] = review_by
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client, "POST", f"/api/v1/items/{ref}/guardrail/propose", json=payload
        )


async def withdraw_question(
    comment_id: int, reason: str, ctx: Context | None = None
) -> dict:
    """Trek een open vraag in (BETON-454) omdat hij achterhaald is: het antwoord
    kwam elders, of de vraag is door ander werk beantwoord. Mag ook op een vraag
    die je niet zelf stelde (BETON-481): laat een achterhaalde vraag nooit open
    staan. ``comment_id`` = de vraag-comment, ``reason`` verplicht (zeg waar het
    antwoord staat). 409 als de vraag al beantwoord of ingetrokken is.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client,
            "POST",
            f"/api/v1/comments/{comment_id}/withdraw",
            json={"reason": reason},
        )


async def get_open_questions(ctx: Context | None = None) -> list[dict]:
    """Open (onbeantwoorde) vragen die aan jóu gericht zijn.

    Toont vragen op tickets waar je assignee of maker van bent, of waarin je
    @gementiond bent. Per vraag krijg je de tekst, eventuele opties en de
    item-ref/-titel. Gebruik dit om te zien of iemand op jouw antwoord wacht.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(client, "GET", "/api/v1/questions", params={"open": "true"})


async def mute_item(ref: str, ctx: Context | None = None) -> dict:
    """Demp een ticket voor jezelf (BETON-466): je krijgt er geen triggers meer van.

    Gebruik dit als een ticket niet (meer) voor jou is. Alleen voor de aanroeper
    zelf; ``unmute_item`` heft het op.
    """
    async with _client(_resolve_key(ctx)) as client:
        handle = (await _me(client))["handle"]
        await _call(client, "POST", f"/api/v1/items/{ref}/subscribers/{handle}/mute")
    return {"ref": ref, "handle": handle, "muted": True}


async def unmute_item(ref: str, ctx: Context | None = None) -> dict:
    """Heft het dempen van een ticket voor jezelf op (BETON-466)."""
    async with _client(_resolve_key(ctx)) as client:
        handle = (await _me(client))["handle"]
        await _call(
            client, "DELETE", f"/api/v1/items/{ref}/subscribers/{handle}/mute"
        )
    return {"ref": ref, "handle": handle, "muted": False}


async def add_label(ref: str, name: str, ctx: Context | None = None) -> dict:
    """Voeg één bestaand label toe aan een ticket (BETON-466).

    Raakt de andere labels niet; ``name`` moet al in het project bestaan
    (anders 400). Geeft het bijgewerkte ticket terug.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client, "POST", f"/api/v1/items/{ref}/labels/{quote(name, safe='')}"
        )


async def remove_label(ref: str, name: str, ctx: Context | None = None) -> dict:
    """Haal één label van een ticket af (BETON-466), de rest blijft staan.

    Geeft het bijgewerkte ticket terug; een onbekend label geeft 400.
    """
    async with _client(_resolve_key(ctx)) as client:
        return await _call(
            client, "DELETE", f"/api/v1/items/{ref}/labels/{quote(name, safe='')}"
        )


_USER_FIELDS = ("handle", "display_name", "kind", "agent_type", "is_virtual", "active")


async def list_users(kind: str | None = None, ctx: Context | None = None) -> list[dict]:
    """Lijst de users (BETON-466) om geldige handles te vinden voor ``assignee`` of een ``@mention``.

    Filter optioneel op ``kind`` (``human``/``agent``). Je krijgt alleen handle,
    naam, kind, agent_type, is_virtual en active — nooit keys of webhook-gegevens.
    """
    async with _client(_resolve_key(ctx)) as client:
        users = await _call(client, "GET", "/api/v1/users")
    return [
        {k: u.get(k) for k in _USER_FIELDS}
        for u in users
        if kind is None or u.get("kind") == kind
    ]


async def upload_attachment(
    ref: str, filename: str, content_base64: str, ctx: Context | None = None
) -> dict:
    """Zet een bijlage (bv. screenshot als bewijs) op een ticket (BETON-466).

    ``content_base64`` is de bestandsinhoud; toegestaan zijn PNG/JPEG/GIF/WEBP,
    PDF, tekst en JSON (de server bepaalt het type uit de inhoud). Geeft ``url``
    en ``markdown`` (``![naam](url)``) terug om in een comment te plakken.
    """
    # Weiger vóór het decoderen: 4 tekens base64 = 3 bytes (+ ruimte voor padding).
    if len(content_base64) > MAX_INLINE_ATTACHMENT_BYTES * 4 // 3 + 4:
        raise RuntimeError(
            f"Bijlage te groot (max {MAX_INLINE_ATTACHMENT_BYTES // (1024 * 1024)} MB)"
        )
    try:
        data = base64.b64decode(content_base64, validate=True)
    except ValueError as exc:
        raise RuntimeError("content_base64 is geen geldige base64") from exc
    async with _client(_resolve_key(ctx)) as client:
        att = await _call(
            client,
            "POST",
            f"/api/v1/items/{ref}/attachments",
            files={"file": (filename, data)},
        )
    return {**att, "markdown": f"![{att.get('filename') or filename}]({att['url']})"}


CREATE_ITEMS_MAX = 50


async def create_items(
    project: str, items: list[dict], ctx: Context | None = None
) -> list[dict]:
    """Maak tot 50 tickets achter elkaar aan in één project (BETON-466).

    Elk item draagt dezelfde velden als ``create_item`` (``title`` verplicht,
    ``plan_md``/``workload``/``labels``/…). Je krijgt per item ``ok`` plus de
    ``ref`` of de ``error``; een fout stopt de rest niet.
    """
    if len(items) > CREATE_ITEMS_MAX:
        raise RuntimeError(f"Maximaal {CREATE_ITEMS_MAX} items per call")
    results: list[dict] = []
    for index, spec in enumerate(items):
        try:
            item = await create_item(project, ctx=ctx, **spec)
            result = {"index": index, "ok": True, "ref": item["ref"]}
            if "next_step" in item:
                result["next_step"] = item["next_step"]
        except (RuntimeError, TypeError, KeyError) as exc:
            result = {"index": index, "ok": False, "error": str(exc)}
        results.append(result)
    return results


# Server-level instructies: deze komen bij de MCP-`initialize`-handshake mee
# (serverInfo.instructions), zodat een agent ze automatisch in zijn context krijgt
# — óók zonder een tool aan te roepen. Hier staan de altijd-geldende conventies
# plus de opdracht om het (dynamische, actuele) geheugen te laden. Zo hoeft de
# agent niet te 'weten' dat de wiki bestaat; hij wordt erop gewezen (BETON-36/33).
SERVER_INSTRUCTIONS = """\
Betonning is je taak-tracker én je persistente geheugen (een LLM-wiki).

**Laad eerst je geheugen.** Roep `load_memory` (globaal) of \
`load_memory(project="KEY")` (globaal + project) aan het BEGIN van elke taak aan. \
Daar staan de actuele, volledige conventies en projectkennis. Werk het bij met \
`set_memory` zodra je iets duurzaams leert. Roep daarna `get_my_issues` \
(wat ligt er voor mij) of `get_inbox` (zijn er verse mentions voor mij) aan.

## Comments en overdracht
Een agent die aan een mens overdraagt, zet in één zin bovenaan wat nodig is:
stel een vraag met `ask_question` of geef `handover_md` mee aan `update_item`
(één alinea, maximaal 300 tekens). Een kale overdracht aan een mens geeft 422.
Begin lange comments met een samenvatting van 1–3 zinnen; zet details eronder
of in `<details>`. Een mens hoeft de thread niet terug te lezen.

Ticketwerk doe je met de MCP-tools (thin wrappers om de Betonning-API): \
`list_items` (wat ligt er), `get_item` (detail incl. comments/relaties/subtaken), \
`create_item`, `update_item`/`set_state` (kolom wisselen binnen hetzelfde project; \
`move_item` is een deprecated alias van `set_state`), `transfer_item` (naar een \
ANDER project — niet te verwarren met `set_state`), \
`comment_item`/`edit_comment`/`delete_comment`, \
`relate_items`/`unrelate_items`, `archive_item`, `list_item_activity` (event-log \
van één ticket), `list_project_activity` (event-log van een héel project). \
Project-config: `list_milestones`/`create_milestone`/`update_milestone`, \
`list_states`/`create_state`/`update_state`/`delete_state`, `list_labels`/`create_label`/`delete_label`. \
Project-beheer: `create_project`/`update_project`/`archive_project`/`restore_project`. \
Triage per project: `set_triage_enabled`/`backfill_triage`.

- Geef agentwerk precies één werkklasselabel: `routine`, `standaard` of `complex`. \
Gebruik geen modelnamen als labels. Nieuwe projecten hebben deze labels al. \
- Wil je één label toevoegen of weghalen? Gebruik `add_label`/`remove_label`; \
`update_item(labels=…)` vervangt de hele set (BETON-466).
- Is een ticket niet (meer) voor jou? Demp het met `mute_item` (`unmute_item` \
heft het op); je krijgt er dan geen triggers meer van (BETON-466).

Altijd geldende werkwijze (samenvatting — `load_memory` heeft de volledige versie):

- Pak je een taak op? Zet 'm meteen op `in-progress` (`set_state(ref, "in-progress")`), \
zodat andere agents zien dat 'ie in behandeling is.
- Werk klaar? Zet 'm op `done` (`set_state(ref, "done")`) en plaats een afsluit-comment \
(`comment_item`) met wat je deed, welke bestanden wijzigden, of de tests groen zijn.
- `backlog` = nog niet oppakken; `todo` = mag opgepakt worden.
- Schrijf comments en omschrijvingen overzichtelijk: witregels tussen gedachten, \
opsommingen, korte koppen, backticks voor code/refs. Geen wall of text.
- Leg na het aanmaken van een ticket de juiste relatie (`relate_items` met \
`blocks`/`blocked_by` voor volgorde, `relates_to`, `duplicate_of`).
- **Maak je een ticket voor een andere agent aan? Zet er meteen een plan bij** \
(`plan_md` in de `create_item`-call zelf; elk ticket dat je aanmaakt krijgt een \
plan): ordelijke stappen, te \
wijzigen bestanden, tests, verificatie, commit-granulariteit — vóórdat er een \
comment op staat (BETON-301 legt het daarna vast). **Pak je zelf een ticket op \
en staat `has_plan` op true** (zie `get_item`/`list_items`)? Haal het plan eerst \
op vóór je begint: `get_item(ref)` levert het plan inline mee als `plan_md` \
(`get_plan(ref)` alleen voor een plan dat daar is afgekapt).
- `ask_question` is UITSLUITEND voor vragen aan een mens — niet agent-naar-agent. \
Heb je iets aan een andere agent te vragen, gebruik dan `comment_item` met een \
gewone `@handle`-mention.
- Een `ask_question` wijst het ticket automatisch toe aan de aangesproken mens en \
het komt na het antwoord vanzelf terug. Zet de toewijzing niet zelf terug of weg: \
zolang de vraag openstaat geeft dat een 409 (BETON-431).
- `ask_question` = precies ÉÉN vraag per aanroep. Meerdere vragen? Roep hem \
meerdere keren aan — meerkeuze-opties horen bij precies één vraag, niet bij \
een lijst vragen door elkaar (BETON-304).
- Kreeg je het antwoord op je vraag elders (chat), of zie je dat een open \
vraag achterhaald is (ook die van een ander)? Trek hem in met \
`withdraw_question` en zeg in de reden waar het antwoord staat; laat hem niet \
open staan. Afsluiten met een open vraag geeft een 409 (BETON-454, BETON-481).
"""


SERVER_INSTRUCTIONS += "\n\n" + outbound("human_comment_references", language="nl")


def build_server():
    """Bouw de FastMCP-server met alle memory-tools geregistreerd."""
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    # DNS-rebinding-bescherming staat standaard alleen localhost als Host toe,
    # waardoor de dienst achter een LAN-IP/hostname 421 Misdirected Request geeft.
    # Dit is een LAN-only, auth-vereiste dienst (elke call heeft een geldige
    # Bearer-key nodig), dus we zetten die hostcheck uit.
    mcp = FastMCP(
        "Betonning memory",
        instructions=SERVER_INSTRUCTIONS,
        session_idle_timeout=300,
        max_sessions=128,
        max_request_body_size=256 * 1024,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    for fn in (
        load_memory,
        list_memory_pages,
        get_memory_page,
        set_memory,
        list_projects,
        search_tickets,
        list_items,
        get_item,
        get_plan,
        create_item,
        update_item,
        set_state,
        move_item,
        comment_item,
        relate_items,
        transfer_item,
        # P1-batch (BETON-146): kern-tools voor agents
        archive_item,
        unrelate_items,
        edit_comment,
        delete_comment,
        list_item_activity,
        list_project_activity,
        get_attachment,
        list_milestones,
        create_milestone,
        update_milestone,
        list_states,
        create_state,
        update_state,
        delete_state,
        # P2-batch (BETON-147): project-CRUD + labels + triage-toggle
        create_project,
        update_project,
        archive_project,
        restore_project,
        list_labels,
        create_label,
        delete_label,
        set_triage_enabled,
        backfill_triage,
        # P3-batch (BETON-150): session-start (my-issues + inbox)
        get_my_issues,
        get_inbox,
        # Vraagmodule (BETON-219)
        ask_question,
        withdraw_question,
        get_open_questions,
        # Guardrails (BETON-420): voorstellen mag een agent; activeren en
        # opheffen is mens-only en heeft daarom bewust géén tool.
        propose_guardrail,
        # BETON-466: gaten tussen REST en MCP
        mute_item,
        unmute_item,
        add_label,
        remove_label,
        list_users,
        upload_attachment,
        create_items,
    ):
        mcp.tool()(fn)
    return mcp


def main() -> None:
    server = build_server()
    transport = os.environ.get("BETONNING_MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        server.settings.host = os.environ.get("BETONNING_MCP_HOST", "0.0.0.0")
        server.settings.port = int(os.environ.get("BETONNING_MCP_PORT", "8129"))
        server.run(transport="streamable-http")
    else:
        server.run()


if __name__ == "__main__":
    main()
