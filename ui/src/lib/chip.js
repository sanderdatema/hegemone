// Pure helpers voor Chip (BETON-221): de class- en element-keuze los testbaar
// houden, spiegelt lib/segmentedControl.js. Het component blijft presentational.

export const CHIP_TONES = ["neutral", "label"];

// Container-class voor een chip. `chip tone-<x>` + optioneel `interactive`
// (klikbaar/link) en `selected` (toggle aan). Onbekende tone → neutral.
export function chipClass(tone, { interactive = false, selected = false } = {}) {
  const t = CHIP_TONES.includes(tone) ? tone : "neutral";
  let c = `chip tone-${t}`;
  if (interactive) c += " interactive";
  if (selected) c += " selected";
  return c;
}

// Welk HTML-element de chip rendert: een <a> bij href, een <button> bij een
// klik-handler, anders een niet-interactieve <span>. BETON-238: `removable`
// alléén maakt de chip GEEN <button> meer — de sluit-x is zelf al een <button>,
// dus een button-wrapper gaf genest-button (ongeldige HTML) én erfde de globale
// button-`min-height: 34px` waardoor de chip veel te groot werd t.o.v. de tekst.
export function chipElement({ href, onclick } = {}) {
  if (href) return "a";
  if (onclick) return "button";
  return "span";
}

// Is de chip interactief (voor de class-hook)? Link of klikbaar.
export function chipInteractive({ href, onclick } = {}) {
  return !!(href || onclick);
}
