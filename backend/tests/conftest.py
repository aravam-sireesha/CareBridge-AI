import os

import pytest

from app.jobs import jobqueue
from app.services import events, redis_client, security


@pytest.fixture(autouse=True)
def _fresh_process_state():
    """Rate-limit counters, the live-event buffer and the in-memory job queue are process-wide; every test starts clean, and queued jobs are
    never run inline or written to the real job log during a test (tests that exercise handlers call them directly)."""
    previous = os.environ.get("JOBS_INLINE")
    os.environ["JOBS_INLINE"] = "false"
    security.reset_rate_limits()
    events.reset_for_tests()
    redis_client.reset_for_tests()
    jobqueue.reset_for_tests()
    jobqueue.job_log = None
    yield
    security.reset_rate_limits()
    events.reset_for_tests()
    jobqueue.reset_for_tests()
    jobqueue.job_log = None
    if previous is None:
        os.environ.pop("JOBS_INLINE", None)
    else:
        os.environ["JOBS_INLINE"] = previous
