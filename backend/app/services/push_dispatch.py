"""Queue a Web Push for a notification and deliver it from a background worker, never inside the request.

Flow: notify() -> queue_push() writes a `queued` NotificationEvent in the SAME transaction -> after the commit, `dispatcher(event_id)`
enqueues a "push.deliver" job (jobs/jobqueue.py: Redis + worker in production, in-process thread when there is no Redis) -> deliver() sends
to each of the person's devices, records the PROVIDER's answer, drops devices the push service says are gone, and finally sets the event
status ("accepted_by_provider", never "delivered").

Retries: when no device accepted and the push service signalled a TEMPORARY problem, deliver() leaves the event `queued` and returns "retry";
the job queue retries with exponential backoff. Only the final attempt records `failed`.
Nothing is queued unless VAPID is configured, the person's preferences allow it, and they have at least one live device subscription.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Callable, Optional

from .. import models
from . import events, webpush
from .notify_rules import safe_link, wants_push

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _enqueue(event_id: int) -> None:
    from ..jobs import jobqueue
    jobqueue.enqueue("push.deliver", {"event_id": event_id}, key=f"push:{event_id}")


dispatcher: Callable[[int], None] = _enqueue          # tests replace this name to observe hand-offs


def queue_push(db, user, kind: str, title: Optional[str], link: Optional[str]) -> Optional["models.NotificationEvent"]:
    """Record a push to send once the caller's transaction commits. Returns None when nothing needs sending."""
    if not webpush.vapid_enabled(os.environ) or not wants_push(user.notification_prefs, kind):
        return None
    has_device = db.query(models.PushSubscription.id).filter(models.PushSubscription.user_id == user.id, models.PushSubscription.expired_at.is_(None)).first()
    if has_device is None:
        return None
    ev = models.NotificationEvent(user_id=user.id, channel="push", kind=str(kind)[:20], title=(title or "")[:120] or None, link=safe_link(link), status="queued", attempts=0, accepted_count=0)
    db.add(ev)
    db.flush()                                              # assigns the id the worker will look up
    events.call_after_commit(db, lambda: dispatcher(ev.id))
    return ev


def deliver(event_id: int, session_factory=None, send=webpush.send, env=None, final: bool = True) -> str:
    """Send one queued notification to all of its recipient's devices, with its OWN database session. Returns "done" or "retry"
    ("retry": nothing was accepted and the push service reported a temporary problem, and this is not the final attempt: nothing was recorded)."""
    env = os.environ if env is None else env
    if session_factory is None:
        from ..database import SessionLocal as session_factory
    db = session_factory()
    try:
        ev = db.get(models.NotificationEvent, event_id)
        if ev is None or ev.status != "queued":
            return "done"                                   # already handled (or removed): sending twice is worse than not sending
        subs = db.query(models.PushSubscription).filter(models.PushSubscription.user_id == ev.user_id, models.PushSubscription.expired_at.is_(None)).all()
        payload = webpush.build_payload(ev.kind, ev.title, ev.link)
        results = [(sub, send({"endpoint": sub.endpoint, "p256dh": sub.p256dh, "auth": sub.auth}, payload, env)) for sub in subs]
        if not final and webpush.should_retry([r for _, r in results]):
            db.rollback()
            return "retry"
        for sub, result in results:
            sub.failure_count, drop = webpush.next_failure_count(sub.failure_count or 0, result)
            if result.status == "accepted":
                sub.last_accepted_at = _now()
            if drop:
                db.delete(sub)                              # the browser unsubscribed, or it keeps failing
        ev.status, ev.accepted_count, ev.error_code = webpush.summarize([r for _, r in results])
        ev.attempts, ev.updated_at = (ev.attempts or 0) + 1, _now()
        db.commit()
        return "done"
    except Exception:
        db.rollback()
        logger.exception("Push delivery failed for notification event %s", event_id)
        return "retry" if not final else "done"
    finally:
        db.close()
