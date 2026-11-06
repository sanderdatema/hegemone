import { afterEach, describe, expect, it } from 'vitest';
import { render } from 'svelte/server';
import InstallationSettings from './InstallationSettings.svelte';
import { setLocale } from './lib/i18n.js';
import { installationDraft, installationUpdate, canManageInstallation, providerStatus } from './lib/installationSettings.js';

export function fixture() {
  return { schema_version:1,revision:7,secret_storage_ready:true,settings:{public_url:'https://own.example',language:'en',ai_language:'en',triage_enabled:false,wiki_compile_enabled:false,
    llm:{enabled:true,base_url:'https://provider.example/v1',model:'own-model',timeout:60,has_api_key:true},
    embedding:{enabled:false,base_url:'',model:'',timeout:30,has_api_key:false}},
    runtime:{providers:{llm:{enabled:true,ready:true,source:'stored',overrides:[]},embedding:{enabled:false,ready:false,source:'stored',overrides:[]}},overrides:[]} };
}
afterEach(() => setLocale('en'));

it.each([['en','Installation settings','Connection not tested'],['nl','Installatie-instellingen','Verbinding niet getest']])('rendert %s met lege keyvelden en bewaarde data', (language,title) => {
  setLocale(language);
  const data = fixture();
  const body = render(InstallationSettings,{props:{initialData:data}}).body;
  expect(body).toContain(title);
  expect(body).toContain('own-model');
  expect(body).toContain('https://own.example');
  expect(body).toContain('type="password"');
  expect(body).not.toContain('api_key');
  expect(data.settings.llm.has_api_key).toBe(true);
});

it('bouwt een partiële update zonder metadata of lege keys', () => {
  const data=fixture();
  const draft=installationDraft(data);
  draft.llm.model='my-model';
  expect(installationUpdate(data,draft,{llm:'',embedding:''})).toEqual({schema_version:1,expected_revision:7,settings:{llm:{model:'my-model'}}});
  expect(installationUpdate(data,draft,{llm:'synthetic-replacement'}).settings.llm.api_key).toBe('synthetic-replacement');
  expect(installationUpdate(data,draft,{}, {llm:true}).settings.llm.api_key).toBeNull();
  expect(() => installationUpdate(data,draft,{llm:'synthetic'},{llm:true})).toThrow();
  expect(data.settings.llm.model).toBe('own-model');
});

it('slaat alle overschreven velden over en toont beheerstatus', () => {
  const data=fixture();
  data.runtime.overrides=['ai_language'];
  data.runtime.providers.llm.overrides=['api_key','model'];
  const draft=installationDraft(data);draft.ai_language='nl';draft.llm.model='ignored';
  expect(installationUpdate(data,draft,{llm:'synthetic'}).settings).toEqual({});
  const body=render(InstallationSettings,{props:{initialData:data}}).body;
  expect(body).toContain('Managed by deployment configuration');
  expect(body).not.toContain('value="synthetic"');
});

it('onderscheidt geconfigureerd van getest en bewaakt mens/admin', () => {
  expect(providerStatus({enabled:true,ready:true})).toBe('configured');
  expect(providerStatus({enabled:true,ready:false})).toBe('incomplete');
  expect(providerStatus({error:'secret_unavailable'})).toBe('secretUnavailable');
  expect(canManageInstallation({kind:'human',credential_policy:{scopes:['read','admin']}})).toBe(true);
  expect(canManageInstallation({kind:'human',credential_policy:{scopes:['read']}})).toBe(false);
  expect(canManageInstallation({kind:'agent',credential_policy:{scopes:['admin']}})).toBe(false);
});
