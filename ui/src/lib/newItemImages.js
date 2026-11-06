// Pure helpers voor de inline-afbeelding-flow in NewItem.svelte (BETON-256).
//
// Attachments zijn content-addressed maar hangen ALTIJD aan een bestaand item
// (`POST /items/{ref}/attachments`) — bij een nog niet aangemaakt ticket is er
// geen ref om aan te uploaden. Om toch hetzelfde "inline"-gevoel te geven als
// de Drawer (die meteen uploadt en `![](url)` op de caretpositie invoegt), zet
// NewItem bij plakken/slepen direct een leesbare placeholder-markdown-regel op
// de caretpositie. Ná het aanmaken van het ticket wordt elke placeholder op
// precies diezelfde plek in de tekst vervangen door de echte
// `![filename](url)` — niet achteraan de omschrijving geplakt.

/**
 * Bouw de placeholder-markdown-regel voor een net gekozen/gesleepte afbeelding.
 * Het id maakt de placeholder uniek, ook als twee bestanden dezelfde naam
 * hebben (bv. twee screenshots die allebei "image.png" heten).
 *
 * @param {string} filename
 * @param {number|string} id
 * @returns {string}
 */
export function imagePlaceholder(filename, id) {
  return `![⏳ ${filename} (${id})]()`;
}

/**
 * Vervang een placeholder door de echte markdown, op precies de plek waar de
 * placeholder stond. Als de placeholder niet meer in de tekst voorkomt (de
 * gebruiker heeft 'm handmatig weggehaald/overschreven), valt dit terug op
 * achteraan toevoegen zodat de geüploade afbeelding niet stilletjes verdwijnt.
 *
 * @param {string} text
 * @param {string} placeholder
 * @param {string} replacement
 * @returns {string}
 */
export function resolvePlaceholder(text, placeholder, replacement) {
  const s = String(text ?? "");
  if (s.includes(placeholder)) return s.replace(placeholder, replacement);
  return s.trim() ? `${s}\n\n${replacement}` : replacement;
}

/**
 * Haal een placeholder weer uit de tekst (bv. omdat de upload mislukte, of de
 * gebruiker de afbeelding weer verwijderde vóórdat het ticket werd
 * aangemaakt). Ruimt overtollige lege regels op, net als
 * `drawerImages.js:removeImageMarkdown`. Geen no-op-fout als de placeholder al
 * weg is (bv. door handmatig bewerken).
 *
 * @param {string} text
 * @param {string} placeholder
 * @returns {string}
 */
export function removePlaceholder(text, placeholder) {
  return String(text ?? "")
    .replace(placeholder, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/**
 * Haal alle placeholders uit de tekst voor de create-body (BETON-435). Het
 * ticket gaat zonder placeholders de deur uit; de geüploade afbeeldingen komen
 * er pas bij de PATCH in. Wordt de pagina tussen aanmaken en PATCH herladen,
 * dan mist er een afbeelding maar blijft er geen dode ⏳-regel staan. Zonder
 * placeholders blijft de tekst byte-voor-byte gelijk.
 *
 * @param {string} text
 * @param {string[]} placeholders
 * @returns {string}
 */
export function stripPlaceholders(text, placeholders) {
  if (!placeholders.length) return String(text ?? "");
  return placeholders.reduce((s, p) => removePlaceholder(s, p), String(text ?? ""));
}

/**
 * Bouw een pending-image-entry (BETON-259): naast de placeholder-markdown
 * (voor de inline-plek in de tekst, ná aanmaken resolved) hoort een lokale
 * preview-URL, zodat de "wordt meegestuurd bij aanmaken"-lijst een echte
 * thumbnail kan tonen vóórdat het bestand geüpload is (de echte
 * attachment-URL bestaat pas ná `api.uploadAttachment`, ná het aanmaken van
 * het ticket). `createObjectUrl` is injecteerbaar zodat dit puur en
 * vitest-testbaar blijft zonder een echte browser/`URL.createObjectURL`.
 *
 * @param {File} file
 * @param {number|string} id
 * @param {(file: File) => string} [createObjectUrl]
 * @returns {{id: number|string, file: File, placeholder: string, url: string}}
 */
export function buildPendingImage(file, id, createObjectUrl = (f) => URL.createObjectURL(f)) {
  return {
    id,
    file,
    placeholder: imagePlaceholder(file.name, id),
    url: createObjectUrl(file),
  };
}
