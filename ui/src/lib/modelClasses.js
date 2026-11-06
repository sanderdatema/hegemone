// Instellingen "werkklasse → model per harnas" (BETON-476). Pure logica.

/** `{harness: {class: model}}` → rijen `[{harness, models: {class: model}}]`, harnas alfabetisch. */
export function mappingToRows(mapping) {
  return Object.keys(mapping || {})
    .sort()
    .map((harness) => ({ harness, models: { ...mapping[harness] } }));
}

/** Rijen terug naar het PUT-lichaam: lege modellen vallen weg, lege harnassen ook. */
export function rowsToMapping(rows, classes) {
  const out = {};
  for (const r of rows || []) {
    const h = String(r.harness ?? "").trim().toLowerCase();
    if (!h) continue;
    for (const c of classes) {
      const m = String(r.models?.[c] ?? "").trim();
      if (m) (out[h] ??= {})[c] = m;
    }
  }
  return out;
}

export function mappingChanged(a, b) {
  return JSON.stringify(sortKeys(a)) !== JSON.stringify(sortKeys(b));
}

function sortKeys(o) {
  if (Array.isArray(o) || o === null || typeof o !== "object") return o;
  return Object.fromEntries(Object.keys(o).sort().map((k) => [k, sortKeys(o[k])]));
}
