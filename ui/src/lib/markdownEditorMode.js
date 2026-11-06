// Preview-modus voor MarkdownEditor.svelte (BETON-365): onthouden per sessie,
// niet per veld — reactie, omschrijving en plan delen dezelfde sessionStorage-
// key, zodat de keuze niet per instantie uit elkaar loopt zodra de gebruiker
// hem één keer zet. Puur zodat het los van de component testbaar is; de
// component leest bij het opzetten en schrijft bij elke wissel.
const MODE_KEY = "betonning-md-preview";

/**
 * Huidige voorkeurs-modus ("write" of "preview"). Zonder sessionStorage
 * (privacy-mode, of een omgeving zonder DOM zoals vitest) is de fallback
 * altijd "write" — nooit stilzwijgend een voorbeeld tonen van tekst die de
 * gebruiker nog aan het schrijven is.
 *
 * @returns {"write"|"preview"}
 */
export function readPreviewMode() {
  try {
    return sessionStorage.getItem(MODE_KEY) === "preview" ? "preview" : "write";
  } catch {
    return "write";
  }
}

/**
 * @param {"write"|"preview"} mode
 */
export function writePreviewMode(mode) {
  try {
    sessionStorage.setItem(MODE_KEY, mode === "preview" ? "preview" : "write");
  } catch {}
}
