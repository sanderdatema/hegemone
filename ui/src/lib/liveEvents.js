// Incrementele verwerking van live SSE-events op de board-state (BETON-186).
//
// Voorheen deed élk SSE-event een debounce + volledige `loadBoard()`: alles
// opnieuw ophalen en renderen bij elke wijziging. Deze pure reducer past een
// (verrijkt) event rechtstreeks op de items-array toe. Het SSE-frame draagt
// sinds BETON-186 een compacte item-snapshot mee (`ref`, `project`, `item`),
// zodat de reducer de kaart kan up-serten of verwijderen zonder refetch.
//
// `applyEvent` geeft óf een nieuwe items-array terug (toegepast — kan dezelfde
// referentie zijn als er niets veranderde), óf `null` = "kan dit niet
// betrouwbaar incrementeel, doe een volledige reload". De caller (App.svelte)
// gebruikt de reducer alleen zónder actieve server-side filters en in de
// project-zoekscope; bij `null` valt hij terug op de bestaande debounce +
// `loadBoard()`.

/**
 * Pas één live-event incrementeel toe op de board-items.
 *
 * @param {{items: Array, project: string|null, showArchived?: boolean}} state
 *   huidige board-state: de items-array, de actieve project-key en of het
 *   archief zichtbaar is.
 * @param {{type: string, project?: string, item?: object, payload?: object}} event
 *   het (verrijkte) SSE-event.
 * @returns {Array|null} nieuwe items-array, of `null` voor "volledige reload".
 */
export function applyEvent(state, event) {
  if (!event || typeof event.type !== "string") return null;
  const items = (state && state.items) || [];
  const type = event.type;

  // Wiki-compilatie raakt het board nooit.
  if (type === "wiki.compiled") return items;

  // Hard-delete: het item is weg (item_id=NULL), de ref staat in de payload.
  if (type === "item.deleted") {
    return removeRef(items, event.payload && event.payload.ref);
  }

  // Cross-project verplaatsing: het bron-item wordt gearchiveerd en verdwijnt
  // hier; het nieuwe item komt als los `item.created`-event binnen.
  if (type === "item.moved") {
    return removeRef(items, event.payload && event.payload.from);
  }

  // Alles hierna heeft de verrijkte snapshot nodig; zonder → reload. Zo vallen
  // ook onbekende/toekomstige event-typen veilig terug op een volledige reload.
  const snap = event.item;
  if (!snap || !snap.ref) return null;

  // Een event van een ander project raakt dit board niet.
  if (!sameProject(event.project, state && state.project)) return items;

  // Gearchiveerd terwijl het archief niet zichtbaar is → van het board af.
  if (snap.archived_at && !(state && state.showArchived)) {
    return removeRef(items, snap.ref);
  }

  // Anders: up-serten. Een statuswissel zit in `snap.state`; de kolom-indeling
  // (buildColumns) volgt vanzelf. Comment-/relatie-events dragen óók een verse
  // snapshot (incl. `last_activity_at`), zodat de "Laatst gewijzigd"-sortering
  // klopt zonder reload — een bewuste afwijking van "no-op" voor die typen.
  return upsert(items, snap);
}

/**
 * Server-count-correctie voor begrensde kolommen (BETON-359): `applyEvent`
 * blijft puur items-in/items-uit (bewust géén tweede returnvorm — dat had 14
 * bestaande call-sites/tests gebroken die "next" als kale items-array
 * behandelen); deze losse, aanroepbare functie berekent per closed-state het
 * verschil in hoeveel items die state vóór en ná het event in de LOKAAL
 * geladen array voorkomen. Zo'n delta is exact ook als de kolom zelf begrensd
 * is (closed_limit): een item dat een closed-kolom binnenkomt/verlaat
 * verandert de telling in de array met precies 1, los van hoeveel er
 * server-side "achter" de limiet nog liggen.
 *
 * Kent geen delta toe voor een item dat de closed-kolom al vóór het event
 * verliet zonder ooit lokaal geladen te zijn (voorbij de closed_limit-rand,
 * dus niet in `itemsBefore`) — die drift heelt zichzelf bij de volgende
 * volledige `loadBoard()`.
 *
 * @param {Array<{state: string|null}>} itemsBefore
 * @param {Array<{state: string|null}>} itemsAfter
 * @param {Iterable<string>} closedStateNames
 * @returns {Record<string, number>} state-naam → delta (alleen states die wijzigden)
 */
export function closedCountDeltas(itemsBefore, itemsAfter, closedStateNames) {
  const closed = new Set(closedStateNames || []);
  const deltas = {};
  for (const name of closed) {
    const before = (itemsBefore || []).filter((i) => i.state === name).length;
    const after = (itemsAfter || []).filter((i) => i.state === name).length;
    if (after !== before) deltas[name] = after - before;
  }
  return deltas;
}

/**
 * Past `closedCountDeltas`-uitkomsten toe op een counts-map (BETON-359).
 * Puur: nieuwe map, geklemd op 0 (nooit negatief door een dubbeltelling).
 *
 * @param {Record<string, number>} counts
 * @param {Record<string, number>} deltas
 * @returns {Record<string, number>}
 */
export function applyCountDeltas(counts, deltas) {
  const next = { ...(counts || {}) };
  for (const [name, d] of Object.entries(deltas || {})) {
    next[name] = Math.max(0, (next[name] ?? 0) + d);
  }
  return next;
}

function sameProject(a, b) {
  if (!a || !b) return false;
  return String(a).toUpperCase() === String(b).toUpperCase();
}

function removeRef(items, ref) {
  if (!ref) return items;
  const next = items.filter((it) => it.ref !== ref);
  return next.length === items.length ? items : next;
}

function upsert(items, snap) {
  let found = false;
  const next = items.map((it) => {
    if (it.ref === snap.ref) {
      found = true;
      return snap;
    }
    return it;
  });
  if (!found) next.push(snap);
  return next;
}
