"""OTP policy and hashing: pure Python, no database. Run with:  python -m pytest tests/test_otp.py -q"""
import logging
from datetime import datetime, timedelta

from app.services import otp

NOW = datetime(2026, 10, 25, 12, 0, 0)
POL = otp.Policy(length=6, ttl_minutes=10, max_attempts=3, resend_cooldown_seconds=60, max_per_hour=3)
SECRET = "unit-test-secret"


def _state(expires_in=600, attempts=0, used=False):
    return otp.ChallengeState(NOW + timedelta(seconds=expires_in), attempts, NOW if used else None)


# ------------------------------------------------------------------ generation
def test_codes_have_the_configured_length_and_are_digits_only():
    for n in (4, 6, 8, 10):
        code = otp.generate_code(n)
        assert len(code) == n and code.isdigit()


def test_codes_are_not_constant_and_use_the_whole_digit_range():
    codes = {otp.generate_code(6) for _ in range(200)}
    assert len(codes) > 190                                   # 200 draws from 1,000,000: collisions are rare
    assert set("".join(codes)) == set("0123456789")


def test_leading_zeros_are_preserved():
    assert any(otp.generate_code(6).startswith("0") for _ in range(400))   # about 10% of codes


def test_generation_uses_the_secrets_module_not_random():
    import inspect
    src = inspect.getsource(otp.generate_code)
    assert "secrets." in src and "random." not in src


# ------------------------------------------------------------------ hashing
def test_hash_is_keyed_salted_and_bound_to_user_and_purpose():
    h = otp.hash_code("123456", "salt", SECRET, "password_reset", 7)
    assert len(h) == 64 and "123456" not in h
    assert h != otp.hash_code("123456", "salt", "another-secret", "password_reset", 7)   # keyed
    assert h != otp.hash_code("123456", "other-salt", SECRET, "password_reset", 7)        # salted
    assert h != otp.hash_code("123456", "salt", SECRET, "password_reset", 8)              # user-bound
    assert h != otp.hash_code("123456", "salt", SECRET, "signup", 7)                       # purpose-bound


def test_matching_accepts_the_right_code_and_formatting_variants():
    h = otp.hash_code("048213", "s", SECRET, "password_reset", 1)
    for typed in ("048213", " 048213 ", "048 213", "048-213", 48213 and "048213"):
        assert otp.code_matches(typed, "s", h, SECRET, "password_reset", 1)


def test_matching_rejects_wrong_empty_and_other_users_codes():
    h = otp.hash_code("048213", "s", SECRET, "password_reset", 1)
    for typed in ("048214", "", None, "abcdef", "48213", "0482133"):
        assert not otp.code_matches(typed, "s", h, SECRET, "password_reset", 1)
    assert not otp.code_matches("048213", "s", h, SECRET, "password_reset", 2)         # same code, different account
    assert not otp.code_matches("048213", "s", "", SECRET, "password_reset", 1)


# ------------------------------------------------------------------ attempt evaluation
def test_right_code_inside_the_window_succeeds():
    assert otp.evaluate_attempt(_state(), True, NOW, POL) == ("ok", 0)


def test_wrong_codes_count_up_then_lock_the_challenge():
    s, outcomes = _state(), []
    attempts = 0
    for _ in range(3):
        outcome, attempts = otp.evaluate_attempt(otp.ChallengeState(s.expires_at, attempts, None), False, NOW, POL)
        outcomes.append(outcome)
    assert outcomes == ["wrong", "wrong", "locked"] and attempts == 3


def test_the_right_code_after_lockout_is_refused_so_guessing_cannot_win_by_persistence():
    assert otp.evaluate_attempt(_state(attempts=3), True, NOW, POL)[0] == "locked"


def test_expired_code_is_refused_even_if_correct_and_exactly_at_expiry_counts_as_expired():
    assert otp.evaluate_attempt(_state(expires_in=-1), True, NOW, POL)[0] == "expired"
    assert otp.evaluate_attempt(_state(expires_in=0), True, NOW, POL)[0] == "expired"
    assert otp.evaluate_attempt(_state(expires_in=1), True, NOW, POL)[0] == "ok"


def test_a_used_code_cannot_be_replayed():
    assert otp.evaluate_attempt(_state(used=True), True, NOW, POL)[0] == "used"


# ------------------------------------------------------------------ resend limits
def test_resend_cooldown_counts_down_and_rounds_up():
    assert otp.seconds_until_resend(None, NOW, POL) == 0
    assert otp.seconds_until_resend(NOW, NOW, POL) == 60
    assert otp.seconds_until_resend(NOW - timedelta(seconds=59, milliseconds=500), NOW, POL) == 1
    assert otp.seconds_until_resend(NOW - timedelta(seconds=60), NOW, POL) == 0
    assert otp.seconds_until_resend(NOW - timedelta(hours=1), NOW, POL) == 0


def test_hourly_cap_only_counts_the_last_hour():
    sent = [NOW - timedelta(minutes=m) for m in (1, 10, 59)]
    assert otp.over_hourly_limit(sent, NOW, POL)
    assert not otp.over_hourly_limit(sent[:2], NOW, POL)
    assert not otp.over_hourly_limit([NOW - timedelta(minutes=m) for m in (61, 90, 120, 200)], NOW, POL)


# ------------------------------------------------------------------ configuration
def test_policy_defaults_and_clamping():
    d = otp.policy_from_env({})
    assert (d.length, d.ttl_minutes, d.max_attempts, d.resend_cooldown_seconds, d.max_per_hour) == (6, 10, 5, 60, 5)
    wild = otp.policy_from_env({"OTP_LENGTH": "99", "OTP_TTL_MINUTES": "0", "OTP_MAX_ATTEMPTS": "-5", "OTP_RESEND_COOLDOWN_SECONDS": "999999", "OTP_MAX_PER_HOUR": "x"})
    assert (wild.length, wild.ttl_minutes, wild.max_attempts, wild.resend_cooldown_seconds, wild.max_per_hour) == (10, 1, 1, 600, 5)


# ------------------------------------------------------------------ delivery safety
def test_nothing_configured_means_no_delivery_and_no_pretending():
    assert otp.delivery_mode({}) == "none"
    assert otp.deliver("a@b.org", "123456", 10, {}) == otp.Delivery(False, "none")


def test_smtp_settings_select_email():
    assert otp.delivery_mode({"SMTP_HOST": "smtp.x.org", "SMTP_FROM": "no-reply@x.org"}) == "email"
    assert otp.delivery_mode({"SMTP_HOST": "smtp.x.org"}) == "none"            # half-configured is not configured


def test_dev_modes_are_refused_in_production_and_when_app_env_is_unset():
    for env in ({"OTP_DELIVERY": "console"}, {"OTP_DELIVERY": "outbox"}, {"OTP_DELIVERY": "console", "APP_ENV": "production"}, {"OTP_DELIVERY": "outbox", "APP_ENV": "staging"}):
        assert otp.delivery_mode(env) == "none", env
    # even with SMTP configured, an explicit dev mode in production does not silently fall back to leaking codes
    assert otp.delivery_mode({"OTP_DELIVERY": "console", "SMTP_HOST": "h", "SMTP_FROM": "f"}) == "none"


def test_dev_modes_work_in_development():
    assert otp.delivery_mode({"OTP_DELIVERY": "outbox", "APP_ENV": "development"}) == "outbox"
    assert otp.delivery_mode({"OTP_DELIVERY": "console", "APP_ENV": "local"}) == "console"


def test_outbox_delivery_keeps_the_code_only_in_memory():
    otp.OUTBOX.clear()
    assert otp.deliver("A@B.org", "123456", 10, {"OTP_DELIVERY": "outbox", "APP_ENV": "test"}) == otp.Delivery(True, "outbox")
    assert otp.OUTBOX == [("a@b.org", "123456")]
    otp.OUTBOX.clear()


def test_smtp_failure_is_reported_as_not_delivered_and_logs_no_code_or_address():
    records = []

    class Catch(logging.Handler):
        def emit(self, record): records.append(record.getMessage())
    handler = Catch(); otp.logger.addHandler(handler); otp.logger.setLevel(logging.DEBUG)
    try:
        env = {"SMTP_HOST": "127.0.0.1", "SMTP_PORT": "1", "SMTP_FROM": "no-reply@x.org"}   # nothing listens on port 1
        result = otp.deliver("person@example.org", "987654", 10, env)
    finally:
        otp.logger.removeHandler(handler)
    assert result == otp.Delivery(False, "email")
    assert records and all("987654" not in r and "person@example.org" not in r for r in records)


# ------------------------------------------------------------------ registration verification policy
def test_verification_is_off_by_default_and_never_traps_users_when_codes_cannot_be_sent():
    smtp = {"SMTP_HOST": "smtp.x.org", "SMTP_FROM": "no-reply@x.org"}
    assert otp.verification_required({}) is False
    assert otp.verification_required({"REQUIRE_EMAIL_VERIFICATION": "true"}) is False                  # wanted, but nothing can deliver a code
    assert otp.verification_required({"REQUIRE_EMAIL_VERIFICATION": "false", **smtp}) is False         # deliverable, but not wanted
    for on in ("true", "1", "YES", "on"):
        assert otp.verification_required({"REQUIRE_EMAIL_VERIFICATION": on, **smtp}) is True
    assert otp.verification_required({"REQUIRE_EMAIL_VERIFICATION": "true", "OTP_DELIVERY": "outbox", "APP_ENV": "test"}) is True
    assert otp.verification_required({"REQUIRE_EMAIL_VERIFICATION": "true", "OTP_DELIVERY": "outbox", "APP_ENV": "production"}) is False   # dev mode refused in production
