// Pure beslissingslogica voor BETON-279: wanneer een duplicaat-relatie gelegd
// wordt, mag het duplicaat gelijk naar de cancelled-state van zijn project.
//
// Semantiek (src/betonning/repo/relations.py:19-23): de opgeslagen item_id
// (src) is ALTIJD het duplicaat, related_item_id (dst) het origineel. Vanuit
// de Drawer van item X (currentRef), met doel Y (targetRef):
//   - "duplicate_of"  → X is het duplicaat (X wordt opgeslagen als src)
//   - "duplicated_by" → Y is het duplicaat (Y wordt opgeslagen als src)
// Cancel dus nooit het canonieke item — alleen de hier berekende duplicateRef.

/**
 * Welk item is het duplicaat voor deze relatie? `null` als het relatietype
 * geen duplicaat-semantiek heeft (blocks/blocked_by/relates_to).
 *
 * @param {string} type - relatietype zoals gekozen in de Drawer
 * @param {string} currentRef - ref van het item waarvan de Drawer open staat
 * @param {string} targetRef - ref van het relatie-doel
 * @returns {string|null}
 */
export function duplicateRefForRelation(type, currentRef, targetRef) {
  if (type === "duplicate_of") return currentRef;
  if (type === "duplicated_by") return targetRef;
  return null;
}

/**
 * Bepaal of het duplicaat gecanceld moet worden, gegeven zijn huidige
 * state-groep en de cancelled-state van zijn eigen project (nooit op naam
 * bepaald — states.grp is genormaliseerd: backlog/unstarted/started/
 * completed/cancelled).
 *
 * Idempotent: een duplicaat dat al completed of cancelled is, wordt
 * overgeslagen. Ontbreekt een cancelled-state in het project, dan gebeurt er
 * niets (geen andere state kiezen) — de caller meldt dat zichtbaar.
 *
 * @param {{stateGroup: string|null|undefined, cancelledStateName: string|null|undefined}} args
 * @returns {{action: "cancel", stateName: string} | {action: "skip", reason: "already-closed"|"no-cancelled-state"}}
 */
export function resolveDuplicateCancelAction({ stateGroup, cancelledStateName }) {
  if (stateGroup === "completed" || stateGroup === "cancelled") {
    return { action: "skip", reason: "already-closed" };
  }
  if (!cancelledStateName) {
    return { action: "skip", reason: "no-cancelled-state" };
  }
  return { action: "cancel", stateName: cancelledStateName };
}
