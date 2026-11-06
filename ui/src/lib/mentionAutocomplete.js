// Pure mention-autocomplete-logica voor NewItem.svelte (BETON-102).
//
// De @-query-parsing (mentionQuery) en het invoegen van een gekozen handle
// (applyMention) bestaan al als pure, geteste functies in lib/mentions.js —
// Drawer.svelte gebruikt ze rechtstreeks. Om duplicatie te vermijden
// hergebruiken we ze hier (re-export) i.p.v. de regex opnieuw te schrijven.
// Wat nog ontbrak als losstaande, testbare functie is de kandidaat-filter:
// in Drawer.svelte zit die inline in onCommentInput — hier geëxtraheerd zodat
// NewItem.svelte 'm kan hergebruiken en los kan testen.
import { mentionQuery, applyMention } from "./mentions.js";

export { mentionQuery, applyMention };

/**
 * Filter de user-lijst op een (partiële, case-insensitive) handle-prefix,
 * zoals Drawer.svelte's comment-mentions doen. `query === null` (geen
 * actieve mention) geeft een lege lijst.
 *
 * @param {Array<{handle: string}>} users
 * @param {string|null} query
 * @param {number} [limit]
 * @returns {Array<{handle: string}>}
 */
export function filterMentionCandidates(users, query, limit = 6) {
  if (query == null) return [];
  const q = query.toLowerCase();
  return (users || [])
    .filter((u) => u.active !== false)
    .filter((u) => (u.handle || "").toLowerCase().startsWith(q))
    .slice(0, limit);
}
