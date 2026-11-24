"""Background worker:  python -m app.worker   (run it as its own process/container; see deploy/docker-compose.yml).

Runs the scheduler (periodic scans) and processes queued jobs until it receives SIGTERM/SIGINT, then finishes the job in hand and exits.
It refuses to start without Redis: with no shared queue a separate worker process would see an empty private queue and do nothing.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time

from .jobs import jobqueue, joblog
from .jobs.scheduler import Scheduler
from .services import observability, redis_client

logger = logging.getLogger("carebridge.worker")


def run(stop: threading.Event, concurrency: int = 1, idle_seconds: float = 1.0, scheduler: Scheduler | None = None, handlers=None) -> None:
    if handlers is None:
        from .jobs.handlers import HANDLERS as handlers
    scheduler = scheduler or Scheduler()

    def loop(lead: bool) -> None:
        last_stats = 0.0
        while not stop.is_set():
            did = False
            try:
                if lead:
                    scheduler.tick()
                    if time.time() - last_stats > 60:
                        last_stats = time.time()
                        logger.info("queue %s", jobqueue.backend().stats())
                did = jobqueue.process_one(handlers)
            except Exception:
                logger.exception("Worker loop error")
                observability.capture_current()
            if not did:
                stop.wait(idle_seconds)

    threads = [threading.Thread(target=loop, args=(i == 0,), name=f"worker-{i}", daemon=True) for i in range(max(1, concurrency))]
    for t in threads:
        t.start()
    for t in threads:
        while t.is_alive():
            t.join(0.5)


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    observability.init("worker")
    if not redis_client.is_configured() or redis_client.get_sync() is None:
        logger.error("REDIS_URL is not set or Redis is unreachable: a separate worker needs the shared queue. Exiting.")
        return 2
    joblog.install()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    concurrency = max(1, min(8, int(os.getenv("WORKER_CONCURRENCY", "2") or 2)))
    from .jobs.handlers import HANDLERS
    logger.info("Worker started (%s thread(s), %s job types)", concurrency, len(HANDLERS))
    run(stop, concurrency)
    logger.info("Worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
