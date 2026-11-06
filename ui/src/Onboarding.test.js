import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import Onboarding from './Onboarding.svelte';

describe('onboarding', () => {
  it('toont de hervatte projectstap in het Engels', () => {
    const {body} = render(Onboarding, {props: {progress: {step: 'project', locale: 'en'}}});
    expect(body).toContain('Create your first project');
    expect(body).toContain('name="key"');
    expect(body).toContain('pattern="[A-Za-z0-9]{1,20}"');
  });
  it('biedt agentconfiguratie en doorgaan zonder agents in het Nederlands', () => {
    const {body} = render(Onboarding, {props: {progress: {step: 'agents', locale: 'nl'}}});
    expect(body).toContain('Agents instellen');
    expect(body).toContain('Hegemone openen');
    expect(body).not.toContain('name="key"');
  });
});
