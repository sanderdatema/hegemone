// Pure logica voor het Overzicht (BETON-464): tellers met woorden, volgorde,
// en de ingeklapte "Stil"-sectie.

export const QUIET_DAYS = 30;

function ms(iso) {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isNaN(t) ? 0 : t;
}

/** "Iets voor jou": een open vraag aan de kijker of ongelezen activiteit. */
export function hasForYou(p) {
  return (p.open_questions || 0) > 0 || (p.unread || 0) > 0;
}

/** Stil = geen activiteit de laatste QUIET_DAYS dagen (BETON-475: alleen
 *  activiteit, niet meer "0 open"). Eén regel voor het Overzicht én de
 *  projectkiezer; bij een leeg project telt de aanmaakdatum (BETON-491). */
export function isQuiet(p, now = Date.now()) {
  return now - Math.max(ms(p.last_activity_at), ms(p.created_at)) > QUIET_DAYS * 86400000;
}

/** Splitst in { active, quiet }. Active: eerst "iets voor jou", dan laatste
 *  activiteit (nieuwste eerst), dan key. Quiet: op key. */
export function splitProjects(rows, now = Date.now()) {
  const active = [];
  const quiet = [];
  for (const p of rows) (isQuiet(p, now) ? quiet : active).push(p);
  active.sort(
    (a, b) =>
      Number(hasForYou(b)) - Number(hasForYou(a)) ||
      Math.max(ms(b.last_activity_at), ms(b.created_at)) - Math.max(ms(a.last_activity_at), ms(a.created_at)) ||
      a.key.localeCompare(b.key),
  );
  quiet.sort((a, b) => a.key.localeCompare(b.key));
  return { active, quiet };
}

/** Tellers met woorden, nul-tellers weg. `mine` = voor jou bedoeld (accent). */
export function countParts(p, locale = "nl") {
  if (locale === "en") return [
    {key:"in_progress",n:p.in_progress,text:`${p.in_progress} in progress`,title:"Tickets in progress"},
    {key:"blocked",n:p.blocked,text:`${p.blocked} blocked`,title:"Blocked by other open work"},
    {key:"unassigned",n:p.unassigned,text:`${p.unassigned} unassigned`,title:"Unassigned open tickets"},
    {key:"open_questions",n:p.open_questions,text:`${p.open_questions} ${p.open_questions === 1 ? "question" : "questions"}`,title:"Open questions for you",mine:true},
    {key:"unread",n:p.unread,text:`${p.unread} unread`,title:"Tickets with unread activity",mine:true},
  ].filter(part => part.n > 0);
  const parts = [
    { key: "in_progress", n: p.in_progress, text: `${p.in_progress} lopend`, title: "Tickets in behandeling" },
    { key: "blocked", n: p.blocked, text: `${p.blocked} geblokkeerd`, title: "Geblokkeerd door ander open werk" },
    { key: "unassigned", n: p.unassigned, text: `${p.unassigned} niet toegewezen`, title: "Open tickets zonder assignee" },
    { key: "open_questions", n: p.open_questions, text: `${p.open_questions} ${p.open_questions === 1 ? "vraag" : "vragen"}`, title: "Open vragen voor jou", mine: true },
    { key: "unread", n: p.unread, text: `${p.unread} ongelezen`, title: "Tickets met ongelezen activiteit", mine: true },
  ];
  return parts.filter((x) => x.n > 0);
}

/** "4 lopend · 7 vragen · 5 ongelezen" (leeg bij alleen nullen). */
export function countsText(p, locale = "nl") {
  return countParts(p, locale).map((x) => x.text).join(" · ");
}
