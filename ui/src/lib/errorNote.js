// Normaliseert de props voor <ErrorNote> (BETON-226): puur zodat de
// weergave-regels (wel/geen retry-knop, welk label) los van de component met
// vitest te toetsen zijn.

const DEFAULT_RETRY_LABEL = "Opnieuw proberen";

export function resolveErrorNote({ message, onRetry, retryLabel } = {}) {
  const trimmed = typeof message === "string" ? message.trim() : "";
  return {
    message: trimmed,
    visible: trimmed.length > 0,
    showRetry: trimmed.length > 0 && typeof onRetry === "function",
    retryLabel: (typeof retryLabel === "string" && retryLabel.trim()) || DEFAULT_RETRY_LABEL,
  };
}
