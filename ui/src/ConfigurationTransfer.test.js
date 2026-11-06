import { afterEach, expect, it } from 'vitest';
import { render } from 'svelte/server';
import ConfigurationTransfer from './ConfigurationTransfer.svelte';
import { setLocale } from './lib/i18n.js';
import { parseConfiguration, canConfirmConfiguration, configurationDownload } from './lib/configurationTransfer.js';

const document = {format:'hegemone.configuration',version:1,installation:{language:'nl'}};
afterEach(() => setLocale('en'));

it('parseert het formaat en weigert ongeldige input zonder broninhoud in de fout', () => {
  expect(parseConfiguration(JSON.stringify(document))).toEqual(document);
  for(const text of ['{"key":"synthetic-private-value"', 'null','[]',JSON.stringify({...document,version:2})]) {
    try { parseConfiguration(text); throw new Error('Niet geweigerd'); }
    catch(error) { expect(error.message).toBe('invalidFile'); }
  }
});

it('bevestigt uitsluitend een verse, gewijzigde preview zonder conflicten', () => {
  const now=Date.parse('2026-11-06T00:00:00Z');
  const preview={preview_token:'x'.repeat(43),can_apply:true,changes:[{}],conflicts:[],expires_at:'2026-11-06T00:10:00Z'};
  expect(canConfirmConfiguration(preview,now)).toBe(true);
  for(const change of [{can_apply:false},{changes:[]},{conflicts:[{code:'unknown_agent'}]},{preview_token:undefined},{expires_at:'invalid'},{expires_at:'2026-11-06T00:00:00Z'}]) expect(canConfirmConfiguration({...preview,...change},now)).toBe(false);
});

it('downloadt een zelfstandige JSON zonder het document te veranderen', () => {
  const before=JSON.stringify(document);
  expect(JSON.parse(configurationDownload(document))).toEqual(document);
  expect(JSON.stringify(document)).toBe(before);
});

it.each([['en','Import and export','Save or discard your changes before importing.'],['nl','Importeren en exporteren','Bewaar je wijzigingen of gooi ze weg voordat je importeert.']])('rendert %s met blokkade voor onbewaarde instellingen', (language,title,note) => {
  setLocale(language);
  const body=render(ConfigurationTransfer,{props:{dirty:true}}).body;
  expect(body).toContain(title);expect(body).toContain(note);
  expect(body).toMatch(/type="file"[^>]*disabled/);
  expect(body).not.toContain('preview_token');
});
