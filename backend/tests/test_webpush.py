"""Web Push: SSRF-safe endpoints, minimal payloads, honest result classification, failure policy, notification preferences. Fake sender only."""
import json

import pytest

from app.services import notify_rules, webpush
from app.services.webpush import PushHttpError, SendResult

ENV = {"VAPID_PUBLIC_KEY": "BPublicKey", "VAPID_PRIVATE_KEY": "private", "VAPID_SUBJECT": "mailto:admin@example.org"}
P256 = "B" + "x" * 86          # a 65-byte uncompressed point is 87 base64url characters
AUTH = "a" * 22
GOOD = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc123", "keys": {"p256dh": P256, "auth": AUTH}}


# ---------------------------------------------------------------- the endpoint is attacker-controlled, so it must be allow-listed
@pytest.mark.parametrize("endpoint", [
    "https://fcm.googleapis.com/fcm/send/abc",
    "https://updates.push.services.mozilla.com/wpush/v2/abc",
    "https://web.push.apple.com/QAbc",
    "https://wns2-par02p.notify.windows.com/w/?token=abc",
    "https://fcm.googleapis.com:443/fcm/send/abc",
])
def test_real_push_services_are_accepted(endpoint):
    assert webpush.host_allowed(endpoint, {}) is True


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/fcm/send/abc",                          # not https
    "https://169.254.169.254/latest/meta-data/",                       # cloud metadata
    "https://localhost/hook", "https://127.0.0.1/x", "https://10.0.0.5/x", "https://[::1]/x",
    "https://backend:8000/admin",                                      # internal service name
    "https://evil.example.com/fcm.googleapis.com",                     # allowed name only in the path
    "https://fcm.googleapis.com.evil.example/fcm/send/abc",            # look-alike suffix
    "https://evilfcm.googleapis.com.attacker.io/x",
    "https://xfcm.googleapis.com.evil.io/x",
    "https://user:pass@fcm.googleapis.com/fcm/send/abc",               # credentials smuggled in
    "https://fcm.googleapis.com@evil.example/x",                       # '@' trick: the real host is evil.example
    "https://fcm.googleapis.com:8443/fcm/send/abc",                    # non-standard port
    "https://fcm.googleapis.com\\@evil.example/x",
    "https://fcm.googleapis.com/x y", "https://fcm.googleapis.com/x\r\nHost: evil",
    "ftp://fcm.googleapis.com/x", "file:///etc/passwd", "javascript:alert(1)", "//fcm.googleapis.com/x",
    "", None, 42, ["https://fcm.googleapis.com/x"], "https://" + "a" * 1100 + ".push.apple.com/x",
])
def test_hostile_or_unknown_endpoints_are_refused(endpoint):
    assert webpush.host_allowed(endpoint, {}) is False


def test_operators_can_extend_the_allow_list_but_not_by_accident():
    env = {"PUSH_ALLOWED_HOSTS": "push.example.net, .other.example"}
    assert webpush.host_allowed("https://api.push.example.net/x", env) and webpush.host_allowed("https://x.other.example/x", env)
    assert not webpush.host_allowed("https://api.push.example.net/x", {})
    assert not webpush.host_allowed("https://push.example.net.evil.io/x", env)


# ---------------------------------------------------------------- subscription validation
def test_a_browser_subscription_is_accepted():
    assert webpush.validate_subscription(GOOD, {}) == (GOOD["endpoint"], P256, AUTH)


@pytest.mark.parametrize("bad", [
    None, "x", [], {}, {"endpoint": GOOD["endpoint"]}, {"endpoint": GOOD["endpoint"], "keys": "k"},
    {"endpoint": GOOD["endpoint"], "keys": {"p256dh": "short", "auth": AUTH}},
    {"endpoint": GOOD["endpoint"], "keys": {"p256dh": P256, "auth": "x"}},
    {"endpoint": GOOD["endpoint"], "keys": {"p256dh": "!" * 87, "auth": AUTH}},
    {"endpoint": GOOD["endpoint"], "keys": {"p256dh": P256, "auth": "a b" + "a" * 20}},
    {"endpoint": GOOD["endpoint"], "keys": {"p256dh": 123, "auth": AUTH}},
    {"endpoint": "https://evil.example/x", "keys": GOOD["keys"]},
])
def test_malformed_or_unsupported_subscriptions_are_refused(bad):
    with pytest.raises(webpush.SubscriptionError):
        webpush.validate_subscription(bad, {})


def test_endpoint_hash_is_stable_and_distinct():
    a, b = webpush.endpoint_hash("https://fcm.googleapis.com/a"), webpush.endpoint_hash("https://fcm.googleapis.com/b")
    assert a == webpush.endpoint_hash("https://fcm.googleapis.com/a") and a != b and len(a) == 64


# ---------------------------------------------------------------- payload: minimal by construction
def test_the_payload_has_a_short_title_a_generic_body_and_a_same_site_link():
    p = json.loads(webpush.build_payload("donation", "Delivery #5: In transit", "/deliveries?open=5"))
    assert p == {"title": "Delivery #5: In transit", "body": webpush.GENERIC_BODY, "url": "/deliveries?open=5", "kind": "donation", "tag": "cb-donation"}


@pytest.mark.parametrize("link", ["https://evil.example/x", "//evil.example", "javascript:alert(1)", "\\evil", None, ""])
def test_an_unsafe_link_falls_back_to_the_notifications_page(link):
    assert json.loads(webpush.build_payload("need", "t", link))["url"] == "/notifications"


@pytest.mark.parametrize("title", ["T" * 5000, "\u00e9" * 5000, "\U0001F600" * 5000, "<script>alert(1)</script>" * 100])
def test_the_payload_is_always_valid_json_with_exactly_five_fields_and_within_the_size_limit(title):
    raw = webpush.build_payload("k" * 500, title, "/a" * 400)
    data = json.loads(raw)                                              # parses: it was never truncated mid-document
    assert set(data) == {"title", "body", "url", "kind", "tag"} and len(raw) <= webpush.MAX_PAYLOAD_BYTES
    assert len(data["title"]) <= 80 and len(data["kind"]) <= 20 and len(data["url"]) <= 300


def test_an_empty_title_becomes_the_product_name():
    assert json.loads(webpush.build_payload("k", "", None))["title"] == "CareBridge"
    assert json.loads(webpush.build_payload("k", "   \n  ", None))["title"] == "CareBridge"


# ---------------------------------------------------------------- sending
class Sender:
    def __init__(self, status=201, exc=None):
        self.status, self.exc, self.calls = status, exc, []

    def __call__(self, info, data, key, claims, ttl):
        self.calls.append((info, data, key, claims, ttl))
        if self.exc:
            raise self.exc
        return self.status


SUB = {"endpoint": GOOD["endpoint"], "p256dh": P256, "auth": AUTH}


def test_vapid_must_be_fully_configured():
    assert webpush.vapid_enabled(ENV)
    for broken in ({}, {**ENV, "VAPID_PUBLIC_KEY": ""}, {**ENV, "VAPID_PRIVATE_KEY": " "}, {**ENV, "VAPID_SUBJECT": "admin@example.org"}, {**ENV, "VAPID_SUBJECT": "http://x"}):
        assert not webpush.vapid_enabled(broken)
    assert webpush.vapid_enabled({**ENV, "VAPID_SUBJECT": "https://example.org/contact"})
    assert webpush.send(SUB, "{}", {}, sender=Sender()).status == "not_configured"


def test_accepted_means_the_push_service_took_it_and_the_key_stays_in_the_sender_call():
    s = Sender(201)
    r = webpush.send(SUB, "{}", ENV, sender=s)
    assert r == SendResult("accepted", "201")
    info, data, key, claims, ttl = s.calls[0]
    assert info == {"endpoint": SUB["endpoint"], "keys": {"p256dh": P256, "auth": AUTH}} and key == "private" and claims == {"sub": "mailto:admin@example.org"}


@pytest.mark.parametrize("status,expected", [(200, "accepted"), (202, "accepted"), (404, "gone"), (410, "gone"), (429, "retry"), (500, "retry"), (503, "retry"),
                                             (400, "failed"), (401, "failed"), (403, "failed"), (413, "failed")])
def test_provider_answers_are_classified(status, expected):
    assert webpush.send(SUB, "{}", ENV, sender=Sender(status)).status == expected


def test_http_errors_and_network_errors_are_classified_without_raising():
    assert webpush.send(SUB, "{}", ENV, sender=Sender(exc=PushHttpError(410))).status == "gone"
    r = webpush.send(SUB, "{}", ENV, sender=Sender(exc=ConnectionError("down https://fcm.googleapis.com/secret-token")))
    assert r.status == "retry" and "secret-token" not in r.code and r.code == "ConnectionError"
    assert webpush.send(SUB, "{}", ENV, sender=Sender(exc=ValueError("bad key"))).status == "retry"


def test_a_stored_row_with_a_disallowed_host_is_refused_at_send_time_too():
    s = Sender()
    r = webpush.send({**SUB, "endpoint": "https://169.254.169.254/latest"}, "{}", ENV, sender=s)
    assert r == SendResult("refused", "host_not_allowed") and s.calls == []


# ---------------------------------------------------------------- one notification across several devices
def test_summary_is_accepted_if_any_device_took_it():
    assert webpush.summarize([SendResult("failed", "403"), SendResult("accepted", "201")]) == ("accepted_by_provider", 1, None)
    assert webpush.summarize([SendResult("accepted", "201"), SendResult("accepted", "201")])[1] == 2


def test_summary_when_nothing_was_accepted():
    assert webpush.summarize([]) == ("no_subscription", 0, None)
    assert webpush.summarize([SendResult("gone", "410")]) == ("no_subscription", 0, "gone")
    assert webpush.summarize([SendResult("retry", "503"), SendResult("gone", "410")]) == ("failed", 0, "503")
    assert webpush.summarize([SendResult("failed", "")])[0] == "failed"


def test_failure_policy_drops_dead_devices_but_forgives_blips():
    assert webpush.next_failure_count(3, SendResult("gone", "410")) == (3, True)            # dropped immediately
    assert webpush.next_failure_count(4, SendResult("accepted", "201")) == (0, False)       # a success resets the counter
    c, drop = 0, False
    for _ in range(webpush.FAILURES_BEFORE_DROP):
        c, drop = webpush.next_failure_count(c, SendResult("retry", "503"))
    assert (c, drop) == (webpush.FAILURES_BEFORE_DROP, True)
    assert webpush.next_failure_count(1, SendResult("retry", "503")) == (2, False)
    assert webpush.next_failure_count(2, SendResult("not_configured")) == (2, False)        # our own misconfiguration never punishes the device
    assert webpush.next_failure_count(2, SendResult("refused", "host_not_allowed"))[1] is True


# ---------------------------------------------------------------- preferences
def test_push_follows_the_persons_category_and_master_choices_and_security_is_unmutable():
    assert notify_rules.wants_push(None, "donation") is True
    assert notify_rules.wants_push({"donation": False}, "donation") is False and notify_rules.wants_push({"donation": False}, "need") is True
    assert notify_rules.wants_push({"push": False}, "donation") is False
    assert notify_rules.wants_push({"push": False, "donation": False}, "security") is True
    assert notify_rules.wants_push({"in_app": False}, "donation") is True            # the in-app master switch is a different channel


def test_push_is_a_known_preference_that_must_be_a_boolean():
    assert notify_rules.merge_prefs(None, {"push": False})["push"] is False
    assert notify_rules.DEFAULT_PREFS["push"] is True
    with pytest.raises(ValueError):
        notify_rules.merge_prefs(None, {"push": "no"})
