// Pure groepsopbouw voor RelatedList.svelte (BETON-471): subtaken en relaties
// delen één lijstvorm (statusstip · ref · titel). Alleen relaties zijn
// verbreekbaar; subtaken niet (die zijn een ouder-kind-koppeling), en de
// parent staat in de drawer-kop.

/**
 * @typedef {{ref: string, title: string, state: string|null}} RelatedItem
 * @typedef {{type: string, label: string, items: RelatedItem[], removable: boolean}} RelatedGroup
 */

/**
 * Subtaken als één groep zonder kop (de rij heeft zelf het label "Subtaken").
 *
 * @param {{children_detail?: Array<{ref: string, title?: string, state?: string|null}>}|null} item
 * @returns {RelatedGroup[]}
 */
export function subtaskGroups(item) {
  const kids = item?.children_detail || [];
  if (!kids.length) return [];
  return [
    {
      type: "subtasks",
      label: "",
      removable: false,
      items: kids.map((c) => ({ ref: c.ref, title: c.title ?? "", state: c.state ?? null })),
    },
  ];
}

/**
 * Relaties per type, in de volgorde van de backend (blocks, blocked_by,
 * duplicate_of, duplicated_by, relates_to). Gebruikt `relations_detail`; valt
 * terug op kale refs (zonder titel/state) als die ontbreekt. Lege groepen
 * vallen weg.
 *
 * @param {object|null} item
 * @param {(type: string) => string} labelOf
 * @returns {RelatedGroup[]}
 */
export function relationGroups(item, labelOf) {
  if (!item) return [];
  const detail = item.relations_detail;
  const source = detail || item.relations || {};
  return Object.entries(source)
    .filter(([, v]) => v && v.length > 0)
    .map(([type, v]) => ({
      type,
      label: labelOf(type),
      removable: true,
      items: v.map((x) =>
        typeof x === "string" ? { ref: x, title: "", state: null } : { ref: x.ref, title: x.title ?? "", state: x.state ?? null },
      ),
    }));
}
