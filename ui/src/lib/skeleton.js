// Skeleton-presets (BETON-226): pure selectie-logica voor <Skeleton>, los van
// rendering zodat de preset/telling-regels met vitest te toetsen zijn. Het
// paneel kiest alleen een preset + optioneel een telling; welke breedtes en
// hoeveel rijen dat oplevert zit hier.

const DEFAULT_COUNTS = {
  title: 1,
  lines: 3,
  rows: 4,
  card: 3,
};

const MIN_COUNT = 1;
const MAX_COUNT = 20;

// Cyclische breedtes voor losse tekstregels — geeft "onregelmatige" regels
// i.p.v. even brede balken, zonder random (deterministisch, dus stabiel in
// screenshots/tests).
const LINE_WIDTH_CYCLE = ["100%", "100%", "65%"];

export function resolveSkeletonCount(preset, count) {
  const fallback = DEFAULT_COUNTS[preset] ?? DEFAULT_COUNTS.lines;
  const n = Number.isFinite(count) ? Math.trunc(count) : fallback;
  return Math.min(MAX_COUNT, Math.max(MIN_COUNT, n));
}

export function lineWidths(count) {
  const n = resolveSkeletonCount("lines", count);
  return Array.from({ length: n }, (_, i) => LINE_WIDTH_CYCLE[i % LINE_WIDTH_CYCLE.length]);
}

// Bouwt de rij-beschrijvingen die het Skeleton-component rendert. Elke rij is
// { kind: 'head' | 'line' | 'row' | 'card', width? }.
export function skeletonRows(preset, count) {
  switch (preset) {
    case "title":
      return [{ kind: "head" }];
    case "rows": {
      const n = resolveSkeletonCount("rows", count);
      return Array.from({ length: n }, () => ({ kind: "row" }));
    }
    case "card": {
      const n = resolveSkeletonCount("card", count);
      return Array.from({ length: n }, () => ({ kind: "card" }));
    }
    case "lines":
    default:
      return lineWidths(count).map((width) => ({ kind: "line", width }));
  }
}
