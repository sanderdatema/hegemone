import apiErrors from '../../../src/betonning/api_errors.json' with { type: 'json' };
// Gedeelde catalogus: Engelse fallback, geen credentials in taalvoorkeuren.
import { uiMessages } from './uiMessages.js';
import { wikiMessages } from './wikiMessages.js';
import { projectMessages } from './projectMessages.js';
import { adminMessages } from './adminMessages.js';
import { dailyMessages } from './dailyMessages.js';
import { writable, derived } from 'svelte/store';

export const LOCALE_KEY = 'hegemone_locale';
export const catalogs = {
  en: {
    ...Object.fromEntries(Object.entries(apiErrors).map(([code, entry]) => [`api.${code}`, entry.en])),
    ...dailyMessages.en,
    ...adminMessages.en,
    ...projectMessages.en,
    ...wikiMessages.en,
    ...uiMessages.en,
    'login.intro': 'Enter your API key. Your browser keeps only a secure session.',
    'login.signIn': 'Sign in', 'login.key': 'API key',
    'nav.board': 'Board', 'nav.list': 'List', 'nav.wiki': 'Wiki',
    'nav.memory': 'Wiki / memory', 'nav.activity': 'Activity', 'nav.view': 'View',
    'nav.search': 'Search', 'nav.more': 'More actions', 'nav.newTicket': 'New ticket',
    'nav.project': 'Project', 'nav.projectSettings': 'Project settings',
    'nav.projects': 'Manage projects', 'nav.agents': 'Agents & users',
    'nav.triage': 'Chat with triage', 'nav.deliveries': 'Webhook deliveries',
    'nav.mySettings': 'My settings', 'nav.myTickets': 'My tickets',
    'nav.logout': 'Sign out', 'nav.selectMany': 'Select multiple',
    'nav.endSelection': 'End selection', 'nav.live': 'Live connected',
    'nav.offline': 'Not live', 'nav.theme': 'Theme',
    'theme.system': 'System', 'theme.light': 'Light', 'theme.dark': 'Dark',
    'filter.clear': 'Clear all', 'filter.title': 'Filters',
    'inbox.unread': '{count} unread', 'language.label': 'Language in this browser',
  },
  nl: {
    ...Object.fromEntries(Object.entries(apiErrors).map(([code, entry]) => [`api.${code}`, entry.nl])),
    ...dailyMessages.nl,
    ...adminMessages.nl,
    ...projectMessages.nl,
    ...wikiMessages.nl,
    ...uiMessages.nl,
    'login.intro': 'Voer je API-key in. Je browser bewaart alleen een beveiligde sessie.',
    'login.signIn': 'Inloggen', 'login.key': 'API-key',
    'nav.board': 'Bord', 'nav.list': 'Lijst', 'nav.wiki': 'Wiki',
    'nav.memory': 'Wiki / geheugen', 'nav.activity': 'Activiteit', 'nav.view': 'Weergave',
    'nav.search': 'Zoeken', 'nav.more': 'Meer acties', 'nav.newTicket': 'Nieuwe ticket',
    'nav.project': 'Project', 'nav.projectSettings': 'Projectinstellingen',
    'nav.projects': 'Projecten beheren', 'nav.agents': 'Agents & gebruikers',
    'nav.triage': 'Chat met triage', 'nav.deliveries': 'Webhook-leveringen',
    'nav.mySettings': 'Mijn instellingen', 'nav.myTickets': 'Mijn tickets',
    'nav.logout': 'Uitloggen', 'nav.selectMany': 'Meerdere selecteren',
    'nav.endSelection': 'Selectie afsluiten', 'nav.live': 'Live verbonden',
    'nav.offline': 'Niet live', 'nav.theme': 'Thema',
    'theme.system': 'Systeem', 'theme.light': 'Licht', 'theme.dark': 'Donker',
    'filter.clear': 'Wis alles', 'filter.title': 'Filters',
    'inbox.unread': '{count} ongelezen', 'language.label': 'Taal in deze browser',
  },
};

export function readLocale(storage) {
  try {
    const target = storage ?? (typeof localStorage === 'undefined' ? null : localStorage);
    return target?.getItem(LOCALE_KEY) === 'nl' ? 'nl' : 'en';
  }
  catch { return 'en'; }
}
export const locale = writable(readLocale());
export function setLocale(value) {
  const selected = value === 'nl' ? 'nl' : 'en';
  locale.set(selected);
  try { localStorage.setItem(LOCALE_KEY, selected); } catch { /* Opslag is optioneel. */ }
}
export function translate(language, key, params = {}) {
  const message = catalogs[language]?.[key] ?? catalogs.en[key] ?? key;
  return message.replace(/\{([a-zA-Z_]+)\}/g, (match, name) => String(params[name] ?? match));
}
export const t = derived(locale, language => (key, params) => translate(language, key, params));
