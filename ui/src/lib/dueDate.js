// Pure einddatum-logica voor de board-kaart (BETON-53, geëxtraheerd uit
// App.svelte voor BETON-185). Vergelijkt op kalenderdag in lokale tijd.

/**
 * De lokale "vandaag" als ISO-datum (YYYY-MM-DD). `now` is injecteerbaar voor
 * tests; default is het huidige moment.
 *
 * @param {Date} [now]
 * @returns {string}
 */
export function todayISO(now = new Date()) {
  const off = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - off).toISOString().slice(0, 10);
}

/**
 * Einddatum-status voor de kaart-chip: rood bij overdue, amber bij vandaag,
 * neutraal in de toekomst. `null` als er geen einddatum is.
 *
 * @param {string|null|undefined} due  ISO-datum/timestamp (dag telt)
 * @param {string} [today]  vergelijkingsdag (default: vandaag, lokaal)
 * @returns {{kind: "overdue"|"today"|"future", title: string}|null}
 */
export function dueMeta(due, today = todayISO(), locale = "nl") {
  if (!due) return null;
  const day = due.slice(0, 10);
  if (day < today) return { kind: "overdue", title: `${locale === "en" ? "Overdue" : "Te laat"}: ${day}` };
  if (day === today) return { kind: "today", title: `${locale === "en" ? "Today" : "Vandaag"}: ${day}` };
  return { kind: "future", title: `${locale === "en" ? "Due date" : "Einddatum"}: ${day}` };
}
