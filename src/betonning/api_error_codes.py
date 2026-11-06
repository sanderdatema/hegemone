"""Additieve foutcodes; bestaande detaildata en status blijven ongewijzigd."""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler

CATALOG = json.loads(Path(__file__).with_name('api_errors.json').read_text())
_EXACT = {entry['nl']: code for code, entry in CATALOG.items() if '{' not in entry['nl']}
# Alleen de expliciete catalogus levert patronen; invoer kan geen regex worden.
_TEMPLATES = []
for _code, _entry in CATALOG.items():
    _parts = re.split(r"(\{[a-z_]+\})", _entry['nl'])
    if len(_parts) > 1 and _code != 'validation':
        _pattern = ''.join(f"(?P<{part[1:-1]}>.*?)" if part.startswith('{') and part.endswith('}')
                           else re.escape(part) for part in _parts)
        _TEMPLATES.append((re.compile(_pattern, re.DOTALL), _code))



def error_payload(detail) -> dict:
    """Herken uitsluitend eigen catalogustekst, nooit willekeurige upstreamdata."""
    payload = {'detail': detail}
    message = detail.get('message') if isinstance(detail, dict) else detail
    if isinstance(detail, dict) and detail.get('error') == 'confirmation_required' and type(detail.get('total')) is int:
        return {**payload, 'error_code': 'bulk_confirmation_required', 'error_params': {'total': detail['total']}}
    if not isinstance(message, str):
        return payload
    code = _EXACT.get(message)
    if code:
        return {**payload, 'error_code': code, 'error_params': {}}
    for pattern, code in _TEMPLATES:
        match = pattern.fullmatch(message)
        if match:
            return {**payload, 'error_code': code, 'error_params': match.groupdict()}
    return payload


async def localized_http_error(request, exc):
    """Behoud de standaardhandler en headers; voeg alleen API-codevelden toe."""
    response = await http_exception_handler(request, exc)
    if request.url.path.startswith(('/api/v1/settings/installation', '/api/v1/settings/configuration')):
        response.headers['Cache-Control'] = 'no-store'
    if not request.url.path.startswith('/api/v1/') or not response.body:
        return response
    payload = error_payload(exc.detail)
    if 'error_code' not in payload:
        return response
    response.body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    response.headers['content-length'] = str(len(response.body))
    return response


async def localized_validation_error(request, exc):
    """Behoud FastAPI-validatiedetails; geef presentatie een stabiele code."""
    response = await request_validation_exception_handler(request, exc)
    if request.url.path.startswith('/api/v1/'):
        payload = json.loads(bytes(response.body))
        if request.url.path.startswith(('/api/v1/settings/installation', '/api/v1/settings/configuration')):
            response.headers['Cache-Control'] = 'no-store'
            for error in payload['detail']:
                error.pop('input', None)
                error.pop('ctx', None)
        fields = list(dict.fromkeys('.'.join(str(part) for part in error.get('loc', ()))
                                    for error in payload['detail']))
        payload.update(error_code='validation', error_params={'fields': ', '.join(fields) or 'body'})
        response.body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        response.headers['content-length'] = str(len(response.body))
    return response
