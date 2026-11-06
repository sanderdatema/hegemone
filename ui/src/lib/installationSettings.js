// Alleen bekende publieke velden; responsemetadata en keys worden geen formulierdata.
export const PROVIDERS = ['llm', 'embedding'];
const GENERAL = ['public_url', 'language', 'ai_language', 'triage_enabled', 'wiki_compile_enabled'];
const PROVIDER = ['enabled', 'base_url', 'model', 'timeout'];

export function canManageInstallation(me) {
  return !!(me?.kind === 'human' && me.credential_policy?.scopes?.includes('admin'));
}

export function installationDraft(data) {
  const settings = data.settings;
  const draft = Object.fromEntries(GENERAL.map(key => [key, settings[key]]));
  for (const name of PROVIDERS) draft[name] = Object.fromEntries(PROVIDER.map(key => [key, settings[name][key]]));
  return draft;
}

export function managed(data, field, provider = null) {
  if (!provider) return data?.runtime?.overrides?.includes(field) || false;
  const status = data?.runtime?.providers?.[provider];
  return status?.source === 'injected' || status?.overrides?.includes(field) || false;
}

export function installationUpdate(data, draft, keys = {}, clear = {}) {
  const original = installationDraft(data);
  const settings = {};
  for (const field of GENERAL) {
    if (!managed(data, field) && draft[field] !== original[field]) settings[field] = draft[field];
  }
  for (const name of PROVIDERS) {
    const provider = {};
    for (const field of PROVIDER) {
      if (!managed(data, field, name) && draft[name][field] !== original[name][field]) provider[field] = draft[name][field];
    }
    if (!managed(data, 'api_key', name)) {
      if (keys[name] && clear[name]) throw new Error('Conflicting key actions');
      if (clear[name]) provider.api_key = null;
      else if (keys[name]) provider.api_key = keys[name];
    }
    if (Object.keys(provider).length) settings[name] = provider;
  }
  return { schema_version: data.schema_version, expected_revision: data.revision, settings };
}

export function providerStatus(status) {
  if (status?.error === 'secret_unavailable') return 'secretUnavailable';
  if (!status?.enabled) return 'disabled';
  return status.ready ? 'configured' : 'incomplete';
}
