// Pure URL-routing-helpers voor de kanban-UI: pad ↔ project/ref/querystring,
// en de legacy hash-deeplink-fallback. Losgetrokken uit board.js (BETON-334);
// uitgebreid met de querystring voor filters/view/scope/sort (BETON-358) zodat
// een bord-toestand een deelbare link + werkende back-knop krijgt.
import { FILTER_KEYS, BOOLEAN_FILTER_KEYS } from "./viewState.js";

// Bekende querystring-keys: de filtervelden + view/scope/sort. Alleen déze
// komen terug uit parsePath/gaan de URL in via buildPath — onbekende keys
// (bv. van een oude link, of experimenteren in de adresbalk) worden genegeerd
// i.p.v. straks als los filterveld door de app te lekken. Vaste volgorde
// (FILTER_KEYS, dan view/scope/sort) zodat buildPath een stabiele URL geeft
// (dezelfde toestand → altijd hetzelfde querystring, goed voor deelbare links
// en voor "is de URL al gelijk aan de state" in de sync-effect).
const QUERY_KEYS = [...FILTER_KEYS, "view", "scope", "sort"];

/**
 * Parse een querystring naar een object met alleen bekende keys (`QUERY_KEYS`).
 * Boolean-filtervelden (mine/unread/question/unassigned) komen als "1" de URL
 * binnen en worden hier naar een echte boolean vertaald; de rest blijft een
 * kale string. Lege/onbekende input → `{}`.
 *
 * @param {string} search  `location.search`, met of zonder leidend `?`
 * @returns {Record<string, string|boolean>}
 */
function parseQuery(search) {
  const out = {};
  const usp = new URLSearchParams(String(search ?? "").replace(/^\?/, ""));
  for (const key of QUERY_KEYS) {
    if (!usp.has(key)) continue;
    const raw = usp.get(key);
    out[key] = BOOLEAN_FILTER_KEYS.has(key) ? raw === "1" : raw;
  }
  return out;
}

/**
 * Serialiseer een query-object terug naar een querystring (zonder leidend
 * `?`). Alleen niet-lege waarden gaan mee (lege string, `false`, `null`,
 * `undefined` vallen weg) en altijd in `QUERY_KEYS`-volgorde, zodat dezelfde
 * toestand altijd exact dezelfde querystring geeft (stabiele URL's).
 *
 * @param {Record<string, string|boolean|null|undefined>} query
 * @returns {string}
 */
function buildQuery(query) {
  const usp = new URLSearchParams();
  for (const key of QUERY_KEYS) {
    const v = query?.[key];
    if (v === undefined || v === null || v === "" || v === false) continue;
    usp.set(key, BOOLEAN_FILTER_KEYS.has(key) ? "1" : String(v));
  }
  return usp.toString();
}

/**
 * Parse het URL-pad (+ querystring) naar een route: project-key, (optioneel)
 * de ticket-ref, en de bekende query-velden. Padvormen: `/` → geen route;
 * `/SOS` → project SOS; `/SOS/42` → project SOS + ref `SOS-42`. De
 * project-key wordt geüppercased zodat `/sos/42` hetzelfde oplevert als
 * `/SOS/42` (case-insensitief pad). Onbekende padvormen → null-route (de
 * query wordt wél altijd geparsed, ook zonder geldig project).
 *
 * @param {string} pathname
 * @param {string} [search]  `location.search`
 * @returns {{project: string|null, ref: string|null, query: Record<string, string|boolean>}}
 */
export function parsePath(pathname, search = "") {
  const query = parseQuery(search);
  const parts = String(pathname ?? "")
    .split("/")
    .filter(Boolean);
  if (parts.length === 0 || !/^[A-Za-z0-9]+$/.test(parts[0])) {
    return { project: null, ref: null, query };
  }
  const project = parts[0].toUpperCase();
  if (parts.length === 1) return { project, ref: null, query };
  if (parts.length === 2 && /^\d+$/.test(parts[1])) {
    return { project, ref: `${project}-${parts[1]}`, query };
  }
  return { project, ref: null, query };
}

/**
 * Parse een oude hash-deeplink (`#SOS-42`) naar een route-object. De path-router
 * (`parsePath`) is leidend; dit is enkel de fallback voor legacy hash-links.
 * De project-key wordt geüppercased. Onbekende vormen → null-route.
 *
 * @param {string} hash  waarde van `location.hash` (met of zonder `#`)
 * @returns {{project: string|null, ref: string|null}}
 */
export function parseHashRef(hash) {
  const h = String(hash ?? "").replace(/^#/, "");
  const m = /^([A-Za-z0-9]+)-(\d+)$/.exec(h);
  if (!m) return { project: null, ref: null };
  const key = m[1].toUpperCase();
  return { project: key, ref: `${key}-${m[2]}` };
}

/**
 * Bouw het URL-pad (+ querystring) voor een geopende drawer of geselecteerd
 * project. Als er een `ref` is bepaalt díe het pad (incl. project), zodat
 * cross-project links naar het juiste project wijzen. Anders het losse
 * project. Niets → `/`. `query` is optioneel (BETON-358); alleen bekende,
 * niet-lege velden komen mee, in vaste volgorde (zie `QUERY_KEYS`).
 *
 * @param {string|null} project  huidige project-key
 * @param {string|null} ref      geopende ticket-ref (bv. `SOS-42`)
 * @param {Record<string, string|boolean|null|undefined>} [query]
 * @returns {string}
 */
export function buildPath(project, ref, query = {}) {
  let base;
  if (ref) {
    const m = /^([A-Za-z0-9]+)-(\d+)$/.exec(ref);
    base = m ? `/${m[1].toUpperCase()}/${m[2]}` : project ? `/${project.toUpperCase()}` : "/";
  } else {
    base = project ? `/${project.toUpperCase()}` : "/";
  }
  const qs = buildQuery(query);
  return qs ? `${base}?${qs}` : base;
}
