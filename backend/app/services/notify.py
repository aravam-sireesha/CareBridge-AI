"""Create in-app notifications. Adds rows to the caller's transaction; the caller commits."""
from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

from .. import models
from . import events, push_dispatch
from ..jobs import jobqueue
from ..jobs.rules import email_job
from .notify_rules import safe_link, wants_email, wants_in_app

logger = logging.getLogger(__name__)


def notify(db: Session, user_id: int, kind: str, title: str, body: str | None = None, link: str | None = None):
    user = db.get(models.User, user_id)
    if user is None or user.is_active is False or not wants_in_app(user.notification_prefs, kind):
        return None
    row = models.Notification(user_id=user_id, kind=kind, title=title[:200], body=(body or None) and body[:2000], link=safe_link(link))
    db.add(row)
    try:   # tell a connected browser right away, once (and only if) the transaction commits; a failure here never blocks the notification itself
        events.publish_after_commit(db, "notification", {"kind": kind, "title": row.title, "link": row.link}, events.audience(users=[user_id]))
    except Exception:
        logger.exception("Could not queue the live notification event for user %s", user_id)
    try:   # Web Push to the person's subscribed devices: queued in this transaction, sent by a worker after it commits
        push_dispatch.queue_push(db, user, kind, row.title, row.link)
    except Exception:
        logger.exception("Could not queue the Web Push for user %s", user_id)
    try:   # e-mail is opt-in, verified addresses only, and sent by the worker after the commit
        _queue_email(db, user, kind, row.title, row.link)
    except Exception:
        logger.exception("Could not queue the e-mail for user %s", user_id)
    return row


def _queue_email(db, user, kind: str, title: str, link: str | None) -> None:
    if os.getenv("EMAIL_NOTIFICATIONS_ENABLED", "").strip().lower() != "true" or not wants_email(user.notification_prefs, kind):
        return
    job = email_job({"is_active": user.is_active, "email": user.email, "email_verified_at": user.email_verified_at}, title, link, os.getenv("APP_BASE_URL", ""))
    if job is None:
        return
    events.call_after_commit(db, lambda: jobqueue.enqueue("email.send", job))


def notify_organization(db: Session, org_id: int | None, kind: str, title: str, body: str | None = None, link: str | None = None) -> int:
    """Notify every account that belongs to an organization. Returns how many were created."""
    if org_id is None:
        return 0
    users = db.query(models.User).filter(models.User.organization_id == org_id, models.User.role == "organization").all()
    return sum(1 for u in users if notify(db, u.id, kind, title, body, link))
