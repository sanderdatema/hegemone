// Pure logica voor het webhook-leveringen-paneel (BETON-174).
// De statusverzameling komt uit migratie 010: pending/delivered/failed/cancelled.

// Volgorde + labels voor de filter-dropdown ("" = alles).
export const DELIVERY_STATUSES = ["pending", "delivered", "failed", "cancelled"];

const STATUS_LABEL = {
  pending: "in wachtrij",
  delivered: "geleverd",
  failed: "mislukt",
  cancelled: "geannuleerd",
};

// Toon-token per status → CSS-klasse die op bestaande kleur-tokens leunt.
const STATUS_TONE = {
  delivered: "ok",
  failed: "bad",
  cancelled: "muted",
  pending: "pending",
};

export function statusLabel(status, locale = "nl") {
  if (locale === "en") return ({pending: "queued", delivered: "delivered", failed: "failed", cancelled: "cancelled"})[status] || status || "unknown";
  return STATUS_LABEL[status] || status || "onbekend";
}

export function statusTone(status) {
  return STATUS_TONE[status] || "muted";
}

// Replay is alleen zinvol voor terminale niet-succes-statussen; een pending
// levering zit al in de wachtrij en een geleverde is klaar.
export function canReplay(status) {
  return status === "failed" || status === "cancelled";
}
