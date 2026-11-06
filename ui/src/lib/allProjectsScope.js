// Pure helpers voor de "Alle projecten"-zoekscope (BETON-225). Er is geen
// cross-project "recent gewijzigd"-endpoint — de UI haalt per project de
// (compacte) itemslijst op en voegt die hier samen tot één platte, op
// recentheid gesorteerde lijst voor de lege staat. Los van Svelte/DOM zodat
// het met vitest te testen is.

/**
 * Tijdstip (ms) waarop een item voor het laatst wijzigde. Valt terug op
 * `created_at` (spiegelt `repo/items.py:compact`); onherkenbaar/ontbrekend → 0
 * zodat zulke items altijd achteraan de sortering belanden i.p.v. de sort te
 * laten crashen.
 *
 * @param {{last_activity_at?: string, created_at?: string}} item
 * @returns {number}
 */
function activityTs(item) {
  const raw = item?.last_activity_at || item?.created_at;
  const t = raw ? Date.parse(raw) : NaN;
  return Number.isNaN(t) ? 0 : t;
}

/**
 * Voeg de per-project itemslijsten samen tot één op recentheid gesorteerde
 * (nieuwste eerst) lijst, begrensd op `limit`. Bedoeld voor de "Recent
 * gewijzigd"-sectie in de "Alle projecten"-lege staat.
 *
 * @param {Array<Array<object>>} itemsByProject  resultaat van meerdere api.items()-calls
 * @param {number} [limit]
 * @returns {Array<object>}
 */
export function mergeRecentItems(itemsByProject, limit = 10) {
  const all = (itemsByProject || []).flat().filter(Boolean);
  return [...all].sort((a, b) => activityTs(b) - activityTs(a)).slice(0, limit);
}

/**
 * Zijn de project-specifieke filter-controls (Filter-knop, chips) zinvol in
 * deze zoek-scope? In "Alle projecten" filtert alleen de cross-project /search
 * op tekst — assignee/label/milestone/prioriteit/sorteren/archief werken daar
 * niet, dus die controls horen verborgen te zijn i.p.v. inert getoond (BETON-225).
 *
 * @param {"project"|"all"} scope
 * @returns {boolean}
 */
export function filterControlsVisible(scope) {
  return scope !== "all";
}
