"""Scheduled-job rules, scheduler, channel handlers (push/email/SMS), the WhatsApp adapter, the worker loop, and a source-level check that every
job name that is enqueued or scheduled has a handler."""
import ast
import pathlib
import re
import threading
from datetime import datetime, timedelta

import pytest

from app.jobs import channels, jobqueue as q, rules
from app.jobs.jobqueue import JobContext, PermanentError, RetryableError
from app.jobs.scheduler import SCHEDULE, Periodic, Scheduler, bucket
from app.services import mailer, whatsapp
from app.services.mailer import MailResult
from app.services.sms import SmsResult

NOW = datetime(2026, 11, 9, 12, 0, 0)
APP = pathlib.Path(__file__).resolve().parent.parent / "app"
CTX = JobContext("j1", 1, 5)
FINAL = JobContext("j1", 5, 5)


# ---------------------------------------------------------------- every job name has a handler
def test_every_job_that_is_enqueued_or_scheduled_has_a_registered_handler():
    tree = ast.parse((APP / "jobs" / "handlers.py").read_text())
    registered = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and getattr(d.func, "id", "") == "handler" and d.args:
                    registered.add(d.args[0].value)
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Subscript) and getattr(node.targets[0].value, "id", "") == "HANDLERS" and isinstance(node.targets[0].slice, ast.Constant):
            registered.add(node.targets[0].slice.value)
    used = set()
    for path in APP.rglob("*.py"):
        for m in re.finditer(r"enqueue\(\s*\"([a-z_.]+)\"", path.read_text()):
            used.add(m.group(1))
    used |= {p.job for p in SCHEDULE}
    assert registered >= {"push.deliver", "email.send", "sms.send", "whatsapp.send", "location.purge", "otp.purge", "tracking.stale_scan", "delivery.scan", "delivery.remind", "payments.reconcile"}
    assert used - registered == set(), f"jobs enqueued/scheduled with no handler: {used - registered}"


# ---------------------------------------------------------------- stale GPS and expiry
def sess(**kw):
    return {"session_id": 1, "task_id": 7, "expires_at": NOW + timedelta(hours=5), "started_at": NOW - timedelta(minutes=30), "last_fix_at": NOW - timedelta(seconds=30), "stale_notified_at": None, **kw}


def test_a_fresh_session_needs_nothing():
    assert rules.stale_actions([sess()], NOW, 120) == []


def test_a_quiet_session_is_flagged_stale_once():
    quiet = sess(last_fix_at=NOW - timedelta(seconds=300))
    assert rules.stale_actions([quiet], NOW, 120) == [{"session_id": 1, "task_id": 7, "action": "stale"}]
    assert rules.stale_actions([{**quiet, "stale_notified_at": NOW - timedelta(seconds=60)}], NOW, 120) == []           # already told: no repeats every minute


def test_a_session_past_its_time_limit_is_expired_even_if_it_is_also_quiet():
    out = rules.stale_actions([sess(expires_at=NOW - timedelta(seconds=1), last_fix_at=NOW - timedelta(hours=2))], NOW, 120)
    assert out == [{"session_id": 1, "task_id": 7, "action": "expire"}]
    assert rules.stale_actions([sess(expires_at=NOW)], NOW, 120)[0]["action"] == "expire"                               # exactly at the limit counts


def test_a_session_that_never_reported_is_not_called_stale():
    assert rules.stale_actions([sess(last_fix_at=None, started_at=NOW - timedelta(hours=1))], NOW, 120) == []            # viewers already see "waiting for first position"


def test_the_stale_threshold_is_respected():
    s = sess(last_fix_at=NOW - timedelta(seconds=100))
    assert rules.stale_actions([s], NOW, 120) == [] and rules.stale_actions([s], NOW, 60)[0]["action"] == "stale"


# ---------------------------------------------------------------- reminders
def d(**kw):
    return {"id": 1, "status": "delivered", "delivered_at": NOW - timedelta(hours=30), "in_transit_at": None, **kw}


def test_receipt_reminders_only_for_old_unconfirmed_deliveries():
    rows = [d(id=1), d(id=2, delivered_at=NOW - timedelta(hours=3)), d(id=3, status="receipt_confirmed"), d(id=4, delivered_at=None), d(id=5, delivered_at=NOW - timedelta(hours=24))]
    assert [x["id"] for x in rules.receipt_reminders(rows, NOW)] == [1, 5]


def test_overdue_transits_use_the_same_six_hour_threshold_as_the_map():
    rows = [d(id=1, status="in_transit", in_transit_at=NOW - timedelta(hours=7)), d(id=2, status="in_transit", in_transit_at=NOW - timedelta(hours=2)), d(id=3, status="in_transit", in_transit_at=None), d(id=4, status="delivered")]
    assert [x["id"] for x in rules.overdue_transits(rows, NOW)] == [1]
    assert rules.DELAYED_AFTER_HOURS == 6


def test_reminder_keys_make_a_second_scan_the_same_day_a_no_op_but_not_the_next_day():
    a = rules.reminder_key("receipt", 7, NOW); b = rules.reminder_key("receipt", 7, NOW + timedelta(hours=5))
    assert a == b == "receipt:7:20261109" and rules.reminder_key("receipt", 7, NOW + timedelta(days=1)) != a and rules.reminder_key("overdue", 7, NOW) != a
    be = q.MemoryBackend()
    t = NOW.timestamp()
    assert be.put(q.Job("a", "delivery.remind", {}, 3, key=a), t, t) and not be.put(q.Job("b", "delivery.remind", {}, 3, key=b), t, t)


def test_one_time_codes_are_kept_a_day_after_expiry():
    assert rules.otp_cutoff(NOW) == NOW - timedelta(days=1)


# ---------------------------------------------------------------- e-mail eligibility
def user(**kw):
    return {"is_active": True, "email": "a@b.org", "email_verified_at": NOW, **kw}


def test_only_active_verified_addresses_are_emailed():
    assert rules.email_job(user(), "Delivery #5", "/deliveries", "https://app.example.org") == {"to": "a@b.org", "template": "generic", "ctx": {"title": "Delivery #5"}, "link": "/deliveries", "base_url": "https://app.example.org"}
    for bad in (user(is_active=False), user(email=None), user(email=""), user(email_verified_at=None)):
        assert rules.email_job(bad, "t", None, "") is None
    assert len(rules.email_job(user(), "x" * 500, None, "")["ctx"]["title"]) == 120


# ---------------------------------------------------------------- scheduler
def test_the_scheduler_enqueues_each_period_once_with_a_bucketed_key():
    sent = []
    s = Scheduler(schedule=(Periodic("a", 60), Periodic("b", 3600)), enqueue=lambda name, payload, key, now: sent.append((name, key)) or "id")
    t0 = 1_800_000_000
    assert s.tick(t0) == ["a", "b"]
    assert s.tick(t0 + 1) == [] and s.tick(t0 + 30) == []                              # same period: nothing more
    assert s.tick(t0 + 61) == ["a"]                                                    # a new minute: only the minute job
    assert sent[0] == ("a", f"sched:a:{bucket(t0, 60)}") and sent[1] == ("b", f"sched:b:{bucket(t0, 3600)}")


def test_two_workers_cannot_double_schedule_a_period(monkeypatch):
    monkeypatch.setenv("JOBS_INLINE", "false"); q.reset_for_tests(); q.job_log = None
    w1, w2 = Scheduler(schedule=(Periodic("x", 60),)), Scheduler(schedule=(Periodic("x", 60),))
    t = 1_800_000_000
    assert w1.tick(t) == ["x"] and w2.tick(t) == []                                    # the shared idempotency key stops the second worker
    assert q._memory.stats()["ready"] == 1
    q.reset_for_tests()


def test_the_default_schedule_covers_the_required_background_work():
    names = {p.job for p in SCHEDULE}
    assert {"tracking.stale_scan", "delivery.scan", "otp.purge", "location.purge", "payments.reconcile"} <= names
    assert all(p.every >= 60 for p in SCHEDULE)


# ---------------------------------------------------------------- channel handlers
def test_push_job_retries_only_when_the_dispatcher_says_so():
    seen = []
    channels.push_deliver({"event_id": "7"}, CTX, deliver=lambda eid, final: seen.append((eid, final)) or "done")
    assert seen == [(7, False)]
    with pytest.raises(RetryableError):
        channels.push_deliver({"event_id": 7}, CTX, deliver=lambda eid, final: "retry")
    channels.push_deliver({"event_id": 7}, FINAL, deliver=lambda eid, final: seen.append(final) or "done")
    assert seen[-1] is True                                                            # the last attempt tells the dispatcher to record the outcome


def test_email_job_sends_a_rendered_message_and_classifies_failures(monkeypatch):
    sent = []
    ok = lambda to, subject, text, html: sent.append((to, subject)) or MailResult(True, "accepted")  # noqa: E731
    payload = {"to": "a@b.org", "template": "generic", "ctx": {"title": "Delivery #5"}, "link": "/deliveries", "base_url": "https://app.example.org"}
    channels.email_send(payload, CTX, send=ok, configured=lambda: True)
    assert sent == [("a@b.org", "Delivery #5")]
    with pytest.raises(RetryableError):
        channels.email_send(payload, CTX, send=lambda *a: MailResult(False, "temporary_error", True), configured=lambda: True)
    with pytest.raises(PermanentError) as e:
        channels.email_send(payload, CTX, send=lambda *a: MailResult(False, "rejected", False), configured=lambda: True)
    assert e.value.code == "rejected"
    with pytest.raises(PermanentError):
        channels.email_send(payload, CTX, send=ok, configured=lambda: False)
    with pytest.raises(PermanentError) as e2:
        channels.email_send({**payload, "template": "nope"}, CTX, send=ok, configured=lambda: True)
    assert e2.value.code == "unknown_template"


def test_sms_job_refuses_free_text_where_the_provider_needs_a_registered_template(monkeypatch):
    class Twilio:
        def __init__(self, ok): self.ok, self.sent = ok, []
        def send(self, to, text): self.sent.append((to, text)); return SmsResult(self.ok, "sent")
    tw = Twilio(True); channels.sms_send({"to": "+919999999999", "text": "x" * 500}, CTX, provider=tw)
    assert len(tw.sent[0][1]) == 320
    with pytest.raises(RetryableError):
        channels.sms_send({"to": "+919999999999", "text": "hi"}, CTX, provider=Twilio(False))
    class Msg91: pass                                                                  # template-only provider
    with pytest.raises(PermanentError) as e:
        channels.sms_send({"to": "+919999999999", "text": "hi"}, CTX, provider=Msg91())
    assert e.value.code == "provider_requires_template"
    monkeypatch.setattr(channels.sms, "provider_from_env", lambda *a, **k: None)
    with pytest.raises(PermanentError) as e2:
        channels.sms_send({"to": "+919999999999", "text": "hi"}, CTX)
    assert e2.value.code == "sms_not_configured"


# ---------------------------------------------------------------- WhatsApp adapter
WA = {"WHATSAPP_ENABLED": "true", "WHATSAPP_PHONE_NUMBER_ID": "1234567890", "WHATSAPP_ACCESS_TOKEN": "tok", "WHATSAPP_TEMPLATE_DELIVERY_UPDATE": "delivery_update_v1"}


class Fake:
    def __init__(self, status=200, data=None): self.status, self.data, self.calls = status, data, []
    def __call__(self, method, url, **kw): self.calls.append((method, url, kw)); return self.status, self.data


def test_whatsapp_is_off_unless_fully_enabled():
    assert whatsapp.enabled(WA)
    for bad in ({}, {**WA, "WHATSAPP_ENABLED": "false"}, {**WA, "WHATSAPP_PHONE_NUMBER_ID": ""}, {**WA, "WHATSAPP_ACCESS_TOKEN": ""}):
        assert not whatsapp.enabled(bad)
    assert whatsapp.send_template("+919999999999", "delivery_update", ["a"], {}, transport=Fake()).status == "not_configured"


def test_a_template_message_is_built_from_the_approved_template_and_never_free_text():
    f = Fake(200, {"messages": [{"id": "wamid.x"}]})
    r = whatsapp.send_template("+91 98765 43210", "delivery_update", ["Rice", "Hope Home"], WA, transport=f)
    assert r.status == "accepted"
    method, url, kw = f.calls[0]
    assert url == "https://graph.facebook.com/v21.0/1234567890/messages" and kw["headers"]["Authorization"] == "Bearer tok"
    body = kw["json"]
    assert body["type"] == "template" and body["template"]["name"] == "delivery_update_v1" and body["to"].startswith("91") and "text" not in body
    assert [x["text"] for x in body["template"]["components"][0]["parameters"]] == ["Rice", "Hope Home"]


@pytest.mark.parametrize("purpose", ["otp", "login_code", "free_text", "", "../x"])
def test_otp_and_unknown_purposes_have_no_template_and_are_never_sent(purpose):
    f = Fake(200, {"messages": [{}]})
    r = whatsapp.send_template("+919999999999", purpose, ["x"], {**WA, "WHATSAPP_TEMPLATE_OTP": "otp_v1"}, transport=f)
    assert r.status == "invalid" and f.calls == []


@pytest.mark.parametrize("to,params", [("12345", ["a"]), ("98765 43210", ["a"]), ("", ["a"]), (None, ["a"]), ("+919999999999", "text"), ("+919999999999", [""]), ("+919999999999", ["a"] * 6), ("+919999999999", None)])
def test_bad_numbers_or_parameters_are_refused_before_sending(to, params):
    f = Fake(200, {"messages": [{}]})
    assert whatsapp.send_template(to, "delivery_update", params, WA, transport=f).status == "invalid" and f.calls == []


def test_parameters_are_flattened_and_truncated_for_whatsapp():
    assert whatsapp.clean_params(["line1\nline2\ttab", "x" * 200]) == ["line1 line2 tab", "x" * 60]


@pytest.mark.parametrize("status,data,expected", [
    (429, {}, "retry"), (503, {}, "retry"), (400, {"error": {"code": 131048}}, "retry"), (400, {"error": {"code": 80007}}, "retry"),
    (400, {"error": {"code": 131030}}, "failed"), (400, {"error": {"code": 132000}}, "failed"),            # not opted in / template mismatch: permanent
    (401, {"error": {"code": 190}}, "failed"), (200, {}, "failed"), (200, None, "failed"),
])
def test_meta_answers_are_classified_and_a_200_without_a_message_id_is_not_success(status, data, expected):
    assert whatsapp.send_template("+919999999999", "delivery_update", ["a"], WA, transport=Fake(status, data)).status == expected


def test_a_network_failure_is_retryable_and_the_token_never_appears_in_results():
    def down(*a, **k): raise whatsapp.maps_http.MapsError("unavailable", "x")
    r = whatsapp.send_template("+919999999999", "delivery_update", ["a"], WA, transport=down)
    assert r.status == "retry" and "tok" not in repr(r)
    r2 = whatsapp.send_template("+919999999999", "delivery_update", ["a"], WA, transport=Fake(401, {"error": {"code": 190, "message": "token tok expired"}}))
    assert "tok" not in repr(r2)


# ---------------------------------------------------------------- the worker loop
def test_the_worker_processes_jobs_until_told_to_stop(monkeypatch):
    from app import worker
    monkeypatch.setenv("JOBS_INLINE", "false"); q.reset_for_tests(); q.job_log = None
    done = []; stop = threading.Event()
    for i in range(3):
        q.enqueue("t", {"i": i})
    def handler(payload, ctx):
        done.append(payload["i"])
        if len(done) == 3: stop.set()
    worker.run(stop, concurrency=1, idle_seconds=0.01, scheduler=Scheduler(schedule=()), handlers={"t": handler})
    assert sorted(done) == [0, 1, 2]
    q.reset_for_tests()


def test_a_crashing_loop_iteration_does_not_kill_the_worker(monkeypatch):
    from app import worker
    monkeypatch.setenv("JOBS_INLINE", "false"); q.reset_for_tests(); q.job_log = None
    stop = threading.Event(); calls = {"n": 0}
    class Boom:
        def tick(self, now=None):
            calls["n"] += 1
            if calls["n"] == 1: raise RuntimeError("scheduler hiccup")
            if calls["n"] >= 3: stop.set()
            return []
    worker.run(stop, concurrency=1, idle_seconds=0.01, scheduler=Boom(), handlers={})
    assert calls["n"] >= 3
    q.reset_for_tests()


def test_the_worker_refuses_to_start_without_redis(monkeypatch):
    from app import worker
    from app.services import redis_client
    monkeypatch.delenv("REDIS_URL", raising=False); redis_client.reset_for_tests()
    assert worker.main() == 2
