// Alleen herkende foutcodes vertalen; ruwe details blijven beschikbaar.
import apiErrors from '../../../src/betonning/api_errors.json' with { type: 'json' };
import { translate } from './i18n.js';

export function apiError(status, data, statusText, language = 'en') {
  const detail = data?.detail || statusText;
  const code = data?.error_code;
  const known = typeof code === 'string' && Object.hasOwn(apiErrors, code);
  const displayDetail = known
    ? translate(language, `api.${code}`, data.error_params || {})
    : typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : '';
  const error = new Error(`${status}: ${displayDetail}`);
  error.status = status;
  error.detail = detail;
  error.displayDetail = displayDetail;
  error.code = code;
  return error;
}
