// Bestandscontrole en bevestigingspoort, zonder browserstorage of credentialkopieën.
export const MAX_CONFIGURATION_BYTES = 2 * 1024 * 1024;

export function parseConfiguration(text) {
  let value;
  try { value = JSON.parse(text); } catch { throw new Error('invalidFile'); }
  if (!value || Array.isArray(value) || value.format !== 'hegemone.configuration' || value.version !== 1) throw new Error('invalidFile');
  return value;
}

export function canConfirmConfiguration(preview, now = Date.now()) {
  const expires = Date.parse(preview?.expires_at);
  return preview?.can_apply === true && !preview.conflicts?.length && typeof preview.preview_token === 'string' && preview.preview_token.length >= 32 && preview.changes?.length > 0 && Number.isFinite(expires) && expires > now;
}

export function configurationDownload(document) {
  return JSON.stringify(document, null, 2) + '\n';
}
