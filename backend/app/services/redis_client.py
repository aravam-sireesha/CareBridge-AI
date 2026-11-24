"""Shared, optional Redis access.

Redis is expected in production (REDIS_URL set) and optional in development: without it every feature that uses Redis
falls back to in-process behaviour, which is correct for ONE worker process and wrong for several. `status()` reports
which mode is active so /health/ready and the operator can see it instead of discovering it under load.

Nothing here raises: an unreachable Redis returns None, logs once, and is retried after a short pause.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_RETRY_AFTER_SECONDS = 5.0
_lock = threading.Lock()
_client: Any = None
_client_url: str = ""
_down_until: float = 0.0
_last_error: Optional[str] = None


def redis_url() -> str:
    return (os.getenv("REDIS_URL") or "").strip()


def is_configured() -> bool:
    return bool(redis_url())


def _connect(url: str) -> Any:
    import redis  # imported lazily so the package stays importable (and testable) without the library

    client = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=5, health_check_interval=30,
                                  decode_responses=True)
    client.ping()
    return client


def get_sync() -> Optional[Any]:
    """A connected synchronous client, or None (not configured, library missing, or unreachable)."""
    global _client, _client_url, _down_until, _last_error
    url = redis_url()
    if not url:
        return None
    with _lock:
        if _client is not None and _client_url == url:
            return _client
        if time.monotonic() < _down_until:
            return None
        try:
            _client, _client_url, _last_error = _connect(url), url, None
            logger.info("Redis connected")
            return _client
        except Exception as exc:  # unreachable, bad URL, or the redis package is not installed
            _client, _down_until = None, time.monotonic() + _RETRY_AFTER_SECONDS
            _last_error = type(exc).__name__   # the class name only: a URL in the message may contain a password
            logger.error("Redis unavailable (%s); using in-process fallbacks", _last_error)
            return None


def mark_failed(exc: Exception) -> None:
    """Called by users of the client when a command fails mid-flight: drop the connection and pause before retrying."""
    global _client, _down_until, _last_error
    with _lock:
        _client, _down_until, _last_error = None, time.monotonic() + _RETRY_AFTER_SECONDS, type(exc).__name__
    logger.warning("Redis command failed (%s); falling back for %.0fs", _last_error, _RETRY_AFTER_SECONDS)


def make_async() -> Any:
    """A NEW asyncio client (each event loop needs its own). Raises when Redis is not configured or the library is absent."""
    import redis.asyncio as aioredis

    url = redis_url()
    if not url:
        raise RuntimeError("REDIS_URL is not configured")
    return aioredis.from_url(url, decode_responses=True, health_check_interval=30)


def status() -> str:
    """not_configured | ok | unreachable. Never includes the URL."""
    if not is_configured():
        return "not_configured"
    return "ok" if get_sync() is not None else "unreachable"


def reset_for_tests() -> None:
    global _client, _client_url, _down_until, _last_error
    with _lock:
        _client, _client_url, _down_until, _last_error = None, "", 0.0, None
