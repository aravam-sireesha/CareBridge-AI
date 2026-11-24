"""Job queue: at-least-once with leases, exponential backoff, dead letters, idempotent enqueue. Memory backend and a FAKE Redis."""
import pytest

from app.jobs import jobqueue as q
from app.jobs.jobqueue import Job, JobContext, PermanentError, RetryableError
from app.services import redis_client

T0 = 1_800_000_000.0


class FakeRedis:
    """Just enough Redis for the queue. eval() emulates RESERVE_LUA (asserting the real script is what was sent)."""

    def __init__(self):
        self.kv, self.z, self.lists, self.ttl = {}, {}, {}, {}

    def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v; self.ttl[k] = ex
        return True

    def get(self, k): return self.kv.get(k)
    def delete(self, *ks): [self.kv.pop(k, None) for k in ks]
    def zadd(self, key, mapping): self.z.setdefault(key, {}).update(mapping)
    def zrem(self, key, member): return 1 if self.z.get(key, {}).pop(member, None) is not None else 0
    def zcard(self, key): return len(self.z.get(key, {}))
    def zrangebyscore(self, key, lo, hi, start=None, num=None):
        hi = float("inf") if hi == "+inf" else float(hi)
        return [m for m, s in sorted(self.z.get(key, {}).items(), key=lambda x: x[1]) if s <= hi]
    def eval(self, script, numkeys, ready, processing, now, until):
        assert script == q.RESERVE_LUA and numkeys == 2
        ids = self.zrangebyscore(ready, "-inf", now)
        if not ids:
            return None
        self.zrem(ready, ids[0]); self.zadd(processing, {ids[0]: until})
        return ids[0]
    def lpush(self, key, v): self.lists.setdefault(key, []).insert(0, v)
    def ltrim(self, key, a, b): self.lists[key] = self.lists.get(key, [])[a:b + 1]
    def lrange(self, key, a, b): return self.lists.get(key, [])[a:b + 1]
    def llen(self, key): return len(self.lists.get(key, []))
    def scan_iter(self, match=None, count=None):
        return [k for k in list(self.kv) + list(self.z) + list(self.lists) if k.startswith((match or "").rstrip("*"))]


def both():
    return [q.MemoryBackend(), q.RedisBackend(FakeRedis())]


def make(name="x", key=None, max_attempts=3, payload=None):
    return Job(id=f"j-{name}-{key}", name=name, payload=payload or {}, max_attempts=max_attempts, key=key, created_at=T0)


# ---------------------------------------------------------------- backoff
def test_backoff_doubles_is_capped_and_jittered():
    assert q.backoff_delay(1, rand=lambda: 0.5) == 15 and q.backoff_delay(2, rand=lambda: 0.5) == 30 and q.backoff_delay(3, rand=lambda: 0.5) == 60
    assert q.backoff_delay(50, rand=lambda: 0.5) == q.MAX_DELAY
    assert q.backoff_delay(1, rand=lambda: 0.0) == pytest.approx(12) and q.backoff_delay(1, rand=lambda: 1.0) == pytest.approx(18)
    assert q.backoff_delay(0, rand=lambda: 0.5) == 15                       # never a negative exponent


def test_default_max_attempts_is_bounded(monkeypatch):
    assert q.default_max_attempts() == 5
    monkeypatch.setenv("JOB_MAX_ATTEMPTS", "0"); assert q.default_max_attempts() == 1
    monkeypatch.setenv("JOB_MAX_ATTEMPTS", "999"); assert q.default_max_attempts() == 10
    monkeypatch.setenv("JOB_MAX_ATTEMPTS", "x"); assert q.default_max_attempts() == 5


# ---------------------------------------------------------------- both backends behave the same
@pytest.mark.parametrize("idx", [0, 1])
def test_a_job_is_not_available_before_its_time_and_is_leased_when_due(idx):
    be = both()[idx]
    assert be.put(make("a"), T0 + 60, T0) is True
    assert be.reserve(T0, 120) is None and be.reserve(T0 + 59, 120) is None
    job = be.reserve(T0 + 60, 120)
    assert job.name == "a" and job.attempts == 1
    assert be.reserve(T0 + 61, 120) is None                                   # leased: nobody else gets it
    assert be.stats() == {"ready": 0, "processing": 1, "dead": 0}


@pytest.mark.parametrize("idx", [0, 1])
def test_earliest_due_job_is_taken_first(idx):
    be = both()[idx]
    be.put(make("late"), T0 + 5, T0); be.put(make("early"), T0 + 1, T0)
    assert be.reserve(T0 + 10, 120).name == "early"


@pytest.mark.parametrize("idx", [0, 1])
def test_the_same_idempotency_key_is_queued_once(idx):
    be = both()[idx]
    assert be.put(make("a", key="remind:7"), T0, T0) is True
    assert be.put(Job(id="other", name="a", payload={}, max_attempts=3, key="remind:7"), T0, T0) is False
    assert be.stats()["ready"] == 1
    assert be.put(Job(id="third", name="a", payload={}, max_attempts=3, key="remind:8"), T0, T0) is True


@pytest.mark.parametrize("idx", [0, 1])
def test_a_crashed_worker_loses_nothing_the_lease_expires_and_the_job_runs_again(idx):
    be = both()[idx]
    be.put(make("a"), T0, T0)
    first = be.reserve(T0, 120)                                               # worker takes it ... and dies
    assert be.requeue_expired(T0 + 119) == 0
    assert be.requeue_expired(T0 + 121) == 1
    again = be.reserve(T0 + 121, 120)
    assert again.id == first.id and again.attempts == 2                        # the crash counted as an attempt


@pytest.mark.parametrize("idx", [0, 1])
def test_ack_removes_it_and_bury_keeps_it_visible(idx):
    be = both()[idx]
    be.put(make("a"), T0, T0); be.ack(be.reserve(T0, 120))
    assert be.stats() == {"ready": 0, "processing": 0, "dead": 0}
    be.put(make("b"), T0, T0); j = be.reserve(T0, 120); j.last_error = "boom"; be.bury(j)
    assert be.stats()["dead"] == 1 and be.dead_jobs()[0].last_error == "boom" and be.stats()["processing"] == 0


@pytest.mark.parametrize("idx", [0, 1])
def test_dead_list_is_capped(idx):
    be = both()[idx]
    for i in range(q.DEAD_KEEP + 25):
        be.bury(Job(id=f"d{i}", name="x", payload={}, max_attempts=1))
    assert be.stats()["dead"] == q.DEAD_KEEP


# ---------------------------------------------------------------- processing semantics
def run_all(handlers, be, start, steps=40, step=3600):
    now, seen = start, 0
    for _ in range(steps):
        while q.process_one(handlers, now=now, backend_=be, rand=lambda: 0.5):
            seen += 1
        now += step
    return seen


@pytest.fixture
def logged(monkeypatch):
    events = []
    monkeypatch.setattr(q, "job_log", lambda job, status: events.append((job.name, status, job.attempts)))
    return events


@pytest.mark.parametrize("idx", [0, 1])
def test_success_runs_once_and_is_logged(idx, logged):
    be = both()[idx]; calls = []
    be.put(make("ok", payload={"n": 1}), T0, T0)
    handlers = {"ok": lambda payload, ctx: calls.append((payload, ctx.attempt, ctx.is_final))}
    assert q.process_one(handlers, now=T0, backend_=be) is True and q.process_one(handlers, now=T0, backend_=be) is False
    assert calls == [({"n": 1}, 1, False)] and [s for _, s, _ in logged] == ["running", "succeeded"]


@pytest.mark.parametrize("idx", [0, 1])
def test_a_retryable_failure_is_retried_with_growing_delay_then_succeeds(idx, logged):
    be = both()[idx]; attempts = []
    be.put(make("flaky", max_attempts=4), T0, T0)

    def flaky(payload, ctx):
        attempts.append(ctx.attempt)
        if ctx.attempt < 3:
            raise RetryableError("provider_busy")
    q.process_one({"flaky": flaky}, now=T0, backend_=be, rand=lambda: 0.5)
    assert be.stats()["ready"] == 1 and q.process_one({"flaky": flaky}, now=T0 + 14, backend_=be) is False      # 15 s backoff not over
    q.process_one({"flaky": flaky}, now=T0 + 15, backend_=be, rand=lambda: 0.5)
    q.process_one({"flaky": flaky}, now=T0 + 15 + 30, backend_=be, rand=lambda: 0.5)                           # second backoff is 30 s
    assert attempts == [1, 2, 3] and be.stats() == {"ready": 0, "processing": 0, "dead": 0}
    assert [s for _, s, _ in logged] == ["running", "retrying", "running", "retrying", "running", "succeeded"]


@pytest.mark.parametrize("idx", [0, 1])
def test_after_max_attempts_the_job_is_dead_not_dropped(idx, logged):
    be = both()[idx]
    be.put(make("bad", max_attempts=3), T0, T0)
    def bad(payload, ctx): raise RetryableError("still_down")
    run_all({"bad": bad}, be, T0)
    assert be.stats() == {"ready": 0, "processing": 0, "dead": 1}
    dead = be.dead_jobs()[0]
    assert dead.attempts == 3 and dead.last_error == "still_down" and logged[-1][1] == "dead"


@pytest.mark.parametrize("idx", [0, 1])
def test_a_permanent_failure_is_not_retried(idx):
    be = both()[idx]; calls = []
    be.put(make("p", max_attempts=5), T0, T0)
    def perm(payload, ctx): calls.append(1); raise PermanentError("invalid_address")
    run_all({"p": perm}, be, T0)
    assert calls == [1] and be.dead_jobs()[0].last_error == "invalid_address"


@pytest.mark.parametrize("idx", [0, 1])
def test_an_unexpected_exception_is_retried_and_only_its_class_is_recorded(idx):
    be = both()[idx]
    be.put(make("u", max_attempts=2), T0, T0)
    def boom(payload, ctx): raise ValueError("user@example.org was rejected")
    run_all({"u": boom}, be, T0)
    assert be.dead_jobs()[0].last_error == "ValueError"                         # the message (which held an address) is not stored


@pytest.mark.parametrize("idx", [0, 1])
def test_a_job_with_no_handler_goes_to_the_dead_list_immediately(idx):
    be = both()[idx]; be.put(make("mystery"), T0, T0)
    assert q.process_one({}, now=T0, backend_=be) is True
    assert be.dead_jobs()[0].last_error == "no_handler"


def test_a_failing_job_log_never_breaks_processing(monkeypatch):
    def broken(job, status): raise RuntimeError("db down")
    monkeypatch.setattr(q, "job_log", broken)
    be = q.MemoryBackend(); be.put(make("ok"), T0, T0)
    assert q.process_one({"ok": lambda p, c: None}, now=T0, backend_=be) is True and be.stats()["processing"] == 0


def test_is_final_is_true_on_the_last_attempt():
    assert JobContext("j", 3, 3).is_final and not JobContext("j", 2, 3).is_final


def test_error_codes_never_carry_messages():
    assert q.error_code(RetryableError("busy")) == "busy" and q.error_code(KeyError("secret@x.org")) == "KeyError"
    assert len(q.error_code(RetryableError("x" * 500))) == 80


# ---------------------------------------------------------------- the public enqueue()
@pytest.fixture
def mem(monkeypatch):
    monkeypatch.setenv("JOBS_INLINE", "false"); monkeypatch.delenv("REDIS_URL", raising=False)
    redis_client.reset_for_tests(); q.reset_for_tests(); q.job_log = None
    yield q._memory
    q.reset_for_tests()


def test_enqueue_without_redis_uses_the_in_process_queue_and_dedupes(mem):
    a = q.enqueue("n", {"x": 1}, key="k1", now=T0); b = q.enqueue("n", {"x": 1}, key="k1", now=T0)
    assert a and b is None and mem.stats()["ready"] == 1


def test_enqueue_honours_delay(mem):
    q.enqueue("n", delay=90, now=T0)
    assert q.process_one({"n": lambda p, c: None}, now=T0 + 89, backend_=mem) is False and q.process_one({"n": lambda p, c: None}, now=T0 + 90, backend_=mem) is True


def test_enqueue_falls_back_when_redis_fails_midway(monkeypatch):
    monkeypatch.setenv("JOBS_INLINE", "false"); q.reset_for_tests()
    class Broken(FakeRedis):
        def set(self, *a, **k): raise ConnectionError("down")
    monkeypatch.setattr(redis_client, "get_sync", lambda: Broken()); marked = []
    monkeypatch.setattr(redis_client, "mark_failed", lambda e: marked.append(e))
    assert q.enqueue("n", {"a": 1}, now=T0) is not None and q._memory.stats()["ready"] == 1 and marked          # not lost, not raised
    q.reset_for_tests()


def test_enqueue_logs_queued_through_the_installed_logger(mem):
    seen = []; q.job_log = lambda job, status: seen.append((job.name, status))
    q.enqueue("n", now=T0); q.job_log = None
    assert seen == [("n", "queued")]
