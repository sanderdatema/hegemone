"""Uitvoertaal van interne AI-prompts, zonder provider- of databasetoegang."""
import copy

import pytest

from betonning import config, decompose, llm, server, triage, triage_chat_engine, wiki_compiler
from betonning.outbound import outbound


@pytest.fixture(autouse=True)
def clean_language(monkeypatch):
    monkeypatch.delenv('HEGEMONE_AI_LANGUAGE', raising=False)
    monkeypatch.delenv('BETONNING_AI_LANGUAGE', raising=False)


def test_default_alias_en_prioriteit(monkeypatch):
    assert config.ai_language() == 'en'
    monkeypatch.setenv('BETONNING_AI_LANGUAGE', 'nl')
    assert config.ai_language() == 'nl'
    monkeypatch.setenv('HEGEMONE_AI_LANGUAGE', ' EN ')
    assert config.ai_language() == 'en'
    monkeypatch.setenv('HEGEMONE_AI_LANGUAGE', '')
    with pytest.raises(ValueError, match='HEGEMONE_AI_LANGUAGE moet en of nl zijn'):
        config.ai_language()


def test_appstart_weigert_ongeldige_taal_zonder_waarde_te_tonen(monkeypatch):
    monkeypatch.setattr(server, 'load_dotenv', lambda: None)
    monkeypatch.setenv('HEGEMONE_AI_LANGUAGE', 'ongeldige-fixture')
    with pytest.raises(ValueError) as error:
        server.create_app()
    assert str(error.value) == 'HEGEMONE_AI_LANGUAGE moet en of nl zijn.'


@pytest.mark.parametrize('path', ['enrich', 'triage', 'comment', 'assign', 'decompose', 'wiki', 'chat'])
def test_alle_promptpaden_selecteren_taal_en_behouden_invoer(monkeypatch, path):
    item = {'ref': 'TEST-1', 'title': 'Eigen titel', 'description_md': 'Eigen inhoud', 'plan_md': 'Eigen plan', 'labels': ['eigen-label']}
    comment = {'id': 1, 'author': 'voorbeeld', 'body_md': 'Bewaar deze Nederlandse reactie', 'role': 'user'}
    image = {'type': 'image_url', 'image_url': {'url': 'https://example.invalid/image.png'}}
    before = copy.deepcopy((item, comment, image))
    monkeypatch.setattr(triage_chat_engine, '_scope_line', lambda *_: 'scope-fixture')
    monkeypatch.setattr(triage_chat_engine, '_context_text', lambda *_: 'context-fixture')
    builders = {
        'enrich': lambda: llm.build_enrich_messages(item['title'], item['description_md'], [comment], project_labels=item['labels']),
        'triage': lambda: triage.build_triage_messages(item, {}, [], images=[image]),
        'comment': lambda: triage.build_comment_eval_messages(item, {}, [comment], comment, images=[image]),
        'assign': lambda: triage.build_assign_eval_messages(item, {}, [comment], images=[image]),
        'decompose': lambda: decompose.build_decompose_messages(item, {}, images=[image]),
        'wiki': lambda: wiki_compiler.build_compile_messages(item, [comment], 'Bestaande wiki', ['eigen-slug']),
        'chat': lambda: triage_chat_engine.build_chat_messages(None, None, [comment]),
    }
    results = {}
    for code, name in [('en', 'English'), ('nl', 'Dutch')]:
        monkeypatch.setenv('HEGEMONE_AI_LANGUAGE', code)
        messages = builders[path]()
        system = messages[0]['content']
        assert f'OUTPUT LANGUAGE: Write newly generated natural-language text in {name}' in system
        assert system.count('OUTPUT LANGUAGE:') == 1
        assert outbound('human_comment_references', language=code) in system
        assert 'in het Nederlands' not in system
        assert '(Nederlands)' not in system
        assert 'JSON' in system
        assert 'Keep JSON keys, enum values, handles, refs, labels, slugs' in system
        if path != 'chat':
            assert llm.UNTRUSTED_INPUT_RULE in system
        results[code] = messages[1:]
    assert results['en'] == results['nl']
    assert (item, comment, image) == before


def test_mcp_instructions_explain_human_comment_references():
    from betonning import mcp_server

    assert outbound('human_comment_references', language='nl') in mcp_server.SERVER_INSTRUCTIONS
    assert 'auteur, datum of een kort citaat' in mcp_server.comment_item.__doc__
