"""Create in-app notifications. Adds rows to the caller's transaction; the caller commits."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models
from .notify_rules import safe_link, wants_in_app


def notify(db: Session, user_id: int, kind: str, title: str, body: str | None = None, link: str | None = None):
    user = db.get(models.User, user_id)
    if user is None or user.is_active is False or not wants_in_app(user.notification_prefs, kind):
        return None
    row = models.Notification(user_id=user_id, kind=kind, title=title[:200], body=(body or None) and body[:2000], link=safe_link(link))
    db.add(row)
    return row


def notify_organization(db: Session, org_id: int | None, kind: str, title: str, body: str | None = None, link: str | None = None) -> int:
    """Notify every account that belongs to an organization. Returns how many were created."""
    if org_id is None:
        return 0
    users = db.query(models.User).filter(models.User.organization_id == org_id, models.User.role == "organization").all()
    return sum(1 for u in users if notify(db, u.id, kind, title, body, link))
