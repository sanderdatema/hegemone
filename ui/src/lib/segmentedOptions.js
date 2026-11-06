// Opties voor de segmented-button-controls (BETON-212): state & werklast als
// knopgroepen i.p.v. dropdowns. Pure helpers zodat labels/volgorde los testbaar
// zijn; het SegmentedControl-component is verder puur presentational.
//
// Labels komen uit lib/labels.js (BETON-227) — één vertaallaag i.p.v. losse
// kopieën per component.
import { WORKLOAD_VALUES, workloadLabel, workloadMeta } from "./labels.js";
import { stateColor } from "./board.js";

export { WORKLOAD_VALUES };

// [{value, label}] voor de werklast-knoppen (BETON-311, vervangt prioriteit).
// Met `{ colored: true }` krijgt elke optie een `color` (BETON-425): de kleur
// van de werklast-badge, zodat de gekozen knop dezelfde kleur toont.
export function workloadOptions({ colored = false, locale = "nl" } = {}) {
  return WORKLOAD_VALUES.map((value) => {
    const opt = { value, label: workloadLabel(value, locale) };
    if (colored) opt.color = workloadMeta(value)?.color;
    return opt;
  });
}

// [{value, label}] voor de state-knoppen, afgeleid van de projectstates.
// Geen aparte "(default)"-pseudo-optie meer (BETON-229): een lege/null-waarde
// matcht simpelweg geen enkele knop, dus niets is geselecteerd — dat IS het
// default-pad (de server valt terug op de projectdefault als er geen `state`
// meekomt in de create-call).
//
// Met `{ colored: true }` krijgt elke optie een `color` (BETON-425), uit
// dezelfde bron als de kolomstip op het bord (`stateColor`: per-state kleur,
// anders de groep-token).
export function stateOptions(states, { colored = false } = {}) {
  const list = states || [];
  return list.map((s) => {
    const opt = { value: s.name, label: s.name };
    if (colored) opt.color = stateColor(list, s.name);
    return opt;
  });
}
