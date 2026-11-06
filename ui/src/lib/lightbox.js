// Lightbox-helpers (BETON-474): een klik op een afbeelding in gerenderde
// markdown opent de afbeelding groot i.p.v. de klik-om-te-bewerken-editor.

/**
 * Is dit klikdoel een afbeelding die een lightbox hoort te openen? Een
 * afbeelding binnen een `<a>` volgt de link (geen lightbox).
 *
 * @param {any} target
 * @returns {{src: string, alt: string}|null}
 */
export function lightboxTarget(target) {
  if (!target || String(target.tagName).toUpperCase() !== "IMG") return null;
  if (target.closest?.("a")) return null;
  const src = target.getAttribute?.("src") ?? target.src;
  if (!src) return null;
  return { src, alt: target.getAttribute?.("alt") ?? target.alt ?? "" };
}

/**
 * Svelte-action voor een gerenderd-markdown-blok. Luistert in de capture-fase,
 * zodat de klik-om-te-bewerken-handler van hetzelfde blok niet meer vuurt.
 *
 * @param {HTMLElement} node
 * @param {(img: {src: string, alt: string}) => void} onopen
 */
export function lightboxClicks(node, onopen) {
  let open = onopen;
  const handler = (e) => {
    const img = lightboxTarget(e.target);
    if (!img) return;
    e.preventDefault();
    e.stopPropagation();
    open(img);
  };
  node.addEventListener("click", handler, true);
  return {
    update(next) {
      open = next;
    },
    destroy() {
      node.removeEventListener("click", handler, true);
    },
  };
}
