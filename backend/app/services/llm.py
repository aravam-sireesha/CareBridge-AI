"""Streaming client for any OpenAI-compatible chat-completions API (OpenAI, Groq, Together, Ollama, vLLM, LM Studio ...).

Configuration comes only from the environment, never from code:
    LLM_API_KEY / OPENAI_API_KEY   key (not needed for a local server such as Ollama when LLM_BASE_URL is set)
    LLM_BASE_URL / OPENAI_BASE_URL e.g. https://api.openai.com/v1  or  http://localhost:11434/v1
    LLM_MODEL / OPENAI_MODEL       the stronger model (default gpt-4o-mini)
    LLM_FAST_MODEL                 optional cheaper/faster model for simple questions
    LLM_TIMEOUT_SECONDS            read timeout between streamed chunks (default 30)
    LLM_MAX_RETRIES                retries (with backoff) for rate limits / 5xx / network errors BEFORE any text was produced (default 2)
    LLM_DAILY_REQUEST_LIMIT        optional cap on model requests per UTC day across all users (0 = unlimited)
One shared HTTP client is reused, so TCP/TLS connections are pooled instead of being opened for every question."""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Iterator


class LLMError(RuntimeError):
    """The provider could not be reached or returned an error."""


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    fast_model: str
    timeout: float


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n, "").strip()
        if v:
            return v
    return default


def config() -> LLMConfig | None:
    """None when no provider is configured (the assistant then answers from retrieval and live analysis only)."""
    key = _env("LLM_API_KEY", "OPENAI_API_KEY")
    base = _env("LLM_BASE_URL", "OPENAI_BASE_URL")
    if not key and not base:
        return None
    model = _env("LLM_MODEL", "OPENAI_MODEL", default="gpt-4o-mini")
    try:
        timeout = float(_env("LLM_TIMEOUT_SECONDS", default="30"))
    except ValueError:
        timeout = 30.0
    return LLMConfig(api_key=key or "local", base_url=(base or "https://api.openai.com/v1").rstrip("/"), model=model,
                     fast_model=_env("LLM_FAST_MODEL", default=model), timeout=max(5.0, min(timeout, 120.0)))


def choose_model(cfg: LLMConfig, question: str, has_live: bool) -> str:
    """Short questions with no live analysis go to the fast model; anything analytical uses the stronger one."""
    simple = len(question.split()) <= 18 and not has_live
    return cfg.fast_model if simple else cfg.model


def parse_stream_line(line: str) -> str | None:
    """Text delta from one `data: {...}` line of an OpenAI-compatible stream. Returns None for keep-alives, role-only
    chunks and the final `[DONE]` marker. Raises LLMError when the provider sent an error object."""
    line = (line or "").strip()
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        obj = json.loads(payload)
    except ValueError:
        return None
    if isinstance(obj, dict) and obj.get("error"):
        err = obj["error"]
        raise LLMError(str(err.get("message") if isinstance(err, dict) else err)[:200])
    try:
        return obj["choices"][0].get("delta", {}).get("content") or None
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


_client = None
_lock = threading.Lock()


def _shared_client(timeout: float):
    global _client
    with _lock:
        if _client is None:
            import httpx  # imported lazily so the pure helpers above work without it
            _client = httpx.Client(timeout=httpx.Timeout(timeout, connect=5.0), limits=httpx.Limits(max_connections=20, max_keepalive_connections=10))
        return _client


RETRYABLE = {408, 429, 500, 502, 503, 504}


def max_retries() -> int:
    try:
        return max(0, min(int(_env("LLM_MAX_RETRIES", default="2")), 4))
    except ValueError:
        return 2


def daily_limit() -> int:
    try:
        return max(0, int(_env("LLM_DAILY_REQUEST_LIMIT", default="0")))
    except ValueError:
        return 0


def mask_key(key: str) -> str:
    """Never show a credential: only whether one is set and its last four characters."""
    if not key or key == "local":
        return ""
    return "\u2022" * 8 + key[-4:] if len(key) > 8 else "\u2022" * 8


def host_of(base_url: str) -> str:
    return base_url.split("://", 1)[-1].split("/", 1)[0]


def status_message(code: int) -> str:
    if code in (401, 403):
        return "The language model service rejected the API key. An administrator needs to check it."
    if code == 404:
        return "The language model or endpoint was not found. An administrator needs to check the model name and base URL."
    if code == 429:
        return "The language model service is rate limiting requests right now."
    if code >= 500:
        return "The language model service had an internal error."
    return f"The language model service returned HTTP {code}."


def _delay(resp, attempt: int) -> float:
    try:
        retry_after = float(resp.headers.get("retry-after", ""))
    except (TypeError, ValueError):
        retry_after = 0.0
    return min(max(retry_after, 0.6 * (2 ** attempt)), 5.0)   # exponential backoff, honoring Retry-After, never longer than 5 s


def stream_chat(cfg: LLMConfig, messages: list[dict], *, model: str | None = None, max_tokens: int = 700, temperature: float = 0.2) -> Iterator[str]:
    """Yield text pieces as the provider generates them. Rate limits, 5xx and network errors are retried with backoff, but only
    until the first piece of text exists: once the user has seen text, a failure raises LLMError instead of restarting the answer."""
    body = {"model": model or cfg.model, "messages": messages, "stream": True, "temperature": temperature, "max_tokens": max_tokens}
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
    attempts = max_retries()
    yielded = False
    for attempt in range(attempts + 1):
        delay = 0.0
        try:
            client = _shared_client(cfg.timeout)
            with client.stream("POST", f"{cfg.base_url}/chat/completions", json=body, headers=headers) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    if resp.status_code in RETRYABLE and attempt < attempts:
                        delay = _delay(resp, attempt)
                    else:
                        raise LLMError(status_message(resp.status_code))
                else:
                    for line in resp.iter_lines():
                        piece = parse_stream_line(line)
                        if piece:
                            yielded = True
                            yield piece
                    return
        except LLMError:
            raise
        except Exception as exc:   # network, timeout, TLS ...
            if yielded or attempt >= attempts:
                raise LLMError(f"The language model service is unreachable ({type(exc).__name__}).") from exc
            delay = min(0.6 * (2 ** attempt), 5.0)
        time.sleep(delay)
    raise LLMError("The language model service did not respond.")


def complete(cfg: LLMConfig, messages: list[dict], *, model: str | None = None, max_tokens: int = 16) -> str:
    """One short non-streamed answer, used by the administrator's connection test."""
    return "".join(stream_chat(cfg, messages, model=model, max_tokens=max_tokens, temperature=0.0))
