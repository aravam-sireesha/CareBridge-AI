"""Database log of job status transitions (table background_jobs). Best effort: never raises into the queue."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from . import jobqueue

logger = logging.getLogger(__name__)
FINISHED = ("succeeded", "dead")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record(job, status: str, session_factory=None) -> None:
    from .. import models
    if session_factory is None:
        from ..database import SessionLocal as session_factory
    db = session_factory()
    try:
        row = db.query(models.BackgroundJob).filter(models.BackgroundJob.job_id == job.id).first()
        if row is None:
            row = models.BackgroundJob(job_id=job.id, name=job.name[:60], status=status, attempts=0, max_attempts=job.max_attempts)
            db.add(row)
        row.status, row.attempts, row.max_attempts = status, job.attempts, job.max_attempts
        row.last_error, row.updated_at = (job.last_error or None), _now()
        if status in FINISHED:
            row.finished_at = _now()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not write the job log")
    finally:
        db.close()


def install() -> None:
    jobqueue.job_log = record
