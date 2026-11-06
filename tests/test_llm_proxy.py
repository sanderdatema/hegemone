"""Modelroutering en optionele reasoning naar de LLM-proxy."""

import httpx
import pytest

from betonning import llm


@pytest.fixture
def captured_request(monkeypatch):
    """Vang de HTTP-aanroep af zonder een echte proxy of credentials."""
    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "OK"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(llm.httpx, "post", post)
    return captured


@pytest.mark.parametrize("effort", [None, "low", "medium"])
def test_proxy_payload(captured_request, effort):
    client = llm.OpenAICompatClient(
        "https://proxy.example/v1/", "test-key", "proxy-model",
        reasoning_effort=effort,
    )
    messages = [{"role": "user", "content": "Test"}]
    assert client.complete(messages) == "OK"
    expected = {
        "model": "proxy-model", "messages": messages, "temperature": 0.3,
        "max_completion_tokens": 4096,
    }
    if effort:
        expected["reasoning_effort"] = effort
    assert captured_request == {
        "url": "https://proxy.example/v1/chat/completions",
        "headers": {"Authorization": "Bearer test-key"},
        "json": expected,
        "timeout": 60.0,
    }


@pytest.mark.parametrize(
    "effort,expected",
    [(None, None), ("medium", "medium"), (" low ", "low"), ("", None), ("  ", None)],
)
def test_reasoning_from_env(monkeypatch, captured_request, effort, expected):
    monkeypatch.setenv("BETONNING_LLM_BASE_URL", "https://proxy.example/v1")
    monkeypatch.setenv("BETONNING_LLM_API_KEY", "test-key")
    monkeypatch.setenv("BETONNING_LLM_MODEL", "proxy-model")
    if effort is None:
        monkeypatch.delenv("BETONNING_LLM_REASONING_EFFORT", raising=False)
    else:
        monkeypatch.setenv("BETONNING_LLM_REASONING_EFFORT", effort)
    client = llm.client_from_env()
    assert client.complete([{"role": "user", "content": "Test"}]) == "OK"
    payload = captured_request["json"]
    if expected is None:
        assert "reasoning_effort" not in payload
    else:
        assert payload["reasoning_effort"] == expected
