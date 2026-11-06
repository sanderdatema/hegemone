import { afterEach, describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import { catalogs, translate, readLocale, setLocale, locale, t } from './i18n.js';

afterEach(() => setLocale('en'));
describe('taalbasis', () => {
  it('heeft dezelfde sleutels in het Engels en Nederlands', () => {
    expect(Object.keys(catalogs.en).sort()).toEqual(Object.keys(catalogs.nl).sort());
  });
  it('valt terug op Engels voor een onbekende taal', () => {
    expect(translate('invalid', 'login.signIn')).toBe('Sign in');
    expect(translate('nl', 'unknown.key')).toBe('unknown.key');
  });
  it('vult parameters in zonder markup te interpreteren', () => {
    expect(translate('en', 'inbox.unread', {count: 3})).toBe('3 unread');
    expect(translate('nl', 'inbox.unread', {count: '<b>3</b>'})).toBe('<b>3</b> ongelezen');
  });
  it('begint met Engels en accepteert alleen ondersteunde opgeslagen taal', () => {
    for (const value of [null, '', 'de']) expect(readLocale({getItem: () => value})).toBe('en');
    expect(readLocale({getItem: () => 'nl'})).toBe('nl');
  });
  it('werkt ook als browseropslag geblokkeerd is', () => {
    expect(readLocale({getItem: () => {throw new Error('blocked');}})).toBe('en');
    expect(() => setLocale('nl')).not.toThrow();
    expect(get(locale)).toBe('nl');
    expect(get(t)('nav.board')).toBe('Bord');
    setLocale('invalid');
    expect(get(t)('nav.board')).toBe('Board');
  });
});

it('vertaalt de dagelijkse ticket- en zoekflow in beide talen', () => {
  expect(translate('en', 'ticket.create')).toBe('Create ticket');
  expect(translate('nl', 'ticket.create')).toBe('Ticket aanmaken');
  expect(translate('en', 'search.notFound', {query: 'release'})).toBe('Nothing found for “release”.');
  expect(translate('en', 'ticket.imagesFailed', {ref: 'TEAM-1', errors: 'upload'})).toBe('TEAM-1 created, but some images could not be added: upload');
});
