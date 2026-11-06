// Pure inbox-groepeerlogica (BETON-228): de platte notificatielijst uit
// GET /inbox groepeert client-side per ticket. Eén groep = alle events over
// hetzelfde ticket (ref), met een korte samenvatting ("3 reacties, 1 wijziging
// — @triage, @person"), ongelezen-telling en de losse events (nieuwste eerst).
//
// Bewust puur en zonder Svelte zodat het los met vitest te testen is; het
// component (Inbox.svelte) en de App-badge delen deze helper zodat de teller in
// de kop en de badge per constructie hetzelfde getal tonen.

// Eén venster-limiet, gedeeld door het paneel én de App-badge. De API klemt
// `limit` op 200 (api/inbox.py); we halen dat venster in één keer op, groeperen
// alles en tonen "Meer laden" als een client-side onthulling van al-geladen
// groepen. Zo tellen kop en badge ongelezen groepen over hetzelfde venster.
export const INBOX_FETCH_LIMIT = 200;

// Vaste volgorde waarin reason-typen in de samenvatting verschijnen, plus hun
// NL enkel-/meervoud. Onbekende reasons vallen terug op "update".
const REASON_ORDER = ["due", "guardrail", "mention", "assigned", "comment", "update"];
const REASON_NOUNS = {
  // BETON-367: afgeleide deadline-entry (geen event, dus geen actor).
  due: ["deadline", "deadlines"],
  // BETON-422: openstaand guardrail-concept, eveneens afgeleid — maar mét
  // actor: wie het voorstelde bepaalt mede of de mens het serieus neemt. Vóór
  // "mention": een wachtende beslissing gaat boven een vermelding.
  guardrail: ["guardrail-voorstel", "guardrail-voorstellen"],
  mention: ["vermelding", "vermeldingen"],
  assigned: ["toewijzing", "toewijzingen"],
  comment: ["reactie", "reacties"],
  update: ["wijziging", "wijzigingen"],
};

const REASON_NOUNS_EN = {
  due: ["due date", "due dates"], guardrail: ["guardrail proposal", "guardrail proposals"],
  mention: ["mention", "mentions"], assigned: ["assignment", "assignments"],
  comment: ["comment", "comments"], update: ["update", "updates"],
};

// Hoeveel actoren we maximaal in de samenvatting noemen voordat we "+N" tonen.
const MAX_ACTORS = 3;

function projectOf(ref) {
  // Refs heten KEY-seq (bv. "SOS-42"); de projectsleutel is alles vóór het
  // laatste koppelteken. Zo blijven gelijke seq-nummers in verschillende
  // projecten aparte groepen.
  const i = String(ref).lastIndexOf("-");
  return i > 0 ? String(ref).slice(0, i) : String(ref);
}

function normReason(reason) {
  return REASON_NOUNS[reason] ? reason : "update";
}

// Bouw de samenvatting: getelde reason-nouns + de betrokken actoren.
export function summarizeGroup(reasonCounts, actors, locale = "nl") {
  const pieces = [];
  for (const r of REASON_ORDER) {
    const n = reasonCounts[r] || 0;
    if (n > 0) {
      const [one, many] = (locale === "en" ? REASON_NOUNS_EN : REASON_NOUNS)[r];
      pieces.push(`${n} ${n === 1 ? one : many}`);
    }
  }
  let out = pieces.join(", ");
  if (actors.length) {
    const shown = actors.slice(0, MAX_ACTORS).map((a) => `@${a}`);
    const extra = actors.length - shown.length;
    out += ` — ${shown.join(", ")}${extra > 0 ? ` +${extra}` : ""}`;
  }
  return out;
}

// Groepeer een platte notificatielijst per ticket. Nieuwste groep bovenaan;
// binnen een groep staan de events ook nieuwste-eerst. Muteert de invoer niet.
export function groupNotifications(items, locale = "nl") {
  const byRef = new Map();
  for (const e of items || []) {
    // Ticketloze entries (onbereikbare agents, BETON-457) horen in geen groep.
    if (!e.ref) continue;
    const ref = e.ref;
    let g = byRef.get(ref);
    if (!g) {
      g = {
        ref,
        project: projectOf(ref),
        title: e.title,
        events: [],
        reasonCounts: {},
        actors: [],
        unread: 0,
        latestEventId: -Infinity,
        latestAt: null,
      };
      byRef.set(ref, g);
    }
    g.events.push(e);
    const reason = normReason(e.reason);
    g.reasonCounts[reason] = (g.reasonCounts[reason] || 0) + 1;
    if (!e.read) g.unread += 1;
    if (e.event_id > g.latestEventId) {
      g.latestEventId = e.event_id;
      g.latestAt = e.created_at;
      g.title = e.title; // titel van het verste event
    }
    if (e.actor && !g.actors.includes(e.actor)) g.actors.push(e.actor);
  }

  const groups = [...byRef.values()];
  for (const g of groups) {
    g.events.sort((a, b) => b.event_id - a.event_id);
    g.total = g.events.length;
    // Actoren nieuwste-eerst (events staan al gesorteerd).
    const seen = new Set();
    g.actors = [];
    for (const e of g.events) {
      if (e.actor && !seen.has(e.actor)) {
        seen.add(e.actor);
        g.actors.push(e.actor);
      }
    }
    g.summary = g.events[0]?.handover_md || summarizeGroup(g.reasonCounts, g.actors, locale);
  }
  groups.sort((a, b) => b.latestEventId - a.latestEventId);
  return groups;
}

// Aantal groepen met minstens één ongelezen event — gedeeld door de kop-teller
// in het paneel én de App-badge.
export function unreadGroupCount(items) {
  return (
    groupNotifications(items).filter((g) => g.unread > 0).length +
    agentAlerts(items).length
  );
}

// Onbereikbare agents (BETON-457): afgeleide entries zonder ticket. Ze staan
// los van de ticketgroepen en tellen wél mee in de ongelezen-teller zolang het
// probleem duurt.
export function agentAlerts(items) {
  return (items || []).filter((e) => e.reason === "agent_unreachable");
}

// Kleur van het statusbolletje per webhook-agent (BETON-457): rood =
// onbereikbaar, groen = laatste levering gelukt, grijs = geen verkeer.
export function webhookDot(h) {
  if (!h) return null;
  if (h.unreachable) return "red";
  if (h.last_delivered_at && !h.failed_count) return "green";
  return h.failed_count ? "amber" : "grey";
}

// "98 leveringen mislukt sinds 25-9" — d-m uit de ISO-timestamp van de eerste
// mislukking (UTC-datum, zoals de rest van de afgeleide entries).
export function agentUnreachableLabel(entry, locale = "nl") {
  if (!entry || entry.reason !== "agent_unreachable") return "";
  const n = entry.failed_count;
  const m = /^\d{4}-(\d{2})-(\d{2})/.exec(entry.created_at || "");
  if (locale === "en") return `${n} ${n === 1 ? "delivery" : "deliveries"} failed${m ? " since " + entry.created_at.slice(0,10) : ""}`;
  const since = m ? ` sinds ${Number(m[2])}-${Number(m[1])}` : "";
  return `${n} ${n === 1 ? "levering" : "leveringen"} mislukt${since}`;
}

// Label voor een deadline-entry (BETON-367). "vandaag" vs "verstreken" komt uit
// de entry zelf (`overdue`), niet uit een event — de reden is de datum.
// Label voor een guardrail-concept (BETON-422). De soort komt uit de entry
// (`proposal_kind`), niet uit een event: een opheffingsvoorstel is iets anders
// dan een nieuwe guardrail en moet in de rij ook anders lezen.
export function guardrailLabel(entry, locale = "nl") {
  if (!entry || entry.reason !== "guardrail") return "";
  if (locale === "en") return entry.proposal_kind === "lift" ? "proposed lifting the guardrail" : "proposed a guardrail";
  return entry.proposal_kind === "lift"
    ? "stelde voor de guardrail op te heffen"
    : "stelde een guardrail voor";
}

export function dueLabel(entry, locale = "nl") {
  if (!entry || entry.reason !== "due") return "";
  if (locale === "en") return entry.overdue ? `overdue (${entry.due_date})` : "due today";
  return entry.overdue
    ? `deadline verstreken (${entry.due_date})`
    : "deadline vandaag";
}

// --- Open vragen direct beantwoorden (BETON-456) ---------------------------
// Een net beantwoorde vraag valt na een herlaad uit GET /questions?open=true,
// maar moet in de inbox blijven staan als "Beantwoord: <optie> · wijzigen"
// (PATCH /comments/{id}/answer, BETON-263) tot de inbox sluit.

/** Is deze vraagrij met één klik te beantwoorden? Zonder opties: naar het ticket. */
export function isOptionQuestion(row) {
  return Boolean(row && row.options && row.options.length > 0);
}

/**
 * Voeg lokaal beantwoorde vragen terug in de rijen van de server.
 * `answered`: { [id]: { row, index } }. Een rij die de server nog als open
 * levert (herlaad liep voor op het antwoord) wordt wél als beantwoord getoond.
 *
 * @returns {Array<object>} rijen nieuwste-eerst, met `answeredIndex` (number|null)
 */
export function mergeAnswered(rows, answered) {
  const done = answered || {};
  const out = (rows || []).map((r) =>
    r.id in done ? { ...r, answeredIndex: done[r.id].index } : { ...r, answeredIndex: null }
  );
  const seen = new Set(out.map((r) => r.id));
  for (const [id, a] of Object.entries(done)) {
    if (!seen.has(Number(id))) out.push({ ...a.row, answeredIndex: a.index });
  }
  return out.sort((a, b) => b.id - a.id);
}

/** Aantal nog onbeantwoorde rijen (de teller van "Open vragen"). */
export function openCount(rows) {
  return (rows || []).filter((r) => r.answeredIndex == null).length;
}

/** Label na beantwoorden; leeg als de index niet (meer) bij de opties past. */
export function answeredLabel(row, locale = "nl") {
  const o = row?.options?.[row?.answeredIndex];
  return o == null ? "" : `${locale === "en" ? "Answered" : "Beantwoord"}: ${o}`;
}

/** Open direct; gelezen markeren mag navigatie nooit ophouden (BETON-492). */
export function openInboxGroup(group, onopen, markGroupRead) {
  onopen(group.ref);
  return markGroupRead(group);
}
