"""Razorpay logic with INDEPENDENT test vectors (signatures computed with `openssl dgst -sha256 -hmac`, not by the code under test). Fake transport."""
import json

import pytest

from app.services import payments as p
from app.services.maps_http import MapsError

ENV = {"PAYMENTS_ENABLED": "true", "RAZORPAY_KEY_ID": "rzp_test_abc", "RAZORPAY_KEY_SECRET": "key_secret_test"}
ORDER, PAY = "order_Abc12345678", "pay_Def12345678"
PAY_SIG = "41c76c0ffc2ff77ceda718847803d23c44d0866ca48de7088e9ca3d7a059ba7d"        # openssl: HMAC-SHA256("order_Abc12345678|pay_Def12345678", "key_secret_test")
WH_BODY = b'{"event":"payment.captured","payload":{"payment":{"entity":{"id":"pay_Def12345678","order_id":"order_Abc12345678","amount":50000}}}}'
WH_SIG = "bf172b89269eb904981c36bb93ce9d484c45a629d2190310909fdded75bdf304"          # openssl: HMAC-SHA256(body, "whsec_test")


# ---------------------------------------------------------------- off by default
def test_payments_are_off_unless_explicitly_enabled_and_keyed():
    assert p.enabled(ENV)
    for broken in ({}, {**ENV, "PAYMENTS_ENABLED": "false"}, {**ENV, "PAYMENTS_ENABLED": ""}, {**ENV, "RAZORPAY_KEY_ID": ""}, {**ENV, "RAZORPAY_KEY_SECRET": " "}, {k: v for k, v in ENV.items() if k != "PAYMENTS_ENABLED"}):
        assert not p.enabled(broken)
    with pytest.raises(MapsError) as e:
        p.create_order(10000, "r", {}, {})
    assert e.value.code == "not_configured"


# ---------------------------------------------------------------- signatures
def test_a_genuine_payment_signature_verifies():
    assert p.verify_payment_signature(ORDER, PAY, PAY_SIG, "key_secret_test") is True
    assert p.verify_payment_signature(ORDER, PAY, PAY_SIG.upper(), "key_secret_test") is True and p.verify_payment_signature(ORDER, PAY, f"  {PAY_SIG} ", "key_secret_test") is True


@pytest.mark.parametrize("order,pay,sig,secret", [
    ("order_Zzz99999999", PAY, PAY_SIG, "key_secret_test"),                           # signature for a different order
    (ORDER, "pay_Zzz99999999", PAY_SIG, "key_secret_test"),                            # ... or payment
    (ORDER, PAY, PAY_SIG, "another_secret"), (ORDER, PAY, PAY_SIG[:-1] + "0", "key_secret_test"), (ORDER, PAY, "", "key_secret_test"),
    (ORDER, PAY, PAY_SIG, ""), (ORDER, PAY, None, "key_secret_test"), (None, PAY, PAY_SIG, "key_secret_test"), (ORDER, None, PAY_SIG, "key_secret_test"),
    ("order_x", PAY, PAY_SIG, "key_secret_test"), (ORDER + "|pay_Evil", PAY, PAY_SIG, "key_secret_test"), ("../" + ORDER, PAY, PAY_SIG, "key_secret_test"),
])
def test_forged_swapped_or_malformed_payment_signatures_fail(order, pay, sig, secret):
    assert p.verify_payment_signature(order, pay, sig, secret) is False


def test_a_genuine_webhook_signature_verifies_over_the_raw_bytes_only():
    assert p.verify_webhook_signature(WH_BODY, WH_SIG, "whsec_test") is True
    reformatted = json.dumps(json.loads(WH_BODY), indent=2).encode()                   # same JSON, different bytes: must NOT verify
    assert p.verify_webhook_signature(reformatted, WH_SIG, "whsec_test") is False
    assert p.verify_webhook_signature(WH_BODY.replace(b"50000", b"50001"), WH_SIG, "whsec_test") is False


@pytest.mark.parametrize("body,sig,secret", [(WH_BODY, None, "whsec_test"), (WH_BODY, "", "whsec_test"), (WH_BODY, WH_SIG, ""), (WH_BODY, WH_SIG, "wrong"), ("text", WH_SIG, "whsec_test"), (None, WH_SIG, "whsec_test")])
def test_missing_or_wrong_webhook_credentials_fail_closed(body, sig, secret):
    assert p.verify_webhook_signature(body, sig, secret) is False


# ---------------------------------------------------------------- amounts
@pytest.mark.parametrize("rupees,paise", [(1, 100), (500, 50000), ("250.50", 25050), (10.5, 1050), (50000, 5_000_000)])
def test_valid_amounts_become_exact_integer_paise(rupees, paise):
    assert p.rupees_to_paise(rupees, {}) == paise


@pytest.mark.parametrize("bad", [0, -5, 0.5, 0.99, "abc", "", None, True, float("nan"), float("inf"), 10.123, "1e3x", 50001, [5], {"a": 1}])
def test_invalid_amounts_are_refused(bad):
    with pytest.raises(p.PaymentError):
        p.rupees_to_paise(bad, {})


def test_the_ceiling_is_configurable_but_bounded():
    assert p.rupees_to_paise(100000, {"PAYMENT_MAX_RUPEES": "100000"}) == 10_000_000
    with pytest.raises(p.PaymentError):
        p.rupees_to_paise(100001, {"PAYMENT_MAX_RUPEES": "100000"})
    assert p.max_paise({"PAYMENT_MAX_RUPEES": "999999999"}) == 1_000_000 * 100 and p.max_paise({"PAYMENT_MAX_RUPEES": "junk"}) == 5_000_000


def test_floats_never_cause_off_by_one_paise_and_binary_float_noise_is_refused():
    assert p.rupees_to_paise("1.10", {}) == 110 and p.rupees_to_paise(19.99, {}) == 1999 and p.rupees_to_paise(1.1, {}) == 110
    with pytest.raises(p.PaymentError):
        p.rupees_to_paise(1.1 + 2.2, {})                                               # 3.3000000000000003: binary-float noise, not a real two-decimal amount


# ---------------------------------------------------------------- state machine
@pytest.mark.parametrize("current,event,expected", [
    ("created", "payment.captured", "captured"), ("created", "order.paid", "captured"), ("created", "payment.failed", "failed"), ("failed", "payment.captured", "captured"),
    ("captured", "payment.failed", "captured"),                      # a late failure event cannot undo a captured payment
    ("captured", "refund.processed", "refunded"), ("created", "refund.processed", "created"),                      # nothing to refund yet
    ("refunded", "payment.captured", "refunded"), ("refunded", "payment.failed", "refunded"),                    # refunded is terminal
    ("captured", "payment.captured", "captured"),                    # duplicates are harmless
    ("created", "something.unknown", "created"), ("captured", "", "captured"),
])
def test_status_only_moves_forward(current, event, expected):
    assert p.next_status(current, event) == expected


# ---------------------------------------------------------------- webhook parsing
def test_a_signed_event_is_parsed_into_the_few_fields_we_use():
    assert p.parse_event(json.loads(WH_BODY)) == {"type": "payment.captured", "order_id": ORDER, "payment_id": PAY, "amount": 50000}


@pytest.mark.parametrize("payload", [None, [], "x", {}, {"event": 5}, {"event": None}])
def test_unreadable_events_are_rejected_for_the_caller_to_ignore(payload):
    with pytest.raises(p.PaymentError):
        p.parse_event(payload)


def test_hostile_ids_and_amounts_are_dropped_not_trusted():
    ev = p.parse_event({"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_'; DROP TABLE", "order_id": "../../x", "amount": "50000"}}}})
    assert ev["payment_id"] is None and ev["order_id"] is None and ev["amount"] is None
    assert len(p.parse_event({"event": "x" * 500})["type"]) == 40


def test_event_ids_prefer_razorpays_header_and_fall_back_to_a_stable_hash():
    assert p.event_id("evt_AbC123", b"{}") == "evt_AbC123"
    a, b = p.event_id(None, b"body-1"), p.event_id("", b"body-1")
    assert a == b and a.startswith("sha256:") and a != p.event_id(None, b"body-2")
    assert p.event_id("bad id with spaces", b"x").startswith("sha256:") and p.event_id("x" * 200, b"x").startswith("sha256:")


# ---------------------------------------------------------------- orders (fake transport)
class Fake:
    def __init__(self, status=200, data=None):
        self.status, self.data, self.calls = status, data, []

    def __call__(self, method, url, **kw):
        self.calls.append((method, url, kw)); return self.status, self.data


def test_an_order_is_created_with_a_server_fixed_amount_and_basic_auth_in_the_header_only():
    fake = Fake(200, {"id": ORDER, "amount": 50000, "currency": "INR", "status": "created"})
    out = p.create_order(50000, "cb_abc", {"organization_id": 7, "user_id": 3}, ENV, transport=fake)
    assert out == {"order_id": ORDER, "amount_paise": 50000, "currency": "INR"}
    method, url, kw = fake.calls[0]
    assert (method, url) == ("POST", p.ORDERS_URL) and "key_secret_test" not in url
    assert kw["json"]["amount"] == 50000 and kw["json"]["currency"] == "INR" and kw["json"]["receipt"] == "cb_abc" and kw["json"]["notes"] == {"organization_id": "7", "user_id": "3"}
    import base64
    assert base64.b64decode(kw["headers"]["Authorization"].split()[1]) == b"rzp_test_abc:key_secret_test"


@pytest.mark.parametrize("data", [{}, None, {"id": "order_x", "amount": 50000}, {"id": ORDER, "amount": 49999}, {"id": ORDER, "amount": "50000"}, {"id": "../x", "amount": 50000}])
def test_an_order_answer_that_does_not_match_what_we_asked_for_is_rejected(data):
    with pytest.raises(MapsError):
        p.create_order(50000, "r", {}, ENV, transport=Fake(200, data))


@pytest.mark.parametrize("status,code", [(401, "rejected"), (400, "no_route"), (429, "unavailable"), (500, "unavailable")])
def test_provider_errors_are_classified(status, code):
    with pytest.raises(MapsError) as e:
        p.create_order(50000, "r", {}, ENV, transport=Fake(status, {"error": {"description": "key rzp_test_abc invalid"}}))
    assert e.value.code == code and "rzp_test" not in e.value.message


def test_receipts_are_unique_and_short():
    ids = {p.new_receipt() for _ in range(200)}
    assert len(ids) == 200 and all(len(i) <= 40 and i.startswith("cb_") for i in ids)


def test_reconciliation_lists_only_well_formed_payments():
    fake = Fake(200, {"items": [{"id": PAY, "status": "captured", "amount": 50000}, {"id": "bad", "status": "captured", "amount": 1}, "junk"]})
    assert p.fetch_order_payments(ORDER, ENV, fake) == [{"id": PAY, "status": "captured", "amount": 50000}]
    assert fake.calls[0][1].endswith(f"/orders/{ORDER}/payments")
    with pytest.raises(MapsError):
        p.fetch_order_payments("../etc", ENV, fake)
