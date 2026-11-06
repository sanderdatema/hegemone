import { translate } from "./i18n.js";
import { isQuiet } from "./overview.js";

// Projectkiezer in de topbar (BETON-453). "Overzicht (alle projecten)" is een
// globale bestemming en geen view van één project, dus het staat als bovenste
// optie in de kiezer i.p.v. als tab naast Bord/Lijst. De view blijft
// `overview` in de URL en in localStorage (viewState.js ongewijzigd).

// Sentinel-waarde in de kiezer; botst niet met een projectkey (die zijn
// hoofdletters/cijfers).
export const OVERVIEW_VALUE = "__overview__";

const toOption = (p) => ({ value: p.key, label: `${p.key} — ${p.name}` });

// Stil-regel is die van het Overzicht (BETON-475). Het geopende project blijft
// in de actieve groep, anders verdwijnt de huidige keuze naar onderaan. Een
// project zonder `last_activity_at`-veld (oude respons) telt als actief; `null`
// valt terug op de aanmaakdatum (BETON-491).
function splitQuiet(projects, current, now) {
  const active = [];
  const quiet = [];
  for (const p of projects || []) {
    (p.key !== current && p.last_activity_at !== undefined && isQuiet(p, now) ? quiet : active).push(p);
  }
  quiet.sort((a, b) => a.key.localeCompare(b.key));
  return { active, quiet };
}

export function projectPickerOptions(projects, current = null, now = Date.now(), locale = "nl") {
  return [
    { value: OVERVIEW_VALUE, label: translate(locale, "project.overview") },
    ...splitQuiet(projects, current, now).active.map(toOption),
  ];
}

/** Optgroups voor de kiezer: "Stille projecten" onderaan, op alfabet. */
export function projectPickerGroups(projects, current = null, now = Date.now(), locale = "nl") {
  const { quiet } = splitQuiet(projects, current, now);
  return quiet.length ? [{ label: translate(locale, "project.quiet"), options: quiet.map(toOption) }] : [];
}

// Wat de kiezer toont: in de overzicht-view het Overzicht, anders het project.
export function projectPickerValue(activeView, current) {
  return activeView === "overview" ? OVERVIEW_VALUE : current;
}

// Keuze → actie. Een project kiezen terwijl je in het overzicht staat verlaat
// het overzicht (anders lijkt er niets te gebeuren: het overzicht toont álle
// projecten); `fallbackView` is de view waar je dan landt.
export function projectPickerAction(choice, activeView, fallbackView = "board") {
  if (choice === OVERVIEW_VALUE) return { view: "overview", project: null };
  return {
    view: activeView === "overview" ? fallbackView : null,
    project: choice,
  };
}
