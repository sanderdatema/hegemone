// Pure logica voor het eigen-instellingen-paneel (BETON-173).
// GET /users/me/settings geeft geen ruw webhook_secret terug (has_webhook_secret);
// het secret is write-only, dus we sturen het alleen mee als de gebruiker iets typt.

// Valideer een webhook-URL. Leeg mag (dan wordt de webhook gewist). Anders
// moet het een http(s)-URL zijn. Geeft een foutstring of "" (geen fout).
export function validateWebhookUrl(url, locale = "nl") {
  const trimmed = (url || "").trim();
  if (!trimmed) return "";
  if (!/^https?:\/\/\S+/i.test(trimmed)) {
    return locale === "en" ? "Webhook URL must start with http:// or https://." : "Webhook-URL moet met http:// of https:// beginnen.";
  }
  return "";
}

// Normaliseer een tekstveld naar de PATCH-waarde: getrimd, en leeg → null
// (zodat de server het veld wist i.p.v. op een lege string te zetten).
function nullIfEmpty(value) {
  const trimmed = (value || "").trim();
  return trimmed ? trimmed : null;
}

// Bouw de partial PATCH-body: alleen velden die t.o.v. de geladen instellingen
// wijzigden. Het secret gaat mee zodra er iets is ingevuld (write-only); een
// leeg secret-veld laat het bestaande secret ongemoeid.
export function buildSettingsPatch(draft, initial) {
  const body = {};

  const url = nullIfEmpty(draft.webhook_url);
  if (url !== (initial.webhook_url ?? null)) body.webhook_url = url;

  const telegram = nullIfEmpty(draft.telegram_chat_id);
  if (telegram !== (initial.telegram_chat_id ?? null)) {
    body.telegram_chat_id = telegram;
  }

  const description = nullIfEmpty(draft.description);
  if (description !== (initial.description ?? null)) body.description = description;

  if (Boolean(draft.subscribe_all) !== Boolean(initial.subscribe_all)) {
    body.subscribe_all = Boolean(draft.subscribe_all);
  }

  const secret = (draft.webhook_secret || "").trim();
  if (secret) body.webhook_secret = secret;

  return body;
}

// Is er iets te bewaren? (voorkomt een no-op PATCH)
export function hasChanges(draft, initial) {
  return Object.keys(buildSettingsPatch(draft, initial)).length > 0;
}
