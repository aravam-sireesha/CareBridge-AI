"""Rate limiting that is correct across several worker processes.

* With Redis: a fixed window per key (INCR + TTL), shared by every worker and every container.
* Without Redis, or while Redis is down: a per-process sliding window. That is the only option, it is logged, and
  /health/ready reports it, but it means N workers allow roughly N times the limit.

Pure Python plus an optional Redis client, so it is unit-tested without a web framework (tests/test_ratelimit.py).
Use `limiter.hit(...)` directly, or `rate_limit(...)` to get a FastAPI dependency.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any, Callable, Optional

from . import redis_client

logger = logging.getLogger(__name__)


class MemoryBackend:
    """Per-process sliding window."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._clock = clock

    def hit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        now = self._clock()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, int(window - (now - q[0])))
            q.append(now)
            if len(self._hits) > 50_000:                    # bound memory: drop idle keys
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > window][:10_000]:
                    self._hits.pop(k, None)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class RedisBackend:
    """Fixed window shared by all processes. A key that somehow lost its TTL is repaired on the next hit."""

    def __init__(self, client: Any, prefix: str = "cb:rl:"):
        self.client, self.prefix = client, prefix

    def hit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        k = f"{self.prefix}{key}"
        pipe = self.client.pipeline()
        pipe.incr(k)
        pipe.ttl(k)
        count, ttl = pipe.execute()
        if ttl is None or int(ttl) < 0:
            self.client.expire(k, window)
            ttl = window
        if int(count) > limit:
            return False, max(1, int(ttl))
        return True, 0

    def reset(self) -> None:
        for k in self.client.scan_iter(match=f"{self.prefix}*", count=500):
            self.client.delete(k)


class RateLimiter:
    def __init__(self):
        self.memory = MemoryBackend()
        self._warned = False

    def _backend(self):
        client = redis_client.get_sync()
        return RedisBackend(client) if client is not None else None

    def hit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """(allowed, retry_after_seconds). `retry_after_seconds` is 0 when allowed."""
        backend = self._backend()
        if backend is not None:
            try:
                return backend.hit(key, limit, window)
            except Exception as exc:                        # Redis hiccup: degrade to the local window, never fail the request
                redis_client.mark_failed(exc)
        elif redis_client.is_configured() and not self._warned:
            self._warned = True
            logger.warning("REDIS_URL is set but Redis is unreachable: rate limits are per-process until it returns")
        return self.memory.hit(key, limit, window)

    def reset(self) -> None:
        self.memory.reset()
        backend = self._backend()
        if backend is not None:
            try:
                backend.reset()
            except Exception as exc:
                redis_client.mark_failed(exc)


limiter = RateLimiter()


def rate_limit(name: str, limit: int, window: int, per: str = "user") -> Callable:
    """A FastAPI dependency: at most `limit` calls per `window` seconds per user (or per client address).

    per="user" needs a signed-in user and keys on the account id, so a shared office IP cannot lock out colleagues.
    """
    from fastapi import Depends, HTTPException, Request          # local import: this module stays importable without FastAPI

    def _raise(retry: int):
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.", headers={"Retry-After": str(retry)})

    if per == "user":
        from ..dependencies import get_current_user

        def dependency(user: dict = Depends(get_current_user)) -> None:
            ok, retry = limiter.hit(f"{name}:u{user['id']}", limit, window)
            if not ok:
                _raise(retry)
    else:
        from .security import client_address

        def dependency(request: Request) -> None:
            ok, retry = limiter.hit(f"{name}:ip:{client_address(request)}", limit, window)
            if not ok:
                _raise(retry)
    return dependency
