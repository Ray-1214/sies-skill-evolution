"""
LLM Client Abstraction Layer — SIES
=====================================
Supports both Anthropic (/v1/messages) and OpenAI (/v1/chat/completions)
formats via httpx. No SDK dependency.

Config-driven format switching:
  api_format: "anthropic"  →  POST {base_url}/v1/messages
  api_format: "openai"     →  POST {base_url}/v1/chat/completions

Migration path: When purchasing Claude API, change base_url + api_key only.
"""

import json
import logging
from typing import Optional
from urllib.parse import quote

from agents.provider_support import api_key, endpoint, post_json, ACTIVE_BUDGET, ProviderError

try:
    import httpx
except ImportError:
    httpx = None  # Optional: only needed for live LLM calls. Install: pip install httpx --break-system-packages

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "base_url": "http://localhost:8080",
    "api_key": "not-needed",
    "model": "coder",                  # coder backend: --jinja, native tool_calls, -c 32768
    "api_format": "anthropic",         # "anthropic" or "openai"
    "temperature": 0.1,                # low for consistent structured output
    "max_tokens": 8192,                # generous for complex Tstruct
    "timeout": 300,
}


# ---------------------------------------------------------------------------
# Response wrapper
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 模組層 usage 累加器（P1-a）
# ---------------------------------------------------------------------------
# 為什麼是模組層而不是 instance state：A1 / A2 / SimpleAgent / A3 各自建自己的
# LLMClient（一個 AgentRunner 底下有 5 個，ReflectiveEvaluator 還會再建兩個
# extractor），而 curriculum_loop.py:74 整個迴圈只建一次 AgentRunner。掛在
# instance 上收不齊，掛在模組上再用 snapshot-diff 取單題增量才涵蓋得到全部。

_USAGE = {"calls": 0, "input_tokens": 0, "output_tokens": 0}


def usage_snapshot() -> dict:
    """取目前累計值的快照，配 usage_since() 算單題增量。"""
    return dict(_USAGE)


def usage_since(snap: dict) -> dict:
    """回傳自 snap 以來的增量，欄位名已對齊 run_summary 的 schema。"""
    return {
        "llm_calls": _USAGE["calls"] - snap.get("calls", 0),
        "prompt_tokens": _USAGE["input_tokens"] - snap.get("input_tokens", 0),
        "completion_tokens": _USAGE["output_tokens"] - snap.get("output_tokens", 0),
    }


def _accumulate(usage: Optional[dict]) -> None:
    """把一次回應的 usage 記進累加器。本機 llama-server 回的是 Anthropic 風格的
    input_tokens / output_tokens；OpenAI 格式則是 prompt_tokens / completion_tokens。"""
    _USAGE["calls"] += 1
    if not usage:
        return
    _USAGE["input_tokens"] += int(
        usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    _USAGE["output_tokens"] += int(
        usage.get("output_tokens") or usage.get("completion_tokens") or 0)


class LLMResponse:
    """Unified response object regardless of API format."""

    def __init__(self, content: str, raw: dict, model: str, usage: Optional[dict] = None):
        self.content = content
        self.raw = raw
        self.model = model
        self.usage = usage or {}

    def __repr__(self):
        return f"LLMResponse(model={self.model}, len={len(self.content)})"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class LLMClient:
    """
    Unified LLM client supporting Anthropic and OpenAI API formats.

    Usage:
        client = LLMClient(config)
        response = client.chat(system_prompt, user_message)
        print(response.content)
    """

    def __init__(self, config: Optional[dict] = None):
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        self.config = cfg

        self.base_url = cfg["base_url"].rstrip("/")
        self.api_key = api_key(cfg)
        self.model = cfg["model"]
        self.api_format = cfg["api_format"]
        self.temperature = cfg["temperature"]
        self.max_tokens = cfg["max_tokens"]
        self.timeout = cfg["timeout"]

        self.max_retries = cfg.get("max_retries", 0)
        if self.api_format not in ("anthropic", "openai", "google"):
            raise ValueError("api_format must be anthropic, openai or google")
        if self.api_format == "google" and "base_url" not in (config or {}):
            self.base_url = "https://generativelanguage.googleapis.com/v1beta"

        if httpx is not None:
            self._client = httpx.Client(timeout=self.timeout)
        else:
            self._client = None  # Will be mocked in tests

    def chat(self, system_prompt: str, user_message: str) -> LLMResponse:
        """
        Send a chat request and return unified LLMResponse.

        Args:
            system_prompt: System-level instructions.
            user_message: User's input text.

        Returns:
            LLMResponse with .content (str), .raw (dict), .model, .usage
        """
        if self.api_format == "anthropic":
            resp = self._chat_anthropic(system_prompt, user_message)
        elif self.api_format == "google":
            resp = self._chat_google(system_prompt, user_message)
        else:
            resp = self._chat_openai(system_prompt, user_message)
        _accumulate(resp.usage)   # P1-a：單一出口，兩種 format 都涵蓋
        if ACTIVE_BUDGET.get():
            ACTIVE_BUDGET.get().observe(resp.usage)
        if not isinstance(resp.content, str) or not resp.content.strip():
            raise ProviderError("Provider returned no usable text (blocked, tool-only, or empty response)")
        return resp

    # ---- Anthropic format (/v1/messages) ----

    def _chat_anthropic(self, system_prompt: str, user_message: str) -> LLMResponse:
        url = endpoint(self.config.get("endpoint_url", self.base_url), "messages")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_message}
            ],
        }

        logger.debug(f"[LLM] POST {url} (anthropic format, model={self.model})")
        data = post_json(self._client, url, headers, payload, self.max_retries)

        # Anthropic response: {"content": [{"type": "text", "text": "..."}], ...}
        content_blocks = data.get("content", [])
        text = ""
        for block in content_blocks:
            if block.get("type") == "text":
                text += block.get("text", "")

        return LLMResponse(
            content=text,
            raw=data,
            model=data.get("model", self.model),
            usage=data.get("usage"),
        )

    # ---- OpenAI format (/v1/chat/completions) ----

    def _chat_openai(self, system_prompt: str, user_message: str) -> LLMResponse:
        url = endpoint(self.config.get("endpoint_url", self.base_url), "chat/completions")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }

        logger.debug(f"[LLM] POST {url} (openai format, model={self.model})")
        token_field = self.config.get("max_tokens_field", "max_tokens")
        if token_field not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError("Unsupported token limit field")
        payload[token_field] = payload.pop("max_tokens")
        if self.temperature is None:
            payload.pop("temperature")
        if self.config.get("reasoning_effort") is not None:
            payload["reasoning_effort"] = self.config["reasoning_effort"]
        data = post_json(self._client, url, headers, payload, self.max_retries)

        # OpenAI response: {"choices": [{"message": {"content": "..."}}], ...}
        choices = data.get("choices") or []
        text = choices[0].get("message", {}).get("content") if choices else None
        if isinstance(text, list):
            text = "".join(block.get("text", "") for block in text if block.get("type") == "text")

        return LLMResponse(
            content=text,
            raw=data,
            model=data.get("model", self.model),
            usage=data.get("usage"),
        )

    def _chat_google(self, system_prompt: str, user_message: str) -> LLMResponse:
        model = quote(self.model.removeprefix("models/"), safe="-._")
        url = endpoint(self.config.get("endpoint_url", self.base_url),
                       f"models/{model}:generateContent", version="v1beta")
        generation = dict(self.config.get("generation_config", {}))
        generation["maxOutputTokens"] = self.max_tokens
        if self.temperature is not None:
            generation["temperature"] = self.temperature
        payload = {"systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_message}]}],
            "generationConfig": generation}
        data = post_json(self._client, url,
            {"Content-Type": "application/json", "x-goog-api-key": self.api_key}, payload, self.max_retries)
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        usage = data.get("usageMetadata") or {}
        return LLMResponse(text, data, data.get("modelVersion", self.model),
            {"input_tokens": usage.get("promptTokenCount", 0),
             "output_tokens": (usage.get("candidatesTokenCount", 0) or 0) + (usage.get("thoughtsTokenCount", 0) or 0)})

    def close(self):
        """Close the underlying httpx client."""
        if self._client is not None:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def create_client(config: Optional[dict] = None) -> LLMClient:
    """Create an LLMClient from config dict."""
    return LLMClient(config)
