"""The Sentry scrubber: nothing sensitive may survive, by key name OR by value pattern, at any depth. If scrubbing fails the event is dropped."""
import pytest

from app.services import observability as o

LAT, LON = 17.385044, 78.486671


def flat(x):
    return str(x)


@pytest.mark.parametrize("key", ["password", "new_password", "otp", "code_hash", "access_token", "refresh_token", "Authorization", "cookie", "api_key", "razorpay_signature",
                                 "latitude", "longitude", "lat", "lng", "lon", "coordinates", "location", "position", "gps", "heading", "speed", "accuracy_m",
                                 "phone", "phone_e164", "email", "address", "street", "child_name", "children", "guardian_name", "dob", "aadhaar", "session_id"])
def test_sensitive_keys_are_redacted(key):
    assert o.scrub({key: "VALUE-123"}) == {key: o.REDACTED}


def test_harmless_keys_survive():
    data = {"status": "in_transit", "task_id": 7, "route": "/deliveries/7", "attempt": 2}
    assert o.scrub(data) == data


def test_redaction_goes_deep_into_lists_and_nested_objects():
    out = o.scrub({"a": [{"b": {"c": [{"latitude": LAT}], "ok": 1}}], "tuple": ({"password": "x"},)})
    assert out == {"a": [{"b": {"c": [{"latitude": o.REDACTED}], "ok": 1}}], "tuple": [{"password": o.REDACTED}]}


def test_absurdly_deep_structures_are_cut_off_not_recursed_forever():
    d = cur = {}
    for _ in range(50):
        cur["n"] = {}; cur = cur["n"]
    assert o.REDACTED in flat(o.scrub(d))


@pytest.mark.parametrize("text,gone", [
    ("failed for donor@example.org today", "donor@example.org"),
    ("Authorization: Bearer abcDEF123456789xyz", "abcDEF123456789xyz"),
    ("token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c", "eyJhbGciOiJIUzI1NiJ9"),
    ("volunteer at 17.385044, 78.486671 was rejected", "17.385044"),
    ("point (17.385044,78.486671)", "78.486671"),
    ("call +91 98765 43210 now", "98765"),
    ("phone 9876543210", "9876543210"),
])
def test_values_are_scrubbed_by_pattern_even_under_innocent_keys(text, gone):
    out = o.scrub({"message": text})
    assert gone not in flat(out)


def test_ordinary_numbers_and_versions_are_not_mangled():
    assert o.scrub_string("took 1234 ms, version 1.2.3, status 500, task 77") == "took 1234 ms, version 1.2.3, status 500, task 77"


def full_event():
    return {
        "exception": {"values": [{"type": "ValueError", "value": f"bad position {LAT}, {LON} for donor@example.org",
                                  "stacktrace": {"frames": [{"vars": {"latitude": LAT, "password": "hunter2", "n": 3}}]}}]},
        "request": {"url": "https://x.org/deliveries/7/location", "method": "PUT", "query_string": "access_token=abc", "cookies": {"s": "1"},
                    "data": {"latitude": LAT, "longitude": LON}, "headers": {"Authorization": "Bearer abcdefghijkl", "User-Agent": "UA", "Cookie": "s=1", "X-Forwarded-For": "1.2.3.4"}},
        "user": {"id": 9, "email": "u@example.org", "ip_address": "1.2.3.4", "username": "someone"},
        "extra": {"otp": "123456", "note": "ok"}, "tags": {"phone": "+919876543210"}, "server_name": "host-1",
        "breadcrumbs": {"values": [{"category": "query", "message": "SELECT * FROM users WHERE email='a@b.org'"}]},
    }


def test_a_realistic_event_leaves_nothing_sensitive():
    out = o.scrub_event(full_event())
    text = flat(out)
    for secret in (str(LAT), str(LON), "78.4866", "donor@example.org", "hunter2", "abcdefghijkl", "123456", "u@example.org", "1.2.3.4", "someone", "9876543210", "a@b.org", "access_token=abc"):
        assert secret not in text, secret
    assert out["user"] == {"id": "9"}
    assert out["request"]["method"] == "PUT" and set(out["request"]["headers"]) == {"User-Agent"}
    assert "data" not in out["request"] and "cookies" not in out["request"] and "server_name" not in out
    assert out["exception"]["values"][0]["type"] == "ValueError"                  # the useful part (what and where) survives


def test_an_event_without_a_user_gets_an_empty_user():
    assert o.scrub_event({"message": "x"})["user"] == {}


def test_scrubbing_does_not_mutate_the_original_event():
    ev = full_event(); before = flat(ev)
    o.scrub_event(ev)
    assert flat(ev) == before


def test_if_scrubbing_fails_the_event_is_dropped_not_sent(monkeypatch):
    monkeypatch.setattr(o, "scrub", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert o.scrub_event({"message": "secret@x.org"}) is None


def test_breadcrumbs_lose_outbound_urls_and_sensitive_text():
    crumb = {"category": "httpx", "message": "POST ok", "data": {"url": "https://maps.googleapis.com/x?key=SECRET", "status_code": 200}}
    out = o.scrub_breadcrumb(crumb)
    assert "SECRET" not in flat(out) and out["data"]["status_code"] == 200
    assert "a@b.org" not in flat(o.scrub_breadcrumb({"category": "query", "message": "email a@b.org"}))


def test_init_is_off_without_a_dsn_and_never_crashes_the_app(monkeypatch):
    assert o.init("api", env={}) is False
    assert o.init("api", env={"SENTRY_DSN": "https://k@o.example/1"}) in (True, False)      # False when sentry-sdk is not installed; True otherwise
