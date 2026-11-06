"""Publieke runtimeconfiguratie met veilige compatibiliteit (BETON-529)."""
import os
import httpx
import pytest

from betonning.config import env
from betonning import llm, embeddings, security, server


@pytest.mark.parametrize('suffix', ['DB', 'MEDIA_SECRET', 'LLM_MODEL', 'EMBED_MODEL', 'MAX_BODY', 'WEBHOOK_ALLOWED_HOSTS'])
def test_nieuwe_naam_heeft_voorrang_zonder_omgeving_te_wijzigen(monkeypatch, suffix):
    old, new = 'BETONNING_' + suffix, 'HEGEMONE_' + suffix
    monkeypatch.setenv(old, 'legacy-fixture')
    monkeypatch.setenv(new, 'public-fixture')
    assert env(old) == 'public-fixture'
    assert os.environ[old] == 'legacy-fixture'
    monkeypatch.delenv(new)
    assert env(old) == 'legacy-fixture'
    monkeypatch.delenv(old)
    assert env(old, 'fallback') == 'fallback'


def test_expliciet_leeg_valt_niet_terug_op_legacycredential(monkeypatch):
    for prefix in ['BETONNING_', 'HEGEMONE_']:
        monkeypatch.setenv(prefix + 'LLM_BASE_URL', 'https://llm.example/v1')
        monkeypatch.setenv(prefix + 'LLM_MODEL', 'test-model')
    monkeypatch.setenv('BETONNING_LLM_API_KEY', 'synthetic-old-key')
    monkeypatch.setenv('HEGEMONE_LLM_API_KEY', '')
    assert llm.client_from_env() is None


def test_hegemone_llm_verstuurt_de_geconfigureerde_request(monkeypatch):
    for key, value in {'BASE_URL': 'https://llm.example/v1', 'API_KEY': 'synthetic-new-key', 'MODEL': 'new-model', 'REASONING_EFFORT': ' low '}.items():
        monkeypatch.setenv('HEGEMONE_LLM_' + key, value)
    captured = {}
    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'OK'}}]}, request=httpx.Request('POST', url))
    monkeypatch.setattr(llm.httpx, 'post', post)
    assert llm.client_from_env().complete([{'role': 'user', 'content': 'Test'}]) == 'OK'
    assert captured['json']['model'] == 'new-model'
    assert captured['json']['reasoning_effort'] == 'low'
    assert captured['headers']['Authorization'] == 'Bearer synthetic-new-key'


def test_embedclient_werkt_met_publieke_instellingen(monkeypatch):
    for key, value in {'BASE_URL': 'https://embed.example/v1', 'API_KEY': 'synthetic-embed-key', 'MODEL': 'embed-model'}.items():
        monkeypatch.setenv('HEGEMONE_EMBED_' + key, value)
    assert embeddings.client_from_env() is not None
    monkeypatch.setenv('HEGEMONE_EMBED_API_KEY', '')
    assert embeddings.client_from_env() is None


def test_media_secret_gebruikt_publieke_configuratie(monkeypatch):
    monkeypatch.setenv('BETONNING_MEDIA_SECRET', 'synthetic-legacy-media')
    monkeypatch.setenv('HEGEMONE_MEDIA_SECRET', 'synthetic-public-media')
    assert security._media_secret() == 'synthetic-public-media'


def test_databasepad_wordt_na_dotenv_opgelost_en_injectie_wint(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HEGEMONE_DB', 'temporary-fixture')
    monkeypatch.delenv('HEGEMONE_DB')
    (tmp_path / '.env').write_text('HEGEMONE_DB=from-config.db\n')
    options = dict(llm_client=None, embed_client=None, enable_mcp=False, enable_dispatcher=False, enable_triage=False, enable_wiki_compile=False)
    app = server.create_app(**options)
    assert app.state.db_path == 'from-config.db'
    assert server.create_app(tmp_path/'injected.db', **options).state.db_path == str(tmp_path/'injected.db')


def test_publieke_veiligheidsinstellingen_bereiken_de_echte_guards(monkeypatch):
    from betonning.bodylimit import BodySizeLimitMiddleware
    from betonning import webhooks
    async def inner(*args):
        pass
    monkeypatch.setenv('BETONNING_MAX_BODY', '500')
    monkeypatch.setenv('HEGEMONE_MAX_BODY', '100')
    assert BodySizeLimitMiddleware(inner).max_body == 100
    monkeypatch.setenv('BETONNING_WEBHOOK_ALLOWED_HOSTS', 'legacy.example.org')
    monkeypatch.setenv('HEGEMONE_WEBHOOK_ALLOWED_HOSTS', 'receiver.example.org')
    assert webhooks.allowed_webhook_hosts() == ['receiver.example.org']


def test_appflags_en_bijlagenpad_gebruiken_publieke_namen(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HEGEMONE_ATTACHMENTS_DIR', str(tmp_path/'media'))
    monkeypatch.setenv('HEGEMONE_DOCS', '1')
    monkeypatch.setenv('HEGEMONE_TRIAGE_ENABLED', '0')
    app = server.create_app(tmp_path/'test.db', llm_client=None, embed_client=None, enable_mcp=False, enable_dispatcher=False, enable_wiki_compile=False)
    assert app.state.attachments_dir == str(tmp_path/'media')
    assert app.state.enable_triage is False
    assert app.openapi_url == '/openapi.json'
