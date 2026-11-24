"""Record and summarise language-model requests, and enforce the optional daily request cap."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import Integer, func
from sqlalchemy.orm import Session

from .. import models
from . import llm

logger = logging.getLogger(__name__)


def record(db: Session, *, user_id: int | None, kind: str, model: str | None, prompt_chars: int, completion_chars: int, latency_ms: int, ok: bool, error: str | None = None) -> None:
    """Best effort: a logging problem must never break an answer."""
    try:
        db.add(models.LLMUsage(user_id=user_id, kind=kind, model=model, prompt_chars=prompt_chars, completion_chars=completion_chars, latency_ms=latency_ms, ok=ok, error=(error or "")[:200] or None))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("could not record language-model usage")


def _since(db: Session, since: datetime):
    q = db.query(func.count(models.LLMUsage.id), func.sum(models.LLMUsage.ok.cast(Integer)), func.avg(models.LLMUsage.latency_ms),
                 func.sum(models.LLMUsage.prompt_chars), func.sum(models.LLMUsage.completion_chars)).filter(models.LLMUsage.created_at >= since)
    n, ok, avg, pc, cc = q.one()
    n = int(n or 0)
    return {"requests": n, "failures": n - int(ok or 0), "avg_latency_ms": int(avg) if avg is not None else None, "prompt_chars": int(pc or 0), "completion_chars": int(cc or 0)}


def summary(db: Session) -> dict:
    now = datetime.utcnow()
    return {"last_24h": _since(db, now - timedelta(hours=24)), "last_7d": _since(db, now - timedelta(days=7)), "today": _since(db, datetime(now.year, now.month, now.day))}


def limit_reached(db: Session) -> bool:
    cap = llm.daily_limit()
    if not cap:
        return False
    now = datetime.utcnow()
    used = db.query(func.count(models.LLMUsage.id)).filter(models.LLMUsage.kind == "chat", models.LLMUsage.created_at >= datetime(now.year, now.month, now.day)).scalar() or 0
    return used >= cap
