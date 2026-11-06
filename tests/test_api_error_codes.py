"""Foutcodes zijn additief; clients behouden status, headers en ruwe details."""
import ast
from pathlib import Path

from fastapi import HTTPException

from betonning.api_error_codes import CATALOG, error_payload


def test_catalogus_dekt_letterlijke_http_fouten_en_beide_talen():
    root = Path(__file__).parents[1] / 'src' / 'betonning'
    missing = []
    for path in [*(root / 'api').glob('*.py'), root / 'deps.py']:
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != 'HTTPException':
                continue
            values = [kw.value for kw in node.keywords if kw.arg == 'detail'] or node.args[1:2]
            if values and isinstance(values[0], ast.Constant) and isinstance(values[0].value, str):
                if 'error_code' not in error_payload(values[0].value):
                    missing.append((path.name, node.lineno))
    assert missing == []
    assert all(entry['en'] and entry['nl'] for entry in CATALOG.values())
    assert len({entry['nl'] for entry in CATALOG.values()}) == len(CATALOG)


def test_dynamic_waarden_en_upstream_details_blijven_letterlijk():
    detail = 'Onbekend item: CUSTOM-{value} <voorbeeld>'
    assert error_payload(detail) == {'detail': detail, 'error_code': 'unknown_item', 'error_params': {'value': 'CUSTOM-{value} <voorbeeld>'}}
    for detail in ['Externe oorzaak met eigen inhoud', {'error': 'confirm', 'total': 4}, ['originele detaildata']]:
        assert error_payload(detail) == {'detail': detail}


def test_auth_en_bodycap_behouden_status_en_detail(client):
    response = client.get('/api/v1/projects')
    assert response.status_code == 401
    assert response.json()['detail'] == 'Ontbrekende, verlopen of ongeldige aanmelding'
    assert response.json()['error_code'] == 'session_required'
    response = client.post('/api/v1/setup', content=b'{}', headers={'Content-Length': '999999999'})
    assert response.status_code == 413
    assert response.json()['detail'] == 'Body te groot'
    assert response.json()['error_code'] == 'body_too_large'
    assert int(response.headers['content-length']) == len(response.content)


def test_validation_behoudt_details_en_geeft_velden(client, auth, project):
    response = client.post(f'/api/v1/projects/{project}/items', json={}, headers=auth)
    assert response.status_code == 422
    data = response.json()
    assert data['error_code'] == 'validation'
    assert 'body.title' in data['error_params']['fields']
    assert data['detail'][0]['type'] == 'missing'
    assert data['detail'][0]['loc'] == ['body', 'title']


def test_exception_handler_behoudt_retry_header_en_onbekende_structuur(client):
    @client.app.get('/api/v1/test-error/{mode}')
    def error(mode: str):
        raise HTTPException(429, 'Geen LLM geconfigureerd' if mode == 'known' else {'error': 'confirmation', 'total': 7}, headers={'Retry-After': '12'})

    # Routes zijn na de SPA-mount toegevoegd: roep de handler via een eigen router vóór de mount aan.
    route = client.app.router.routes.pop()
    client.app.router.routes.insert(0, route)
    known = client.get('/api/v1/test-error/known')
    assert known.status_code == 429
    assert known.headers['retry-after'] == '12'
    assert known.json()['detail'] == 'Geen LLM geconfigureerd'
    assert known.json()['error_code'] == 'llm_unconfigured'
    unknown = client.get('/api/v1/test-error/unknown')
    assert unknown.json() == {'detail': {'error': 'confirmation', 'total': 7}}
    assert unknown.headers['retry-after'] == '12'


def test_samengestelde_fout_behoudt_alle_ingevulde_waarden():
    detail = "Kolom 'Eigen {name}' bevat nog 12 item(s) — verplaats ze eerst naar een andere kolom"
    assert error_payload(detail) == {'detail': detail, 'error_code': 'column_not_empty', 'error_params': {'name': 'Eigen {name}', 'count': '12'}}
    assert error_payload('LLM-limiet bereikt (max 10 per uur). Probeer over 45s opnieuw.')['error_params'] == {'limit': '10', 'seconds': '45'}


def test_domeincodes_behouden_itemdata_en_bevestigingsaantallen():
    detail = {'message': 'Item is intussen gewijzigd (updated_at komt niet overeen)', 'item': {'title': 'Eigen titel', 'labels': ['eigen-label']}}
    payload = error_payload(detail)
    assert payload['detail'] is detail
    assert payload['error_code'] == 'ticket_changed'
    assert detail == {'message': 'Item is intussen gewijzigd (updated_at komt niet overeen)', 'item': {'title': 'Eigen titel', 'labels': ['eigen-label']}}
    detail = {'error': 'confirmation_required', 'total': 17}
    payload = error_payload(detail)
    assert payload['detail'] is detail
    assert payload['error_code'] == 'bulk_confirmation_required'
    assert payload['error_params'] == {'total': 17}
    assert error_payload({'message': 'Eigen domeinmelding'}) == {'detail': {'message': 'Eigen domeinmelding'}}


def test_webhook_validatiefouten_krijgen_codes_zonder_de_guard_te_wijzigen(monkeypatch):
    from betonning import webhooks
    monkeypatch.setenv('HEGEMONE_WEBHOOK_ALLOW_LOOPBACK', '0')
    monkeypatch.setenv('HEGEMONE_WEBHOOK_ALLOWED_HOSTS', '')
    for url, code in [
        ('https://example.invalid:0/hook', 'webhook_port_invalid'),
        ('https://example.invalid:invalid/hook', 'webhook_address_invalid'),
        ('ftp://example.invalid/hook', 'webhook_scheme_invalid'),
        ('https:///hook', 'webhook_host_missing'),
        ('https://user:synthetic@example.invalid/hook', 'webhook_credentials_forbidden'),
        ('https://localhost/hook', 'webhook_host_forbidden'),
    ]:
        reason = webhooks.webhook_url_error(url)
        assert reason is not None
        assert error_payload(reason)['error_code'] == code
    assert webhooks.webhook_url_error('https://example.invalid/hook') is None
