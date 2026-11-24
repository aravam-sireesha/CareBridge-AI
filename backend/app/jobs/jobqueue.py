"""A small durable job queue: Redis when available, in-process otherwise.

Guarantees (and their limits), stated plainly:
* AT-LEAST-ONCE. A job is leased for LEASE_SECONDS; if the worker dies, the lease expires and another worker runs it again. Handlers must
  therefore be idempotent (every handler in jobs/handlers.py is written that way).
* RETRIES with exponential backoff and jitter (15 s, 30 s, 1 min ... capped at 1 h). After `max_attempts` the job goes to the DEAD list
  (kept, capped at DEAD_KEEP) instead of being dropped, so a failure is visible and can be re-queued by an operator.
* IDEMPOTENT ENQUEUE. `enqueue(..., key=...)` is a no-op if the same key was already queued within IDEM_TTL: scheduled scans and "send this
  reminder" jobs cannot double up, even with several workers.
* NO RETRY FOR PERMANENT FAILURES: a handler raises PermanentError to send a job straight to the dead list.
* Without Redis the queue is in memory and (unless JOBS_INLINE=false) jobs run on a small background thread in the same process. That is
  fine for development and a single small instance; it LOSES queued jobs on restart. Production uses Redis and a separate worker.
The Redis claim script is Lua so "take from ready" and "mark processing" cannot be split by a crash. It is untested against a real Redis.
"""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping, Optional

from ..services import redis_client

logger = logging.getLogger(__name__)

READY, PROCESSING, DEAD, DATA = "cb:jobs:ready", "cb:jobs:processing", "cb:jobs:dead", "cb:jobs:data:"
IDEM = "cb:jobs:idem:"
LEASE_SECONDS = 120
BASE_DELAY, MAX_DELAY = 15.0, 3600.0
IDEM_TTL = 24 * 3600
DATA_TTL = 7 * 24 * 3600
DEAD_KEEP = 1000

RESERVE_LUA = """
local ids = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, 1)
if #ids == 0 then return false end
redis.call('ZREM', KEYS[1], ids[1])
redis.call('ZADD', KEYS[2], ARGV[2], ids[1])
return ids[1]
"""


class RetryableError(Exception):
    """Try again later (network blip, provider busy). `code` is what gets logged: never put personal data in it."""

    def __init__(self, code: str = "retry"):
        super().__init__(code)
        self.code = code


class PermanentError(Exception):
    """Do not retry (bad address, provider refused for good, nothing to do)."""

    def __init__(self, code: str = "permanent"):
        super().__init__(code)
        self.code = code


def default_max_attempts() -> int:
    try:
        return max(1, min(10, int(os.getenv("JOB_MAX_ATTEMPTS", "5") or 5)))
    except ValueError:
        return 5


@dataclass
class Job:
    id: str
    name: str
    payload: dict
    max_attempts: int
    attempts: int = 0
    key: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_error: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> "Job":
        return cls(**json.loads(raw))


@dataclass(frozen=True)
class JobContext:
    job_id: str
    attempt: int
    max_attempts: int

    @property
    def is_final(self) -> bool:
        return self.attempt >= self.max_attempts


def backoff_delay(attempt: int, rand: Callable[[], float] = random.random, base: float = BASE_DELAY, cap: float = MAX_DELAY) -> float:
    """Seconds to wait after the `attempt`-th failure (1-based), with +/-20% jitter so retries from many jobs do not arrive together."""
    exp = min(cap, base * (2 ** max(0, attempt - 1)))
    return exp * (0.8 + 0.4 * rand())


def error_code(exc: BaseException) -> str:
    return (getattr(exc, "code", None) or type(exc).__name__)[:80]


# --------------------------------------------------------------------------- backends
class MemoryBackend:
    def __init__(self):
        self._lock = threading.Lock()
        self.ready: dict[str, tuple[float, Job]] = {}
        self.processing: dict[str, tuple[float, Job]] = {}
        self.dead: list[Job] = []
        self.idem: dict[str, float] = {}

    def put(self, job: Job, run_at: float, now: float) -> bool:
        with self._lock:
            if job.key:
                if self.idem.get(job.key, 0) > now:
                    return False
                self.idem[job.key] = now + IDEM_TTL
            self.ready[job.id] = (run_at, job)
            return True

    def reserve(self, now: float, lease: float) -> Optional[Job]:
        with self._lock:
            due = sorted((t, jid) for jid, (t, _) in self.ready.items() if t <= now)
            if not due:
                return None
            _, job = self.ready.pop(due[0][1])
            job.attempts += 1
            self.processing[job.id] = (now + lease, job)
            return job

    def ack(self, job: Job) -> None:
        with self._lock:
            self.processing.pop(job.id, None)

    def retry(self, job: Job, run_at: float) -> None:
        with self._lock:
            self.processing.pop(job.id, None)
            self.ready[job.id] = (run_at, job)

    def bury(self, job: Job) -> None:
        with self._lock:
            self.processing.pop(job.id, None)
            self.dead.append(job)
            del self.dead[:-DEAD_KEEP]

    def requeue_expired(self, now: float) -> int:
        with self._lock:
            expired = [jid for jid, (t, _) in self.processing.items() if t < now]
            for jid in expired:
                _, job = self.processing.pop(jid)
                self.ready[jid] = (now, job)
            return len(expired)

    def stats(self) -> dict:
        with self._lock:
            return {"ready": len(self.ready), "processing": len(self.processing), "dead": len(self.dead)}

    def dead_jobs(self, limit: int = 50) -> list[Job]:
        with self._lock:
            return list(self.dead[-limit:])

    def clear(self) -> None:
        with self._lock:
            self.ready.clear(); self.processing.clear(); self.dead.clear(); self.idem.clear()


class RedisBackend:
    def __init__(self, client: Any):
        self.c = client

    def put(self, job: Job, run_at: float, now: float) -> bool:
        if job.key and not self.c.set(IDEM + job.key, job.id, nx=True, ex=IDEM_TTL):
            return False
        self.c.set(DATA + job.id, job.to_json(), ex=DATA_TTL)
        self.c.zadd(READY, {job.id: run_at})
        return True

    def reserve(self, now: float, lease: float) -> Optional[Job]:
        for _ in range(5):                                              # a few tries in case a job's data has expired
            jid = self.c.eval(RESERVE_LUA, 2, READY, PROCESSING, now, now + lease)
            if not jid:
                return None
            raw = self.c.get(DATA + jid)
            if raw is None:
                self.c.zrem(PROCESSING, jid)
                continue
            job = Job.from_json(raw)
            job.attempts += 1
            self.c.set(DATA + jid, job.to_json(), ex=DATA_TTL)
            return job
        return None

    def ack(self, job: Job) -> None:
        self.c.zrem(PROCESSING, job.id)
        self.c.delete(DATA + job.id)

    def retry(self, job: Job, run_at: float) -> None:
        self.c.set(DATA + job.id, job.to_json(), ex=DATA_TTL)
        self.c.zadd(READY, {job.id: run_at})
        self.c.zrem(PROCESSING, job.id)

    def bury(self, job: Job) -> None:
        self.c.lpush(DEAD, job.to_json())
        self.c.ltrim(DEAD, 0, DEAD_KEEP - 1)
        self.c.zrem(PROCESSING, job.id)
        self.c.delete(DATA + job.id)

    def requeue_expired(self, now: float) -> int:
        n = 0
        for jid in self.c.zrangebyscore(PROCESSING, "-inf", now):
            if self.c.zrem(PROCESSING, jid) == 1:                       # exactly one worker wins the requeue
                self.c.zadd(READY, {jid: now}); n += 1
        return n

    def stats(self) -> dict:
        return {"ready": self.c.zcard(READY), "processing": self.c.zcard(PROCESSING), "dead": self.c.llen(DEAD)}

    def dead_jobs(self, limit: int = 50) -> list[Job]:
        return [Job.from_json(r) for r in self.c.lrange(DEAD, 0, limit - 1)]

    def clear(self) -> None:
        for k in list(self.c.scan_iter(match="cb:jobs:*", count=500)):
            self.c.delete(k)


# --------------------------------------------------------------------------- module API
_memory = MemoryBackend()
job_log: Optional[Callable[[Job, str], None]] = None        # set by the worker / app start-up to a database logger (jobs/joblog.py)
_inline_lock = threading.Lock()


def backend() -> Any:
    client = redis_client.get_sync()
    return RedisBackend(client) if client is not None else _memory


def redis_mode() -> bool:
    return redis_client.get_sync() is not None


def _log(job: Job, status: str) -> None:
    if job_log is None:
        return
    try:
        job_log(job, status)
    except Exception:
        logger.exception("Could not record job status")            # logging must never break the queue


def enqueue(name: str, payload: Optional[dict] = None, *, key: Optional[str] = None, delay: float = 0.0, max_attempts: Optional[int] = None,
            now: Optional[float] = None) -> Optional[str]:
    """Queue a job. Returns its id, or None if `key` was already queued recently. Never raises into the caller: if the queue is
    unreachable the job runs inline (when allowed) so a notification is not silently lost."""
    now = time.time() if now is None else now
    job = Job(id=str(uuid.uuid4()), name=name, payload=payload or {}, max_attempts=max_attempts or default_max_attempts(), key=key)
    try:
        be = backend()
        if not be.put(job, now + max(0.0, delay), now):
            return None
    except Exception as exc:
        redis_client.mark_failed(exc)
        logger.warning("Job queue unavailable (%s); using the in-process queue", type(exc).__name__)
        be = _memory
        if not be.put(job, now + max(0.0, delay), now):
            return None
    _log(job, "queued")
    if be is _memory and inline_enabled():
        _kick(max(0.0, delay))
    return job.id


def inline_enabled() -> bool:
    return os.getenv("JOBS_INLINE", "true").strip().lower() != "false"


def _kick(delay: float) -> None:
    t = threading.Timer(delay, _drain_inline)
    t.daemon = True
    t.start()


def _drain_inline() -> None:
    """Run due in-memory jobs on this thread. Only used when there is no Redis worker."""
    from . import handlers
    if not _inline_lock.acquire(blocking=False):
        return
    try:
        while process_one(handlers.HANDLERS, backend_=_memory):
            pass
        stats = _memory.stats()
        if stats["ready"]:                                          # something is waiting for its retry time: look again later
            soonest = min(t for t, _ in _memory.ready.values())
            _kick(max(1.0, soonest - time.time()))
    finally:
        _inline_lock.release()


def process_one(handlers: Mapping[str, Callable], now: Optional[float] = None, backend_: Any = None, rand: Callable[[], float] = random.random) -> bool:
    """Claim and run ONE due job. Returns False when there was nothing to do."""
    be = backend_ or backend()
    now = time.time() if now is None else now
    be.requeue_expired(now)
    job = be.reserve(now, LEASE_SECONDS)
    if job is None:
        return False
    _log(job, "running")
    fn = handlers.get(job.name)
    if fn is None:
        job.last_error = "no_handler"; be.bury(job); _log(job, "dead")
        logger.error("No handler registered for job %s", job.name)
        return True
    try:
        fn(job.payload, JobContext(job.id, job.attempts, job.max_attempts))
    except PermanentError as exc:
        job.last_error = error_code(exc); be.bury(job); _log(job, "dead")
    except Exception as exc:                                        # RetryableError or anything unexpected
        job.last_error = error_code(exc)
        if not isinstance(exc, RetryableError):
            logger.exception("Job %s (%s) failed unexpectedly", job.name, job.id)
        if job.attempts >= job.max_attempts:
            be.bury(job); _log(job, "dead")
        else:
            be.retry(job, now + backoff_delay(job.attempts, rand)); _log(job, "retrying")
    else:
        be.ack(job); _log(job, "succeeded")
    return True


def reset_for_tests() -> None:
    _memory.clear()
