// Pure helpers voor browser-notificaties op nieuwe inbox-items (BETON-368).
// Geen DOM, geen Notification-API hier — dat blijft in App.svelte/
// UserSettings.svelte; dit bestand beslist alleen OF er gemeld moet worden en
// WAT er in staat, zodat het los met vitest te testen is.
import { dueLabel } from "./inbox.js";

// localStorage-key voor de opt-in-voorkeur, gedeeld tussen UserSettings.svelte
// (schrijft 'm bij het schakelen) en App.svelte (leest 'm vlak vóór elke
// notificatie-beslissing) — één plek zodat ze niet uit elkaar kunnen lopen.
export const NOTIFY_STORAGE_KEY = "betonning-notify";

// Reason → NL-omschrijving voor de meldingstekst. Spiegelt Inbox.svelte's
// REASON_META, maar zonder icoon (die is Svelte-specifiek en hoort niet in
// een pure lib) — alleen het label.
const REASON_LABELS = {
  due: "deadline",
  mention: "noemde je",
  assigned: "wees je toe",
  comment: "reageerde op je item",
  update: "wijzigde je item",
};

/**
 * Mag er een browser-notificatie komen? Puur — geen toegang tot
 * `Notification`/`document` hier, de caller geeft de staat mee.
 *
 * @param {{enabled?: boolean, permission?: string, hidden?: boolean, delta?: number}} ctx
 *   `enabled`    — opt-in-voorkeur van de gebruiker (localStorage).
 *   `permission` — `Notification.permission` ("granted"/"denied"/"default").
 *   `hidden`     — `document.hidden` (alleen melden als het tabblad niet
 *                  actief in beeld is — anders zie je het al op het scherm).
 *   `delta`      — aantal nieuwe ongelezen items sinds de vorige poll.
 * @returns {boolean}
 */
export function shouldNotify({ enabled, permission, hidden, delta } = {}) {
  return Boolean(enabled) && permission === "granted" && Boolean(hidden) && (delta ?? 0) > 0;
}

/**
 * Titel + body voor een browser-notificatie op basis van één inbox-entry.
 * `due`-entries gebruiken `dueLabel` (vandaag vs. verstreken); de rest krijgt
 * `@actor <label>` uit `REASON_LABELS` (onbekende reason → "update").
 *
 * @param {{ref: string, reason?: string, actor?: string|null}} entry
 * @returns {{title: string, body: string}}
 */
export function notificationText(entry, locale = "nl") {
  const labels = locale === "en" ? {due:"due date",mention:"mentioned you",assigned:"assigned you",comment:"commented on your item",update:"updated your item"} : REASON_LABELS;
  const ref = entry?.ref ?? "";
  const body =
    entry?.reason === "due"
      ? dueLabel(entry, locale)
      : `${entry?.actor ? `@${entry.actor} ` : ""}${labels[entry?.reason] ?? labels.update}`;
  return { title: ref, body };
}

/**
 * Titel met ongelezen-teller vooraan (bv. voor de browser-tab-titel).
 * `n <= 0` laat de titel ongewijzigd.
 *
 * @param {string} base
 * @param {number} n
 * @returns {string}
 */
export function titleWithUnread(base, n) {
  return n > 0 ? `(${n}) ${base}` : base;
}
