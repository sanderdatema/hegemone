// BETON-486: hoogte van alles boven het bord, als CSS-variabele.
//
// `.column` krijgt `max-height: calc(100dvh - var(--board-top) - ...)` zodat het
// bord precies in het scherm past en alleen de kolommen zelf scrollen. Een vaste
// aftrek (88px) klopte alleen zonder snelfilter-rij; elke extra rij erboven
// (snelfilters, actieve filters, sleep-tip) liet de pagina een stukje scrollen.
// Wat erboven staat verschilt per scherm, dus meten we het op het bord zelf.

export const BOARD_TOP_VAR = "--board-top";

/** Afstand van de bovenkant van het document tot de bovenkant van `node`, in px. */
export function boardTop(node, win) {
  return Math.ceil(node.getBoundingClientRect().top + (win.scrollY || 0));
}

/**
 * Svelte-action: houdt `--board-top` op :root bij. `deps` is de testnaad
 * (de vitest-omgeving heeft geen DOM).
 */
export function trackBoardTop(node, deps = {}) {
  const win = deps.win ?? (typeof window !== "undefined" ? window : null);
  const doc = deps.doc ?? (typeof document !== "undefined" ? document : null);
  const RO =
    deps.ResizeObserver ??
    (typeof ResizeObserver !== "undefined" ? ResizeObserver : null);
  if (!win || !doc) return {};

  const root = doc.documentElement;
  const set = () => root.style.setProperty(BOARD_TOP_VAR, `${boardTop(node, win)}px`);
  set();

  win.addEventListener("resize", set);
  // Elke rij boven het bord die verschijnt of verdwijnt verandert de hoogte van
  // de body; de topbar zelf kan ook van hoogte wisselen (wrap op smalle schermen).
  const observer = RO ? new RO(set) : null;
  if (observer) {
    observer.observe(doc.body);
    if (node.parentElement) observer.observe(node.parentElement);
  }

  return {
    destroy() {
      win.removeEventListener("resize", set);
      observer?.disconnect();
      root.style.removeProperty(BOARD_TOP_VAR);
    },
  };
}
