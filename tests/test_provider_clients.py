import json

import httpx
import pytest
import yaml

from agents.llm_client import LLMClient
from agents.provider_support import ACTIVE_BUDGET, RequestBudget, BudgetExceeded, ProviderError, endpoint


@pytest.mark.parametrize("base, expected", [
    ("https://host.example", "https://host.example/v1/chat/completions"),
    ("https://host.example/v1", "https://host.example/v1/chat/completions"),
    ("https://host.example/v1beta/openai/", "https://host.example/v1beta/openai/chat/completions"),
    ("https://host.example/v1/chat/completions", "https://host.example/v1/chat/completions")])
def test_endpoint_prefixes(base, expected):
    assert endpoint(base, "chat/completions") == expected


@pytest.mark.parametrize("fmt", ["anthropic", "openai", "google"])
def test_actual_executor_over_mock_http_for_each_provider(tmp_path, monkeypatch, fmt):
    from agents.simple_agent import SimpleAgent
    from agents.task_decomposer import _load_llm_config
    monkeypatch.setenv("SIES_TEST_KEY", "test-credential")
    cfg = {"llm": {"api_format": fmt, "model": "test-model", "base_url": "https://host.example",
                    "api_key_env": "SIES_TEST_KEY", "max_tokens": 120},
           "llm_budget": {"max_requests": 1}, "system": {"trace_dir": str(tmp_path / "episodic")}}
    config = tmp_path / "config.codex.yaml"
    config.write_text(yaml.safe_dump(cfg))
    assert _load_llm_config(config)["api_key_env"] == "SIES_TEST_KEY"
    response_text = json.dumps({"thought": "done", "action": "finish", "action_input": "42"})
    requests = []
    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        if fmt == "google":
            assert request.headers["x-goog-api-key"] == "test-credential"
            assert "key=" not in str(request.url)
            assert body["contents"][0]["role"] == "user"
            assert body["systemInstruction"] and body["generationConfig"]["maxOutputTokens"] == 120
            reply = {"candidates": [{"content": {"parts": [{"text": "not final", "thought": True}, {"text": response_text}]}}],
                     "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "thoughtsTokenCount": 3}}
        elif fmt == "anthropic":
            assert request.headers["x-api-key"] == "test-credential" and body["system"]
            reply = {"content": [{"type": "text", "text": response_text}], "usage": {"input_tokens": 10, "output_tokens": 8}}
        else:
            assert request.headers["authorization"] == "Bearer test-credential"
            assert body["messages"][0]["role"] == "system"
            reply = {"choices": [{"message": {"content": response_text}}], "usage": {"prompt_tokens": 10, "completion_tokens": 8}}
        return httpx.Response(200, json=reply)
    agent = SimpleAgent(str(config), allowed_tools={"finish"})
    agent.llm.close()
    agent.llm._client = httpx.Client(transport=httpx.MockTransport(handler))
    result = agent.run("Answer 42", task_id="provider-"+fmt)
    assert result["answer"] == "42" and len(requests) == 1
    assert result["provider_budget"]["requests"] == 1
    assert result["provider_budget"]["observed_tokens"] == 18
    agent.llm.close()


def test_retry_reservations_shared_budget_and_sanitized_errors(monkeypatch):
    monkeypatch.setattr("agents.provider_support.time.sleep", lambda *_: None)
    budget = RequestBudget(max_requests=2)
    token = ACTIVE_BUDGET.set(budget)
    client = LLMClient({"api_format": "openai", "max_retries": 1})
    client.close()
    requests = []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "sensitive detail"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        assert client.chat("s", "u").content == "ok"
        with pytest.raises(BudgetExceeded):
            client.chat("s", "u")
        assert len(requests) == 2
    finally:
        ACTIVE_BUDGET.reset(token)
        client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, text="sensitive detail")))
    with pytest.raises(ProviderError, match="401") as exc:
        client.chat("s", "u")
    assert "sensitive detail" not in str(exc.value)
    client.close()


def test_missing_credentials_empty_output_and_token_stop(monkeypatch):
    monkeypatch.delenv("SIES_TEST_MISSING", raising=False)
    with pytest.raises(ProviderError, match="SIES_TEST_MISSING"):
        LLMClient({"api_key_env": "SIES_TEST_MISSING"})
    client = LLMClient({"api_format": "google"})
    client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"candidates": []})))
    with pytest.raises(ProviderError, match="no usable text"):
        client.chat("s", "u")
    client.close()
    budget = RequestBudget(max_total_tokens=10)
    budget.reserve()
    budget.observe({"input_tokens": 7, "output_tokens": 5})
    with pytest.raises(BudgetExceeded, match="token"):
        budget.reserve()
