// Pure helpers voor de attachments-galerij in de Drawer (BETON-175).

/**
 * Of dit attachment een afbeelding is. Bepaalt overal in de UI het verschil
 * tussen "toon 'm" en "link ernaar": sinds BETON-374 kan een bijlage ook een
 * logbestand, JSON of PDF zijn, en die serveert de backend als download.
 *
 * @param {{content_type?: string}|null|undefined} att
 */
export function isImageAttachment(att) {
  return String(att?.content_type ?? "").startsWith("image/");
}

// Bouwt de markdown-referentie voor een attachment, exact zoals de bestaande
// upload-flow die genereert (zie Drawer.svelte:uploadFiles) — zodat "invoegen
// in omschrijving" identieke markdown produceert. Een afbeelding wordt
// ingebed (`![]()`), een bestand gelinkt (`[]()`): een `![](…)` naar een
// logbestand geeft een kapot plaatje.
export function attachmentMarkdown(att) {
  const bang = isImageAttachment(att) ? "!" : "";
  return `${bang}[${att.filename}](${att.url})`;
}
