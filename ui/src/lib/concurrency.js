import { translate } from "./i18n.js";

// Optimistic-concurrency-helpers voor PATCH-requests (BETON-44). Losgetrokken
// uit board.js (BETON-334).

/**
 * Bouw de PATCH-body met de optimistic-concurrency-precondition (BETON-44):
 * het gelezen `updated_at` van het item gaat mee als `expected_updated_at`,
 * zodat de server een tussentijdse wijziging kan detecteren. Zonder een geladen
 * item (of zonder updated_at) blijft de body ongewijzigd (last-writer-wins).
 *
 * @param {Record<string, unknown>} body
 * @param {{updated_at?: string}|null|undefined} item
 * @returns {Record<string, unknown>}
 */
export function withPrecondition(body, item) {
  if (!item || !item.updated_at) return { ...body };
  return { ...body, expected_updated_at: item.updated_at };
}

/**
 * Gelokaliseerde conflict-melding voor een 409 uit een PATCH met precondition,
 * of `null` als het geen conflict is (dan hoort de caller de gewone foutmelding
 * te tonen).
 *
 * @param {{status?: number}|null|undefined} err
 * @returns {string|null}
 */
export function conflictMessage(err, locale = "nl") {
  if (!err || err.status !== 409) return null;
  return translate(locale, "detail.conflict");
}
