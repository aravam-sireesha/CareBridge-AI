"""Shared rate limiter: Redis backend semantics, fallback when Redis fails, and no URL/password leakage in status."""

from app.services import ratelimit, redis_client


class FakePipe:
    def __init__(self, r):
        self.r, self.ops = r, []

    def incr(self, k):
        self.ops.append(("incr", k))

    def ttl(self, k):
        self.ops.append(("ttl", k))

    def execute(self):
        if self.r.explode:
            raise ConnectionError("redis://:secret@host down")
        out = []
        for op, k in self.ops:
            if op == "incr":
                self.r.store[k] = self.r.store.get(k, 0) + 1
                out.append(self.r.store[k])
            else:
                out.append(self.r.ttls.get(k, -1))
        return out


class FakeRedis:
    def __init__(self):
        self.store, self.ttls, self.explode = {}, {}, False

    def pipeline(self):
        return FakePipe(self)

    def expire(self, k, t):
        self.ttls[k] = t

    def scan_iter(self, match=None, count=None):
        prefix = (match or "").rstrip("*")
        return [k for k in list(self.store) if k.startswith(prefix)]

    def delete(self, k):
        self.store.pop(k, None)
        self.ttls.pop(k, None)


def test_memory_backend_allows_exactly_limit_then_blocks_then_recovers():
    now = [1000.0]
    mem = ratelimit.MemoryBackend(clock=lambda: now[0])
    assert [mem.hit("k", 3, 60)[0] for _ in range(3)] == [True, True, True]
    allowed, retry = mem.hit("k", 3, 60)
    assert allowed is False and 1 <= retry <= 60
    now[0] += 61
    assert mem.hit("k", 3, 60)[0] is True


def test_memory_backend_keys_are_independent():
    mem = ratelimit.MemoryBackend()
    for _ in range(2):
        mem.hit("a", 2, 60)
    assert mem.hit("a", 2, 60)[0] is False
    assert mem.hit("b", 2, 60)[0] is True


def test_redis_backend_counts_sets_ttl_and_blocks():
    r = FakeRedis()
    be = ratelimit.RedisBackend(r)
    assert be.hit("x", 2, 30) == (True, 0)
    assert r.ttls["cb:rl:x"] == 30                      # first hit sets the window
    assert be.hit("x", 2, 30) == (True, 0)
    allowed, retry = be.hit("x", 2, 30)
    assert allowed is False and retry == 30


def test_redis_backend_repairs_a_key_that_lost_its_ttl():
    r = FakeRedis()
    r.store["cb:rl:y"] = 1                               # exists, TTL missing (-1): would otherwise never expire
    ratelimit.RedisBackend(r).hit("y", 5, 45)
    assert r.ttls["cb:rl:y"] == 45


def test_limiter_uses_redis_when_available(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(redis_client, "get_sync", lambda: r)
    lim = ratelimit.RateLimiter()
    assert lim.hit("z", 1, 10)[0] is True
    assert lim.hit("z", 1, 10)[0] is False
    assert "cb:rl:z" in r.store                          # shared state really went to Redis


def test_limiter_falls_back_to_memory_when_redis_errors(monkeypatch):
    r = FakeRedis()
    r.explode = True
    failures = []
    monkeypatch.setattr(redis_client, "get_sync", lambda: r)
    monkeypatch.setattr(redis_client, "mark_failed", lambda exc: failures.append(type(exc).__name__))
    lim = ratelimit.RateLimiter()
    assert lim.hit("q", 1, 10)[0] is True                # request is NOT failed by a Redis outage
    assert lim.hit("q", 1, 10)[0] is False               # and the local window still limits
    assert failures                                       # the outage was recorded


def test_limiter_reset_clears_memory():
    lim = ratelimit.RateLimiter()
    lim.hit("m", 1, 60)
    assert lim.hit("m", 1, 60)[0] is False
    lim.reset()
    assert lim.hit("m", 1, 60)[0] is True


def test_redis_status_never_contains_url_or_password(monkeypatch):
    redis_client.reset_for_tests()
    monkeypatch.setenv("REDIS_URL", "redis://:hunter2@127.0.0.1:1/0")
    monkeypatch.setattr(redis_client, "_connect", lambda url: (_ for _ in ()).throw(ConnectionError(url)))
    assert redis_client.get_sync() is None
    assert redis_client.status() == "unreachable"
    assert redis_client._last_error == "ConnectionError"   # class name only
    redis_client.reset_for_tests()


def test_redis_not_configured_is_reported_plainly(monkeypatch):
    redis_client.reset_for_tests()
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert redis_client.status() == "not_configured" and redis_client.get_sync() is None
