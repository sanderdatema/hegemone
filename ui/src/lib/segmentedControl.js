// Pure helpers voor SegmentedControl (BETON-221): variant→class en aria-mapping
// los testbaar houden, spiegelt lib/segmentedOptions.js. Het component blijft
// verder presentational.

// Beschikbare visuele varianten. Onbekende waarden vallen terug op 'accent'
// zodat een typo nooit een kale, ongestylede knopgroep oplevert.
export const SEGMENTED_VARIANTS = ["accent", "soft", "joined", "pill"];

// Container-class voor een variant. Altijd `segmented` + `variant-<x>`.
export function segmentedClass(variant) {
  const v = SEGMENTED_VARIANTS.includes(variant) ? variant : "accent";
  return `segmented variant-${v}`;
}

// Container-role: een radiogroup (single-select) of een neutrale group
// (toggle-button-semantiek, bv. de bord/lijst-view-toggle).
export function containerRole(itemAria) {
  return itemAria === "pressed" ? "group" : "radiogroup";
}

// Aria-attributen per knop, afhankelijk van de modus. Ongebruikte attributen
// zijn `undefined` (Svelte laat ze dan weg). `radio` = aria-checked op role
// radio; `pressed` = aria-pressed op een gewone button.
export function itemAriaProps(itemAria, active) {
  if (itemAria === "pressed") {
    return { role: undefined, ariaChecked: undefined, ariaPressed: active };
  }
  return { role: "radio", ariaChecked: active, ariaPressed: undefined };
}

// Vuurt de onchange? Niet bij disabled of bij herselecteren van de actieve
// waarde (idempotent, geen ruis-events).
export function willFire(current, next, disabled) {
  return !disabled && next !== current;
}
