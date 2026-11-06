// Centrale vertaallaag (BETON-227): datawaarden die uit de backend komen als
// Engelse enum (priority, relation-type, state-group, agent-type) worden hier
// éénmalig naar NL-weergave gemapt, zodat geen enkel component een ruwe
// enum-waarde direct rendert. Onbekende waarde → veilige fallback (de ruwe
// waarde zelf), nooit een crash.
//
// States zelf zijn GEEN kandidaat hier: `state.name` is een per-project vrije
// tekst (bv. "Todo"/"In Progress" of een custom kolomnaam) en hoort dus zoals
// hij is getoond te worden — alleen de vaste systeemteksten er omheen zijn NL.

import {
  SignalLow,
  SignalMedium,
  SignalHigh,
  Ban,
  Hourglass,
  Copy,
  Files,
  Link2,
  CornerUpLeft,
} from "@lucide/svelte";

// --- Prioriteit --------------------------------------------------------------
const PRIO_LABELS = {
  none: "Geen",
  low: "Laag",
  medium: "Middel",
  high: "Hoog",
  urgent: "Urgent",
};

/** Vertaal een ruwe priority-enum-waarde naar het NL-label. Onbekend → ruwe waarde.
 *  Priority is uitgefaseerd (BETON-311) — nog aanwezig voor de weergave van
 *  historische activiteit (oude item.updated-events met een priority-diff). */
export function prioLabel(p) {
  return PRIO_LABELS[p] ?? p;
}

// --- Werklast (BETON-311, vervangt priority) ---------------------------------
// Hoeveel tokens een ticket kost. Volgorde licht → zwaar; leeg = nog niet
// geschat. Interne waarden Engels (light/medium/heavy), UI toont NL.
export const WORKLOAD_VALUES = ["light", "medium", "heavy"];

const WORKLOAD_LABELS = {
  light: "Licht",
  medium: "Middel",
  heavy: "Zwaar",
};

/** Vertaal een ruwe workload-waarde naar het NL-label. Leeg → "—"; onbekend → ruwe waarde. */
export function workloadLabel(w, locale = "nl") {
  if (w === undefined || w === null || w === "") return "—";
  if (locale === "en") return ({ light: "Light", medium: "Medium", heavy: "Heavy" })[w] ?? w;
  return WORKLOAD_LABELS[w] ?? w;
}

// Icoon/kleur per werklast (BETON-311/328), gedeeld door WorkloadBadge.svelte —
// voorheen verbatim gedupliceerd als `WORKLOAD_META` in App.svelte en
// ListView.svelte. Alleen de drie bekende waarden hebben een badge; een lege/
// onbekende workload toont geen icoon (`workloadMeta` geeft dan `null`).
const WORKLOAD_META = {
  light: { icon: SignalLow, color: "var(--workload-light)" },
  medium: { icon: SignalMedium, color: "var(--workload-medium)" },
  heavy: { icon: SignalHigh, color: "var(--workload-heavy)" },
};

// Korte tekst op de badge: L / M / Z (BETON-461) — de vorm van een
// signaalbalkje was op 8px niet te lezen en rood leek op urgentie.
const WORKLOAD_SHORT = { light: "L", medium: "M", heavy: "Z" };

/** Geef `{icon, color, label}` voor een workload-waarde, of `null` als er geen
 *  badge getoond moet worden (leeg of onbekend). */
export function workloadMeta(w, locale = "nl") {
  const m = WORKLOAD_META[w];
  return m
    ? {
        ...m,
        label: workloadLabel(w, locale),
        short: locale === "en" && w === "heavy" ? "H" : WORKLOAD_SHORT[w],
        title: `${locale === "en" ? "Workload" : "Werklast"}: ${workloadLabel(w, locale).toLowerCase()} (tokens)`,
      }
    : null;
}

// --- Relatietypen --------------------------------------------------------------
const RELATION_LABELS = {
  parent: "subtaak van",
  blocks: "blokkeert",
  blocked_by: "geblokkeerd door",
  duplicate_of: "duplicaat van",
  duplicated_by: "gedupliceerd door",
  relates_to: "gerelateerd aan",
};

/** Relatietypen die de gebruiker handmatig kan aanmaken (Drawer + NewItem
 *  relatie-picker, BETON-247/331) — bewust zonder `parent` (die volgt uit
 *  decompose/subtaken, niet uit deze picker). */
export const RELATION_TYPES = [
  "relates_to",
  "blocks",
  "blocked_by",
  "duplicate_of",
  "duplicated_by",
];

/** Vertaal een ruwe relation-type-waarde naar het NL-label. Onbekend → ruwe waarde. */
export function relationLabel(r, locale = "nl") {
  if (locale === "en") return ({parent: "subtask of", blocks: "blocks", blocked_by: "blocked by", duplicate_of: "duplicate of", duplicated_by: "duplicated by", relates_to: "related to"})[r] ?? r;
  return RELATION_LABELS[r] ?? r;
}

// Icoon per relatietype voor de kaart (BETON-344) — het label leeft in de
// `title`-tooltip (relationLabel) én als getal in de
// pill zelf (alleen het ticketnummer, geen projectslug — ruis binnen hetzelfde
// board). `duplicate_of`/`duplicated_by` delen geen icoon: de richting (jij
// bent het duplicaat vs. de ander is het duplicaat) is precies het verschil
// dat de kaart moet tonen. `parent` ("subtaak van") komt niet uit de
// relations-tabel maar uit `items.parent_id` — toch hier, want op de kaart is
// het visueel dezelfde soort pill; `.card-progress` toont alleen het
// kind-totaal, niet welke ticket de párent is.
const RELATION_META = {
  parent: { icon: CornerUpLeft },
  blocks: { icon: Ban },
  blocked_by: { icon: Hourglass },
  duplicate_of: { icon: Copy },
  duplicated_by: { icon: Files },
  relates_to: { icon: Link2 },
};

/** Geef `{icon, label}` voor een relatietype, of `null` voor een onbekend type. */
export function relationMeta(type) {
  const m = RELATION_META[type];
  return m ? { ...m, label: relationLabel(type) } : null;
}

// Vaste hue per relatietype (0–360, zelfde `--label-h`-mechanisme als de
// gewone label-chips) — geen hash zoals `labelHue` (dat is voor vrije,
// gebruiker-gedefinieerde labelnamen); dit zijn zes vaste, bekende types, dus
// een bewust gekozen, goed gespreide kleur per betekenis.
const RELATION_HUE = {
  parent: 150, // teal/groen — "hoort bij", geen actie nodig
  blocks: 0, // rood — stopt iets
  blocked_by: 30, // amber — wacht op iets
  relates_to: 210, // blauw — neutrale link
  duplicate_of: 270, // paars
  duplicated_by: 300, // magenta — zelfde familie als duplicate_of, andere richting
};

/** Hue voor een relatietype (BETON-344), voor `style:--label-h`. Onbekend
 *  type → een neutrale blauwe fallback (nooit een crash op een vreemde waarde). */
export function relationHue(type) {
  return RELATION_HUE[type] ?? 210;
}

/** Platte, stabiel geordende lijst `{type, ref}` uit een relations-object
 *  zoals de backend het levert (verb → refs, BETON-344). Volgorde = vaste
 *  RELATION_TYPES-volgorde, dan refs zoals aangeleverd (al gesorteerd door de
 *  backend). Ontbrekende/lege input → lege lijst, geen crash. */
export function relationEntries(relations) {
  if (!relations) return [];
  const out = [];
  for (const type of RELATION_TYPES) {
    for (const ref of relations[type] || []) out.push({ type, ref });
  }
  return out;
}

/** Combineer `parent` (uit `items.parent_id`, dus los van de relations-tabel —
 *  vandaar niet al in `relationEntries`) met de overige relaties tot één
 *  geordende pill-lijst voor de kaart (inclusief subtaken/parent). Parent eerst — "subtaak van" is de belangrijkste
 *  context — dan de rest in `relationEntries`-volgorde.
 *
 *  `duplicated_by` blijft eruit (BETON-349): die staat op het ticket dat
 *  *overblijft* ("een ander ticket is een duplicaat van dit ticket") — een
 *  duplicaat-pill hoort daar niet, want dit ticket zelf dupliceert niets. Op
 *  het duplicaat-ticket zelf toont `duplicate_of` het al. `relationEntries`
 *  blijft bewust compleet (alle 5 verba) — deze uitzondering is kaart-
 *  specifiek, geen eigenschap van "alle relaties van een item".
 *  @param {{parent?: string|null, relations?: object}} item
 *  @returns {Array<{type: string, ref: string}>} */
export function cardRelationPills(item) {
  const out = [];
  if (item?.parent) out.push({ type: "parent", ref: item.parent });
  for (const entry of relationEntries(item?.relations)) {
    if (entry.type !== "duplicated_by") out.push(entry);
  }
  return out;
}

// --- State-groep (ProjectSettings: kolom-groep bij aanmaken/tonen) -----------
const STATE_GROUP_LABELS = {
  backlog: "Backlog",
  unstarted: "Nog niet gestart",
  started: "Gestart",
  completed: "Afgerond",
  cancelled: "Geannuleerd",
};

/** Vertaal een ruwe state-group-waarde naar het NL-label. Onbekend → ruwe waarde. */
export function stateGroupLabel(g, locale = "nl") {
  if (locale === "en") return ({backlog:"Backlog", unstarted:"Not started", started:"Started", completed:"Completed", cancelled:"Cancelled"})[g] ?? g;
  return STATE_GROUP_LABELS[g] ?? g;
}

// --- Agent-type (ProjectSettings: per-agent-toegangslijst) -------------------
const AGENT_TYPE_LABELS = {
  coding: "coding-agent",
  hermes: "Hermes-agent",
};

/** Vertaal een ruwe agent-type-waarde naar het NL-label. Onbekend → ruwe waarde. */
export function agentTypeLabel(t, locale = "nl") {
  if (locale === "en") return ({coding:"Coding agent", hermes:"Webhook agent (Hermes compatible)"})[t] ?? t;
  return AGENT_TYPE_LABELS[t] ?? t;
}

// --- Modellabels (BETON-461, BETON-476) ---------------------------------------
// De drie werkklassen routine/standaard/complex zeggen voor elke agent hoe zwaar
// het werk is (welk model erbij hoort staat in de instellingen). Routing-
// informatie, geen soort werk: op kaart en lijst muted tekst i.p.v. een chip.
export const MODEL_CLASSES = ["routine", "standaard", "complex"];

export function isModelLabel(name) {
  return MODEL_CLASSES.includes(String(name ?? "").toLowerCase());
}

/** Splits labelnamen in `{plain, models}`; volgorde blijft behouden. */
export function splitModelLabels(names) {
  const plain = [];
  const models = [];
  for (const n of names || []) (isModelLabel(n) ? models : plain).push(n);
  return { plain, models };
}

/**
 * Past de gewone labels in één regel (BETON-479): de eerste `max` blijven
 * zichtbaar, de rest wordt `hidden` en in de UI een `+N`-chip met de volledige
 * lijst in `title`. Het modellabel telt niet mee, dat staat altijd achteraan.
 */
export function fitChips(labels, max) {
  const all = labels || [];
  const limit = Math.max(0, max);
  if (all.length <= limit) return { shown: [...all], hidden: [] };
  return { shown: all.slice(0, limit), hidden: all.slice(limit) };
}
