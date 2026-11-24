"""SMS boundary: pure Python, no network. Run with:  python -m pytest tests/test_sms.py -q"""
import logging
import urllib.parse

from app.services import sms

ENV = {"SMS_PROVIDER": "twilio", "TWILIO_ACCOUNT_SID": "ACsecretsid", "TWILIO_AUTH_TOKEN": "supersecrettoken", "TWILIO_FROM": "+15551234567"}


def test_phone_numbers_are_normalised_or_refused():
    assert sms.normalize_phone("+91 98765 43210") == "+919876543210"
    assert sms.normalize_phone("0091 98765 43210") == "+919876543210"
    assert sms.normalize_phone("098765 43210", "91") == "+919876543210" and sms.normalize_phone("9876543210", "+91") == "+919876543210"
    for bad in ("", None, "9876543210", "+0123456", "+12", "call me", "+91 98765 4321O", "+" + "9" * 20, "+91 98765; DROP TABLE"):
        assert sms.normalize_phone(bad) is None, bad


def test_masking_hides_most_of_the_number():
    assert sms.mask("+919876543210") == "+91********10" and sms.mask("123") == "***"


def test_nothing_is_configured_means_no_provider_and_no_pretending():
    assert sms.provider_from_env({}) is None
    assert sms.send_code("+919876543210", "123456", 10, {}) == sms.SmsResult(False, "none")
    for missing in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"):
        partial = {k: v for k, v in ENV.items() if k != missing}
        assert sms.provider_from_env(partial) is None, missing
    assert sms.provider_from_env({**ENV, "TWILIO_FROM": "not a number"}) is None
    assert sms.provider_from_env({**ENV, "SMS_PROVIDER": "carrier-pigeon"}) is None


def test_a_successful_send_is_reported_only_after_the_provider_accepts():
    seen = {}

    def fake(url, body, headers):
        seen.update(url=url, body=urllib.parse.parse_qs(body.decode()), headers=headers); return 201
    res = sms.send_code("+919876543210", "123456", 10, ENV, fake)
    assert res == sms.SmsResult(True, "twilio")
    assert seen["url"] == "https://api.twilio.com/2010-04-01/Accounts/ACsecretsid/Messages.json"
    assert seen["body"]["To"] == ["+919876543210"] and seen["body"]["From"] == ["+15551234567"] and "123456" in seen["body"]["Body"][0] and "Do not share" in seen["body"]["Body"][0]
    assert seen["headers"]["Authorization"].startswith("Basic ")


def test_provider_errors_and_network_failures_are_failures_and_never_leak_anything():
    records = []

    class Catch(logging.Handler):
        def emit(self, r): records.append(r.getMessage())
    h = Catch(); sms.logger.addHandler(h); sms.logger.setLevel(logging.DEBUG)
    try:
        assert sms.send_code("+919876543210", "654321", 10, ENV, lambda *a: 400) == sms.SmsResult(False, "twilio")
        assert sms.send_code("+919876543210", "654321", 10, ENV, lambda *a: (_ for _ in ()).throw(OSError("network down"))) == sms.SmsResult(False, "twilio")
    finally:
        sms.logger.removeHandler(h)
    joined = " ".join(records)
    assert records and all(x not in joined for x in ("654321", "+919876543210", "ACsecretsid", "supersecrettoken"))


def test_an_invalid_destination_is_never_sent_to_the_provider():
    called = []
    assert sms.send_code("98765", "123456", 10, ENV, lambda *a: called.append(1) or 201).ok is False and called == []


def test_the_provider_object_never_shows_its_credentials():
    p = sms.provider_from_env(ENV)
    assert "supersecrettoken" not in repr(p) and "ACsecretsid" not in repr(p) and "supersecrettoken" not in str(p)


# ------------------------------------------------------------------ MSG91 (India, DLT) and phone verification policy
import json

MSG91 = {"SMS_PROVIDER": "msg91", "MSG91_AUTH_KEY": "authkey-secret", "MSG91_TEMPLATE_ID": "tmpl123", "SMS_SENDER_ID": "CAREBR",
         "DLT_ENTITY_ID": "1101234567890", "DLT_TEMPLATE_ID": "1107000000000001"}


def test_mobile_numbers_are_checked_more_strictly_for_india():
    assert sms.is_valid_mobile("+919876543210") and sms.is_valid_mobile("+14155550123")
    for bad in ("+911234567890", "+91987654321", "+9198765432100", "9876543210", "", None, "+0123456789"):
        assert not sms.is_valid_mobile(bad), bad


def test_msg91_sends_the_documented_payload_and_reports_success_only_when_the_body_says_so():
    seen = {}

    def fake(url, body, headers):
        seen.update(url=url, body=json.loads(body), headers=headers)
        return 200, '{"type":"success","message":"abc"}'
    res = sms.send_code("+919876543210", "123456", 10, MSG91, fake)
    assert res == sms.SmsResult(True, "msg91")
    assert seen["url"] == "https://control.msg91.com/api/v5/flow/" and seen["headers"]["authkey"] == "authkey-secret"
    assert seen["body"] == {"flow_id": "tmpl123", "sender": "CAREBR",
                            "recipients": [{"mobiles": "919876543210", "VAR1": "123456", "VAR2": "10"}]}
    # HTTP 200 with an error body is a failure, never "sent"
    assert sms.send_code("+919876543210", "123456", 10, MSG91, lambda u, b, h: (200, '{"type":"error","message":"template missing"}')).ok is False
    assert sms.send_code("+919876543210", "123456", 10, MSG91, lambda u, b, h: (200, "not json")).ok is False
    assert sms.send_code("+919876543210", "123456", 10, MSG91, lambda u, b, h: (500, "{}")).ok is False

    def boom(u, b, h):
        raise OSError("network down")
    assert sms.send_code("+919876543210", "123456", 10, MSG91, boom).ok is False


def test_nothing_is_sent_to_an_indian_number_without_the_dlt_settings():
    called = []
    for missing in ("SMS_SENDER_ID", "DLT_ENTITY_ID", "DLT_TEMPLATE_ID"):
        env = {k: v for k, v in MSG91.items() if k != missing}
        assert sms.send_code("+919876543210", "123456", 10, env, lambda u, b, h: called.append(1) or (200, '{"type":"success"}')).ok is False, missing
    assert called == []
    # a non-Indian number does not need the Indian registration
    env = {k: v for k, v in MSG91.items() if k not in ("SMS_SENDER_ID", "DLT_ENTITY_ID", "DLT_TEMPLATE_ID")}
    assert sms.send_code("+14155550123", "123456", 10, env, lambda u, b, h: (200, '{"type":"success"}')).ok is True


def test_msg91_needs_its_key_and_template_and_never_shows_credentials():
    assert sms.provider_from_env({k: v for k, v in MSG91.items() if k != "MSG91_AUTH_KEY"}) is None
    assert sms.provider_from_env({k: v for k, v in MSG91.items() if k != "MSG91_TEMPLATE_ID"}) is None
    assert "authkey-secret" not in repr(sms.provider_from_env(MSG91))


def test_phone_verification_is_required_only_when_switched_on_and_deliverable():
    assert sms.verification_required({}) is False
    assert sms.verification_required({"REQUIRE_PHONE_VERIFICATION": "true"}) is False              # cannot deliver: never lock people out
    assert sms.verification_required({**MSG91, "REQUIRE_PHONE_VERIFICATION": "true"}) is True
    assert sms.verification_required({**MSG91}) is False                                           # not switched on


def test_dev_delivery_modes_are_refused_in_production():
    assert sms.delivery_mode({"SMS_DELIVERY": "outbox"}) == "none"
    assert sms.delivery_mode({"SMS_DELIVERY": "outbox", "APP_ENV": "production"}) == "none"
    assert sms.delivery_mode({"SMS_DELIVERY": "outbox", "APP_ENV": "test"}) == "outbox"
    sms.OUTBOX.clear()
    assert sms.send_code("+919876543210", "654321", 10, {"SMS_DELIVERY": "outbox", "APP_ENV": "test"}).ok is True
    assert sms.OUTBOX == [("+919876543210", "654321")]
    sms.OUTBOX.clear()


def test_twilio_phone_number_is_accepted_as_an_alias_for_twilio_from():
    env = {"SMS_PROVIDER": "twilio", "TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_PHONE_NUMBER": "+14155550100"}
    assert sms.provider_from_env(env)._sender == "+14155550100"
    # the original name still wins when both are present
    assert sms.provider_from_env({**env, "TWILIO_FROM": "+14155550199"})._sender == "+14155550199"
