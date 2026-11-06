// Triage bepaalt alleen de toelichting; extra velden beginnen altijd dicht
// (BETON-495), ook bij een project zonder triage.
export function newItemDefaults(project) {
  const triage = project?.triage_enabled === true;
  return { showTriageHint: triage, moreOpen: false };
}
