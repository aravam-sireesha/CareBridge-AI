"""Phase 5 through the real database: scheduled handlers, the e-mail/push channels, and Razorpay endpoints. Needs FastAPI + SQLAlchemy.
Run with:  python -m pytest tests/test_phase5_api.py -q"""
import hashlib
import hmac
import json
from datetime import timedelta

import pytest

from app import models
from app.jobs import handlers, jobqueue as q
from app.jobs.jobqueue import JobContext, PermanentError
from app.routers import payments as pay_router
from app.services import events as live, payments, push_dispatch, tracking, webpush
from app.services.webpush import SendResult
from test_deliveries_api import _put_fix, _to_transit, do, env, journey_to  # noqa: F401  (env is a fixture)

VOL, ORG, DONOR, ADMIN, OUT = "vol@x.org", "org@x.org", "donor@x.org", "admin@x.org", "donor2@x.org"
CTX, FINAL = JobContext("j", 1, 5), JobContext("j", 5, 5)
SECRET, WH_SECRET = "key_secret_test", "whsec_test"


def user(db, email):
    return db.query(models.User).filter_by(email=email).one()


@pytest.fixture
def worker_db(env, monkeypatch):
    """Handlers open their own session; point them at the test database and keep jobs in memory (no inline execution)."""
    client, db, h, ids = env
    monkeypatch.setattr(handlers, "_session", lambda: db)
    monkeypatch.setenv("JOBS_INLINE", "false"); monkeypatch.delenv("REDIS_URL", raising=False); q.reset_for_tests(); q.job_log = None
    yield env
    q.reset_for_tests()


def start(client, h, tid, retain=False):
    client.post(f"/deliveries/{tid}/tracking/start", headers=h(VOL), json={"retain_history": retain})
    return _put_fix(client, h, VOL, tid, seq=0)


# ---------------------------------------------------------------- retention
def test_location_purge_deletes_only_points_past_retention(worker_db):
    client, db, h, ids = worker_db
    tid = _to_transit(client, h, ids); start(client, h, tid, retain=True)
    sid = db.query(models.TrackingSession).one().id
    old = models.LocationHistory(session_id=sid, task_id=tid, seq=500, latitude=17.4, longitude=78.4, recorded_at=tracking_now() - timedelta(days=tracking.retention_days() + 1), flagged=False)
    db.add(old); db.commit()
    assert db.query(models.LocationHistory).count() == 2
    handlers.location_purge({}, CTX)
    assert [p.seq for p in db.query(models.LocationHistory).all()] == [0]                   # the fresh point stays


def tracking_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------- stale GPS and expiry
def kinds(state):
    return [e for e in live._ring if e.type == "delivery.tracking" and e.payload["state"] == state]


def test_a_quiet_session_is_announced_stale_exactly_once(worker_db):
    client, db, h, ids = worker_db
    tid = _to_transit(client, h, ids); start(client, h, tid)
    row = db.query(models.DeliveryLocation).one(); row.recorded_at = row.recorded_at - timedelta(seconds=tracking.stale_after_seconds() + 60); db.commit()
    handlers.tracking_stale_scan({}, CTX)
    assert db.query(models.TrackingSession).one().stale_notified_at is not None and len(kinds("stale")) == 2           # viewers + the volunteer
    handlers.tracking_stale_scan({}, CTX)
    assert len(kinds("stale")) == 2                                                                              # not repeated every minute


def test_a_fresh_fix_re_arms_the_stale_notice(worker_db):
    client, db, h, ids = worker_db
    tid = _to_transit(client, h, ids); start(client, h, tid)
    row = db.query(models.DeliveryLocation).one(); row.recorded_at = row.recorded_at - timedelta(seconds=600); db.commit()
    handlers.tracking_stale_scan({}, CTX)
    row = db.query(models.DeliveryLocation).one(); row.recorded_at = row.recorded_at - timedelta(seconds=10); db.commit()
    _put_fix(client, h, VOL, tid, seq=1)
    assert db.query(models.TrackingSession).one().stale_notified_at is None


def test_an_expired_session_is_stopped_and_the_position_erased(worker_db):
    client, db, h, ids = worker_db
    tid = _to_transit(client, h, ids); start(client, h, tid)
    s = db.query(models.TrackingSession).one(); s.expires_at = tracking_now() - timedelta(minutes=1); db.commit()
    handlers.tracking_stale_scan({}, CTX)
    db.expire_all()
    assert db.query(models.TrackingSession).one().status == "expired"
    loc = db.query(models.DeliveryLocation).one()
    assert loc.latitude is None and loc.stopped_at is not None and kinds("stopped")


def test_a_healthy_session_is_left_alone(worker_db):
    client, db, h, ids = worker_db
    tid = _to_transit(client, h, ids); start(client, h, tid)
    before = len(live._ring)
    handlers.tracking_stale_scan({}, CTX)
    assert len(live._ring) == before and db.query(models.TrackingSession).one().status == "active"


# ---------------------------------------------------------------- reminders
def deliver(client, h, ids):
    tid = _to_transit(client, h, ids)
    assert do(client, h, VOL, tid, "deliver", note="Handed to the warden").status_code == 200
    return tid


def test_the_scan_enqueues_one_reminder_per_delivery_per_day(worker_db):
    client, db, h, ids = worker_db
    tid = deliver(client, h, ids)
    t = db.get(models.DeliveryTask, tid); t.delivered_at = tracking_now() - timedelta(hours=30); db.commit()
    handlers.delivery_scan({}, CTX); handlers.delivery_scan({}, CTX)
    assert q._memory.stats()["ready"] == 1 and list(q._memory.ready.values())[0][1].payload == {"task_id": tid, "kind": "receipt"}


def test_a_receipt_reminder_notifies_the_receiving_organization_only(worker_db):
    client, db, h, ids = worker_db
    tid = deliver(client, h, ids)
    handlers.delivery_remind({"task_id": tid, "kind": "receipt"}, CTX)
    got = db.query(models.Notification).filter(models.Notification.title.like("Please confirm what you received%")).all()
    assert got and {n.user_id for n in got} == {user(db, ORG).id}


def test_an_overdue_reminder_alerts_administrators_and_emits_a_risk_alert(worker_db):
    client, db, h, ids = worker_db
    tid = _to_transit(client, h, ids)
    handlers.delivery_remind({"task_id": tid, "kind": "overdue"}, CTX)
    assert db.query(models.Notification).filter_by(user_id=user(db, ADMIN).id, kind="admin").count() == 1
    alert = [e for e in live._ring if e.type == "risk.alert"]
    assert alert and alert[0].payload["kind"] == "delayed" and alert[0].audience.roles == frozenset({"admin"})


def test_a_reminder_for_a_delivery_that_has_moved_on_sends_nothing(worker_db):
    client, db, h, ids = worker_db
    tid = _to_transit(client, h, ids)
    handlers.delivery_remind({"task_id": tid, "kind": "receipt"}, CTX)                      # still in transit: not "delivered"
    handlers.delivery_remind({"task_id": 99999, "kind": "overdue"}, CTX)                    # no such delivery: harmless
    assert db.query(models.Notification).filter(models.Notification.title.like("Please confirm%")).count() == 0


# ---------------------------------------------------------------- e-mail channel
def email_jobs():
    return [j for _, j in q._memory.ready.values() if j.name == "email.send"]


def opt_in(db, email, **prefs):
    u = user(db, email); u.notification_prefs = {"email": True, **prefs}
    from datetime import datetime
    u.email_verified_at = u.email_verified_at or datetime(2026, 1, 1); db.commit()


def test_an_opted_in_verified_person_gets_an_email_job_after_commit(worker_db, monkeypatch):
    client, db, h, ids = worker_db
    monkeypatch.setenv("EMAIL_NOTIFICATIONS_ENABLED", "true"); monkeypatch.setenv("APP_BASE_URL", "https://app.example.org")
    opt_in(db, VOL)
    journey_to(client, h, ids, "offer")
    jobs = email_jobs()
    assert jobs and all(j.payload["to"] == VOL and j.payload["template"] == "generic" and j.payload["base_url"] == "https://app.example.org" for j in jobs)


@pytest.mark.parametrize("setup", ["flag_off", "not_opted_in", "unverified", "category_muted", "inactive"])
def test_no_email_job_unless_every_condition_holds(worker_db, monkeypatch, setup):
    client, db, h, ids = worker_db
    monkeypatch.setenv("EMAIL_NOTIFICATIONS_ENABLED", "false" if setup == "flag_off" else "true")
    opt_in(db, VOL)
    u = user(db, VOL)
    if setup == "not_opted_in": u.notification_prefs = {"email": False}
    if setup == "unverified": u.email_verified_at = None
    if setup == "category_muted": u.notification_prefs = {"email": True, "donation": False, "volunteer": False, "need": False}
    if setup == "inactive": u.is_active = False
    db.commit()
    journey_to(client, h, ids, "offer")
    assert email_jobs() == []


# ---------------------------------------------------------------- push retry semantics
KEYS = {"p256dh": "B" + "x" * 86, "auth": "a" * 22}


def device(db, email):
    row = models.PushSubscription(user_id=user(db, email).id, endpoint_hash=webpush.endpoint_hash("https://fcm.googleapis.com/x"), endpoint="https://fcm.googleapis.com/x", failure_count=0, **KEYS)
    ev = models.NotificationEvent(user_id=row.user_id, channel="push", kind="donation", title="t", link="/x", status="queued", attempts=0, accepted_count=0)
    db.add_all([row, ev]); db.commit()
    return row.id, ev.id


def run(db, eid, result, final):
    out = push_dispatch.deliver(eid, session_factory=lambda: db, send=lambda *a: result, env={}, final=final)
    db.expire_all(); return out


def test_a_temporary_push_failure_leaves_the_notification_queued_for_a_retry(worker_db):
    client, db, h, ids = worker_db
    sid, eid = device(db, ORG)
    assert run(db, eid, SendResult("retry", "503"), final=False) == "retry"
    assert db.get(models.NotificationEvent, eid).status == "queued" and db.get(models.PushSubscription, sid).failure_count == 0       # nothing recorded yet


def test_the_final_attempt_records_the_failure(worker_db):
    client, db, h, ids = worker_db
    sid, eid = device(db, ORG)
    assert run(db, eid, SendResult("retry", "503"), final=True) == "done"
    ev = db.get(models.NotificationEvent, eid)
    assert (ev.status, ev.error_code, ev.attempts) == ("failed", "503", 1) and db.get(models.PushSubscription, sid).failure_count == 1


def test_a_success_on_a_retry_is_recorded_and_a_gone_device_does_not_trigger_a_retry(worker_db):
    client, db, h, ids = worker_db
    sid, eid = device(db, ORG)
    assert run(db, eid, SendResult("accepted", "201"), final=False) == "done" and db.get(models.NotificationEvent, eid).status == "accepted_by_provider"
    row = db.get(models.PushSubscription, sid); ev = models.NotificationEvent(user_id=row.user_id, channel="push", kind="x", status="queued", attempts=0, accepted_count=0); db.add(ev); db.commit()
    assert run(db, ev.id, SendResult("gone", "410"), final=False) == "done" and db.query(models.PushSubscription).count() == 0


# ---------------------------------------------------------------- WhatsApp consent
WA_ENV = {"WHATSAPP_ENABLED": "true", "WHATSAPP_PHONE_NUMBER_ID": "123456", "WHATSAPP_ACCESS_TOKEN": "tok", "WHATSAPP_TEMPLATE_DELIVERY_UPDATE": "delivery_update_v1"}


class WaFake:
    def __init__(self): self.calls = []
    def __call__(self, method, url, **kw): self.calls.append(kw["json"]); return 200, {"messages": [{"id": "wamid"}]}


def test_whatsapp_needs_opt_in_and_a_verified_number(worker_db):
    client, db, h, ids = worker_db
    from datetime import datetime
    u = user(db, VOL); payload = {"user_id": u.id, "purpose": "delivery_update", "params": ["Rice"], "kind": "volunteer"}; fake = WaFake()
    for prefs, phone, verified in (({}, "+919999999999", datetime(2026, 1, 1)), ({"whatsapp": True}, None, datetime(2026, 1, 1)), ({"whatsapp": True}, "+919999999999", None), ({"whatsapp": True, "volunteer": False}, "+919999999999", datetime(2026, 1, 1))):
        u.notification_prefs, u.phone_e164, u.phone_verified_at = prefs, phone, verified; db.commit()
        with pytest.raises(PermanentError) as e:
            handlers.whatsapp_send(payload, CTX, transport=fake, env=WA_ENV)
        assert e.value.code == "no_consent_or_phone"
    assert fake.calls == []
    u.notification_prefs, u.phone_e164, u.phone_verified_at = {"whatsapp": True}, "+919999999999", datetime(2026, 1, 1); db.commit()
    handlers.whatsapp_send(payload, CTX, transport=fake, env=WA_ENV)
    assert fake.calls and fake.calls[0]["template"]["name"] == "delivery_update_v1"


# ---------------------------------------------------------------- Razorpay endpoints
PAY_ENV = {"PAYMENTS_ENABLED": "true", "RAZORPAY_KEY_ID": "rzp_test_abc", "RAZORPAY_KEY_SECRET": SECRET, "RAZORPAY_WEBHOOK_SECRET": WH_SECRET}
ORDER, PAYID = "order_Abc12345678", "pay_Def12345678"


@pytest.fixture
def razorpay(env, monkeypatch):
    for k, v in PAY_ENV.items():
        monkeypatch.setenv(k, v)
    calls = []
    def fake_order(amount, receipt, notes, env_, transport=None):
        calls.append((amount, receipt, notes)); return {"order_id": ORDER, "amount_paise": amount, "currency": "INR"}
    monkeypatch.setattr(pay_router.payments, "create_order", fake_order)
    client, db, h, ids = env
    org = user(db, ORG).organization_id; o = db.get(models.Organization, org); o.verified = True; db.commit()
    return env, org, calls


def order(client, h, who, org, amount=500):
    return client.post("/payments/orders", headers=h(who), json={"amount_rupees": amount, "organization_id": org})


def sign(order_id, pid): return hmac.new(SECRET.encode(), f"{order_id}|{pid}".encode(), hashlib.sha256).hexdigest()
def wh(body: dict, secret=WH_SECRET): raw = json.dumps(body).encode(); return raw, hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
def event(kind, amount=50000, order_id=ORDER, pid=PAYID): return {"event": kind, "payload": {"payment": {"entity": {"id": pid, "order_id": order_id, "amount": amount}}}}
def post_wh(client, raw, sig, eid="evt_1"): return client.post("/payments/webhook", content=raw, headers={"x-razorpay-signature": sig, "x-razorpay-event-id": eid, "content-type": "application/json"})


def test_payments_are_off_by_default(env, monkeypatch):
    client, db, h, ids = env
    for k in PAY_ENV: monkeypatch.delenv(k, raising=False)
    assert client.get("/payments/config", headers=h(DONOR)).json() == {"enabled": False, "key_id": None}
    assert order(client, h, DONOR, user(db, ORG).organization_id).status_code == 503
    assert client.post("/payments/webhook", content=b"{}").status_code == 503


def test_only_donors_can_start_a_payment_for_a_verified_organization_with_a_valid_amount(razorpay):
    (client, db, h, ids), org, calls = razorpay
    assert order(client, h, ORG, org).status_code == 403 and order(client, h, VOL, org).status_code == 403
    assert order(client, h, DONOR, 999999).status_code == 404
    db.get(models.Organization, org).verified = False; db.commit()
    assert order(client, h, DONOR, org).status_code == 404
    db.get(models.Organization, org).verified = True; db.commit()
    for bad in (0, -5, 0.5, 10.123, 50001):
        assert order(client, h, DONOR, org, bad).status_code == 422
    assert calls == []                                                                  # nothing reached Razorpay for any of those


def test_the_server_fixes_the_amount_and_records_the_order(razorpay):
    (client, db, h, ids), org, calls = razorpay
    r = order(client, h, DONOR, org, 500)
    assert r.status_code == 200 and calls[0][0] == 50000 and r.json()["amount_paise"] == 50000 and r.json()["key_id"] == "rzp_test_abc" and "key_secret" not in r.text
    t = db.query(models.PaymentTransaction).one()
    assert (t.status, t.amount_paise, t.user_id) == ("created", 50000, user(db, DONOR).id)


def test_verification_needs_a_genuine_signature_and_the_buyers_own_order(razorpay):
    (client, db, h, ids), org, _ = razorpay
    order(client, h, DONOR, org)
    body = lambda sig, pid=PAYID: {"razorpay_order_id": ORDER, "razorpay_payment_id": pid, "razorpay_signature": sig}   # noqa: E731
    assert client.post("/payments/verify", headers=h(DONOR), json=body("0" * 64)).status_code == 400
    assert db.query(models.PaymentTransaction).one().status == "created"
    assert db.query(models.AuditLog).filter_by(action="payment.signature_rejected").count() == 1
    assert client.post("/payments/verify", headers=h(OUT), json=body(sign(ORDER, PAYID))).status_code == 404            # someone else's order
    ok = client.post("/payments/verify", headers=h(DONOR), json=body(sign(ORDER, PAYID)))
    assert ok.status_code == 200 and ok.json()["status"] == "captured"
    assert client.post("/payments/verify", headers=h(DONOR), json=body(sign(ORDER, PAYID))).status_code == 200            # repeating is harmless
    assert client.post("/payments/verify", headers=h(DONOR), json=body(sign(ORDER, "pay_Other1234567", ), "pay_Other1234567")).status_code == 409


def test_the_webhook_trusts_only_a_correct_signature_over_the_raw_body(razorpay):
    (client, db, h, ids), org, _ = razorpay
    order(client, h, DONOR, org)
    raw, sig = wh(event("payment.captured"))
    assert post_wh(client, raw, "0" * 64).status_code == 400 and post_wh(client, raw, "").status_code == 400
    assert post_wh(client, raw.replace(b"50000", b"50001"), sig).status_code == 400
    assert post_wh(client, raw, wh(event("payment.captured"), "wrong")[1]).status_code == 400
    assert db.query(models.PaymentTransaction).one().status == "created" and db.query(models.PaymentEvent).count() == 0
    assert post_wh(client, raw, sig).status_code == 200
    db.expire_all(); assert db.query(models.PaymentTransaction).one().status == "captured"


def test_a_redelivered_webhook_changes_nothing(razorpay):
    (client, db, h, ids), org, _ = razorpay
    order(client, h, DONOR, org)
    raw, sig = wh(event("payment.captured"))
    assert post_wh(client, raw, sig, "evt_1").json() == {"ok": True}
    assert post_wh(client, raw, sig, "evt_1").json() == {"ok": True, "duplicate": True}
    assert db.query(models.PaymentEvent).count() == 1


def test_late_or_wrong_events_cannot_undo_or_corrupt_a_payment(razorpay):
    (client, db, h, ids), org, _ = razorpay
    order(client, h, DONOR, org)
    post_wh(client, *wh(event("payment.captured")), "evt_a")
    post_wh(client, *wh(event("payment.failed")), "evt_b")                              # a late failure after capture
    db.expire_all(); assert db.query(models.PaymentTransaction).one().status == "captured"
    post_wh(client, *wh(event("refund.processed")), "evt_c")
    post_wh(client, *wh(event("payment.captured")), "evt_d")
    db.expire_all(); assert db.query(models.PaymentTransaction).one().status == "refunded"


def test_a_webhook_with_a_different_amount_never_marks_the_payment(razorpay):
    (client, db, h, ids), org, _ = razorpay
    order(client, h, DONOR, org)
    assert post_wh(client, *wh(event("payment.captured", amount=100)), "evt_x").status_code == 200
    db.expire_all(); assert db.query(models.PaymentTransaction).one().status == "created"


def test_unknown_orders_and_unreadable_events_are_acknowledged_so_razorpay_stops_retrying(razorpay):
    (client, db, h, ids), org, _ = razorpay
    assert post_wh(client, *wh(event("payment.captured", order_id="order_Nope1234567")), "evt_u").status_code == 200
    raw = b"not json"; sig = hmac.new(WH_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert post_wh(client, raw, sig, "evt_v").json()["ignored"] == "unreadable"


def test_receipts_exist_only_for_confirmed_payments_and_only_for_their_owner_or_an_admin(razorpay):
    (client, db, h, ids), org, _ = razorpay
    order(client, h, DONOR, org); pid = db.query(models.PaymentTransaction).one().id
    assert client.get(f"/payments/{pid}/receipt", headers=h(DONOR)).status_code == 409                    # not confirmed yet
    post_wh(client, *wh(event("payment.captured")), "evt_r")
    r = client.get(f"/payments/{pid}/receipt", headers=h(DONOR))
    assert r.status_code == 200 and r.json()["amount_rupees"] == 500 and "NOT a tax" in r.json()["notice"] and r.json()["payment_reference"] == "\u2026345678"                 # only the last six characters of the payment id
    assert client.get(f"/payments/{pid}/receipt", headers=h(ADMIN)).status_code == 200
    assert client.get(f"/payments/{pid}/receipt", headers=h(OUT)).status_code == 404 and client.get(f"/payments/{pid}/receipt", headers=h(ORG)).status_code == 404


def test_reconciliation_marks_an_order_only_for_a_captured_payment_of_the_exact_amount(razorpay, monkeypatch):
    (client, db, h, ids), org, _ = razorpay
    order(client, h, DONOR, org)
    t = db.query(models.PaymentTransaction).one(); t.created_at = tracking_now() - timedelta(hours=1); db.commit()
    monkeypatch.setattr(handlers, "_session", lambda: db)
    from app.services import payments as svc
    monkeypatch.setattr(svc, "fetch_order_payments", lambda order_id, env_, transport=None: [{"id": PAYID, "status": "captured", "amount": 99}])
    handlers.payments_reconcile({}, CTX, env=PAY_ENV); db.expire_all()
    assert db.query(models.PaymentTransaction).one().status == "created"                                      # wrong amount: left for a human
    monkeypatch.setattr(svc, "fetch_order_payments", lambda order_id, env_, transport=None: [{"id": PAYID, "status": "captured", "amount": 50000}])
    handlers.payments_reconcile({}, CTX, env=PAY_ENV); db.expire_all()
    t = db.query(models.PaymentTransaction).one(); assert (t.status, t.razorpay_payment_id) == ("captured", PAYID)
