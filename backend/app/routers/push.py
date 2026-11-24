"""Web Push subscriptions for the signed-in person's own devices.

* Subscribing needs the browser's permission prompt, so a subscription is the person's own consent for that device. They can remove it
  here, in the browser, or by switching the "push" preference off; security notices are the one category that cannot be muted.
* Endpoints are allow-listed (services/webpush.py): the server never POSTs to an address a client merely claims is a push service.
* A device that signs in as someone else takes over the subscription (an endpoint belongs to ONE person at a time), so a shared phone
  never keeps delivering the previous account's notices.
* "accepted_by_provider" in /push/events means the push service took the message. It is never described as delivered.
"""
from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_user
from ..services import audit, push_dispatch, ratelimit, webpush

router = APIRouter(prefix="/push", tags=["push"])
MAX_DEVICES = 10


class Keys(BaseModel):
    model_config = ConfigDict(extra="ignore")
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class SubscribeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    endpoint: str = Field(max_length=1000)
    keys: Keys
    user_agent: Optional[str] = Field(default=None, max_length=200)


class UnsubscribeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    endpoint: str = Field(max_length=1000)


def _iso(dt):
    return dt.isoformat() if dt else None


@router.get("/config")
def config(user: dict = Depends(get_current_user)):
    """Whether push is set up on this server, and the PUBLIC VAPID key the browser needs to subscribe."""
    on = webpush.vapid_enabled(os.environ)
    return {"enabled": on, "public_key": os.environ["VAPID_PUBLIC_KEY"].strip() if on else None}


@router.post("/subscribe", dependencies=[Depends(ratelimit.rate_limit("push_sub", 20, 3600))])
def subscribe(body: SubscribeBody, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if not webpush.vapid_enabled(os.environ):
        raise HTTPException(status_code=503, detail="Push notifications are not set up on this server.")
    try:
        endpoint, p256dh, auth = webpush.validate_subscription(body.model_dump(), os.environ)
    except webpush.SubscriptionError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    h = webpush.endpoint_hash(endpoint)
    row = db.query(models.PushSubscription).filter(models.PushSubscription.endpoint_hash == h).first()
    reassigned = row is not None and row.user_id != user["id"]
    if row is None:
        row = models.PushSubscription(user_id=user["id"], endpoint_hash=h, endpoint=endpoint, p256dh=p256dh, auth=auth, failure_count=0)
        db.add(row)
    row.user_id, row.endpoint, row.p256dh, row.auth = user["id"], endpoint, p256dh, auth
    row.failure_count, row.expired_at = 0, None
    row.user_agent = (body.user_agent or None) and " ".join(body.user_agent.split())[:200]
    db.flush()
    others = (db.query(models.PushSubscription).filter(models.PushSubscription.user_id == user["id"], models.PushSubscription.id != row.id)
              .order_by(models.PushSubscription.id.desc()).all())
    for old in others[MAX_DEVICES - 1:]:                       # keep the newest devices only
        db.delete(old)
    audit.record(db, user, "push.subscribed", "user", user["id"], {"host": urlsplit(endpoint).hostname, "reassigned_from_another_account": reassigned})
    db.commit()
    return {"subscribed": True, "id": row.id}


@router.delete("/subscribe")
def unsubscribe(body: UnsubscribeBody, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Remove one of YOUR devices. Someone else's endpoint is reported as not found, like a missing one."""
    h = webpush.endpoint_hash(body.endpoint)
    row = db.query(models.PushSubscription).filter(models.PushSubscription.endpoint_hash == h, models.PushSubscription.user_id == user["id"]).first()
    if row is not None:
        db.delete(row)
        audit.record(db, user, "push.unsubscribed", "user", user["id"], {})
        db.commit()
    return {"removed": 1 if row is not None else 0}


@router.get("/subscriptions")
def subscriptions(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """The person's own devices. Keys and full endpoints are never returned."""
    rows = db.query(models.PushSubscription).filter(models.PushSubscription.user_id == user["id"]).order_by(models.PushSubscription.id.desc()).all()
    return {"devices": [{"id": r.id, "service": urlsplit(r.endpoint).hostname, "user_agent": r.user_agent, "added": _iso(r.created_at),
                         "last_accepted": _iso(r.last_accepted_at), "failing": (r.failure_count or 0) > 0} for r in rows]}


@router.get("/events")
def recent_events(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """The person's last push attempts with the provider's answer, so "did it work?" has an honest answer."""
    rows = (db.query(models.NotificationEvent).filter(models.NotificationEvent.user_id == user["id"], models.NotificationEvent.channel == "push")
            .order_by(models.NotificationEvent.id.desc()).limit(10).all())
    return {"events": [{"id": r.id, "kind": r.kind, "title": r.title, "status": r.status, "accepted_devices": r.accepted_count, "error": r.error_code, "at": _iso(r.created_at)} for r in rows]}


@router.post("/test", dependencies=[Depends(ratelimit.rate_limit("push_test", 5, 3600))])
def send_test(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send a test notification to the person's own devices (asynchronously; see /push/events for the provider's answer)."""
    if not webpush.vapid_enabled(os.environ):
        raise HTTPException(status_code=503, detail="Push notifications are not set up on this server.")
    me = db.get(models.User, user["id"])
    ev = push_dispatch.queue_push(db, me, "test", "Test notification", "/notifications")
    if ev is None:
        raise HTTPException(status_code=409, detail="No notifications are switched on for this device, or push is turned off in your notification settings.")
    db.commit()
    return {"queued": True, "event_id": ev.id}
