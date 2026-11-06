// Pure niet-DOM-logica voor Drawer.svelte (BETON-185): relatie-groepering,
// caret-invoeging en de verrijk-melding. De component houdt de runes/DOM; deze
// functies krijgen state als argument en geven een nieuwe waarde terug.

import { translate } from "./i18n.js";
import { parseHashQuery } from "./hashAutocomplete.js";
import { workloadLabel } from "./labels.js";
import { questionState, matchedOptionIndex } from "./question.js";

/**
 * Zichtbare relatiegroepen voor een item: alleen niet-lege groepen. De parent
 * zit er sinds BETON-471 bewust niet meer in — die staat al in de kop van de
 * drawer (BETON-137), twee keer tonen was ruis.
 *
 * @param {{relations?: Record<string, string[]>}|null} item
 * @returns {Array<[string, string[]]>}
 */
export function visibleRelationGroups(item) {
  if (!item) return [];
  return Object.entries(item.relations || {}).filter(([, v]) => v.length > 0);
}

/**
 * Voeg `insert` in `text` in op positie `pos` (caret). `pos == null`
 * (geen selectie/caret bekend) voegt aan het eind toe. Een caret van 0 blijft
 * behouden (invoegen aan het begin).
 *
 * @param {string} text
 * @param {number|null|undefined} pos
 * @param {string} insert
 * @returns {string}
 */
export function insertAt(text, pos, insert) {
  const s = String(text ?? "");
  const at = pos == null ? s.length : pos;
  return s.slice(0, at) + insert + s.slice(at);
}

/**
 * De melding die de Drawer toont wanneer de verrijk-bot te weinig info had en
 * (idealiter) vragen als comment plaatste i.p.v. een omschrijvings-voorstel
 * (BETON-163). `commentPosted` bepaalt de exacte tekst.
 *
 * @param {boolean} commentPosted
 * @returns {string}
 */
export function enrichQuestionsNotice(commentPosted, locale = "nl") {
  return translate(locale, commentPosted ? "detail.questions" : "detail.questionsFailed");
}

/**
 * Voeg comments en activiteitsregels samen tot één chronologische tijdlijn
 * (BETON-223). Een comment wordt een kaart, een event één regel. Oplopend
 * gesorteerd op tijd; bij een gelijk tijdstip behouden comments (eerst
 * toegevoegd) hun plek vóór events (stabiele sort). De composer hangt in de UI
 * onderaan onder de nieuwste entry.
 *
 * `held` (BETON-338) is de comment die op de noodstop stuitte en nog niet
 * geplaatst is. Die hoort altijd ONDERAAN, ongeacht zijn tijdstip: hij is nog
 * geen deel van het gesprek maar een openstaande handeling ("dit wacht op jou").
 * Chronologisch tussenvoegen zou hem juist verstoppen tussen de reacties.
 *
 * @param {Array<{id: number|string, created_at: string}>} comments
 * @param {Array<{id?: number|string, type: string, created_at: string}>} events
 * @param {{id: number|string, author: string, body_md: string, created_at: string}|null} [held]
 * @returns {Array<{kind: 'comment'|'event'|'held', key: string, at: string, comment?: object, event?: object, held?: object}>}
 */
export function mergeTimeline(comments = [], events = [], held = null) {
  const entries = [];
  // BETON-265: het antwoord staat inline op de vraag; historische antwoord-comments
  // (nog gelinkt via answer_comment_id) horen niet meer los in de tijdlijn.
  const answerIds = new Set(
    (comments || []).filter((c) => c && c.answer_comment_id).map((c) => c.answer_comment_id),
  );
  for (const c of comments || []) {
    if (answerIds.has(c.id)) continue;
    entries.push({ kind: "comment", key: `c${c.id}`, at: c.created_at, comment: c });
  }
  for (const e of events || []) {
    entries.push({
      kind: "event",
      key: `e${e.id ?? ""}-${e.type}-${e.created_at}`,
      at: e.created_at,
      event: e,
    });
  }
  // Array.prototype.sort is stabiel (ES2019+): gelijke tijdstippen houden hun
  // invoegvolgorde, dus comments blijven vóór events bij exact dezelfde tijd.
  entries.sort((a, b) => (Date.parse(a.at) || 0) - (Date.parse(b.at) || 0));
  // Ná het sorteren aangehaakt: de wachtende comment staat bewust altijd
  // onderaan (zie de docstring), niet op zijn chronologische plek.
  if (held) {
    entries.push({
      kind: "held",
      key: `h${held.id}`,
      at: held.created_at,
      held,
    });
  }
  return entries;
}

/**
 * Filter de tijdlijn voor de "Reacties"-modus (BETON-364): alleen comments,
 * de wachtende comment (`held`) en het `question.answered`-event blijven —
 * dat laatste is bewust geen comment maar hoort inhoudelijk bij het gesprek
 * (het linkt naar de vraag die net beantwoord is, BETON-274). Alle overige
 * systeem-events (state-wissels, toewijzingen, labels, …) vallen weg.
 * `mode = "all"` geeft de tijdlijn ongewijzigd terug.
 *
 * @param {Array<{kind: string, event?: {type?: string}}>} timeline  mergeTimeline-output
 * @param {"all"|"comments"} mode
 * @returns {Array}
 */
export function filterTimeline(timeline, mode) {
  const entries = timeline || [];
  if (mode !== "comments") return entries;
  return entries.filter(
    (e) =>
      e.kind === "comment" ||
      e.kind === "held" ||
      (e.kind === "event" && e.event?.type === "question.answered"),
  );
}

/**
 * Klap opeenvolgende system-events samen tot één inklapbare groep (BETON-364):
 * een ononderbroken reeks van 3 of meer `kind === "event"`-entries wordt één
 * `event-group`-entry; een comment, `held` of een kortere reeks (1-2) breekt
 * de reeks en blijft ongewijzigd staan. Werkt op de rauwe `mergeTimeline`-
 * output — de tijdlijnfilter (`filterTimeline`) draait er los van, vóór of
 * zonder deze stap.
 *
 * @param {Array<{kind: string, key: string, event?: object}>} timeline
 * @returns {Array}
 */
export function collapseEvents(timeline) {
  const entries = timeline || [];
  const out = [];
  let run = [];

  function flushRun() {
    if (run.length === 0) return;
    if (run.length < 3) {
      out.push(...run);
    } else {
      const events = run.map((e) => e.event);
      const actors = [...new Set(events.map((e) => e?.actor).filter(Boolean))];
      out.push({
        kind: "event-group",
        key: `eg-${run[0].key}-${run[run.length - 1].key}`,
        events,
        actors,
        first: events[0],
        last: events[events.length - 1],
      });
    }
    run = [];
  }

  for (const entry of entries) {
    if (entry.kind === "event") {
      run.push(entry);
    } else {
      flushRun();
      out.push(entry);
    }
  }
  flushRun();
  return out;
}

/**
 * Lijst voor de label-picker-popover (BETON-223): alleen de projectlabels die
 * op de (gefilterde) zoekterm matchen, elk gemarkeerd of ze al toegekend zijn.
 *
 * @param {Array<{name: string}>} projectLabels
 * @param {string[]} assigned  namen van de reeds toegekende labels
 * @param {string} query
 * @returns {Array<{name: string, assigned: boolean}>}
 */
export function labelPickerList(projectLabels = [], assigned = [], query = "") {
  const q = (query || "").trim().toLowerCase();
  const assignedSet = new Set(assigned || []);
  return (projectLabels || [])
    .filter((l) => !q || l.name.toLowerCase().includes(q))
    .map((l) => ({ name: l.name, assigned: assignedSet.has(l.name) }));
}

/**
 * Welke drawer-secties leeg zijn (BETON-242) → de UI toont dan een compacte
 * "+ toevoegen"-affordance i.p.v. een vol blok. Puur zodat de leeg-detectie
 * los testbaar is; let op het onderscheid `children` (rauwe ref-lijst) vs
 * `children_detail` (verrijkte subtaak-rijen) — beide tellen als subtaken.
 *
 * @param {{has_plan?: boolean, children?: string[], children_detail?: any[], parent?: string|null, relations?: Record<string, string[]>}|null} item
 * @returns {{plan: boolean, subtasks: boolean, relations: boolean}}
 */
export function emptySections(item) {
  const i = item || {};
  const hasSubtasks = Boolean(i.children_detail?.length) || Boolean(i.children?.length);
  return {
    plan: !i.has_plan,
    subtasks: !hasSubtasks,
    relations: visibleRelationGroups(i).length === 0,
  };
}

// Volgorde van de Escape-ladder (BETON-223): binnenste sub-state eerst. Zodra
// een vlag actief is, vangt die Escape af; niets actief = de drawer mag sluiten.
export const ESCAPE_ORDER = [
  "mention",
  "hashMatches",
  "relMatches",
  "editingComment",
  "editingTitle",
  "descMention",
  "descHashMatches",
  "editingDesc",
  "editingPlan",
  // BETON-420: het guardrail-formulier is een eigen bewerkstand met een
  // ongeschreven concept; zonder eigen rung zou Escape de hele drawer sluiten
  // en de tekst weggooien.
  "editingGuardrail",
  "confirm",
  "unsavedComment",
];

/**
 * Bepaal welke sub-state Escape moet afhandelen (BETON-223). Pure state-machine
 * voor het één-idioom-bewerken: geeft de eerste actieve rung terug, of `null`
 * als er niets openstaat (dan mag de dialog sluiten). Houdt de Esc-logica los
 * van de DOM zodat ze te testen is.
 *
 * @param {Record<string, boolean>} flags
 * @returns {string|null}
 */
export function escapeLadder(flags = {}) {
  for (const key of ESCAPE_ORDER) {
    if (flags[key]) return key;
  }
  return null;
}

/**
 * Compacte samenvatting van de property-rijen voor de ingeklapte chips
 * (BETON-223): "@claude", "Hoog", "12 jul" enz. Puur zodat de chip-teksten
 * los testbaar zijn.
 *
 * @param {{assignee?: string|null, workload?: string, due_date?: string|null, deferred_until?: string|null, milestone?: string|null}|null} item
 * @param {{workloadOpts?: Array<{value: string, label: string}>}} [opts]
 * @returns {{assignee: string, workload: string, due: string, defer: string|null, milestone: string}}
 */
export function propertySummary(item, { workloadOpts = [], locale = "nl" } = {}) {
  const i = item || {};
  const wl = workloadOpts.find((o) => o.value === i.workload)?.label ?? i.workload ?? "—";
  return {
    assignee: i.assignee ? `@${i.assignee}` : (locale === "en" ? "unassigned" : "niet toegewezen"),
    workload: wl,
    due: i.due_date ? i.due_date.slice(0, 10) : (locale === "en" ? "no date" : "geen datum"),
    defer: i.deferred_until ? i.deferred_until.slice(0, 10) : null,
    milestone: i.milestone || (locale === "en" ? "no milestone" : "geen milestone"),
  };
}

/**
 * Normaliseer de afgeleide subscribers-union voor de "Volgers"-chips (BETON-245).
 * Ontdubbelt op handle (defensief; de server ontdubbelt al), sorteert alfabetisch
 * en zet de niet-gemute volgers vóór de gemute — zo staan de actieve volgers
 * bovenaan en zakken de gedempte naar onderen. Puur zodat de lijst-vorm los
 * testbaar is.
 *
 * Draagt sinds BETON-369 ook `following` mee: wie het item expliciet volgt
 * (`item_follows`) i.p.v. er alleen afgeleid in te zitten.
 *
 * @param {Array<{handle: string, muted?: boolean, following?: boolean}>} subscribers
 * @returns {Array<{handle: string, muted: boolean, following: boolean}>}
 */
export function subscriberChips(subscribers = []) {
  const byHandle = new Map();
  for (const s of subscribers) {
    if (!s || !s.handle) continue;
    // Eerste voorkomen wint; een latere muted-vlag mag een eerdere niet omzetten.
    if (!byHandle.has(s.handle)) {
      byHandle.set(s.handle, {
        muted: Boolean(s.muted),
        following: Boolean(s.following),
      });
    }
  }
  return [...byHandle.entries()]
    .map(([handle, flags]) => ({ handle, ...flags }))
    .sort((a, b) => a.muted - b.muted || a.handle.localeCompare(b.handle));
}

/**
 * De comment-id om naartoe te scrollen na het plaatsen van een reactie
 * (BETON-253). Prefereert de id uit de POST-response (`api.comment` geeft de
 * geserialiseerde comment terug — óók op het dedup-pad); valt terug op de
 * nieuwste comment (hoogste id) uit de verse lijst als de response er geen had.
 *
 * @param {{id?: number}|null|undefined} response
 * @param {Array<{id?: number}>} comments
 * @returns {number|null}
 */
export function commentScrollTargetId(response, comments = []) {
  if (response && response.id != null) return response.id;
  let newest = null;
  for (const c of comments) {
    if (c && c.id != null && (newest == null || c.id > newest)) newest = c.id;
  }
  return newest;
}

/**
 * Mag er nu naar de doel-comment gescrolld worden (BETON-273)? Alleen als er een
 * doel is, het item klaar met laden is, en die comment ook echt in de tijdlijn
 * staat — anders bestaat het anker `#cmt-{id}` nog niet in de DOM. Pure guard
 * zodat het te testen is zonder DOM.
 *
 * @param {number|null|undefined} targetId
 * @param {boolean} loading
 * @param {Array<{id?: number}>} comments
 * @returns {boolean}
 */
export function shouldScrollToComment(targetId, loading, comments = []) {
  if (targetId == null || loading) return false;
  return (comments || []).some((c) => c && c.id === targetId);
}

/**
 * Hoe moet de relatie-target-autocomplete een (al getrimde) query behandelen
 * (BETON-347)? Een pure cijferquery ("12") is een project-scoped ref-lookup
 * (via `refCandidates`/`filterTicketCandidates`, spiegelt de #-picker,
 * BETON-254) — die is al bij 1 teken zinvol dankzij seq-substring-matching.
 * Al het overige (tekst, of cijfers mét letters zoals "B1") blijft de gewone
 * cross-project titel-FTS (`api.search`), met de bestaande drempel van 2
 * tekens — 1-letter FTS is te ruis.
 *
 * @param {string} q reeds getrimde query
 * @returns {"ref"|"text"|null} `null` = te kort, niet zoeken
 */
export function relSearchMode(q) {
  const { letters, digits } = parseHashQuery(q);
  const mode = !letters && digits ? "ref" : "text";
  const minLen = mode === "ref" ? 1 : 2;
  return (q || "").length >= minLen ? mode : null;
}

// Compacte, deterministische datum/tijd-notatie voor de markdown-export
// (BETON-373): "2026-06-01 10:00" — géén `toLocaleString` (locale/tijdzone-
// afhankelijk, dus niet stabiel testbaar) en géén relatieve tekst zoals
// `formatTimestamp` in board.js (die is voor de live-UI, niet voor een export
// die later gelezen wordt).
function exportTimestamp(iso) {
  return (iso || "").slice(0, 16).replace("T", " ");
}

/**
 * Render één comment/vraag-regel voor `itemToMarkdown`: een kop met auteur +
 * tijd, gevolgd door de body. Een vraag krijgt een `> Vraag: …`-citaat; is hij
 * beantwoord, dan volgt een `Antwoord: …`-regel (gekozen optie of vrije tekst).
 *
 * @param {object} c comment
 * @returns {string}
 */
function commentToMarkdown(c, locale = "nl") {
  const head = `### @${c.author ?? "?"} · ${exportTimestamp(c.created_at)}`;
  const qs = questionState(c);
  if (!qs.isQuestion) {
    return `${head}\n\n${c.body_md ?? ""}`;
  }
  const lines = [head, "", `> ${locale === "en" ? "Question" : "Vraag"}: ${c.body_md ?? ""}`];
  if (qs.answered) {
    const chosen = qs.answerOptionIndex ?? matchedOptionIndex(qs.options, qs.answerText);
    const answerText = chosen >= 0 && qs.options[chosen] ? qs.options[chosen] : qs.answerText;
    lines.push(`${locale === "en" ? "Answer" : "Antwoord"}: ${answerText ?? ""}`);
  } else if (qs.withdrawn) {
    lines.push(`${locale === "en" ? "Withdrawn" : "Ingetrokken"}: ${qs.withdrawnReason ?? ""}`);
  }
  return lines.join("\n");
}

/**
 * Render een item als een zelfstandig markdown-document (BETON-373:
 * "Kopieer als markdown") — bruikbaar buiten Betonning (plakken in een
 * editor/chat). `comments` en `plan` komen los binnen (de aanroeper bepaalt
 * of het plan al geladen is; leeg/`null` plan laat de sectie weg). Historische
 * antwoord-comments (nog gelinkt via `answer_comment_id`, BETON-265) worden
 * overgeslagen — spiegelt `mergeTimeline`'s dedup, het antwoord staat al
 * inline op de vraag.
 *
 * @param {object} item
 * @param {{comments?: Array<object>, plan?: string|null, states?: Array<{name: string}>}} [opts]
 * @returns {string}
 */
export function itemToMarkdown(item, { comments = [], plan = null, states = [], locale = "nl" } = {}) {
  const i = item || {};
  // `states` is puur informatief meegegeven (BETON-373-signatuur): de
  // state-naam ís al het label (stateOptions() in segmentedOptions.js maakt
  // er geen apart label van), dus deze lookup is vandaag een no-op — hij
  // documenteert wél dat een toekomstige state→label-mapping hier moet landen.
  const stateLabel = (states || []).find((s) => s.name === i.state)?.name ?? i.state ?? "—";
  const meta = [
    `**Status:** ${stateLabel}`,
    `**${locale === "en" ? "Workload" : "Werklast"}:** ${i.workload ? workloadLabel(i.workload, locale) : "—"}`,
    `**${locale === "en" ? "Assignee" : "Toegewezen"}:** ${i.assignee ? `@${i.assignee}` : (locale === "en" ? "unassigned" : "niet toegewezen")}`,
    `**Labels:** ${i.labels?.length ? i.labels.join(", ") : (locale === "en" ? "no labels" : "geen labels")}`,
    `**Milestone:** ${i.milestone || (locale === "en" ? "no milestone" : "geen milestone")}`,
    `**Due:** ${i.due_date ? i.due_date.slice(0, 10) : (locale === "en" ? "no date" : "geen datum")}`,
  ].join(" · ");

  const parts = [`# ${i.ref ?? "?"} — ${i.title ?? ""}`, "", meta, "", locale === "en" ? "## Description" : "## Omschrijving", "", i.description_md || (locale === "en" ? "_empty_" : "_leeg_")];

  if (plan) {
    parts.push("", "## Plan", "", plan);
  }

  const answerIds = new Set(
    (comments || []).filter((c) => c && c.answer_comment_id).map((c) => c.answer_comment_id),
  );
  const visibleComments = (comments || []).filter((c) => c && !answerIds.has(c.id));
  parts.push("", locale === "en" ? "## Comments" : "## Reacties", "");
  parts.push(
    visibleComments.length
      ? visibleComments.map(c => commentToMarkdown(c, locale)).join("\n\n")
      : (locale === "en" ? "_no comments_" : "_geen reacties_"),
  );

  return parts.join("\n");
}

/**
 * Voorinvulling voor een nieuw ticket op basis van een bestaand item
 * (BETON-373: "Dupliceer"). Laat bewust comments/relaties/subtaken weg — dat
 * is de essentie van een kopie i.p.v. een klonen-met-historie. `title` krijgt
 * de "(kopie)"-suffix zodat de twee tickets in een lijst niet identiek ogen.
 * `parent` draagt de PARENT van het origineel over (de kopie wordt een
 * broertje in dezelfde subtaken-groep) — niet het origineel zelf; de relatie
 * náár het origineel legt de aanroeper apart via `pendingRelations`
 * (relates_to, spiegelt BETON-247), zoals bij een gewoon nieuw ticket.
 *
 * @param {object} item
 * @returns {{title: string, description: string, labels: string[], workload: string, milestone: string, parent: string|null}}
 */
export function duplicateDraft(item, locale = "nl") {
  const i = item || {};
  return {
    title: `${i.title ?? ""} (${locale === "en" ? "copy" : "kopie"})`,
    description: i.description_md || "",
    labels: [...(i.labels || [])],
    workload: i.workload || "",
    milestone: i.milestone || "",
    parent: i.parent ?? null,
  };
}

/**
 * Mag een klik op het gerenderde omschrijving/plan-blok de bewerkmodus
 * starten (BETON-415)? Nee bij een actieve, niet-lege tekstselectie binnen het
 * blok — anders slikt "klik om te bewerken" een kopieerpoging op een lang
 * plan op (het blok klapt om in een textarea en de selectie is weg). Nee ook
 * bij een ticketref (`[data-ticket]`) of een link (`<a>`), die houden hun
 * eigen actie.
 *
 * Een enkele klik in tekst zet in sommige browsers een lege/collapsed
 * selectie — `window.getSelection().toString()` is dan `""`, dus die telt
 * niet als "actief" en de gewone klik start gewoon de edit.
 *
 * @param {{closest?: (sel: string) => Element|null}|null} target
 * @param {string} [selectionText]  window.getSelection()?.toString() ?? ""
 * @returns {boolean}
 */
export function shouldStartEdit(target, selectionText = "") {
  if (target?.closest?.("[data-ticket]") || target?.closest?.("a")) return false;
  return (selectionText || "").length === 0;
}

/**
 * Vorige/volgende ref in de zichtbare volgorde (BETON-362) — de bordvolgorde
 * (kolommen in weergavevolgorde, elke kolom in zijn sorteervolgorde) of de
 * lijstvolgorde, aangeleverd door de aanroeper als `orderedRefs`. Puur: geen
 * kennis van hoe die volgorde is opgebouwd.
 *
 * Ontbreekt `ref` in `orderedRefs` (bv. een archiefitem buiten de huidige
 * filters, of de lijst is nog niet geladen) dan is er geen navigatie — `prev`/
 * `next` blijven `null` en `index`/`total` geven toch de lijstgrootte, zodat
 * de teller niet crasht op "0 / N" terwijl er feitelijk geen positie is.
 *
 * @param {string[]} orderedRefs
 * @param {string} ref
 * @returns {{prev: string|null, next: string|null, index: number, total: number}}
 *   `index` is 1-based ("3 / 41"); `-1` als `ref` niet in de lijst voorkomt.
 */
export function neighbours(orderedRefs, ref) {
  const list = orderedRefs || [];
  const i = list.indexOf(ref);
  if (i === -1) return { prev: null, next: null, index: -1, total: list.length };
  return {
    prev: i > 0 ? list[i - 1] : null,
    next: i < list.length - 1 ? list[i + 1] : null,
    index: i + 1,
    total: list.length,
  };
}

// ---------------------------------------------------------------------------
// Rail-indeling (BETON-414)
//
// De rail was twaalf gelijkwaardige groepen die allemaal altijd openstonden.
// Nu twee lagen: een ACTIEGROEP met de drie mutaties waarvoor de drawer
// opengaat, en daaronder een compacte EIGENSCHAPPENLIJST (naslag). De twee
// tijdstempels zijn read-only en worden door de component zelf gerenderd
// (relatieve tijd + absolute tooltip komen uit board.js) — ze staan hier als
// aparte constante zodat de indeling compleet en toetsbaar blijft.
// ---------------------------------------------------------------------------

/** De altijd zichtbare, sticky actiegroep bovenaan de rail. */
export const RAIL_ACTIONS = ["state", "workload", "assignee"];

/** Read-only regels onderaan de eigenschappenlijst. */
export const RAIL_META = ["created", "updated"];

const RAIL_PROPERTY_LABELS = {
  milestone: "Milestone",
  due: "Einddatum",
  defer: "Uitstellen tot",
  labels: "Labels",
  subtasks: "Subtaken",
  relations: "Relaties",
  followers: "Volgers",
};

/** Vaste volgorde van de bewerkbare eigenschappenlijst. */
export const RAIL_PROPERTIES = Object.keys(RAIL_PROPERTY_LABELS);

/**
 * In welke laag van de rail hoort een eigenschap? `null` = onbekende sleutel.
 *
 * @param {string} key
 * @returns {"actions"|"properties"|"meta"|null}
 */
export function railGroupOf(key) {
  if (RAIL_ACTIONS.includes(key)) return "actions";
  if (RAIL_PROPERTIES.includes(key)) return "properties";
  if (RAIL_META.includes(key)) return "meta";
  return null;
}

/**
 * De regels van de compacte eigenschappenlijst: label links, waarde rechts.
 * `empty` bepaalt of de component de grijze plaatsvervangende tekst toont
 * (`text`) of zijn eigen chips/waarde rendert — een eigenschap zonder waarde
 * verdwijnt dus niet, hij krijgt één stille regel.
 *
 * Milestone valt weg als het project er geen heeft (er valt dan niets te
 * kiezen); de overige zes staan er altijd.
 *
 * @param {object|null} item
 * @param {{subscribers?: Array<object>, milestones?: Array<object>}} [opts]
 * @returns {Array<{key: string, label: string, text: string, empty: boolean}>}
 */
export function railProperties(item, { subscribers = [], milestones = [], locale = "nl" } = {}) {
  const i = item || {};
  const summary = propertySummary(i, {locale});
  const subs = subscriberChips(subscribers);
  const relCount = visibleRelationGroups(i).length;
  const childCount = i.children_detail?.length || i.children?.length || 0;
  const values = {
    milestone: { empty: !i.milestone, text: summary.milestone },
    due: { empty: !i.due_date, text: summary.due },
    defer: { empty: !i.deferred_until, text: summary.defer ?? (locale === "en" ? "not deferred" : "niet uitgesteld") },
    labels: { empty: !(i.labels || []).length, text: locale === "en" ? "no labels" : "geen labels" },
    subtasks: { empty: childCount === 0, text: locale === "en" ? "no subtasks" : "geen subtaken" },
    relations: { empty: relCount === 0, text: locale === "en" ? "no relations" : "geen relaties" },
    followers: { empty: subs.length === 0, text: locale === "en" ? "no followers" : "geen volgers" },
  };
  return RAIL_PROPERTIES.filter((key) => key !== "milestone" || milestones.length > 0).map(
    (key) => ({ key, label: locale === "en" ? ({milestone:"Milestone",due:"Due date",defer:"Defer until",labels:"Labels",subtasks:"Subtasks",relations:"Relations",followers:"Followers"})[key] : RAIL_PROPERTY_LABELS[key], ...values[key] }),
  );
}

// --- Lange comments inklappen (BETON-458) ---------------------------------
// De beslissing valt op de GEMETEN hoogte van de gerenderde comment (tabellen
// en code tellen zo eerlijk mee), niet op tekenaantal.
export const COMMENT_COLLAPSE_ABOVE = 320; // px: hoger dan dit = inklapbaar
export const COMMENT_COLLAPSED_HEIGHT = 240; // px: zichtbaar als ingeklapt

/**
 * Altijd uitgeklapt: de nieuwste comment, eigen comments en een comment waar
 * naartoe gesprongen is (deep-link / "Naar de vraag").
 *
 * @param {{id: number, author?: string|null}} c
 * @param {{lastCommentId?: number|null, meHandle?: string|null, pinnedId?: number|null}} [ctx]
 * @returns {boolean}
 */
export function commentAlwaysOpen(c, { lastCommentId = null, meHandle = null, pinnedId = null } = {}) {
  if (lastCommentId != null && c.id === lastCommentId) return true;
  if (pinnedId != null && c.id === pinnedId) return true;
  return !!meHandle && c.author === meHandle;
}

/**
 * @param {{height?: number, firstBlockHeight?: number, alwaysOpen?: boolean, expanded?: boolean}} p
 *   height = gemeten volle hoogte (0/undefined = nog niet gemeten → niet inklappen)
 *   firstBlockHeight = hoogte van de eerste alinea/het eerste blok (blijft altijd zichtbaar)
 * @returns {{collapsible: boolean, collapsed: boolean, maxHeight: number}}
 */
export function commentCollapse({ height = 0, firstBlockHeight = 0, alwaysOpen = false, expanded = false } = {}) {
  const maxHeight = Math.max(COMMENT_COLLAPSED_HEIGHT, firstBlockHeight);
  const collapsible = !alwaysOpen && height > COMMENT_COLLAPSE_ABOVE && height > maxHeight + 40;
  return { collapsible, collapsed: collapsible && !expanded, maxHeight };
}

/** Aantal regels van een comment-tekst, voor "Toon alles (N regels)". */
export function commentLineCount(body) {
  return String(body ?? "").replace(/\s+$/, "").split("\n").length;
}

// --- Volgersrail (BETON-459) ----------------------------------------------

/**
 * Avatarrij: max `max` handles, de rest als "+N". Mute-status van anderen
 * hoort hier bewust niet in — die is van die persoon.
 *
 * @param {Array<{handle?: string}>} subscribers
 * @param {number} [max]
 * @returns {{shown: string[], extra: number}}
 */
export function followerAvatars(subscribers = [], max = 5) {
  const handles = subscriberChips(subscribers).map((s) => s.handle);
  return { shown: handles.slice(0, max), extra: Math.max(0, handles.length - max) };
}

export const FOLLOW_CHOICES = [
  { value: "follow", label: "Volgen" },
  { value: "mute", label: "Dempen" },
  { value: "normal", label: "Normaal" },
];

/** Vertaal uitsluitend volglabels; API-keuzes en volgorde blijven gelijk. */
export function followChoices(locale = "nl") {
  return FOLLOW_CHOICES.map(option => ({...option,
    label: locale === "en" ? ({follow:"Follow",mute:"Mute",normal:"Normal"})[option.value] : option.label}));
}

/**
 * Eigen status op dit ticket: gedempt wint van volgend.
 * @returns {{state: "muted"|"following"|"normal", label: string}}
 */
export function selfFollowState({ following = false, muted = false } = {}, locale = "nl") {
  if (muted) return { state: "muted", label: locale === "en" ? "Muted" : "Gedempt" };
  if (following) return { state: "following", label: locale === "en" ? "Following" : "Volgend" };
  return { state: "normal", label: locale === "en" ? "Follow" : "Volgen" };
}

/**
 * Welke API-calls horen bij een keuze, gegeven de huidige toestand.
 * @param {"follow"|"mute"|"normal"} choice
 * @returns {Array<"follow"|"unfollow"|"mute"|"unmute">}
 */
export function followChoiceOps(choice, { following = false, muted = false } = {}) {
  const ops = [];
  if (choice === "follow") {
    if (muted) ops.push("unmute");
    if (!following) ops.push("follow");
  } else if (choice === "mute") {
    if (!muted) ops.push("mute");
  } else if (choice === "normal") {
    if (muted) ops.push("unmute");
    if (following) ops.push("unfollow");
  }
  return ops;
}

// Snelle overdracht gebruikt de ingestelde coding-agents, met legacyqueue-compatibiliteit.
export function handoffTargets(item, me, users = []) {
  if (!item || me?.kind !== "human" || !me.handle || item.locked_at || item.archived_at) return [];
  const activeAgents = users.filter((u) => u.kind === "agent" && u.active !== false && u.active !== 0);
  const previous = item.assignee === me.handle ? item.previous_assignee : null;
  const coding = activeAgents.filter((u) => u.handle !== item.assignee && (u.agent_type === "coding" || u.handle === "coding-agent"));
  const targets = coding.map((u) => ({ handle: u.handle, label: u.handle === previous && u.handle !== "coding-agent" ? `↩ @${u.handle}` : `→ ${u.handle}` }));
  if (previous && !targets.some((t) => t.handle === previous) && activeAgents.some((u) => u.handle === previous)) {
    targets.push({ handle: previous, label: `↩ @${previous}` });
  }
  return targets;
}

/** Teruggeven heeft bij de sneltoets voorrang op een nieuwe coding-toewijzing. */
export function preferredHandoffTarget(targets, item, me) {
  const previous = item?.assignee === me?.handle ? item?.previous_assignee : null;
  return targets.find((target) => target.handle === previous) ?? targets[0] ?? null;
}

// "Triage reageert zo" (BETON-478): een toewijzing aan triage die nog niet is
// afgehandeld. De backend leidt `triage_pending` af; hier alleen de tekst, en
// alleen als het ticket nog echt bij triage staat (een live-event kan de
// assignee al hebben gewijzigd voordat het veld ververst is).
export function triagePendingNote(item, locale = "nl") {
  if (!item || !item.triage_pending || item.assignee !== "triage") return null;
  return translate(locale, "detail.triagePending");
}
