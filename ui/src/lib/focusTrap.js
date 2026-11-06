// Herbruikbare focus-trap voor de handgemaakte overlay-panelen die (nog) niet
// op bits-ui Dialog draaien (BETON-172). Eén oplossing i.p.v. per-overlay
// ad-hoc: houdt Tab-focus binnen het paneel, zet de focus erin bij openen,
// geeft de focus terug aan de opener bij sluiten, en markeert het paneel als
// aria-modal. Escape blijft aan de component (die vaak gelaagde Esc heeft):
// geef desgewenst een `onEscape`-callback mee, die alleen vuurt als de event
// nog niet is afgehandeld (bv. door een @mention-/[[-autocomplete).
//
// De pure volgorde-logica (welke node krijgt focus bij Tab) staat los zodat
// vitest 'm kan testen zonder echte DOM-focus (jsdom traps focus niet).

// Selector voor tabbare elementen binnen een paneel.
export const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

// Pure trap-beslissing: gegeven de tabbare nodes, de nu-gefocuste node en of
// Shift ingedrukt is, geef de node terug die focus moet krijgen — of null om
// de browser zijn normale Tab-gedrag te laten doen (focus midden in de lijst).
// Wrap rond aan beide uiteinden zodat focus nooit uit het paneel ontsnapt; als
// de focus buiten het paneel zit, trek 'm terug naar het eerste/laatste item.
export function trapTarget(focusables, active, shiftKey) {
  if (!focusables.length) return null;
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  if (!focusables.includes(active)) return shiftKey ? last : first;
  if (shiftKey && active === first) return last;
  if (!shiftKey && active === last) return first;
  return null;
}

function isVisible(el) {
  return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
}

function focusables(node) {
  return [...node.querySelectorAll(FOCUSABLE_SELECTOR)].filter(isVisible);
}

// Svelte-action: use:focusTrap of use:focusTrap={{ onEscape }}.
export function focusTrap(node, params = {}) {
  const opener = document.activeElement;
  node.setAttribute("aria-modal", "true");
  if (!node.hasAttribute("role")) node.setAttribute("role", "dialog");

  // Focus naar binnen: eerste tabbare element, anders het paneel zelf.
  const initial = focusables(node)[0];
  if (initial) {
    initial.focus();
  } else {
    if (!node.hasAttribute("tabindex")) node.tabIndex = -1;
    node.focus();
  }

  let onEscape = params.onEscape;

  function onKeydown(e) {
    if (e.key === "Tab") {
      const target = trapTarget(focusables(node), document.activeElement, e.shiftKey);
      if (target) {
        e.preventDefault();
        target.focus();
      }
    } else if (e.key === "Escape" && onEscape && !e.defaultPrevented) {
      onEscape(e);
    }
  }

  node.addEventListener("keydown", onKeydown);

  return {
    update(p = {}) {
      onEscape = p.onEscape;
    },
    destroy() {
      node.removeEventListener("keydown", onKeydown);
      // Focus terug naar de trigger (bv. topbar-knop) als die er nog is.
      if (opener && typeof opener.focus === "function" && document.contains(opener)) {
        opener.focus();
      }
    },
  };
}
