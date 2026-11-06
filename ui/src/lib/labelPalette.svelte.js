// Reactieve naam→tint-tabellen per project (BETON-461, BETON-472). App.svelte
// zet de tabel van het geopende project zodra de projectlabels geladen zijn;
// alle label-chips lezen via `labelHueOf(name, projectKey)`. Chips van een
// ander project (Alle projecten-zoeken, Overzicht, Mijn tickets) geven de key
// van hun eigen project mee: die tabel wordt lui geladen (één GET per project
// per sessie) en tot hij er is geldt de naam-hash als terugval.
import { labelHue, labelHueMap } from "./avatar.js";

// `byProject` wordt herschreven i.p.v. gemuteerd: een Map in $state is niet
// diep reactief, een nieuwe referentie wel.
const palette = $state({ key: null, byProject: new Map() });
const requested = new Set();
let loader = null;

/** Injecteert hoe de labels van een project worden opgehaald (App: api.labels). */
export function setLabelLoader(fn) {
  loader = fn;
}

function store(key, labels) {
  palette.byProject = new Map(palette.byProject).set(key, labelHueMap(labels));
}

/** Zet de tabel van het geopende project. */
export function setLabelPalette(labels, projectKey) {
  palette.key = projectKey ?? null;
  if (projectKey) {
    requested.add(projectKey);
    store(projectKey, labels);
  } else {
    palette.byProject = new Map(palette.byProject).set(null, labelHueMap(labels));
  }
}

/** Projectkey uit een ref ("BRAND-12" → "BRAND"; keys mogen zelf een streepje bevatten). */
export function projectKeyOfRef(ref) {
  if (!ref) return null;
  const i = ref.lastIndexOf("-");
  return i > 0 ? ref.slice(0, i) : null;
}

/** Laadt de labels van een project één keer; mislukken laat de hash-terugval staan. */
export async function ensureProjectLabels(projectKey) {
  if (!projectKey || requested.has(projectKey) || !loader) return;
  requested.add(projectKey);
  try {
    store(projectKey, await loader(projectKey));
  } catch {
    // Mislukte request: opnieuw proberen bij een volgende render.
    requested.delete(projectKey);
  }
}

export function labelHueOf(name, projectKey) {
  const key = projectKey ?? palette.key;
  const map = palette.byProject.get(key ?? null);
  if (projectKey && projectKey !== palette.key && !map) void ensureProjectLabels(projectKey);
  return map?.get(name) ?? labelHue(name);
}
