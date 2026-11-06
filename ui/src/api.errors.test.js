import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from './api.js';
import { setLocale } from './lib/i18n.js';
import { apiError } from './lib/apiError.js';
import { errorCause } from './lib/loadError.js';

beforeEach(() => {
  vi.stubGlobal('localStorage', { getItem: vi.fn(() => null), setItem: vi.fn(), removeItem: vi.fn() });
  vi.stubGlobal('window', { dispatchEvent: vi.fn() });
  setLocale('en');
});
afterEach(() => { vi.unstubAllGlobals(); });

function fail(status, body) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })));
}

describe('API-foutpresentatie', () => {
  it.each([['en', 'Unknown item: EIGEN-{value}'], ['nl', 'Onbekend item: EIGEN-{value}']])('vertaalt %s met behoud van detail en data', async (language, message) => {
    setLocale(language);
    const data = { detail: 'Onbekend item: EIGEN-{value}', error_code: 'unknown_item', error_params: { value: 'EIGEN-{value}' } };
    fail(404, data);
    const error = await api.projects().catch(e => e);
    expect(error.message).toBe(`404: ${message}`);
    expect(errorCause(error)).toBe(`404: ${message}`);
    expect(error.detail).toBe(data.detail);
    expect(error.status).toBe(404);
    expect(error.code).toBe('unknown_item');
  });

  it('behoudt gestructureerde validatiefouten naast de vertaalde veldmelding', () => {
    const detail = [{ type: 'missing', loc: ['body', 'title'] }];
    const error = apiError(422, { detail, error_code: 'validation', error_params: { fields: 'body.title' } }, '', 'en');
    expect(error.message).toBe('422: Check the input: body.title.');
    expect(error.detail).toBe(detail);
    expect(errorCause(error)).toBe(error.message);
  });

  it('behoudt onbekende fouttekst en gestructureerde bevestigingsdata', () => {
    expect(apiError(502, { detail: 'Eigen upstreamoorzaak', error_code: 'unknown' }, '').message).toBe('502: Eigen upstreamoorzaak');
    const detail = { error: 'confirmation', total: 7 };
    expect(apiError(409, { detail }, '').detail).toBe(detail);
    expect(apiError(500, { detail: 'bron', error_code: '__proto__' }, '').message).toBe('500: bron');
  });

  it('laat een verkeerd setup-token de bestaande sessie behouden', async () => {
    fail(401, { detail: 'Ongeldig setup-token', error_code: 'setup_token_invalid' });
    await expect(api.setup({ handle: 'test' }, 'synthetic-token')).rejects.toThrow('401: Invalid setup token');
    expect(window.dispatchEvent).not.toHaveBeenCalled();
    expect(localStorage.removeItem).not.toHaveBeenCalled();
  });

  it('laat gewone 401-fouten de sessie intrekken en vertalen', async () => {
    fail(401, { detail: 'Ongeldige API-key', error_code: 'invalid_api_key' });
    await expect(api.projects()).rejects.toThrow('401: Invalid API key');
    expect(window.dispatchEvent).toHaveBeenCalledOnce();
    expect(localStorage.removeItem).toHaveBeenCalledWith('betonning_session');
  });

  it('behoudt een HTTP-fallback als de server geen JSON stuurt', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('gateway', { status: 502, statusText: 'Bad Gateway' })));
    await expect(api.projects()).rejects.toThrow('502: Bad Gateway');
  });
});

it('toont domeinmeldingen met behoud van oorspronkelijke itemdata', () => {
  const detail = { message: 'Item is intussen gewijzigd (updated_at komt niet overeen)', item: { title: 'Eigen titel', labels: ['eigen-label'] } };
  const error = apiError(409, { detail, error_code: 'ticket_changed' }, '', 'en');
  expect(error.message).toContain('This item has changed since it was loaded');
  expect(error.detail).toBe(detail);
  expect(error.detail.item.title).toBe('Eigen titel');
  expect(errorCause(error)).toBe(error.message);
  expect(apiError(409, { detail: { message: 'Eigen domeinmelding' } }, '').message).toBe('409: Eigen domeinmelding');
});

it('behoudt een vraag met accolades bij vertaling en geeft bevestigingsaantallen weer', () => {
  const error = apiError(409, { detail: { message: 'bron' }, error_code: 'open_question_close_forbidden', error_params: { id: '7', question: 'Eigen {id} vraag?' } }, '', 'en');
  expect(error.message).toContain('comment 7: Eigen {id} vraag?');
  expect(error.message).toContain('withdraw_question');
  expect(apiError(409, { detail: { error: 'confirmation_required', total: 17 }, error_code: 'bulk_confirmation_required', error_params: { total: 17 } }, '', 'en').message).toBe('409: Confirm changes to 17 tickets.');
});
