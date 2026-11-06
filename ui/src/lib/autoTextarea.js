// Gedeelde logica van AutoTextarea (BETON-462): Cmd/Ctrl+Enter = indienen,
// Escape = annuleren, meegroeien met de tekst. Puur (geen Svelte) zodat de
// toetsregels en de hoogteberekening los te testen zijn.
import { isSubmitChord } from "./board.js";

/**
 * Bepaal wat een toetsaanslag in een tekstveld doet.
 * `submit` wint van alles (ook van een open mention-popup), tijdens
 * IME-compositie gebeurt er niets (`isSubmitChord`); kale Enter is nooit submit.
 *
 * @param {{key: string, metaKey?: boolean, ctrlKey?: boolean, isComposing?: boolean}} e
 * @param {{canSubmit: boolean, canCancel: boolean}} caps
 * @returns {"submit"|"cancel"|"swallow"|null}
 */
export function textFieldAction(e, { canSubmit, canCancel }) {
  // Een vastgehouden Cmd+Enter herhaalt keydown: dat mag niet opnieuw indienen.
  if (canSubmit && isSubmitChord(e)) return e.repeat ? "swallow" : "submit";
  if (canCancel && e.key === "Escape" && !e.isComposing) return "cancel";
  return null;
}

/**
 * Pas de hoogte van een textarea aan op zijn inhoud (BETON-438-aanpak:
 * border-box, scrollHeight mist de randen). De maximale hoogte zit in CSS.
 *
 * @param {HTMLTextAreaElement|null|undefined} el
 */
export function growToFit(el) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight + el.offsetHeight - el.clientHeight}px`;
}
