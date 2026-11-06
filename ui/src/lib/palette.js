import { translate } from "./i18n.js";

// Pure logica voor het command palette (Cmd+K) en globale sneltoetsen
// (BETON-56). Geen DOM/fetch — getest via vitest.

/**
 * Fuzzy subsequence-score van `query` in `text`. Elke query-letter moet in
 * volgorde voorkomen; aaneengesloten treffers en een match aan het woordbegin
 * scoren hoger. Geen match → `-Infinity`. Lege query → 0 (alles matcht neutraal).
 *
 * @param {string} query
 * @param {string} text
 * @returns {number}
 */
export function fuzzyScore(query, text) {
  const q = String(query ?? "").toLowerCase();
  const t = String(text ?? "").toLowerCase();
  if (!q) return 0;
  let score = 0;
  let ti = 0;
  let prevMatch = -2;
  for (let qi = 0; qi < q.length; qi++) {
    const ch = q[qi];
    let found = -1;
    for (let j = ti; j < t.length; j++) {
      if (t[j] === ch) {
        found = j;
        break;
      }
    }
    if (found === -1) return -Infinity;
    // Bonussen: aaneengesloten (+3), woordbegin (+2), anders +1.
    if (found === prevMatch + 1) score += 3;
    else if (found === 0 || /[\s\-_/.]/.test(t[found - 1])) score += 2;
    else score += 1;
    prevMatch = found;
    ti = found + 1;
  }
  // Kortere strings die volledig matchen scoren iets hoger (minder ruis).
  return score - t.length * 0.01;
}

/**
 * True als `query` als subsequence in `text` past (case-insensitief).
 * @param {string} query
 * @param {string} text
 * @returns {boolean}
 */
export function fuzzyMatch(query, text) {
  return fuzzyScore(query, text) > -Infinity;
}

/**
 * Rangschik commando's/entiteiten op fuzzy-score t.o.v. `query`. Elk item wordt
 * gescoord op zijn `label` plus optionele `keywords` (array of string); het
 * hoogste deelresultaat telt. Niet-matchende items vallen weg. Bij lege query
 * blijft de oorspronkelijke volgorde behouden. Stabiel bij gelijke score.
 *
 * @param {Array<{label: string, keywords?: string|string[]}>} items
 * @param {string} query
 * @returns {Array} de matchende items (zonder toegevoegde velden), best eerst
 */
export function rankItems(items, query) {
  const list = items || [];
  if (!String(query ?? "").trim()) return [...list];
  const scored = [];
  for (let i = 0; i < list.length; i++) {
    const it = list[i];
    const kw = it.keywords == null ? [] : Array.isArray(it.keywords) ? it.keywords : [it.keywords];
    let best = fuzzyScore(query, it.label);
    for (const k of kw) best = Math.max(best, fuzzyScore(query, k));
    if (best > -Infinity) scored.push([it, best, i]);
  }
  scored.sort((a, b) => b[1] - a[1] || a[2] - b[2]);
  return scored.map((s) => s[0]);
}

/**
 * Volgende index bij pijl-navigatie met wrap-around. Lege lijst → 0.
 * @param {number} current
 * @param {number} delta   +1 (omlaag) of -1 (omhoog)
 * @param {number} length
 * @returns {number}
 */
export function moveIndex(current, delta, length) {
  if (!length || length <= 0) return 0;
  return (((current + delta) % length) + length) % length;
}

/**
 * Zit de focus in een tekstinvoer (input/textarea/select, de eigen keuzelijst
 * of contentEditable)?
 * Zulke elementen mogen de kale sneltoetsen niet kapen.
 * @param {EventTarget|null} el
 * @returns {boolean}
 */
export function isTypingTarget(el) {
  if (!el || typeof el !== "object") return false;
  const tag = (el.tagName || "").toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  // Eigen keuzelijst (Select.svelte, BETON-439): de knop en het open menu
  // hebben pijltjes en typen-om-te-springen nodig, net als een native select.
  if (el.closest?.("[data-select-trigger], [data-select-content]")) return true;
  return el.isContentEditable === true;
}

/**
 * Eén tabel voor alle kale (niet-mod, niet-chord) sneltoetsen (BETON-56/64,
 * uitgebreid met acties op de gefocuste kaart/rij en globale navigatie in
 * BETON-361). `scope` bepaalt waar de toets geldig is:
 *  - "global": overal (behalve in een tekstveld/palette/chord — die poorten
 *    zitten in de aanroeper, niet hier).
 *  - "card": werkt op de gefocuste kaart/rij (`focusedRef` in App.svelte,
 *    via `data-ref` — zie `navigateCards`).
 *  - "drawer": alleen relevant terwijl de drawer open is (BETON-362:
 *    vorige/volgende ticket).
 * `extra` komt 1-op-1 terecht in de teruggegeven actie (bv. `delta` voor
 * kaartnavigatie, `chord` voor de g-chord-start).
 */
export const SHORTCUTS = [
  { key: "c", label: "Nieuw ticket", type: "new-item", scope: "global" },
  { key: "/", label: "Zoeken", type: "focus-search", scope: "global" },
  { key: "g", label: "dan projectletter — wissel project", type: "chord-start", scope: "global", extra: { chord: "g" } },
  { key: "ArrowDown", label: "Kaart omlaag", type: "nav-card", scope: "global", extra: { delta: 1 }, hidden: true },
  { key: "j", label: "Kaart omlaag", type: "nav-card", scope: "global", extra: { delta: 1 } },
  { key: "ArrowUp", label: "Kaart omhoog", type: "nav-card", scope: "global", extra: { delta: -1 }, hidden: true },
  { key: "k", label: "Kaart omhoog", type: "nav-card", scope: "global", extra: { delta: -1 } },
  { key: "Enter", label: "Open gefocuste kaart", type: "open-card", scope: "global" },
  { key: "Escape", label: "Sluit overlay", type: "escape", scope: "global" },
  { key: "?", label: "Deze hulp", type: "toggle-hints", scope: "global" },
  { key: "i", label: "Inbox", type: "open-inbox", scope: "global" },
  { key: "v", label: "Wissel bord/lijst", type: "toggle-view", scope: "global" },
  { key: "w", label: "Wiki", type: "open-wiki", scope: "global" },
  { key: "x", label: "Selecteren aan/uit", type: "toggle-select", scope: "card" },
  { key: "a", label: "Toewijzen", type: "quick-assign", scope: "card" },
  { key: "s", label: "Status wijzigen", type: "quick-state", scope: "card" },
  { key: "l", label: "Label toevoegen", type: "quick-label", scope: "card" },
  { key: "e", label: "Bewerken", type: "edit-card", scope: "card" },
  { key: "m", label: "Markeer gelezen", type: "mark-read", scope: "card" },
  { key: "A", shift: true, label: "Geef terug (Shift+A)", type: "handoff", scope: "drawer" },
  { key: "[", label: "Vorig ticket", type: "prev-item", scope: "drawer" },
  { key: "]", label: "Volgend ticket", type: "next-item", scope: "drawer" },
];

/**
 * Bepaal de sneltoets-actie voor een keydown wanneer de focus NIET in een
 * tekstveld staat (BETON-56/64/361). Geeft een actie-descriptor terug of `null`.
 *
 * Ondersteunt: Cmd/Ctrl+K → palette; `g` start een "ga naar"-chord (volgende
 * letter/cijfer kiest een project); alle overige kale toetsen komen uit
 * `SHORTCUTS`.
 *
 * @param {{key: string, metaKey?: boolean, ctrlKey?: boolean, altKey?: boolean, shiftKey?: boolean}} e
 * @param {{chord?: string|null}} [ctx]  actieve chord-staat (bv. 'g')
 * @returns {{type: string, [k: string]: any}|null}
 */
export function shortcutAction(e, ctx = {}) {
  if (!e) return null;
  const key = e.key;
  const mod = e.metaKey || e.ctrlKey;
  if (mod && (key === "k" || key === "K")) return { type: "palette" };
  if (mod || e.altKey) return null; // andere modifier-combo's negeren we

  // Actieve "g"-chord: volgende letter/cijfer = projectkeuze.
  if (ctx.chord === "g") {
    if (/^[a-zA-Z0-9]$/.test(key)) return { type: "goto-project", char: key };
    return { type: "chord-cancel" };
  }

  const entry = SHORTCUTS.find((s) => s.key === key && (!s.shift || e.shiftKey));
  if (!entry) return null;
  return { type: entry.type, ...(entry.extra || {}) };
}

/**
 * Gegroepeerde sneltoets-lijst voor de `?`-overlay (BETON-361). Elke toets
 * uit `SHORTCUTS` komt precies één keer voor (de verborgen pijltjes-aliassen
 * voor j/k worden overgeslagen — ze delen hun label al met j/k), plus de
 * twee die buiten de tabel om afgehandeld worden (⌘K, g-chord-vervolg).
 * @returns {Array<{scope: string, scopeLabel: string, items: Array<{key: string, label: string}>}>}
 */


export function shortcutHelp(locale = "nl") {
  // ⌘K/Ctrl+K wordt vóór de tabel afgehandeld (shortcutAction) en staat er
  // daarom niet in — hier wél nodig zodat de hulp compleet is.
  const extra = [{ key: "⌘K / Ctrl+K", label: "Opdrachtenpalet", type: "palette", scope: "global" }];
  const bySc = new Map();
  for (const s of [...extra, ...SHORTCUTS.filter((s) => !s.hidden)]) {
    if (!bySc.has(s.scope)) bySc.set(s.scope, []);
    const messageKey = s.type === "nav-card" ? (s.extra.delta > 0 ? "nav-down" : "nav-up") : s.type;
    bySc.get(s.scope).push({ key: s.key, label: translate(locale, `shortcut.${messageKey}`) });
  }
  return ["global", "card", "drawer"]
    .filter((scope) => bySc.has(scope))
    .map((scope) => ({ scope, scopeLabel: translate(locale, `shortcut.scope.${scope}`), items: bySc.get(scope) }));
}


// De drawer gebruikt dezelfde tabel als de help, met één invoer-/modifierpoort.
export function drawerShortcutAction(e) {
  if (!e || e.defaultPrevented || isTypingTarget(e.target)) return null;
  const action = shortcutAction(e);
  if (e.repeat && action?.type === "handoff") return null;
  return action && ["prev-item", "next-item", "handoff"].includes(action.type) ? action : null;
}
