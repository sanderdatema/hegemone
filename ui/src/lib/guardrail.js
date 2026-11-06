/**
 * Guardrail-logica (BETON-420) — puur, zodat de regels los testbaar zijn.
 *
 * Een guardrail is kennis die niet in een regressietest past en die elke agent
 * hierna moet naleven. Hij kost tokens bij elke ronde, vandaar de harde
 * tekencap en de verplichte reviewdatum.
 *
 * De cap staat hier én in `src/betonning/models.py`; `tests/test_constants_parity.py`
 * bewaakt dat de twee gelijk blijven (JS kan de Python-constante niet importeren).
 */

import { translate } from "./i18n.js";
import { lineDiff } from "./diff.js";

export const GUARDRAIL_MAX_CHARS = 1000;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Vandaag als `YYYY-MM-DD` in de LOKALE tijdzone van de browser. */
function localToday() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/**
 * Weergavegegevens van de guardrail van één ticket.
 *
 * `active` komt uit `has_guardrail` en wordt hier BEWUST niet herrekend: de
 * backend-definitie heeft drie termen (tekst aanwezig, niet opgeheven, ticket
 * niet gearchiveerd) en een tweetermige JS-kopie zou een gearchiveerd ticket
 * ten onrechte als actief tonen. De overige velden zijn puur weergave.
 *
 * `overdue` spiegelt de review-poll-query (`guardrail_review_by <= date('now')`):
 * de reviewdatum van vandaag is al aan de beurt.
 *
 * @param {object|null} item
 * @param {string} [today] ISO-datum; default de lokale klok.
 */
export function guardrailMeta(item, today = localToday()) {
  const i = item || {};
  const active = Boolean(i.has_guardrail);
  const reviewBy = i.guardrail_review_by || null;
  return {
    active,
    text: i.guardrail_md || "",
    reviewBy,
    setBy: i.guardrail_set_by || null,
    setAt: i.guardrail_set_at || null,
    liftedAt: i.guardrail_lifted_at || null,
    scope: i.guardrail_scope || [],
    overdue: Boolean(active && reviewBy && reviewBy <= today),
  };
}

/**
 * Dezelfde regels als de backend-validatie, zodat de gebruiker de 422 niet
 * hoeft op te halen.
 *
 * ADVIESEREND, niet beslissend: de backend rekent met `date('now')` (UTC) en de
 * browser met de lokale klok, dus rond middernacht kunnen ze een dag schelen.
 * Toon daarom altijd de servertekst als er tóch een 422/409 terugkomt.
 *
 * @param {{text?: string, reviewBy?: string}} input
 * @param {string} [today]
 * @returns {{ok: boolean, error: string}}
 */
export function guardrailValidation({ text = "", reviewBy = "" } = {}, today = localToday(), locale = "nl") {
  const t = (text || "").trim();
  if (!t) {
    return {
      ok: false,
      error: translate(locale, "guardrail.empty"),
    };
  }
  if (t.length > GUARDRAIL_MAX_CHARS) {
    return {
      ok: false,
      error: translate(locale, "guardrail.long", { count: t.length, max: GUARDRAIL_MAX_CHARS }),
    };
  }
  const d = (reviewBy || "").trim();
  if (!ISO_DATE.test(d)) {
    return { ok: false, error: translate(locale, "guardrail.dateRequired") };
  }
  if (d < today) {
    return { ok: false, error: translate(locale, "guardrail.datePast") };
  }
  return { ok: true, error: "" };
}

/**
 * Korte omschrijving van de scope: lege scope = projectbreed (en telt dan mee
 * in het plafond van vijf).
 *
 * @param {string[]|null} scope
 */
export function scopeSummary(scope, locale = "nl") {
  const s = scope || [];
  return s.length ? s.join(", ") : translate(locale, "guardrail.project");
}

/**
 * Het openstaande CONCEPT van een ticket (BETON-422), of `null`.
 *
 * Bewust een eigen functie naast `guardrailMeta` en géén veld daarin: concept
 * en actieve versie bestaan náást elkaar op één ticket. Een concept bindt
 * niets — tot een mens het goedkeurt geldt de actieve versie onverkort, en de
 * backend laat `GUARDRAIL_ACTIVE` er dan ook nooit naar kijken. Eén gedeelde
 * meta met een `isConcept`-vlag zou die scheiding juist opheffen.
 *
 * @param {object|null} item
 */
export function guardrailProposalMeta(item) {
  const p = (item || {}).guardrail_proposal;
  if (!p) return null;
  return {
    kind: p.kind || "set",
    isLift: p.kind === "lift",
    text: p.guardrail_md || "",
    reviewBy: p.review_by || null,
    reason: p.reason || "",
    scope: p.scope || [],
    proposedBy: p.proposed_by || null,
    proposedAt: p.proposed_at || null,
  };
}

/**
 * De reviewregel van een concept.
 *
 * `approve` vervangt een ontbrekende **of al verstreken** voorgestelde datum
 * door de default-horizon (vandaag + 90), dus een verstreken datum tonen zou
 * een datum beloven die de server niet gaat gebruiken. Géén overdue-accent: een
 * concept loopt nog niet.
 *
 * @param {string|null} reviewBy
 * @param {string} [today]
 */
export function proposalReviewLabel(reviewBy, today = localToday(), locale = "nl") {
  const d = (reviewBy || "").trim();
  if (!d || d < today) return translate(locale, "guardrail.reviewPending");
  return translate(locale, "guardrail.reviewOn", { date: d });
}

/**
 * Regel-diff tussen de actieve guardrail en het concept — tekst, scope en
 * reviewdatum als regels, zodat één weergave alle drie de wijzigingen toont.
 *
 * `null` (dus: geen diff) als er niets te vergelijken valt: zonder actieve
 * guardrail zou élke regel een `add` zijn, en een opheffingsvoorstel draagt
 * geen tekst maar een reden. De component toont dan het concept zelf.
 *
 * @param {ReturnType<typeof guardrailMeta>} active
 * @param {ReturnType<typeof guardrailProposalMeta>} proposal
 * @param {string} [today]
 */
export function proposalDiffSegments(active, proposal, today = localToday(), locale = "nl") {
  if (!proposal || proposal.isLift) return null;
  if (!active || !active.active) return null;
  const lines = (text, scope, reviewLine) => [
    ...String(text || "").split("\n"),
    `Scope: ${scopeSummary(scope, locale)}`,
    reviewLine,
  ];
  return lineDiff(
    lines(
      active.text,
      active.scope,
      active.reviewBy ? translate(locale, "guardrail.reviewOn", { date: active.reviewBy }) : translate(locale, "guardrail.reviewNone"),
    ).join("\n"),
    lines(
      proposal.text,
      proposal.scope,
      proposalReviewLabel(proposal.reviewBy, today, locale),
    ).join("\n"),
  );
}

/**
 * Welke "+ toevoegen"-links de compacte regel onder de omschrijving toont
 * (BETON-459): alleen voor secties die leeg zijn (geen inhoud, niet in
 * bewerking). Volgorde: Plan, dan Guardrail; Guardrail alleen voor mensen.
 *
 * @returns {Array<"plan"|"guardrail">}
 */
export function emptyAddLinks({ hasPlan = false, planEditing = false, guardrailVisible = false, isHuman = false } = {}) {
  const links = [];
  if (!hasPlan && !planEditing) links.push("plan");
  if (isHuman && !guardrailVisible) links.push("guardrail");
  return links;
}
