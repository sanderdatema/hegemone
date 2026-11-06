import {afterEach, describe, it, expect} from 'vitest';
import {render} from 'svelte/server';
import {readFileSync} from 'node:fs';
import Agents from './Agents.svelte';
import ModelClasses from './ModelClasses.svelte';
import {setLocale, translate} from './lib/i18n.js';

afterEach(() => setLocale('en'));
describe('lokalisatie van agentbeheer', () => {
  it('rendert Engelse en Nederlandse panelen', () => {
    setLocale('en');
    expect(render(Agents).body).toContain('Agents &amp; users');
    expect(render(ModelClasses).body).toContain('Work classes → model');
    setLocale('nl');
    expect(render(Agents).body).toContain('Agents &amp; gebruikers');
    expect(render(ModelClasses).body).toContain('Werkklassen → model');
  });
  it('beschrijft een configureerbare ontvanger zonder private gateway', () => {
    expect(translate('en', 'agents.webhookHint')).toContain('receiver endpoint');
    const source = readFileSync(new URL('./Agents.svelte', import.meta.url), 'utf8');
    expect(source).not.toContain('host:8644');
    expect(source).not.toContain('/webhooks/smid');
    expect(source).toContain('https://agent.example.org/events');
    expect(source).toContain('type="password"');
  });
});

import UserSettings from './UserSettings.svelte';
import CredentialPolicy from './CredentialPolicy.svelte';
import ErrorNote from './ErrorNote.svelte';

it('vertaalt persoonlijke instellingen, sleutelbeleid en herhaalactie', () => {
  setLocale('en');
  expect(render(UserSettings, {props: {me: {handle: 'operator'}}}).body).toContain('My settings');
  expect(render(CredentialPolicy, {props: {handle: 'worker'}}).body).toContain('Key permissions and expiry');
  expect(render(ErrorNote, {props: {message: 'Fixture', onRetry: () => {}}}).body).toContain('Retry');
  setLocale('nl');
  expect(render(UserSettings, {props: {me: {handle: 'operator'}}}).body).toContain('Mijn instellingen');
  expect(render(CredentialPolicy, {props: {handle: 'worker'}}).body).toContain('Sleutelrechten en vervaldatum');
  expect(render(ErrorNote, {props: {message: 'Fixture', onRetry: () => {}}}).body).toContain('Opnieuw');
});

import Deliveries from './Deliveries.svelte';
import {formatTimestamp} from './lib/board.js';

it('vertaalt leveringen en hun relatieve tijd', () => {
  setLocale('en');
  expect(render(Deliveries).body).toContain('Webhook deliveries');
  expect(render(Deliveries).body).toContain('No webhook deliveries yet.');
  expect(translate('en', 'deliveries.attemptOne', {count: 1})).toBe('1 attempt');
  expect(translate('en', 'deliveries.attemptMany', {count: 2})).toBe('2 attempts');
  const now = Date.parse('2026-11-05T12:00:00Z');
  expect(formatTimestamp('2026-11-05T11:30:00Z', now, 'en')).toBe('30 min ago');
  expect(formatTimestamp('2026-11-05T11:30:00Z', now)).toBe('30 min geleden');
  setLocale('nl');
  expect(render(Deliveries).body).toContain('Webhook-leveringen');
});

import ProjectSettings from './ProjectSettings.svelte';
import {stateGroupLabel, agentTypeLabel} from './lib/labels.js';

it('vertaalt projectinstellingen zonder gebruikersnamen of groepen te hernoemen', () => {
  const props = {projectKey:'TEAM', projectName:'Eigen projectnaam'};
  setLocale('en');
  const english = render(ProjectSettings, {props}).body;
  expect(english).toContain('Project name');
  expect(english).toContain('Automatic triage');
  expect(english).toContain('Agent access');
  expect(english).toContain('Columns (states)');
  expect(english).toContain('Eigen projectnaam');
  expect(stateGroupLabel('unstarted','en')).toBe('Not started');
  expect(agentTypeLabel('hermes','en')).toContain('Webhook agent');
  setLocale('nl');
  expect(render(ProjectSettings, {props}).body).toContain('Automatische triage');
  expect(stateGroupLabel('unstarted')).toBe('Nog niet gestart');
  expect(translate('en','projectSettings.deleteColumn',{name:'Eigen kolom'})).toContain('Eigen kolom');
});

import ProjectTemplate from './ProjectTemplate.svelte';

it('vertaalt de template zonder kolomwaarden aan te passen', () => {
  setLocale('en');
  const editable = render(ProjectTemplate, {props: {editable:true}}).body;
  expect(editable).toContain('Edit project template');
  expect(editable).toContain('Existing projects keep their own columns.');
  expect(render(ProjectTemplate).body).toContain('View project template');
  setLocale('nl');
  expect(render(ProjectTemplate, {props:{editable:true}}).body).toContain('Projecttemplate aanpassen');
});
