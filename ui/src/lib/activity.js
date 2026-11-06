// Pure opmaak van de projectactiviteitenfeed (BETON-463): interne events
// weg, priority-diffs weg, opeenvolgende gelijke events samengevoegd.
// De Drawer-tijdlijn (drawerLogic.collapseEvents, BETON-364) klapt reeksen
// van ≥3 verschillende events in; dit voegt *gelijke* events samen tot één
// regel met "(N×)" — een andere eenheid, dus een eigen helper.
import { describeEvent } from "./board.js";

/** Interne bot-events die de feed standaard verbergt. */
export const INTERNAL_TYPES = ["wiki.compiled"];
/** Filterwaarde "standaard": alles behalve de interne types. */
export const DEFAULT_TYPE = "__default";
/** Samenvoegvenster: een reeks beslaat hooguit 10 minuten. */
export const MERGE_WINDOW_MS = 10 * 60 * 1000;

/**
 * Haal priority uit item.updated-events (priority is uitgefaseerd, BETON-311).
 * Een event dat alleen een priority-diff droeg valt weg (`null`).
 */
function withoutPriority(event) {
  if (event.type !== "item.updated" || !event.payload || !("priority" in event.payload)) {
    return event;
  }
  const { priority: _p, ...rest } = event.payload;
  const meaningful = Object.keys(rest).filter((k) => k !== "reason");
  if (!meaningful.length) return null;
  return { ...event, payload: rest };
}

function mergeKey(event) {
  const p = event.payload || {};
  const fields =
    event.type === "item.updated"
      ? Object.keys(p).filter((k) => k !== "reason").sort().join(",")
      : describeEvent(event);
  return [event.actor ?? "", event.ref ?? "", event.type, fields].join("|");
}

/**
 * Filter + samenvoegen. `events` komt nieuwste-eerst binnen. Elk resultaat is
 * het nieuwste event van de reeks plus `count` (aantal samengevoegde events)
 * en `oldest_created_at`.
 *
 * @param {Array<object>} events
 * @param {{showInternal?: boolean}} [opts]
 */
export function buildFeed(events, { showInternal = false } = {}) {
  const out = [];
  for (const raw of events || []) {
    if (!showInternal && INTERNAL_TYPES.includes(raw.type)) continue;
    const event = withoutPriority(raw);
    if (!event) continue;
    const last = out[out.length - 1];
    const t = Date.parse(event.created_at);
    if (
      last &&
      mergeKey(last) === mergeKey(event) &&
      Math.abs(Date.parse(last.created_at) - t) <= MERGE_WINDOW_MS &&
      Math.abs(Date.parse(last.oldest_created_at) - t) <= MERGE_WINDOW_MS
    ) {
      last.count += 1;
      last.oldest_created_at = event.created_at;
      continue;
    }
    out.push({ ...event, count: 1, oldest_created_at: event.created_at });
  }
  return out;
}
