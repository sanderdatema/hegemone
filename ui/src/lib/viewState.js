import { workloadLabel } from "./labels.js";

// Gedeelde localStorage-persistentie (BETON-61/58/54, verplaatst uit
// App.svelte in BETON-364 zodat Drawer.svelte 'm ook kan gebruiken): lees een
// key, valideer tegen wat toegestaan is met een fallback bij ontbreken/
// ongeldige waarde; schrijf een key guarded (localStorage kan ontbreken of
// gooien, bv. privacy-mode).
export function readPersisted(key, isValid, fallback) {
  const v = typeof localStorage !== "undefined" ? localStorage.getItem(key) : null;
  return isValid(v) ? v : fallback;
}
export function writePersisted(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {}
}

// Pure view-model voor de app-shell (BETON-222). Vervangt de losse `view` +
// ~14 `show*`-booleans in App.svelte door één samenhangend model:
//
//   - activeView : de mutually-exclusive basis-content-view (persistent).
//   - overlays   : een LIFO-stack van modale/dialoog-lagen bovenop de basis.
//
// Alle helpers zijn puur (geen Svelte, geen DOM) zodat de transities los
// testbaar zijn (vitest); het component blijft de dunne bind-laag.
//
// NB: Inbox is bewust GEEN activeView-lid maar een overlay — `Inbox.svelte`
// rendert zichzelf als een bits-ui DrawerDialog (portal + focus-trap + eigen
// Escape), dus het hoort in de overlay-stack, niet in de content-enum. De
// primaire nav toont 'm wel als vierde knop (met ongelezen-badge).

// --- Basis-content-view -----------------------------------------------------
// Persistent onder dezelfde localStorage-key als de oude board/lijst-toggle
// (BETON-54), uitgebreid met de wiki-view (BETON-182). Onbekende/ontbrekende
// waarde valt terug op het bord.
// BETON-372: "activity" is de vierde basis-view (de activiteitenfeed).
// BETON-371: "overview" is de vijfde — de stand over ÁLLE projecten.
export const VIEWS = ["board", "list", "wiki", "activity", "overview"];
export const DEFAULT_VIEW = "board";
export const VIEW_KEY = "betonning-view";

export function isView(v) {
  return VIEWS.includes(v);
}
// Valideer een ruwe (localStorage-)waarde tot een geldige view.
export function readView(raw) {
  return isView(raw) ? raw : DEFAULT_VIEW;
}

// Views die niet over één project gaan (wiki heeft een eigen scope-switch,
// activiteit een eigen filterrij, overzicht draait over álle projecten): daar
// horen de project-zoekbalk en de filter-pills van het bord niet bij. Eén
// predicaat i.p.v. drie losse `activeView !== …`-ketens in App.svelte — die
// liepen bij elke nieuwe view uit de pas.
export function hidesProjectFilters(view) {
  return view === "wiki" || view === "activity" || view === "overview";
}

// --- Overlay-stack ----------------------------------------------------------
// Alle niet-basis-lagen: modals, dialoog-panelen en de mobiele filter-sheet.
// De stack is een array; de laatste is de bovenste (top). Overlays worden nooit
// gepersisteerd — je herlaadt niet in een modal.
export const OVERLAYS = [
  "installation",
  "agents",
  "chat",
  "deliveries",
  "settings",
  "projects",
  "userSettings",
  "new",
  "newProject",
  "palette",
  "mine",
  "inbox",
  "filters",
  "hints",
];

export function isOverlay(name) {
  return OVERLAYS.includes(name);
}

// Open een overlay: zet 'm bovenop de stack. Al open? Dan verhuist hij naar de
// top (dedup — nooit twee keer dezelfde laag). Onbekende naam = no-op.
export function pushOverlay(stack, name) {
  if (!isOverlay(name)) return stack;
  const without = (stack || []).filter((o) => o !== name);
  return [...without, name];
}

// Sluit de bovenste overlay (Esc-gedrag). Geeft de nieuwe stack + welke laag
// sloot (of null als er niets openstond).
export function popOverlay(stack) {
  if (!stack || !stack.length) return { stack: stack || [], closed: null };
  return { stack: stack.slice(0, -1), closed: stack[stack.length - 1] };
}

// Sluit een specifieke overlay, waar hij ook in de stack zit (bv. een paneel
// dat zichzelf via onclose sluit). Idempotent.
export function closeOverlay(stack, name) {
  return (stack || []).filter((o) => o !== name);
}

// De bovenste overlay, of null.
export function topOverlay(stack) {
  return stack && stack.length ? stack[stack.length - 1] : null;
}

// Staat een overlay open?
export function hasOverlay(stack, name) {
  return (stack || []).includes(name);
}

// --- Filters ----------------------------------------------------------------
// Welke filtervelden meetellen voor de teller/chips (spiegelt het board-filter
// + de server-side q/milestone). `q` (vrije zoektekst) telt mee.
// BETON-357: snelfilters toegevoegd — mine/unread/question/unassigned zijn
// booleans, due is "" | "week" | "overdue", state geldt alleen in de lijst
// (allemaal client-side, zie board.js:filterItems).
export const FILTER_KEYS = [
  "assignee",
  "label",
  "workload",
  "milestone",
  "q",
  "mine",
  "unread",
  "question",
  "due",
  "unassigned",
  "state",
];

// Filtervelden die booleans zijn (geen waarde te tonen in de chip — het label
// zelf ís de betekenis, bv. "Aan mij" i.p.v. "Aan mij: true"). Ook gebruikt
// door lib/routing.js (BETON-358) om ze in de URL als "1"/afwezig te
// serialiseren i.p.v. "true"/"false".
export const BOOLEAN_FILTER_KEYS = new Set(["mine", "unread", "question", "unassigned"]);

// Leesbare labels voor de "due"-snelfilterwaarden.
const DUE_VALUE_LABELS = { week: "Deze week", overdue: "Te laat" };

// Aantal actieve (niet-lege/niet-false) filters over ÁLLE filtervelden —
// gebruikt voor `isColumnCollapsed` (een zoekterm hoort een ingeklapte kolom
// te openen) en de "wis filters"-rij. BEWUST breed: hier is meetellen van `q`
// en de snelfilter-booleans juist het gewenste gedrag. Niet geschikt voor de
// Filter-knop-badge (zie `countPanelFilters`) — die zou dan een teller tonen
// die niet overeenkomt met wat het paneel toont (BETON-398).
export function countActiveFilters(filters) {
  if (!filters) return 0;
  return FILTER_KEYS.filter((k) => filters[k]).length;
}

// De filtervelden die daadwerkelijk in het Filter-paneel staan (BETON-398):
// toegewezen-aan, label, werklast, milestone. NIET `q` (woont in de
// zoekbalk) en NIET de snelfilters mine/unread/question/due/unassigned/state
// (chiprij onder de topbar, BETON-357) — die zijn nergens in het paneel te
// zien of te wissen.
export const PANEL_FILTER_KEYS = ["assignee", "label", "workload", "milestone"];

// Aantal actieve filters die ook echt in het Filter-paneel staan — voor de
// "Filter · N"-badge op de knop zelf. `archived` ("toon gearchiveerde items")
// telt mee omdat die toggle ook in het paneel staat, maar niet in `filters`
// zit (het is losse UI-state, `showArchived` in App.svelte).
export function countPanelFilters(filters, { archived } = {}) {
  const base = filters ? PANEL_FILTER_KEYS.filter((k) => filters[k]).length : 0;
  return base + (archived ? 1 : 0);
}

// Verwijderbare chips voor de actieve filters (onder de topbar). Elke chip
// draagt de veld-key, een leesbaar label en de waarde; volgorde = FILTER_KEYS.
// BETON-227: veldlabels zijn NL (geen ruwe backend-termen), en de werklast-
// waarde gaat door de centrale vertaallaag i.p.v. de ruwe enum te tonen.
export function activeFilterChips(filters, locale = "nl") {
  if (!filters) return [];
  const LABELS = locale === "en" ? {
    assignee: "Assigned to", label: "Label", workload: "Workload", milestone: "Milestone",
    q: "Search", mine: "Assigned to me", unread: "Unread", question: "Open question",
    due: "Due date", unassigned: "Unassigned", state: "State",
  } : {
    assignee: "Toegewezen aan",
    label: "Label",
    workload: "Werklast",
    milestone: "Milestone",
    q: "Zoek",
    mine: "Aan mij",
    unread: "Ongelezen",
    question: "Open vraag",
    due: "Deadline",
    unassigned: "Zonder assignee",
    state: "Status",
  };
  return FILTER_KEYS.filter((k) => filters[k]).map((k) => {
    if (BOOLEAN_FILTER_KEYS.has(k)) {
      return { key: k, field: LABELS[k], value: null, boolean: true };
    }
    if (k === "due") {
      return { key: k, field: LABELS[k], value: (locale === "en" ? {week: "This week", overdue: "Overdue"} : DUE_VALUE_LABELS)[filters[k]] ?? filters[k] };
    }
    return {
      key: k,
      field: LABELS[k],
      value: k === "workload" ? workloadLabel(filters[k], locale) : filters[k],
    };
  });
}
