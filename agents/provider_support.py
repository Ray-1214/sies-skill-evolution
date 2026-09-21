"""Shared provider URL, credential and per-run request budget handling."""
import os
import time
from contextvars import ContextVar
from functools import wraps
from urllib.parse import urlsplit


class ProviderError(RuntimeError):
    pass


class BudgetExceeded(ProviderError):
    pass


class RequestBudget:
    def __init__(self, max_requests=None, max_total_tokens=None):
        self.max_requests, self.max_total_tokens = max_requests, max_total_tokens
        if any(v is not None and (type(v) is not int or v < 1) for v in [max_requests, max_total_tokens]):
            raise ValueError("Budget limits must be positive integers")
        self.requests = self.tokens = 0

    def reserve(self):
        if self.max_requests is not None and self.requests >= self.max_requests:
            raise BudgetExceeded("Provider request budget exhausted")
        if self.max_total_tokens is not None and self.tokens >= self.max_total_tokens:
            raise BudgetExceeded("Observed token budget exhausted")
        self.requests += 1

    def observe(self, usage):
        self.tokens += int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
        self.tokens += int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)

    def summary(self):
        return {"requests": self.requests, "observed_tokens": self.tokens,
                "max_requests": self.max_requests, "max_total_tokens": self.max_total_tokens}


ACTIVE_BUDGET = ContextVar("sies_provider_budget", default=None)


def with_run_budget(fn):
    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        # Nested executor inherits the entire pipeline's budget, including A3.
        if ACTIVE_BUDGET.get() is not None:
            return fn(self, *args, **kwargs)
        cfg = self.config.get("llm_budget", {})
        budget = RequestBudget(**cfg)
        token = ACTIVE_BUDGET.set(budget)
        try:
            return fn(self, *args, **kwargs)
        finally:
            ACTIVE_BUDGET.reset(token)
    return wrapped


def budget_summary():
    budget = ACTIVE_BUDGET.get()
    return budget.summary() if budget else {}


def api_key(config):
    env = config.get("api_key_env")
    if env:
        value = os.environ.get(env)
        if not value:
            raise ProviderError(f"Required credential environment variable is not set: {env}")
        return value
    return config.get("api_key", "not-needed")


def endpoint(base, suffix, version="v1"):
    """Origin defaults to /v1; an explicit API prefix or full endpoint is preserved."""
    parts = urlsplit(base)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Provider URL must be HTTP(S), with no embedded credentials, query or fragment")
    base = base.rstrip("/")
    if base.endswith("/"+suffix):
        return base
    if not parts.path.strip("/"):
        base += "/"+version
    return base+"/"+suffix


def post_json(client, url, headers, payload, retries=0):
    if client is None:
        raise ProviderError("httpx is required for provider requests")
    if type(retries) is not int or not 0 <= retries <= 3:
        raise ValueError("max_retries must be between 0 and 3")
    for attempt in range(retries+1):
        budget = ACTIVE_BUDGET.get()
        if budget:
            budget.reserve()
        try:
            response = client.post(url, headers=headers, json=payload)
        except Exception as error:
            # Do not expose request headers or provider response bodies in logs.
            raise ProviderError(f"Provider transport failed ({type(error).__name__}); no automatic retry") from None
        if response.status_code in {429, 502, 503, 504} and attempt < retries:
            try:
                delay = float(response.headers.get("Retry-After", 2**attempt))
            except ValueError:
                delay = 2**attempt
            time.sleep(min(5, max(0, delay)))
            continue
        if not 200 <= response.status_code < 300:
            raise ProviderError(f"Provider HTTP {response.status_code}; response body omitted")
        try:
            data = response.json()
        except ValueError:
            raise ProviderError("Provider returned invalid JSON") from None
        if not isinstance(data, dict):
            raise ProviderError("Provider response must be a JSON object")
        return data
