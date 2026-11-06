// Pure afbeeldings-helpers voor Drawer.svelte (BETON-185, geëxtraheerd uit de
// component zodat de upload-/plak-/verwijder-logica los onder vitest valt).
// Geen DOM en geen fetch: de component levert de FileList/DataTransfer aan en
// verwerkt de teruggegeven File-array (upload) of tekst (markdown-verwijdering).

import { insertAt } from "./drawerLogic.js";

/**
 * Filter een FileList/array van File-objecten op afbeeldingen (BETON-74).
 * Gedeeld door de zichtbare upload-knop (file-input) én de sleep/plak-flow.
 *
 * @param {Iterable<{type?: string}>|null|undefined} fileList
 * @returns {Array<{type?: string}>}
 */
export function imageFilesFromFileList(fileList) {
  if (!fileList) return [];
  return Array.from(fileList).filter((f) => f.type && f.type.startsWith("image/"));
}

/**
 * De niet-afbeeldings-typen die de backend accepteert (BETON-374). De browser
 * geeft voor een `.log` vaak een lege of `application/octet-stream`-type op, dus
 * die worden op extensie herkend; het echte oordeel valt op de server, die op de
 * inhoud sniff't en desnoods 415 geeft.
 */
const FILE_TYPES = ["text/", "application/json", "application/pdf"];
const FILE_EXTENSIONS = [".log", ".txt", ".md", ".csv", ".json", ".pdf"];

function isAttachable(f) {
  const type = String(f?.type ?? "");
  if (type.startsWith("image/")) return true;
  if (FILE_TYPES.some((t) => type.startsWith(t))) return true;
  const name = String(f?.name ?? "").toLowerCase();
  return FILE_EXTENSIONS.some((ext) => name.endsWith(ext));
}

/**
 * Filter een FileList/array op alles wat als bijlage mag: afbeeldingen én
 * tekst/log/JSON/PDF (BETON-374). Wat hier doorheen komt gaat naar de upload;
 * de rest wordt stilzwijgend genegeerd, net als voorheen bij niet-afbeeldingen.
 *
 * @param {Iterable<{type?: string, name?: string}>|null|undefined} fileList
 */
export function attachableFilesFromFileList(fileList) {
  if (!fileList) return [];
  return Array.from(fileList).filter(isAttachable);
}

/**
 * Zelfde als `imageFilesFromTransfer`, maar met de bredere whitelist — voor
 * slepen/plakken van een logbestand of PDF (BETON-374).
 *
 * @param {{files?: any, items?: Iterable<{kind: string, type?: string, getAsFile: () => any}>}|null|undefined} dt
 */
export function attachableFilesFromTransfer(dt) {
  if (!dt) return [];
  const out = attachableFilesFromFileList(dt.files);
  if (!out.length && dt.items) {
    for (const it of dt.items) {
      if (it.kind !== "file") continue;
      const f = it.getAsFile();
      if (f && isAttachable({ type: it.type ?? f.type, name: f.name })) out.push(f);
    }
  }
  return out;
}

/**
 * Haal de afbeeldingsbestanden uit een DataTransfer/ClipboardData-achtig object
 * (sleep of plak). Gebruikt eerst `.files`; valt daarna terug op `.items`
 * (nodig bij plakken, waar Safari alleen items levert) en trekt daar de
 * File-objecten uit.
 *
 * @param {{files?: any, items?: Iterable<{kind: string, type?: string, getAsFile: () => any}>}|null|undefined} dt
 * @returns {Array<{type?: string}>}
 */
export function imageFilesFromTransfer(dt) {
  if (!dt) return [];
  const out = imageFilesFromFileList(dt.files);
  if (!out.length && dt.items) {
    for (const it of dt.items) {
      if (it.kind === "file" && (it.type || "").startsWith("image/")) {
        const f = it.getAsFile();
        if (f) out.push(f);
      }
    }
  }
  return out;
}

/**
 * Verwijder de markdown-image-regel van een net geüploade comment-afbeelding
 * uit de nog niet geplaatste comment-tekst (BETON-94): haalt exact de
 * `![filename](url)`-referentie eruit, ruimt overtollige lege regels op en
 * trimt.
 *
 * @param {string} text
 * @param {string} filename
 * @param {string} url
 * @returns {string}
 */
export function removeImageMarkdown(text, filename, url) {
  return String(text ?? "")
    .replace(`![${filename}](${url})`, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/**
 * Voeg `markdown` op de caretpositie in bij het juiste draft-veld voor een
 * sleep/plak/upload-doel (BETON-403). Drie doelen: de omschrijving ("desc"),
 * de nieuwe-reactie-composer ("comment") en een reactie die al in bewerkmodus
 * staat ("editComment"). Geeft de VOLLEDIGE `drafts`-triple terug (alleen het
 * geraakte veld gewijzigd) zodat een test kan aantonen dat het juiste veld
 * verandert én de andere twee ongewijzigd blijven — vóór BETON-403 had
 * "editComment" geen eigen doel, dus slepen tijdens het bewerken deed niets
 * (er was geen derde tak) en een latere regressie die per ongeluk terugvalt
 * op "comment" zou hetzelfde effect hebben, alleen zichtbaar in het verkeerde
 * veld. Onbekende doelen vallen terug op "comment", gelijk aan het gedrag van
 * de oorspronkelijke ternary in Drawer.svelte.
 *
 * @param {"desc"|"comment"|"editComment"|"answer"|"editAnswer"|string} target
 * @param {{desc: string, comment: string, editComment: string, answer?: string, editAnswer?: string}} drafts
 * @param {number|null|undefined} caretPos
 * @param {string} markdown
 * @returns {{desc: string, comment: string, editComment: string}}
 */
export function insertIntoDrafts(target, drafts, caretPos, markdown) {
  // "answer"/"editAnswer": het antwoordveld van een vraag (BETON-434).
  const key = ["desc", "editComment", "answer", "editAnswer"].includes(target) ? target : "comment";
  const current = drafts?.[key] ?? "";
  const next = insertAt(current, caretPos, markdown);
  return { ...drafts, [key]: next };
}
