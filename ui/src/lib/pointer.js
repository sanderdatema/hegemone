// Pure pointer-/touch-detectie voor het bord (BETON-255).
//
// HTML5-drag&drop op de kaarten moet UIT op elk touch-capabel toestel: een tik
// met minieme vingerbeweging op een `draggable`-kaart wordt door de browser als
// een drag-start opgevat, waarna de klik (drawer openen) niet meer vuurt — de
// kaart lijkt "dood" (grab-cursor, maar niets opent).
//
// De oude check keek alleen naar de PRIMAIRE pointer (`pointer: coarse`). Op
// hybride toestellen (iPad + trackpad, touchscreen-laptop) is de primaire pointer
// `fine`, dus bleef drag aan terwijl het toestel wél touch heeft → precies de
// regressie. We kijken daarom naar ELKE pointer (`any-pointer: coarse`) plus
// `navigator.maxTouchPoints` als vangnet.

// Pure beslissing: mag drag&drop aan? Alleen als er geen enkele touch-indicatie is.
export function computeCanDrag({ anyPointerCoarse = false, maxTouchPoints = 0 } = {}) {
  return !(anyPointerCoarse || maxTouchPoints > 0);
}

// Leest de indicatoren uit een window-achtig object en past computeCanDrag toe.
// Zonder window (SSR) → drag toestaan: onschadelijk, want touch-toestellen
// re-evalueren dit in de browser.
export function detectCanDrag(win = typeof window !== "undefined" ? window : undefined) {
  if (!win) return true;
  const anyPointerCoarse =
    typeof win.matchMedia === "function" && win.matchMedia("(any-pointer: coarse)").matches;
  const maxTouchPoints = win.navigator?.maxTouchPoints ?? 0;
  return computeCanDrag({ anyPointerCoarse, maxTouchPoints });
}
