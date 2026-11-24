"""Web Push through the real API and database, with a FAKE push service. Needs FastAPI + SQLAlchemy like the other API tests."""
import pytest

from app import models
from app.services import push_dispatch, webpush
from app.services.webpush import SendResult
from test_deliveries_api import env, journey_to  # noqa: F401  (env is a fixture)

VOL, ORG, DONOR, ADMIN = "vol@x.org", "org@x.org", "donor@x.org", "admin@x.org"
VAPID = {"VAPID_PUBLIC_KEY": "BPublicKeyForTests", "VAPID_PRIVATE_KEY": "private", "VAPID_SUBJECT": "mailto:admin@example.org"}
KEYS = {"p256dh": "B" + "x" * 86, "auth": "a" * 22}


@pytest.fixture
def vapid(monkeypatch):
    for k, v in VAPID.items():
        monkeypatch.setenv(k, v)


def sub(n=1, host="fcm.googleapis.com"):
    return {"endpoint": f"https://{host}/fcm/send/device-{n}-secret-token", "keys": KEYS, "user_agent": "TestBrowser/1"}


def uid(db, email):
    return db.query(models.User).filter_by(email=email).one().id


# ---------------------------------------------------------------- configuration and auth
def test_push_endpoints_require_sign_in(env):
    client, db, h, ids = env
    for method, path in (("get", "/push/config"), ("get", "/push/subscriptions"), ("get", "/push/events"), ("post", "/push/subscribe"), ("post", "/push/test")):
        assert getattr(client, method)(path).status_code == 401, path


def test_config_says_off_without_keys_and_never_leaks_the_private_key(env, monkeypatch):
    client, db, h, ids = env
    for k in VAPID:
        monkeypatch.delenv(k, raising=False)
    assert client.get("/push/config", headers=h(ORG)).json() == {"enabled": False, "public_key": None}
    assert client.post("/push/subscribe", json=sub(), headers=h(ORG)).status_code == 503
    for k, v in VAPID.items():
        monkeypatch.setenv(k, v)
    body = client.get("/push/config", headers=h(ORG)).json()
    assert body == {"enabled": True, "public_key": "BPublicKeyForTests"} and "private" not in str(body)


# ---------------------------------------------------------------- subscribing
def test_subscribing_stores_the_device_and_listing_never_returns_keys_or_the_endpoint(env, vapid):
    client, db, h, ids = env
    assert client.post("/push/subscribe", json=sub(), headers=h(ORG)).json()["subscribed"] is True
    row = db.query(models.PushSubscription).one()
    assert row.user_id == uid(db, ORG) and row.endpoint_hash == webpush.endpoint_hash(sub()["endpoint"])
    listed = client.get("/push/subscriptions", headers=h(ORG))
    text = listed.text
    assert listed.json()["devices"][0]["service"] == "fcm.googleapis.com" and "secret-token" not in text and KEYS["p256dh"] not in text and KEYS["auth"] not in text


@pytest.mark.parametrize("endpoint", ["https://169.254.169.254/latest/meta-data", "http://fcm.googleapis.com/x", "https://localhost/x", "https://evil.example/x",
                                      "https://fcm.googleapis.com@evil.example/x", "https://fcm.googleapis.com:8443/x", "file:///etc/passwd"])
def test_a_subscription_pointing_anywhere_but_a_push_service_is_refused_and_nothing_is_stored(env, vapid, endpoint):
    client, db, h, ids = env
    r = client.post("/push/subscribe", json={**sub(), "endpoint": endpoint}, headers=h(ORG))
    assert r.status_code == 422 and db.query(models.PushSubscription).count() == 0


def test_malformed_keys_are_refused(env, vapid):
    client, db, h, ids = env
    for keys in ({"p256dh": "short", "auth": KEYS["auth"]}, {"p256dh": KEYS["p256dh"], "auth": "!!"}, {}):
        assert client.post("/push/subscribe", json={**sub(), "keys": keys}, headers=h(ORG)).status_code == 422
    assert db.query(models.PushSubscription).count() == 0


def test_resubscribing_the_same_device_updates_it_instead_of_duplicating(env, vapid):
    client, db, h, ids = env
    client.post("/push/subscribe", json=sub(), headers=h(ORG)); client.post("/push/subscribe", json=sub(), headers=h(ORG))
    assert db.query(models.PushSubscription).count() == 1


def test_a_device_that_signs_in_as_someone_else_takes_the_subscription_over(env, vapid):
    client, db, h, ids = env
    client.post("/push/subscribe", json=sub(), headers=h(ORG))
    client.post("/push/subscribe", json=sub(), headers=h(DONOR))                 # same phone, other account
    assert db.query(models.PushSubscription).one().user_id == uid(db, DONOR)
    assert client.get("/push/subscriptions", headers=h(ORG)).json()["devices"] == []


def test_each_person_keeps_at_most_ten_devices_newest_first(env, vapid):
    client, db, h, ids = env
    for n in range(12):
        assert client.post("/push/subscribe", json=sub(n), headers=h(ORG)).status_code == 200
    rows = db.query(models.PushSubscription).filter_by(user_id=uid(db, ORG)).all()
    assert len(rows) == push_cap() and all("device-0-" not in r.endpoint and "device-1-" not in r.endpoint for r in rows)


def push_cap():
    from app.routers.push import MAX_DEVICES
    return MAX_DEVICES


def test_subscribing_is_rate_limited_and_audited_without_the_secret_part_of_the_endpoint(env, vapid):
    client, db, h, ids = env
    codes = [client.post("/push/subscribe", json=sub(n), headers=h(ORG)).status_code for n in range(22)]
    assert codes[:20] == [200] * 20 and 429 in codes[20:]
    entries = db.query(models.AuditLog).filter_by(action="push.subscribed").all()
    assert entries and all("secret-token" not in str(e.detail) and "fcm.googleapis.com" in str(e.detail) for e in entries)


# ---------------------------------------------------------------- unsubscribing
def test_a_person_can_remove_only_their_own_device(env, vapid):
    client, db, h, ids = env
    client.post("/push/subscribe", json=sub(), headers=h(ORG))
    assert client.request("DELETE", "/push/subscribe", json={"endpoint": sub()["endpoint"]}, headers=h(DONOR)).json() == {"removed": 0}
    assert db.query(models.PushSubscription).count() == 1                          # someone else's request changed nothing
    assert client.request("DELETE", "/push/subscribe", json={"endpoint": sub()["endpoint"]}, headers=h(ORG)).json() == {"removed": 1}
    assert db.query(models.PushSubscription).count() == 0


# ---------------------------------------------------------------- queueing
@pytest.fixture
def collected(monkeypatch):
    got = []
    monkeypatch.setattr(push_dispatch, "dispatcher", lambda event_id: got.append(event_id))
    return got


def test_a_notification_queues_a_push_only_after_commit_for_a_subscribed_person(env, vapid, collected):
    client, db, h, ids = env
    client.post("/push/subscribe", json=sub(), headers=h(VOL))
    journey_to(client, h, ids, "offer")                                             # the volunteer is offered a delivery
    events = db.query(models.NotificationEvent).filter_by(user_id=uid(db, VOL), channel="push").all()
    assert events and all(e.status == "queued" for e in events)
    assert collected == [e.id for e in events]                                      # handed to the worker exactly once each, after commit


def test_nothing_is_queued_without_a_device_without_vapid_or_when_the_person_muted_push(env, monkeypatch, collected):
    client, db, h, ids = env
    for k, v in VAPID.items():
        monkeypatch.setenv(k, v)
    journey_to(client, h, ids, "offer")                                             # volunteer has NO device
    assert db.query(models.NotificationEvent).count() == 0 and collected == []


def test_the_push_master_switch_and_category_switch_are_respected_but_security_is_not_mutable(env, vapid, collected):
    client, db, h, ids = env
    client.post("/push/subscribe", json=sub(), headers=h(VOL))
    me = db.get(models.User, uid(db, VOL))
    me.notification_prefs = {"push": False}; db.commit()
    assert push_dispatch.queue_push(db, me, "donation", "t", "/x") is None
    assert push_dispatch.queue_push(db, me, "security", "Password changed", "/settings") is not None
    me.notification_prefs = {"donation": False}; db.commit()
    assert push_dispatch.queue_push(db, me, "donation", "t", "/x") is None


def test_a_rolled_back_transaction_never_dispatches(env, vapid, collected):
    client, db, h, ids = env
    client.post("/push/subscribe", json=sub(), headers=h(VOL))
    me = db.get(models.User, uid(db, VOL))
    assert push_dispatch.queue_push(db, me, "donation", "t", "/x") is not None
    db.rollback()
    assert collected == [] and db.query(models.NotificationEvent).count() == 0


def test_the_test_button_is_rate_limited_and_needs_a_device(env, vapid, collected):
    client, db, h, ids = env
    assert client.post("/push/test", headers=h(ORG)).status_code == 409           # no device yet
    client.post("/push/subscribe", json=sub(), headers=h(ORG))
    codes = [client.post("/push/test", headers=h(ORG)).status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429


# ---------------------------------------------------------------- delivery (fake push service)
def make_event(db, user_email, kind="donation"):
    ev = models.NotificationEvent(user_id=uid(db, user_email), channel="push", kind=kind, title="Delivery #1: In transit", link="/deliveries?open=1", status="queued", attempts=0, accepted_count=0)
    db.add(ev); db.commit()
    return ev.id


def add_device(db, email, n=1):
    row = models.PushSubscription(user_id=uid(db, email), endpoint_hash=webpush.endpoint_hash(sub(n)["endpoint"]), endpoint=sub(n)["endpoint"], p256dh=KEYS["p256dh"], auth=KEYS["auth"], failure_count=0)
    db.add(row); db.commit()
    return row.id


class Fake:
    def __init__(self, *results):
        self.results, self.sent = list(results), []

    def __call__(self, subscription, payload, env):
        self.sent.append((subscription["endpoint"], payload))
        return self.results.pop(0) if self.results else SendResult("accepted", "201")


def run(db, event_id, fake):
    push_dispatch.deliver(event_id, session_factory=lambda: db, send=fake, env=VAPID)
    db.expire_all()


def test_accepted_is_recorded_as_accepted_by_provider_never_as_delivered(env):
    client, db, h, ids = env
    add_device(db, ORG); eid = make_event(db, ORG)
    run(db, eid, Fake(SendResult("accepted", "201")))
    ev = db.get(models.NotificationEvent, eid)
    assert (ev.status, ev.accepted_count, ev.attempts) == ("accepted_by_provider", 1, 1)
    assert db.query(models.PushSubscription).one().last_accepted_at is not None


def test_the_payload_sent_is_minimal(env):
    client, db, h, ids = env
    add_device(db, ORG); eid = make_event(db, ORG); fake = Fake()
    run(db, eid, fake)
    import json
    payload = json.loads(fake.sent[0][1])
    assert set(payload) == {"title", "body", "url", "kind", "tag"} and payload["body"] == webpush.GENERIC_BODY and payload["url"] == "/deliveries?open=1"


def test_delivering_twice_sends_once(env):
    client, db, h, ids = env
    add_device(db, ORG); eid = make_event(db, ORG); fake = Fake()
    run(db, eid, fake); run(db, eid, fake)
    assert len(fake.sent) == 1


def test_a_gone_device_is_removed_and_the_event_says_so(env):
    client, db, h, ids = env
    add_device(db, ORG); eid = make_event(db, ORG)
    run(db, eid, Fake(SendResult("gone", "410")))
    assert db.query(models.PushSubscription).count() == 0
    assert db.get(models.NotificationEvent, eid).status == "no_subscription"


def test_one_working_device_is_enough_and_the_dead_one_is_dropped(env):
    client, db, h, ids = env
    add_device(db, ORG, 1); add_device(db, ORG, 2); eid = make_event(db, ORG)
    run(db, eid, Fake(SendResult("gone", "410"), SendResult("accepted", "201")))
    assert db.get(models.NotificationEvent, eid).status == "accepted_by_provider" and db.query(models.PushSubscription).count() == 1


def test_a_flaky_device_survives_blips_but_is_dropped_after_repeated_failures(env):
    client, db, h, ids = env
    add_device(db, ORG)
    for n in range(webpush.FAILURES_BEFORE_DROP - 1):
        run(db, make_event(db, ORG), Fake(SendResult("retry", "503")))
        assert db.query(models.PushSubscription).one().failure_count == n + 1
    run(db, make_event(db, ORG), Fake(SendResult("retry", "503")))
    assert db.query(models.PushSubscription).count() == 0


def test_a_success_resets_the_failure_counter(env):
    client, db, h, ids = env
    sid = add_device(db, ORG)
    run(db, make_event(db, ORG), Fake(SendResult("retry", "503")))
    run(db, make_event(db, ORG), Fake(SendResult("accepted", "201")))
    assert db.get(models.PushSubscription, sid).failure_count == 0


def test_a_failed_send_is_recorded_with_its_code_and_does_not_claim_success(env):
    client, db, h, ids = env
    add_device(db, ORG); eid = make_event(db, ORG)
    run(db, eid, Fake(SendResult("failed", "403")))
    ev = db.get(models.NotificationEvent, eid)
    assert (ev.status, ev.accepted_count, ev.error_code) == ("failed", 0, "403")


def test_events_endpoint_shows_only_the_callers_own_attempts(env, vapid):
    client, db, h, ids = env
    make_event(db, ORG); make_event(db, DONOR)
    mine = client.get("/push/events", headers=h(ORG)).json()["events"]
    assert len(mine) == 1 and set(mine[0]) == {"id", "kind", "title", "status", "accepted_devices", "error", "at"}
