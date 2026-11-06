// Pure helpers voor het chat-met-triage-paneel (BETON-120) — los te testen met
// vitest, zodat de veiligheidsrem-logica niet in Svelte-componenten verstopt zit.

// Boven de veiligheidsdrempel moet de mens het aantal typen om een bulk-actie te
// bevestigen; op/onder de drempel volstaat één klik "Bevestig".
export function needsTypedConfirm(proposal) {
  if (!proposal) return false;
  const total = proposal.total_count ?? 0;
  const threshold = proposal.threshold ?? Infinity;
  return total > threshold;
}

// Is het getypte aantal geldig om te bevestigen? Moet exact het totaal zijn
// (spiegelt de server-gate — voorkomt per ongeluk bevestigen van een bulk).
export function typedCountValid(proposal, typed) {
  if (!proposal) return false;
  const n = Number(typed);
  return Number.isInteger(n) && n === (proposal.total_count ?? 0);
}

// Beknopte preview per commando: de eerste `limit` refs tonen, de rest als "+N".
export function summarizePreview(command, limit = 8) {
  const refs = command?.refs ?? [];
  return {
    verb: command?.verb ?? "",
    shown: refs.slice(0, limit),
    hidden: Math.max(0, refs.length - limit),
    count: command?.count ?? refs.length,
    detail: command?.detail ?? null,
  };
}
