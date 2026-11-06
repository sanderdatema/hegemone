// `@handle`-mention-helpers voor tekstinvoer (comments/omschrijving).
// Losgetrokken uit board.js (BETON-334).

/**
 * Bepaal de mention-query voor autocomplete: de partiële handle direct vóór de
 * caret na een `@`. Geeft null als er geen actieve mention wordt getypt.
 *
 * @param {string} textUpToCaret  tekst van begin tot de cursorpositie
 * @returns {string|null}
 */
export function mentionQuery(textUpToCaret) {
  const m = /(?:^|[^\w-])@([A-Za-z0-9_-]*)$/.exec(textUpToCaret ?? "");
  return m ? m[1] : null;
}

/**
 * Vervang de actieve mention-partial vóór de caret door `@handle ` en geef de
 * nieuwe tekst + nieuwe caretpositie terug.
 *
 * @param {string} text
 * @param {number} caret
 * @param {string} handle
 * @returns {{text: string, caret: number}}
 */
export function applyMention(text, caret, handle) {
  const before = text.slice(0, caret);
  const after = text.slice(caret);
  const replaced = before.replace(/@([A-Za-z0-9_-]*)$/, `@${handle} `);
  return { text: replaced + after, caret: replaced.length };
}
