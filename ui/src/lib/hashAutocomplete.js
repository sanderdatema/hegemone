// Pure #-autocomplete-logica voor ticket-refs (BETON-254), mirror van
// mentionAutocomplete.js/mentionQuery+applyMention (@handle). Twee onafhankelijke
// parsers draaien op dezelfde textarea: @ zoekt users, # zoekt tickets.

/**
 * Vind een actief `#...`-token vlak vóór de caret, net als mentionQuery (@)
 * dat doet. Staat een koppelteken toe (`#BETON-42`) zodat een volledige ref
 * ook als lopende query herkend wordt.
 *
 * @param {string} textUpToCaret
 * @returns {string|null} de tekst na de `#`, of `null` als er geen actief token is
 */
export function hashQuery(textUpToCaret) {
  const m = /(?:^|[^\w-])#([A-Za-z0-9-]*)$/.exec(textUpToCaret ?? "");
  return m ? m[1] : null;
}

/**
 * Splits een hash-query in een letters-deel (project-key-fragment) en een
 * cijfers-deel (seq-fragment). Een koppelteken tussen beide (`BETON-42`)
 * wordt genegeerd. Voorbeelden: "B1" → {letters:"B", digits:"1"};
 * "42" → {letters:"", digits:"42"}; "SOS" → {letters:"SOS", digits:""}.
 *
 * @param {string} query
 * @returns {{letters: string, digits: string}}
 */
export function parseHashQuery(query) {
  const m = /^([A-Za-z]*)-?(\d*)$/.exec(query ?? "");
  if (!m) return { letters: "", digits: "" };
  return { letters: m[1], digits: m[2] };
}

/**
 * Haal project-key + seq uit een ref (`"BETON-42"` → `{key:"BETON", seq:42}`).
 * Project-keys bevatten zelf geen koppelteken, dus het laatste streepje
 * scheidt altijd key en seq — robuuster dan vertrouwen op een `project`-veld
 * in het zoekresultaat.
 *
 * @param {string} ref
 * @returns {{key: string, seq: number}|null}
 */
function splitRef(ref) {
  const i = (ref || "").lastIndexOf("-");
  if (i < 0) return null;
  const key = ref.slice(0, i);
  const seq = Number(ref.slice(i + 1));
  if (!key || Number.isNaN(seq)) return null;
  return { key, seq };
}

/**
 * Filter zoekresultaten (van `api.search`) op de slimme #-regels (BETON-254):
 * - alleen cijfers → alleen tickets in het huidige project.
 * - letters (+ evt. cijfers) → project-key bevat de letters (case-insensitief).
 * - cijfers → de seq bevat de cijfers als substring.
 * `query === null`/leeg (geen actief token) geeft een lege lijst.
 *
 * @param {Array<{ref: string, title?: string}>} results
 * @param {string|null} query ruwe tekst na de `#` (vóór parsing)
 * @param {string} currentProjectKey
 * @param {number} [limit]
 * @returns {Array<{ref: string, title?: string}>}
 */
export function filterTicketCandidates(results, query, currentProjectKey, limit = 6) {
  if (query == null || !query) return [];
  const { letters, digits } = parseHashQuery(query);
  if (!letters && !digits) return [];
  const key = (currentProjectKey || "").toLowerCase();
  const lettersLc = letters.toLowerCase();
  return (results || [])
    .filter((r) => {
      const parsed = splitRef(r.ref);
      if (!parsed) return false;
      if (letters) {
        if (!parsed.key.toLowerCase().includes(lettersLc)) return false;
      } else if (parsed.key.toLowerCase() !== key) {
        return false;
      }
      if (digits && !String(parsed.seq).includes(digits)) return false;
      return true;
    })
    .slice(0, limit);
}

/**
 * Vervang het actieve `#...`-token op de caretpositie door de gekozen ref
 * (+ spatie), mirror van applyMention.
 *
 * @param {string} text
 * @param {number} caret
 * @param {string} ref
 * @returns {{text: string, caret: number}}
 */
export function applyHashRef(text, caret, ref) {
  const before = text.slice(0, caret);
  const after = text.slice(caret);
  const replaced = before.replace(/#([A-Za-z0-9-]*)$/, `${ref} `);
  return { text: replaced + after, caret: replaced.length };
}
