import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import Setup from './Setup.svelte';

describe('eerste installatie', () => {
  it('begint in het Engels en toont expliciete setupvelden', () => {
    const {body} = render(Setup, {props: {enabled: true}});
    expect(body).toContain('Welcome to Hegemone');
    expect(body).toContain('type="password"');
    expect(body).toContain('name="handle"');
    expect(body).toContain('Nederlands');
  });
  it('biedt zonder setupconfiguratie geen registratieformulier', () => {
    const {body} = render(Setup);
    expect(body).toContain('Setup is disabled');
    expect(body).not.toContain('<form');
  });
});
