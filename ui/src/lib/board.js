import { describeEventEnglish } from "./eventEnglish.js";
// Pure board-logica — geen DOM, geen fetch. Hier zit de state-berekening die
// via vitest getest wordt; de Svelte-componenten blijven dun eromheen.
// Routing (lib/routing.js), wiki-tekst (lib/wikiText.js), SSE-parsing
// (lib/sse.js), mentions (lib/mentions.js) en concurrency-helpers
// (lib/concurrency.js) zijn losgetrokken (BETON-334).

// BETON-227: workload-weergave (en historische priority-diffs, BETON-311)
// loopt via de centrale vertaallaag, zodat de activity-timeline nooit een
// ruwe enum-waarde (urgent/high/…/light/medium/heavy) toont.
import { prioLabel, workloadLabel } from "./labels.js";
import { dueMeta, todayISO } from "./dueDate.js";

/**
 * Groepeer items in kolommen op basis van de states van het project.
 * States bepalen kolomvolgorde; items komen in de kolom met dezelfde state-naam.
 * Items zonder (bekende) state komen in een aparte kolom "(geen state)".
 *
 * Gearchiveerde items (`archived_at` gezet) horen NOOIT in een normale kolom
 * (BETON-100) — de caller haalt ze alleen op als de archief-toggle aanstaat
 * (`?archived=true`), en dat resultaat bevat zowel archiefitems als actieve
 * items. Hier worden ze eruit gefilterd en in een aparte, altijd-laatste
 * "Archief"-kolom gezet (alleen aanwezig als er iets in zit).
 *
 * Elke kolom draagt zijn state-metadata (group/color/closed) mee zodat de UI de
 * stipkleur en het gesloten-gedrag (inklappen/dempen) kan bepalen. De
 * archief-kolom start dichtgeklapt (`closed: true`) en draagt `archived: true`
 * zodat de UI hem herkenbaar apart kan stylen.
 *
 * @param {Array<{name: string, group?: string, color?: string, closed?: boolean}>} states
 * @param {Array<{ref: string, state: string|null, archived_at?: string|null}>} items
 * @param {Record<string, number>} [counts]  state-naam → totaal-aantal op de
 *   server (BETON-359, `GET /projects/{key}/state-counts`) — alleen relevant
 *   voor kolommen die de server begrensd heeft (`closed_limit`, dus altijd
 *   `closed`-kolommen); zonder counts (of een count die niet hoger is dan wat
 *   al binnen is) is `hasMore` gewoon false, exact het oude gedrag.
 * @param {Array} [loadedItems] alle geladen items vóór client-side filtering
 * @returns {Array<{name: string, group: ?string, color: ?string, closed: boolean, items: Array, archived?: boolean, total: number, remaining: number, hasMore: boolean}>}
 */
export function buildColumns(states, items, counts = {}, loadedItems = items) {
  const columns = states.map((s) => ({
    name: s.name,
    group: s.group ?? null,
    color: s.color ?? null,
    closed: !!s.closed,
    items: [],
  }));
  const byName = new Map(columns.map((c) => [c.name, c]));
  const orphans = { name: "(geen state)", group: null, color: null, closed: false, items: [] };
  const archived = {
    name: "Archief",
    group: null,
    color: null,
    closed: true,
    items: [],
    archived: true,
  };

  for (const item of items) {
    if (item && item.archived_at) {
      archived.items.push(item);
      continue;
    }
    const col = item.state != null ? byName.get(item.state) : undefined;
    (col ?? orphans).items.push(item);
  }
  if (orphans.items.length > 0) columns.push(orphans);
  if (archived.items.length > 0) columns.push(archived);
  // Snelfilters verbergen kaarten zonder ze uit de geladen pagina te halen.
  const loadedCounts = new Map();
  for (const item of loadedItems) {
    if (!item.archived_at) loadedCounts.set(item.state, (loadedCounts.get(item.state) || 0) + 1);
  }
  for (const col of columns) {
    const loaded = col.archived ? col.items.length : Math.max(col.items.length, loadedCounts.get(col.name) || 0);
    const known = col.archived ? undefined : counts[col.name];
    col.total = typeof known === "number" ? Math.max(known, loaded) : loaded;
    col.remaining = col.total - loaded;
    col.hasMore = col.remaining > 0;
  }
  return columns;
}

/** Voeg een vervolgpagina toe; een korte pagina corrigeert een verouderde telling. */
export function appendColumnPage(items, counts, stateName, page, pageSize) {
  const existing = new Set(items.map((item) => item.ref));
  const merged = [...items, ...page.filter((item) => !existing.has(item.ref))];
  if (page.length >= pageSize) return { items: merged, counts };
  const loaded = merged.filter((item) => item.state === stateName && !item.archived_at).length;
  return { items: merged, counts: { ...counts, [stateName]: loaded } };
}

/**
 * Het getal in de kolomkop (BETON-451): het totaal aan tickets in de state, niet
 * het aantal geladen kaarten (een gesloten kolom laadt er maximaal
 * `CLOSED_LIMIT`). Met een actief filter — server-side (state-counts kennen die
 * niet, BETON-397) of client-side — is `col.total` ongefilterd en dus
 * misleidend; dan telt het geladen aantal.
 *
 * @param {{items: any[], total?: number}} col
 * @param {boolean} filtersActive
 */
export function columnCount(col, filtersActive) {
  if (filtersActive) return col.items.length;
  return typeof col.total === "number" ? col.total : col.items.length;
}

/**
 * Bepaalt of de huidige haal-actie een begrensd (`closed_limit`) venster mag
 * gebruiken en of de state-counts opgehaald mogen worden (BETON-397).
 *
 * Twee bugs versterkten elkaar: `GET .../state-counts` kent geen
 * server-filters (`q`/`assignee`/`label`/`workload`/`milestone`) en gaf dus
 * altijd de ONGEFILTERDE tellingen terug, terwijl `hasMore` daaruit berekend
 * werd tegen de wél gefilterde items — resultaat: een "toon meer"-knop op een
 * kolom waar niets meer te halen viel. Tegelijk stuurt `loadBoard` tijdens een
 * tekstzoek bewust geen `closed_limit` mee (BETON-359: een treffer buiten het
 * venster mag niet wegvallen) — en zónder venster kán er per definitie niets
 * bíj te laden zijn.
 *
 * De backend niet uitbreiden met dezelfde vijf filters (dat dupliceert de
 * hele filterclausule + FTS-join van `list_items` in `state_counts`) maar de
 * goedkopere invariant afdwingen: zodra een server-filter actief is, bestaat
 * er geen venster — dus geen `closed_limit` en geen counts. Zonder counts is
 * `col.total === col.items.length` (zie `buildColumns`) en dus `hasMore`
 * structureel `false`.
 *
 * @param {Record<string, any>} filters
 * @param {string[]} serverKeys  filtersleutels die de server al toepast
 *   (App.svelte: `SERVER_FILTER_KEYS`)
 * @param {number} closedLimit  de limiet die gebruikt wordt als er GEEN
 *   server-filter actief is (App.svelte: `CLOSED_LIMIT`)
 * @returns {{closedLimit: number|undefined, wantCounts: boolean}}
 */
export function boardWindow(filters, serverKeys, closedLimit) {
  const serverFiltered = (serverKeys || []).some((k) => filters && filters[k]);
  return {
    closedLimit: serverFiltered ? undefined : closedLimit,
    wantCounts: !serverFiltered,
  };
}

/**
 * Herschik kolommen (uit `buildColumns`) in vaste horizontale volgorde voor het
 * bord (BETON-224): werk-kolommen (`closed: false`) eerst, in hun bestaande
 * onderlinge volgorde (de state-volgorde uit de project-config); daarna de
 * rust-kolommen (`closed: true` — bv. done/cancelled/deferred) als rail aan
 * het eind, óók in hun bestaande onderlinge volgorde; de Archief-kolom
 * (`archived: true`) blijft altijd absoluut laatste, ook ná de rust-rail.
 *
 * Puur en stabiel: gebruikt geen hardcoded state-namen, alleen de `closed`/
 * `archived`-metadata die `buildColumns` al meegeeft — werkt dus ook voor
 * projecten met custom states/groepen. Uitklappen van een rust-kolom
 * verandert alleen zijn `closed`-kolombreedte in de UI, niet zijn positie
 * hier: hij blijft in de rust-rail, ín de rij (schuift niet naar een losse
 * cel), wat exact het gewenste "opent inline"-gedrag geeft.
 *
 * @param {Array<{name: string, closed: boolean, archived?: boolean}>} columns
 * @returns {Array} nieuwe, herschikte array (input blijft ongemoeid)
 */
export function orderColumns(columns) {
  const work = [];
  const resting = [];
  const archived = [];
  for (const col of columns || []) {
    if (col.archived) archived.push(col);
    else if (col.closed) resting.push(col);
    else work.push(col);
  }
  return [...work, ...resting, ...archived];
}

/**
 * Optimistische verplaatsing: geef een nieuwe items-array terug waarin het item
 * met `ref` de nieuwe state heeft. Onbekende ref → ongewijzigd.
 *
 * @param {Array<{ref: string, state: string|null}>} items
 * @param {string} ref
 * @param {string} newState
 */
export function applyMove(items, ref, newState) {
  return items.map((it) => (it.ref === ref ? { ...it, state: newState } : it));
}

/**
 * Optimistische mark-as-read: geef een nieuwe items-array terug waarin het
 * item met `ref` `has_unread = false` heeft (BETON-308). Onbekende ref of
 * al-gelezen item → ongewijzigd.
 *
 * @param {Array<{ref: string, has_unread?: boolean}>} items
 * @param {string} ref
 */
export function applyRead(items, ref) {
  return items.map((it) =>
    it.ref === ref && it.has_unread ? { ...it, has_unread: false } : it,
  );
}

/**
 * Verplaats meerdere items in één keer naar dezelfde state (multi-select,
 * BETON-14). Puur: geeft een nieuwe lijst terug.
 *
 * @param {Array<{ref: string, state: string|null}>} items
 * @param {Iterable<string>} refs   te verplaatsen refs
 * @param {string} newState
 */
export function applyBulkMove(items, refs, newState) {
  const set = refs instanceof Set ? refs : new Set(refs);
  return items.map((it) => (set.has(it.ref) ? { ...it, state: newState } : it));
}

/**
 * Filter een selectie tot de refs die daadwerkelijk van state veranderen
 * (multi-select bulk-move, BETON-14): onbekende refs en refs die al in
 * `newState` staan vallen af, zodat een bulk-move geen no-op-calls doet.
 * Behoudt de volgorde van `refs`.
 *
 * @param {Array<{ref: string, state: string|null}>} items
 * @param {Array<string>} refs      geselecteerde refs
 * @param {string} newState
 * @returns {Array<string>}
 */
export function refsToMove(items, refs, newState) {
  const stateByRef = new Map((items || []).map((it) => [it.ref, it.state]));
  return (refs || []).filter(
    (r) => stateByRef.has(r) && stateByRef.get(r) !== newState
  );
}

/**
 * Optimistische bulk-assign: vervangt de assignee op alle geselecteerde refs.
 * Puur: geeft een nieuwe lijst terug (BETON-140). Lege string = unassign.
 *
 * @param {Array<{ref: string, assignee: string|null}>} items
 * @param {Iterable<string>} refs   toe te wijzen refs
 * @param {string} newAssignee      handle of "" (unassign)
 */
export function applyBulkAssign(items, refs, newAssignee) {
  const set = refs instanceof Set ? refs : new Set(refs);
  return items.map((it) => (set.has(it.ref) ? { ...it, assignee: newAssignee || null } : it));
}

/**
 * Optimistische bulk-label: voegt `name` toe aan (of verwijdert 'm van) de
 * `labels`-array van elk geselecteerd item (BETON-360). Puur: geeft een
 * nieuwe lijst terug; items die de gevraagde toestand al hebben (label al
 * aanwezig bij `add`, of al afwezig bij verwijderen) blijven ongewijzigd
 * (zelfde referentie), zodat een re-render niets onnodig aanraakt.
 *
 * @param {Array<{ref: string, labels?: Array<string>}>} items
 * @param {Iterable<string>} refs   geselecteerde refs
 * @param {string} name             labelnaam
 * @param {boolean} add             true = toevoegen, false = verwijderen
 */
export function applyBulkLabel(items, refs, name, add) {
  const set = refs instanceof Set ? refs : new Set(refs);
  return items.map((it) => {
    if (!set.has(it.ref)) return it;
    const labels = it.labels || [];
    const has = labels.includes(name);
    if (add === has) return it; // al in de gevraagde toestand
    return {
      ...it,
      labels: add ? [...labels, name] : labels.filter((l) => l !== name),
    };
  });
}

/**
 * Optimistische bulk-veldwijziging: zet `field` (milestone/workload) op
 * `value` voor elk geselecteerd item (BETON-360). Generiek i.p.v. twee losse
 * functies — beide velden zijn een platte scalar-vervanging, zoals
 * `applyBulkAssign` voor assignee.
 *
 * @param {Array<Record<string, any>>} items
 * @param {Iterable<string>} refs   geselecteerde refs
 * @param {string} field            bv. "milestone" of "workload"
 * @param {*} value
 */
export function applyBulkField(items, refs, field, value) {
  const set = refs instanceof Set ? refs : new Set(refs);
  return items.map((it) => (set.has(it.ref) ? { ...it, [field]: value } : it));
}

/**
 * Refs tussen `anchor` en `target` (inclusief), in de volgorde van
 * `orderedRefs` — voor shift-klik-bereikselectie (BETON-360). Ontbreekt
 * `target` in `orderedRefs`, dan is er niets te selecteren (lege lijst).
 * Ontbreekt `anchor` (bv. weg door een filter-wissel), dan valt het bereik
 * terug op alleen `target` zelf.
 *
 * @param {Array<string>} orderedRefs  zichtbare volgorde (kolom of lijst)
 * @param {string} anchor              vorige klik
 * @param {string} target              huidige klik
 * @returns {Array<string>}
 */
export function rangeBetween(orderedRefs, anchor, target) {
  const refs = orderedRefs || [];
  const it = refs.indexOf(target);
  if (it === -1) return [];
  const ia = refs.indexOf(anchor);
  if (ia === -1) return [target];
  const [lo, hi] = ia <= it ? [ia, it] : [it, ia];
  return refs.slice(lo, hi + 1);
}

/**
 * Toggle een ref in een selectie-array (multi-select). Puur: geeft een nieuwe
 * array terug, zodat Svelte-reactiviteit meekomt.
 *
 * @param {Array<string>} selection  huidige selectie
 * @param {string} ref
 * @returns {Array<string>}
 */
export function toggleSelection(selection, ref) {
  return selection.includes(ref)
    ? selection.filter((r) => r !== ref)
    : [...selection, ref];
}

/**
 * Dag-ISO-string `days` dagen na `dateISO` (UTC-kalenderdag, geen tijdzone-
 * afhankelijkheid). Hulpje voor het "due binnen 7 dagen"-snelfilter.
 * @param {string} dateISO  YYYY-MM-DD
 * @param {number} days
 * @returns {string}
 */
function addDaysISO(dateISO, days) {
  const d = new Date(`${dateISO}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/**
 * Client-side filter (server filtert al assignee/label/workload/milestone/q;
 * dit houdt de UI snel bij lokale wijzigingen). Alle opgegeven filters zijn
 * AND-gecombineerd.
 *
 * BETON-357: snelfilters — allemaal client-side op velden die al in de
 * compacte item-rij staan (`has_unread`, `has_open_question`, `due_date`,
 * `assignee`, `state`), dus geen extra fetch:
 *   - `mine`       → assignee === ctx.me
 *   - `unread`     → has_unread
 *   - `question`   → has_open_question
 *   - `unassigned` → geen assignee
 *   - `due`        → "overdue" (te laat) of "week" (binnen 7 dagen, niet te laat)
 *   - `state`      → exacte state-naam (alleen relevant in de lijstweergave)
 *
 * `q` wordt hier BEWUST niet herfilterd (BETON-396): de server matcht 'm op
 * ref, omschrijving en comments (FTS), terwijl deze functie alleen de titel
 * kent. Een client-side herfiltering op titel gooit dus elke treffer weg die
 * via een ander veld matchte — precies wat er gebeurde toen zoeken op een ref
 * (`376`) een leeg bord opleverde terwijl de server netjes één item terug gaf.
 * `items` komt bij een actieve `q` altijd rechtstreeks van de server (zie
 * `SERVER_FILTER_KEYS`/`canApplyIncremental` in App.svelte), dus herfilteren
 * kan hier alleen maar schade aanrichten, nooit iets toevoegen.
 *
 * @param {Array} items
 * @param {{assignee?: string, label?: string, workload?: string, q?: string,
 *   mine?: boolean, unread?: boolean, question?: boolean, unassigned?: boolean,
 *   due?: ""|"week"|"overdue", state?: string}} filters
 * @param {{me?: string|null, today?: string}} [ctx]  `me` = eigen handle (voor
 *   `mine`); `today` injecteerbaar voor tests (default: vandaag, lokaal).
 */
export function filterItems(items, filters = {}, { me, today = todayISO() } = {}) {
  const { assignee, label, workload, mine, unread, question, unassigned, due, state } = filters;
  return items.filter((it) => {
    if (assignee && it.assignee !== assignee) return false;
    if (workload && it.workload !== workload) return false;
    if (label && !(it.labels || []).includes(label)) return false;
    if (mine && it.assignee !== me) return false;
    if (unread && !it.has_unread) return false;
    if (question && !it.has_open_question) return false;
    if (unassigned && it.assignee) return false;
    if (state && it.state !== state) return false;
    if (due === "overdue") {
      if (dueMeta(it.due_date, today)?.kind !== "overdue") return false;
    } else if (due === "week") {
      if (!it.due_date) return false;
      const day = it.due_date.slice(0, 10);
      if (day < today || day > addDaysISO(today, 7)) return false;
    }
    return true;
  });
}

/**
 * Sorteeropties voor de board-kolommen (BETON-58, BETON-141). `key` = persistente
 * id, `label` = NL-tekst voor het keuzemenu. Default = laatst gewijzigd (BETON-141):
 * een nieuw of recent bewerkt ticket verschijnt bovenaan i.p.v. weg te zakken in
 * de werklast-bucket.
 */
export const SORT_OPTIONS = [
  { key: "activity-desc", label: "Laatst gewijzigd" },
  { key: "workload", label: "Werklast" },
  { key: "created-desc", label: "Nieuwste eerst" },
  { key: "created-asc", label: "Oudste eerst" },
];
export const DEFAULT_SORT = "activity-desc";

// BETON-311: werklast-rang (zwaar → licht; leeg/onbekend onderaan).
const WORKLOAD_RANK = { heavy: 3, medium: 2, light: 1 };
function workloadRank(w) {
  return WORKLOAD_RANK[w] ?? 0;
}
function tsOf(field) {
  return (it) => {
    const t = Date.parse(it && it[field]);
    return Number.isNaN(t) ? 0 : t;
  };
}
const activityTs = tsOf("last_activity_at");
const createdTs = tsOf("created_at");
const SORTERS = {
  // Zwaar→licht; gelijke werklast behoudt de serverorde (stabiele sort).
  workload: (a, b) => workloadRank(b.workload) - workloadRank(a.workload),
  "created-desc": (a, b) => createdTs(b) - createdTs(a),
  "created-asc": (a, b) => createdTs(a) - createdTs(b),
  "activity-desc": (a, b) => activityTs(b) - activityTs(a),
};

/**
 * Sorteer items (bv. binnen een board-kolom) volgens een sorteersleutel.
 * Puur en immutable: geeft een nieuwe array terug; onbekende sleutel → de
 * volgorde blijft ongemoeid (serverorde). JS-sort is stabiel, dus gelijke
 * sleutels behouden hun onderlinge volgorde.
 *
 * @param {Array} items
 * @param {"workload"|"created-desc"|"created-asc"|string} [sort]
 * @returns {Array}
 */
export function sortItems(items, sort = DEFAULT_SORT) {
  const arr = [...(items || [])];
  const cmp = SORTERS[sort];
  return cmp ? arr.sort(cmp) : arr;
}

/**
 * Kolommen voor de lijst/tabel-view (BETON-54). `key` = veld/sorteersleutel,
 * `label` = NL-koptekst. De volgorde bepaalt de kolomvolgorde in de tabel.
 */
export const LIST_COLUMNS = [
  { key: "ref", label: "Ref" },
  { key: "title", label: "Titel" },
  { key: "state", label: "Status" },
  { key: "workload", label: "Werklast" },
  { key: "assignee", label: "Toegewezen aan" },
  { key: "labels", label: "Labels" },
  { key: "milestone", label: "Milestone" },
  { key: "last_activity_at", label: "Bijgewerkt" },
  { key: "created_at", label: "Aangemaakt" },
];

/** Sorteersleutel → vergelijkbare waarde uit een item-rij. */
function rowSortValue(item, key) {
  switch (key) {
    case "workload":
      return workloadRank(item.workload);
    case "labels":
      return (item.labels || []).join(", ").toLowerCase() || null;
    case "created_at":
    case "due_date":
    case "last_activity_at": {
      const t = Date.parse(item[key]);
      return Number.isNaN(t) ? null : t;
    }
    case "ref": {
      // Sorteer op project-key, dan numeriek op seq (SOS-9 vóór SOS-10).
      const m = /^([A-Za-z0-9]+)-(\d+)$/.exec(item.ref || "");
      return m ? [m[1].toUpperCase(), Number(m[2])] : [String(item.ref || ""), 0];
    }
    default: {
      const v = item[key];
      return v == null || v === "" ? null : String(v).toLowerCase();
    }
  }
}

/** Vergelijk twee (mogelijk array/number/string) niet-null sorteerwaarden. */
function compareValues(a, b) {
  if (Array.isArray(a) && Array.isArray(b)) {
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      const av = a[i] == null ? "" : a[i];
      const bv = b[i] == null ? "" : b[i];
      const c = compareValues(av, bv);
      if (c !== 0) return c;
    }
    return 0;
  }
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a) < String(b) ? -1 : String(a) > String(b) ? 1 : 0;
}

/**
 * Sorteer lijst-rijen op een kolom (BETON-54). Puur en immutable: geeft een
 * nieuwe array terug. `dir` is 'asc' of 'desc'. Onbekende sleutel → serverorde.
 * Lege waarden komen altijd achteraan (ongeacht richting); de sort is stabiel.
 *
 * @param {Array} items
 * @param {string} key   kolom-sleutel uit LIST_COLUMNS
 * @param {"asc"|"desc"} [dir]
 * @returns {Array}
 */
export function sortRows(items, key, dir = "asc") {
  const arr = [...(items || [])];
  if (!key) return arr;
  const factor = dir === "desc" ? -1 : 1;
  return arr
    .map((it, i) => [it, i, rowSortValue(it, key)])
    .sort((x, y) => {
      const av = x[2];
      const bv = y[2];
      if (av == null && bv == null) return x[1] - y[1];
      if (av == null) return 1; // lege waarden altijd achteraan
      if (bv == null) return -1;
      return factor * compareValues(av, bv) || x[1] - y[1];
    })
    .map((triple) => triple[0]);
}

/**
 * Bepaal de volgende sorteerstand bij een klik op een kolomkop (BETON-54):
 * klik op een andere kolom → die kolom, oplopend; klik op de actieve kolom →
 * richting omdraaien.
 *
 * @param {{key: string|null, dir: "asc"|"desc"}} current
 * @param {string} key  aangeklikte kolom
 * @returns {{key: string, dir: "asc"|"desc"}}
 */
export function nextSort(current, key) {
  if (current && current.key === key) {
    return { key, dir: current.dir === "asc" ? "desc" : "asc" };
  }
  return { key, dir: "asc" };
}

/**
 * Haal de nieuwe (`to`) waarde uit een veld dat als {from,to} óf als kale waarde
 * kan binnenkomen (backwards-compatible met oudere events).
 */
function toVal(v) {
  return v && typeof v === "object" && "to" in v ? v.to : v;
}
function fromVal(v) {
  return v && typeof v === "object" && "from" in v ? v.from : undefined;
}

/**
 * Vat een item.updated-payload samen tot leesbare tekst. Velden komen als
 * {from,to} binnen (fase A) — state/priority tonen de overgang expliciet.
 * @param {Record<string, any>} p
 */
function summarizeUpdate(p) {
  const parts = [];
  const dash = (x) => (x === undefined || x === null || x === "" ? "—" : x);
  // BETON-354: de deferred-reactivatie benoemt zijn aanleiding in payload.reason
  // (spiegelt item.locked). Zonder dat las de regel als een kale statuswissel
  // zonder waarom — en met een actorloos event zelfs als "@? status: ... → ...".
  if (p.reason === "deferred_expired") parts.push("uitstel verlopen");
  if ("state" in p) parts.push(`status: ${dash(fromVal(p.state))} → ${dash(toVal(p.state))}`);
  // Priority is uitgefaseerd (BETON-311), maar oude events dragen nog een
  // priority-diff — die blijven we leesbaar tonen in de historie.
  if ("priority" in p) {
    const prio = (x) => (x === undefined || x === null || x === "" ? "—" : prioLabel(x));
    parts.push(`prioriteit: ${prio(fromVal(p.priority))} → ${prio(toVal(p.priority))}`);
  }
  if ("workload" in p) {
    const wl = (x) => workloadLabel(x);
    parts.push(`werklast: ${wl(fromVal(p.workload))} → ${wl(toVal(p.workload))}`);
  }
  if ("assignee" in p) {
    const t = toVal(p.assignee);
    parts.push(t ? `toegewezen aan @${t}` : "toewijzing gewist");
  }
  if ("title" in p) parts.push("titel gewijzigd");
  if ("description_md" in p) parts.push("omschrijving gewijzigd");
  if ("parent" in p) {
    const t = toVal(p.parent);
    parts.push(t ? `parent → ${t}` : "parent losgekoppeld");
  }
  if ("milestone" in p) {
    const t = toVal(p.milestone);
    parts.push(t ? `milestone → ${t}` : "milestone gewist");
  }
  if ("labels" in p) {
    const t = toVal(p.labels);
    parts.push(t && t.length ? `labels: ${t.join(", ")}` : "labels gewist");
  }
  // BETON-218: het plan-event draagt bewust geen inhoud, alleen een marker
  // ({changed, cleared}) — de tekst volgt de marker.
  if ("plan_md" in p) parts.push(p.plan_md?.cleared ? "plan gewist" : "plan bijgewerkt");
  return parts.length ? parts.join(", ") : "bijgewerkt";
}

/**
 * Zet een activity-event om naar een leesbare beschrijving (NL).
 * @param {{type: string, payload?: Record<string, any>}} event
 * @returns {string}
 */
export function describeEvent(event, locale = "nl") {
  if (locale === "en") return describeEventEnglish(event);
  const p = event.payload || {};
  switch (event.type) {
    case "item.created":
      return "ticket aangemaakt";
    case "item.updated":
      return summarizeUpdate(p);
    case "item.archived":
      return "gearchiveerd";
    case "item.moved":
      // BETON-272: toon ook waar het item vandaan kwam (payload draagt from+to).
      return p.from ? `verplaatst van ${p.from} naar ${p.to}` : `verplaatst naar ${p.to}`;
    case "question.answered":
      // BETON-274: leesbaar i.p.v. de rauwe event-type; de UI maakt de regel
      // klikbaar naar de vraag-comment (payload.comment_id).
      return "beantwoordde de vraag";
    case "item.restored":
      return "hersteld uit archief";
    // BETON-302/338: de noodstop. Zonder deze cases viel het door naar `default`
    // en verscheen het rauwe event-type ("item.locked") in de tijdlijn staan.
    case "item.locked":
      return p.reason === "comment_limit"
        ? "zette het ticket op slot — te veel reacties"
        : "zette het ticket op slot (noodstop)";
    case "item.unlocked":
      return p.headroom
        ? `haalde het slot eraf — ruimte voor ${p.headroom} reacties`
        : "haalde het slot eraf";
    // BETON-420/422: de payload draagt bewust geen tekst, alleen een marker.
    case "item.guardrail_set":
      return "zette een guardrail";
    case "item.guardrail_lifted":
      return "hief de guardrail op";
    case "item.guardrail_proposed":
      return p.guardrail?.proposal === "lift"
        ? "stelde voor de guardrail op te heffen"
        : "stelde een guardrail voor";
    case "item.guardrail_rejected":
      return "wees het guardrail-voorstel af";
    // BETON-463: interne bot-event; zonder deze case stond het rauwe type in de feed.
    case "wiki.compiled": {
      const pages = Array.isArray(p.pages) ? p.pages : [];
      if (p.skipped || !pages.length) return "wiki-compilatie overgeslagen";
      return `wiki bijgewerkt: ${pages.join(", ")}`;
    }
    case "comment.created":
      return "reageerde";
    case "comment.updated":
      return "reactie bewerkt";
    case "comment.deleted":
      return "reactie verwijderd";
    case "relation.created":
      return `relatie gelegd: ${p.type} ${p.target}`;
    case "relation.deleted":
      return `relatie verwijderd: ${p.type} ${p.target}`;
    default:
      return event.type;
  }
}

/**
 * Comments staan al in hun eigen gesprekstijdlijn. Houd ze uit de compacte
 * activiteitentijdlijn, zonder de onderliggende events voor andere consumers
 * (webhooks, inbox) te verwijderen.
 * @param {Array<{type: string}>} events
 * @returns {Array<{type: string}>}
 */
export function timelineEvents(events) {
  return events.filter((event) => !event.type.startsWith("comment."));
}

/**
 * Groepeer project-activiteitenevents per dag (BETON-372), nieuwste dag
 * eerst — de volgorde binnen elke dag wordt overgenomen zoals aangeleverd
 * (de backend levert al nieuwste-eerst). Dagsleutel is de lokale kalenderdag
 * van `created_at`, niet UTC-middernacht — anders springt een event van
 * 23:30 lokale tijd naar de volgende dag in de groepering.
 *
 * @param {Array<{created_at: string}>} events
 * @returns {Array<{day: string, events: Array}>}  `day` = "YYYY-MM-DD" lokaal
 */
export function groupByDay(events) {
  const map = new Map();
  for (const event of events || []) {
    const d = new Date(event.created_at);
    const day = Number.isNaN(d.getTime())
      ? "onbekend"
      : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
          d.getDate()
        ).padStart(2, "0")}`;
    if (!map.has(day)) map.set(day, []);
    map.get(day).push(event);
  }
  return [...map.entries()].map(([day, events]) => ({ day, events }));
}

/**
 * Relatieve, leesbare tijd (NL) t.o.v. `now`. Voor de tooltip met absolute tijd
 * is er absoluteTime().
 * @param {string} iso  ISO-8601 timestamp (UTC, met Z)
 * @param {number} [now]  referentiemoment in ms (default Date.now())
 */
export function formatTimestamp(iso, now = Date.now(), locale = "nl") {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso ?? "";
  const secs = Math.round((now - t) / 1000);
  if (secs < 45) return locale === "en" ? "just now" : "zojuist";
  const mins = Math.round(secs / 60);
  if (mins < 60) return locale === "en" ? `${mins} min ago` : `${mins} min geleden`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return locale === "en" ? `${hrs} h ago` : `${hrs} u geleden`;
  const days = Math.round(hrs / 24);
  if (days < 7) return locale === "en" ? `${days} d ago` : `${days} d geleden`;
  return new Date(t).toLocaleDateString(locale === "en" ? "en-GB" : "nl-NL");
}

/** Een reeks toont gelijke afgeronde tijden slechts eenmaal (BETON-488). */
export function formatTimeRange(first, last, now = Date.now(), locale = "nl") {
  const start = formatTimestamp(first, now, locale);
  const end = formatTimestamp(last, now, locale);
  return start === end ? start : `${start}–${end}`;
}

/** Absolute lokale tijd voor in een tooltip. */
export function absoluteTime(iso, locale = "nl") {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? iso ?? "" : new Date(t).toLocaleString(locale === "en" ? "en-GB" : "nl-NL");
}

/** Escape HTML zodat gebruikerstekst nooit als markup wordt geïnterpreteerd. */
export function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Regex voor een ticketref zoals `BETON-91` (project-key gevalideerd tegen knownProjectKeys). */
const TICKETREF_RE = /\b([A-Z][A-Z0-9]*)-(\d+)\b/g;

/**
 * Vervang ticketrefs (bv. `BETON-91`) in tekst-segmenten van al-gerenderde HTML
 * door klikbare ankers, zonder in tags/attributen of `<code>`/`<pre>`-blokken te
 * breken (BETON-106). Werkt door de HTML te splitsen op tags: alleen de
 * tekst-segmenten (niet de tags zelf) worden doorzocht, en segmenten binnen
 * `<code>`/`<pre>` worden overgeslagen.
 *
 * Ook overgeslagen: de zichtbare tekst van een **autolink** (`data-autolink`,
 * BETON-406) — een kale URL die markdown-it's `linkify` omzette naar een
 * `<a>`. Die tekst IS de URL zelf; een ticketref-achtig patroon daarin
 * (`https://x.nl/BETON-123`) zou anders een tweede `<a>` binnen die eerste
 * openen, wat de browser als geneste ankers niet correct weergeeft en de
 * klikbaarheid van de buitenste link breekt. Voor een **handmatige**
 * markdown-link (`[BETON-91](url)`) geldt dat risico niet op dezelfde manier
 * — de linktekst is dan een bewuste keuze van de auteur, geen kopie van de
 * URL — en dat blijft ongewijzigd gelinkificeerd (bestaand gedrag, BETON-107).
 * @param {string} html
 * @param {Set<string>} keys bekende project-keys (uppercase)
 * @returns {string}
 */
export function linkifyTicketRefs(html, keys) {
  if (!keys.size) return html;
  const parts = html.split(/(<[^>]+>)/);
  let codeDepth = 0;
  let preDepth = 0;
  let autolinkDepth = 0;
  const anchor = (m) => `<a class="ticketlink" data-ticket="${m}" role="link" tabindex="0">${m}</a>`;
  return parts
    .map((part, i) => {
      if (/^<[^>]+>$/.test(part)) {
        if (/^<code(\s|>)/i.test(part)) codeDepth++;
        else if (/^<\/code>$/i.test(part)) codeDepth = Math.max(0, codeDepth - 1);
        else if (/^<pre(\s|>)/i.test(part)) preDepth++;
        else if (/^<\/pre>$/i.test(part)) preDepth = Math.max(0, preDepth - 1);
        else if (/^<a\b[^>]*\bdata-autolink="1"/i.test(part)) autolinkDepth++;
        else if (/^<\/a>$/i.test(part)) autolinkDepth = Math.max(0, autolinkDepth - 1);
        return part;
      }
      if (preDepth > 0 || autolinkDepth > 0) return part;
      if (codeDepth > 0) {
        // BETON-433: inline code die uit precies één bekende ref bestaat
        // (`TODAY-44`) is een verwijzing en wordt klikbaar; code met meer
        // tekst blijft letterlijk. split levert om-en-om tekst/tag, dus de
        // buren van dit segment zijn de open- en sluittag.
        const exact = /^([A-Z][A-Z0-9]*)-(\d+)$/.exec(part);
        const whole = /^<code(\s|>)/i.test(parts[i - 1] ?? "") && /^<\/code>$/i.test(parts[i + 1] ?? "");
        return exact && whole && keys.has(exact[1]) ? anchor(part) : part;
      }
      return part.replace(TICKETREF_RE, (m, key) => (keys.has(key) ? anchor(m) : m));
    })
    .join("");
}

/**
 * Kies een project-key (case-insensitief) uit de bekende projecten. Valt terug
 * op het eerste project, of `null` als er geen projecten zijn. Gebruikt bij boot
 * (deep-link-project) en back/forward-navigatie.
 *
 * @param {Array<{key: string}>} projects
 * @param {string|null|undefined} wanted  gewenste key (bv. uit de route)
 * @returns {string|null}
 */
export function resolveProject(projects, wanted) {
  if (wanted) {
    const hit = (projects || []).find((p) => p.key.toUpperCase() === wanted);
    if (hit) return hit.key;
  }
  return (projects || []).find((p) => !p.archived_at)?.key ?? projects?.[0]?.key ?? null;
}

/**
 * Haal de project-key uit een ref (`BRAND-14` → `BRAND`). Null bij onzin.
 * @param {string} ref
 * @returns {string|null}
 */
export function projectKeyOf(ref) {
  const m = /^([A-Za-z0-9]+)-\d+$/.exec(String(ref ?? ""));
  return m ? m[1].toUpperCase() : null;
}

/**
 * Groepeer "Mijn tickets"-rijen op state of op project (BETON-55). Behoudt de
 * invoervolgorde binnen elke groep en de volgorde waarin groepen voor het eerst
 * voorkomen. Lege state/ref valt terug op een leesbaar restlabel.
 *
 * @param {Array<{ref: string, state?: string}>} rows
 * @param {"state"|"project"} by
 * @returns {Array<{label: string, items: Array}>}
 */
export function groupMine(rows, by) {
  const map = new Map();
  for (const it of rows || []) {
    const key =
      by === "state"
        ? it.state || "(geen state)"
        : projectKeyOf(it.ref) || "(overig)";
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(it);
  }
  return [...map.entries()].map(([label, items]) => ({ label, items }));
}

/**
 * Verrijk cross-project zoekresultaten met hun project-key + -naam, zodat de
 * platte resultatenlijst per resultaat kan tonen waar het vandaan komt
 * (BETON-7). Onbekende key valt terug op de key zelf als label.
 *
 * @param {Array<{ref: string}>} rows      compacte zoekresultaten (met ref)
 * @param {Array<{key: string, name: string}>} projects
 * @returns {Array} rows met extra `project` (key) en `projectName`
 */
export function annotateSearchResults(rows, projects = []) {
  const nameByKey = new Map((projects || []).map((p) => [p.key.toUpperCase(), p.name]));
  return (rows || []).map((r) => {
    const key = projectKeyOf(r.ref);
    return { ...r, project: key, projectName: (key && nameByKey.get(key)) || key };
  });
}

/**
 * Is dit keyboard-event de "indienen/opslaan"-sneltoets (Cmd+Enter op Mac,
 * Ctrl+Enter elders)? Zo werkt de submit-chord consistent in álle velden —
 * ook in een <textarea>, waar een kale Enter een gewone regeleinde blijft.
 *
 * @param {{key: string, metaKey?: boolean, ctrlKey?: boolean, isComposing?: boolean}} e
 * @returns {boolean}
 */
export function isSubmitChord(e) {
  if (!e || e.isComposing) return false;
  const isEnter = e.key === "Enter" || e.key === "NumpadEnter";
  return isEnter && (e.metaKey === true || e.ctrlKey === true);
}

/**
 * Thema-cyclus voor de handmatige dark-mode-toggle (BETON-61):
 * systeem → licht → donker → systeem. Onbekende invoer valt terug op de
 * cyclus vanaf "systeem" (dus → licht).
 *
 * @param {"system"|"light"|"dark"|string} current
 * @returns {"system"|"light"|"dark"}
 */
const THEMES = ["system", "light", "dark"];
export function nextTheme(current) {
  const i = THEMES.indexOf(current);
  return THEMES[(i + 1) % THEMES.length];
}

/**
 * Naam van de kolom die uitgeklapt moet worden zodat `ref` zichtbaar is op het
 * bord (BETON-200): een zoekresultaat/deep-link kan in een standaard-
 * ingeklapte gesloten kolom (done/cancelled/archief) zitten, waar de kaart
 * anders onzichtbaar blijft. `null` als het item onbekend is, geen state heeft,
 * of al in een open kolom zit — dan hoeft er niets uitgeklapt te worden.
 *
 * @param {Array<{ref: string, state: string|null}>} items
 * @param {Array<{name: string, closed?: boolean}>} states
 * @param {string} ref
 * @returns {string|null}
 */
export function columnToExpandFor(items, states, ref) {
  const item = items.find((i) => i.ref === ref);
  if (!item || !item.state) return null;
  const state = states.find((s) => s.name === item.state);
  return state && state.closed ? state.name : null;
}

/**
 * Of kolom `col` ingeklapt moet blijven (BETON-230). Gesloten kolommen
 * (done/cancelled/archief) starten ingeklapt en blijven dat tot de gebruiker
 * ze zelf uitklapt (`expandedCols`) — BEHALVE tijdens een actieve zoek/filter
 * met treffers in die kolom: dan zou een matchend ticket anders onzichtbaar
 * blijven (zelfde probleem als BETON-200, maar dan voor de hele resultaatset
 * i.p.v. één genavigeerd item). Lege kolommen worden niet geforceerd
 * uitgeklapt — dat zou alleen ruis toevoegen.
 *
 * @param {{name: string, closed?: boolean, items?: Array}} col
 * @param {Set<string>} expandedCols
 * @param {boolean} hasActiveFilter
 * @returns {boolean}
 */
export function isColumnCollapsed(col, expandedCols, hasActiveFilter) {
  if (!col || !col.closed) return false;
  if (expandedCols && expandedCols.has(col.name)) return false;
  if (hasActiveFilter && (col.items || []).length > 0) return false;
  return true;
}

// State-groep → kleur-token voor het stipje vóór een kolomnaam/state-chip.
// Gedeeld tussen het bord (kolomkop) en de subtakenlijst in de Drawer
// (BETON-203), zodat beide dezelfde stipkleur per status tonen.
const GROUP_COLOR = {
  backlog: "var(--text-tertiary)",
  unstarted: "var(--prio-low)",
  started: "var(--accent)",
  completed: "var(--success)",
  cancelled: "var(--text-tertiary)",
};

/**
 * Stipkleur voor een state-naam: de per-state ingestelde kleur (data) wint;
 * anders de groep-token; anders een neutrale rand-kleur voor een onbekende
 * state (bv. een verwijderde state waar oude items nog naar verwijzen).
 *
 * @param {Array<{name: string, group?: string|null, color?: string|null}>} states
 * @param {string|null|undefined} name
 * @returns {string}
 */
export function stateColor(states, name) {
  const state = states.find((s) => s.name === name);
  if (state?.color) return state.color;
  return GROUP_COLOR[state?.group] ?? "var(--border-strong)";
}

/**
 * Browser-tab-titel (BETON-345): het huidige project vóóraan zodat meerdere
 * open tabbladen uit elkaar te houden zijn, anders (geen project geselecteerd
 * — bv. de globale wiki, of nog niets geladen) gewoon "Betonning". Met een
 * ongelezen-teller > 0 (BETON-368) komt die als `(N)` vooraan, zodat een
 * achtergrondtabblad ook zonder browser-notificatie zichtbaar blijft dat er
 * iets nieuw is.
 *
 * @param {string|null|undefined} projectName
 * @param {number} [unread]
 * @returns {string}
 */
export function pageTitle(projectName, unread = 0) {
  const base = projectName ? `${projectName} · Hegemone` : "Hegemone";
  return unread > 0 ? `(${unread}) ${base}` : base;
}
