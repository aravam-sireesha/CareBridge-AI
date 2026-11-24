"""What each background job does. Handlers receive (payload, ctx) and must be IDEMPOTENT: the queue is at-least-once.
They raise RetryableError for temporary trouble and PermanentError when retrying cannot help; an error code never contains personal data.
Database work uses its own short session (a worker has no request)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Callable

from .. import models
from ..services import events as live, tracking, whatsapp
from ..services.notify import notify, notify_organization
from ..services.notify_rules import wants_whatsapp
from . import channels, jobqueue, rules
from .jobqueue import JobContext, PermanentError, RetryableError

logger = logging.getLogger(__name__)
HANDLERS: dict[str, Callable] = {}


def handler(name: str):
    def deco(fn):
        HANDLERS[name] = fn
        return fn
    return deco


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _session():
    from ..database import SessionLocal
    return SessionLocal()


# ---------------------------------------------------------------- outbound channels
HANDLERS["push.deliver"] = channels.push_deliver
HANDLERS["email.send"] = channels.email_send
HANDLERS["sms.send"] = channels.sms_send


@handler("whatsapp.send")
def whatsapp_send(payload: dict, ctx: JobContext, transport=None, env=None) -> None:
    env = os.environ if env is None else env
    db = _session()
    try:
        user = db.get(models.User, int(payload["user_id"]))
        if user is None or not user.is_active or not user.phone_e164 or user.phone_verified_at is None or not wants_whatsapp(user.notification_prefs, str(payload.get("kind", ""))):
            raise PermanentError("no_consent_or_phone")        # opt-in and a verified number are required; otherwise nothing is sent
        to = user.phone_e164
    finally:
        db.close()
    r = whatsapp.send_template(to, payload["purpose"], payload.get("params"), env, transport=transport)
    if r.status == "accepted":
        return
    raise (RetryableError(r.code) if r.status == "retry" else PermanentError(r.code or r.status))


# ---------------------------------------------------------------- scheduled housekeeping
@handler("location.purge")
def location_purge(payload: dict, ctx: JobContext) -> None:
    """Delete route-record points older than the retention period (LOCATION_RETENTION_DAYS, 1-365)."""
    db = _session()
    try:
        n = db.query(models.LocationHistory).filter(models.LocationHistory.recorded_at < tracking.retention_cutoff(_now())).delete(synchronize_session=False)
        db.commit()
        if n:
            logger.info("Deleted %s location history points past retention", n)
    finally:
        db.close()


@handler("otp.purge")
def otp_purge(payload: dict, ctx: JobContext) -> None:
    db = _session()
    try:
        cut = rules.otp_cutoff(_now())
        db.query(models.OtpChallenge).filter(models.OtpChallenge.expires_at < cut).delete(synchronize_session=False)
        db.query(models.PasswordResetToken).filter(models.PasswordResetToken.expires_at < cut).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


@handler("tracking.stale_scan")
def tracking_stale_scan(payload: dict, ctx: JobContext) -> None:
    """Expire sessions past their time limit (erasing the shared position) and tell viewers ONCE when a live position has gone quiet."""
    db = _session()
    try:
        now = _now()
        rows = []
        for sess, loc in (db.query(models.TrackingSession, models.DeliveryLocation)
                          .outerjoin(models.DeliveryLocation, models.DeliveryLocation.task_id == models.TrackingSession.task_id)
                          .filter(models.TrackingSession.status == "active").all()):
            rows.append({"session_id": sess.id, "task_id": sess.task_id, "expires_at": sess.expires_at, "started_at": sess.consented_at,
                         "last_fix_at": getattr(loc, "recorded_at", None), "stale_notified_at": sess.stale_notified_at})
        for act in rules.stale_actions(rows, now, tracking.stale_after_seconds()):
            sess = db.get(models.TrackingSession, act["session_id"]); task = db.get(models.DeliveryTask, act["task_id"])
            if sess is None or task is None or sess.status != "active":
                continue
            viewers = live.audience(orgs=[task.org_id], donors=[task.donor_id], roles=["admin"])
            mine = live.audience(volunteers=[task.volunteer_id])
            if act["action"] == "expire":
                sess.status, sess.stopped_at = "expired", now
                loc = db.query(models.DeliveryLocation).filter(models.DeliveryLocation.task_id == task.id).first()
                if loc is not None:
                    loc.stopped_at, loc.latitude, loc.longitude, loc.accuracy_m, loc.recorded_at = now, None, None, None, None
                state = "stopped"
            else:
                sess.stale_notified_at = now
                state = "stale"
            live.publish_after_commit(db, "delivery.tracking", {"task_id": task.id, "state": state}, viewers)
            live.publish_after_commit(db, "delivery.tracking", {"task_id": task.id, "state": state}, mine)
        db.commit()
    finally:
        db.close()


@handler("delivery.scan")
def delivery_scan(payload: dict, ctx: JobContext) -> None:
    """Find deliveries needing a reminder and enqueue ONE job per delivery per day (the idempotency key makes re-scans harmless)."""
    db = _session()
    try:
        now = _now()
        rows = [{"id": t.id, "status": t.status, "delivered_at": t.delivered_at, "in_transit_at": t.in_transit_at}
                for t in db.query(models.DeliveryTask).filter(models.DeliveryTask.status.in_(("delivered", "in_transit"))).all()]
        for d in rules.receipt_reminders(rows, now):
            jobqueue.enqueue("delivery.remind", {"task_id": d["id"], "kind": "receipt"}, key=rules.reminder_key("receipt", d["id"], now))
        for d in rules.overdue_transits(rows, now):
            jobqueue.enqueue("delivery.remind", {"task_id": d["id"], "kind": "overdue"}, key=rules.reminder_key("overdue", d["id"], now))
    finally:
        db.close()


@handler("delivery.remind")
def delivery_remind(payload: dict, ctx: JobContext) -> None:
    db = _session()
    try:
        task = db.get(models.DeliveryTask, int(payload["task_id"]))
        if task is None:
            return
        title = (task.item_description or f"Delivery #{task.id}")[:80]
        if payload["kind"] == "receipt" and task.status == "delivered":
            notify_organization(db, task.org_id, "donation", f"Please confirm what you received: {title}", "The delivery was marked delivered. Confirm the quantity you received.", "/deliveries")
        elif payload["kind"] == "overdue" and task.status == "in_transit":
            for admin in db.query(models.User).filter(models.User.role == "admin", models.User.is_active.is_(True)).all():
                notify(db, admin.id, "admin", f"Delivery running late: {title}", "A delivery has been in transit for several hours.", "/map")
            live.publish_after_commit(db, "risk.alert", {"task_id": task.id, "kind": "delayed", "severity": "medium"}, live.audience(roles=["admin"]))
        db.commit()
    finally:
        db.close()


@handler("payments.reconcile")
def payments_reconcile(payload: dict, ctx: JobContext, transport=None, env=None) -> None:
    """Orders still 'created' after 15 minutes: ask Razorpay what happened (a webhook may have been missed). Only a CAPTURED payment whose
    amount equals the amount we set moves an order forward; anything else is left alone for a human to look at."""
    from datetime import timedelta
    from ..services import payments
    from ..services.maps_http import MapsError
    env = os.environ if env is None else env
    if not payments.enabled(env):
        return
    db = _session()
    try:
        now = _now()
        for t in db.query(models.PaymentTransaction).filter(models.PaymentTransaction.status == "created", models.PaymentTransaction.created_at < now - timedelta(minutes=15),
                                                          models.PaymentTransaction.created_at > now - timedelta(days=7)).limit(50).all():
            try:
                found = payments.fetch_order_payments(t.razorpay_order_id, env, transport)
            except MapsError as e:
                if e.code in ("unavailable",):
                    raise RetryableError("razorpay_unavailable") from None
                continue
            paid = [p for p in found if p["status"] == "captured" and p["amount"] == t.amount_paise]
            if paid and not t.razorpay_payment_id:
                t.razorpay_payment_id, t.status, t.updated_at = paid[0]["id"], payments.next_status(t.status, "payment.captured"), now
        db.commit()
    finally:
        db.close()
