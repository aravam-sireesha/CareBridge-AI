"""Periodic work. Every worker may run this loop: the queue's idempotency key (job name + time bucket) means each period is enqueued ONCE
across all workers, so no leader election or lock is needed. The first tick after a deploy enqueues immediately."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from . import jobqueue


@dataclass(frozen=True)
class Periodic:
    job: str
    every: int          # seconds


SCHEDULE = (
    Periodic("tracking.stale_scan", 60),       # stale GPS, expired tracking sessions
    Periodic("delivery.scan", 3600),           # overdue deliveries, receipts nobody confirmed
    Periodic("otp.purge", 3600),               # expired one-time codes and reset tokens
    Periodic("location.purge", 6 * 3600),      # trail points past the retention period
    Periodic("payments.reconcile", 900),       # orders whose webhook may have been missed (does nothing while payments are off)
)


def bucket(now: float, every: int) -> int:
    return int(now // every)


class Scheduler:
    def __init__(self, schedule=SCHEDULE, enqueue: Optional[Callable] = None):
        self.schedule, self._enqueue, self._last = schedule, enqueue or jobqueue.enqueue, {}

    def tick(self, now: Optional[float] = None) -> list[str]:
        now = time.time() if now is None else now
        fired = []
        for p in self.schedule:
            b = bucket(now, p.every)
            if self._last.get(p.job) == b:
                continue                                  # already handled this period in this process
            self._last[p.job] = b
            if self._enqueue(p.job, {}, key=f"sched:{p.job}:{b}", now=now):
                fired.append(p.job)
        return fired
