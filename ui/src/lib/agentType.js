// Pure helpers voor het Agents-panel (BETON-103): agent_type-badges en de
// vraag of het webhook-formulier zichtbaar moet zijn. Los van Svelte
// getest zodat de UI-logica niet stilzwijgend afwijkt van het backend-
// contract (agent_type is alleen zinvol bij kind='agent'; webhook alleen bij
// de compatibele webhooksoort agent_type='hermes'. De zichtbare naam en
// aanwijzingen zijn generiek; een ontvanger hoeft geen Hermes-installatie te zijn).

export const AGENT_TYPES = ["coding", "hermes"];

/**
 * Mag agent_type getoond/bewerkt worden voor deze user-kind?
 * @param {string} kind - 'human' | 'agent'
 * @returns {boolean}
 */
export function showsAgentType(kind) {
  return kind === "agent";
}

/**
 * Moet het webhook-configuratieformulier (url/secret) getoond worden?
 * Alleen voor Hermes-agents — coding-agents (Claude/Codex) worden gepolld.
 * @param {string} kind
 * @param {string|null|undefined} agentType
 * @returns {boolean}
 */
export function showsWebhookFields(kind, agentType) {
  return kind === "agent" && agentType === "hermes";
}

// --- Gegroepeerde toewijs-keuze (BETON-366) ---------------------------------
//
// Eén ruwe select met 12+ handles op alfabet is onbruikbaar zodra er queues
// en Hermes-agents bijkomen (BETON-207/83). `groupAssignees` verdeelt de
// users-lijst in optgroups, "Aan mij" altijd bovenaan. Puur en los van Svelte
// getest — de UI-select (AssigneeSelect.svelte) rendert alleen wat hier
// uitkomt.

/**
 * Groepeer users voor een toewijs-select.
 * @param {Array<object>} users - ruwe user-rijen (users_repo.serialize-vorm:
 *   handle/kind/agent_type/is_virtual/active).
 * @param {{handle?: string}|null} [me] - ingelogde user, voor "Aan mij".
 * @param {{keep?: string}} [opts] - `keep`: handle die altijd blijft staan
 *   ook als hij inactief is (de huidige assignee van het item).
 * @returns {Array<{label: string, options: Array<object>}>} lege groepen weggelaten.
 */
export function groupAssignees(users, me, { keep } = {}) {
  const list = (users || []).filter((u) => u.active !== false || u.handle === keep);
  const byHandle = (a, b) => (a.handle || "").localeCompare(b.handle || "");
  const meHandle = me?.handle;
  const meUser = meHandle ? list.find((u) => u.handle === meHandle) : null;

  const rest = list.filter((u) => u.handle !== meHandle);
  const groups = [
    { label: "Aan mij", options: meUser ? [meUser] : [] },
    { label: "Queues", options: rest.filter((u) => u.is_virtual) },
    { label: "Mensen", options: rest.filter((u) => u.kind === "human") },
    {
      label: "Coding-agents",
      options: rest.filter((u) => u.kind === "agent" && u.agent_type === "coding" && !u.is_virtual),
    },
    {
      label: "Hermes-agents",
      options: rest.filter((u) => u.kind === "agent" && u.agent_type === "hermes" && !u.is_virtual),
    },
    {
      label: "Overig",
      options: rest.filter(
        (u) => u.kind !== "human" && !u.is_virtual && u.agent_type !== "coding" && u.agent_type !== "hermes",
      ),
    },
  ];
  for (const g of groups) g.options = [...g.options].sort(byHandle);
  return groups.filter((g) => g.options.length);
}
