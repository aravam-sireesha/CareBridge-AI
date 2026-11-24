"""One-time codes for account recovery.

Everything that decides "is this code acceptable?" is a pure function here, so it is unit-tested without a database.
The router (routers/otp.py) only stores state and applies these decisions.

Security properties:
* Codes come from the `secrets` module (a cryptographic random generator), never from `random`.
* A 6-digit code has only a million possibilities, so a plain hash would be reversed in milliseconds if the table
  leaked. Codes are therefore stored as HMAC-SHA256 keyed with the server's SECRET_KEY plus a per-code salt, and the
  online guessing budget is capped (OTP_MAX_ATTEMPTS) so the keyed hash is not the only defence.
* Comparison is constant-time. A code works once, expires, and is burned after too many wrong guesses.
* Code values are never logged and never returned by the API.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Mapping, Optional, Sequence

logger = logging.getLogger("carebridge.otp")

PURPOSE_PASSWORD_RESET = "password_reset"
PURPOSE_EMAIL_VERIFICATION = "email_verification"
PURPOSE_PHONE_VERIFICATION = "phone_verification"


# --------------------------------------------------------------------------- policy
def _int(env: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(str(env.get(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


@dataclass(frozen=True)
class Policy:
    length: int                 # digits in a code
    ttl_minutes: int            # how long a code stays valid
    max_attempts: int           # wrong guesses allowed per code
    resend_cooldown_seconds: int
    max_per_hour: int           # codes one account may be sent per hour


def policy_from_env(env: Mapping[str, str] | None = None) -> Policy:
    """Configurable limits, each clamped to a sane range so a typo cannot disable a protection."""
    env = os.environ if env is None else env
    return Policy(
        length=_int(env, "OTP_LENGTH", 6, 4, 10),
        ttl_minutes=_int(env, "OTP_TTL_MINUTES", 10, 1, 60),
        max_attempts=_int(env, "OTP_MAX_ATTEMPTS", 5, 1, 10),
        resend_cooldown_seconds=_int(env, "OTP_RESEND_COOLDOWN_SECONDS", 60, 0, 600),
        max_per_hour=_int(env, "OTP_MAX_PER_HOUR", 5, 1, 20),
    )


# --------------------------------------------------------------------------- codes
def generate_code(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def new_salt() -> str:
    return secrets.token_hex(16)


def normalize(code: object) -> str:
    """What a person typed, reduced to digits: tolerates spaces and dashes ("123 456", "123-456")."""
    return "".join(ch for ch in str(code or "") if ch.isdigit())


def hash_code(code: str, salt: str, secret: str, purpose: str, user_id: int) -> str:
    message = f"{purpose}:{user_id}:{salt}:{normalize(code)}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def code_matches(code: object, salt: str, expected_hash: str, secret: str, purpose: str, user_id: int) -> bool:
    supplied = normalize(code)
    if not supplied:
        return False
    return hmac.compare_digest(hash_code(supplied, salt, secret, purpose, user_id), expected_hash or "")


# --------------------------------------------------------------------------- decisions
@dataclass(frozen=True)
class ChallengeState:
    expires_at: datetime
    attempts: int
    used_at: Optional[datetime]


def evaluate_attempt(state: ChallengeState, code_is_right: bool, now: datetime, policy: Policy) -> tuple[str, int]:
    """Decide one verification attempt. Returns (outcome, attempts_to_store).

    outcome: "ok" | "wrong" | "expired" | "locked" | "used".
    An already-used, expired or exhausted challenge never succeeds, even with the right code (no replay)."""
    if state.used_at is not None:
        return "used", state.attempts
    if now >= state.expires_at:
        return "expired", state.attempts
    if state.attempts >= policy.max_attempts:
        return "locked", state.attempts
    if code_is_right:
        return "ok", state.attempts
    attempts = state.attempts + 1
    return ("locked" if attempts >= policy.max_attempts else "wrong"), attempts


def seconds_until_resend(last_sent_at: Optional[datetime], now: datetime, policy: Policy) -> int:
    if last_sent_at is None:
        return 0
    remaining = (last_sent_at + timedelta(seconds=policy.resend_cooldown_seconds) - now).total_seconds()
    return max(0, int(remaining + 0.999))


def over_hourly_limit(sent_times: Sequence[datetime], now: datetime, policy: Policy) -> bool:
    cutoff = now - timedelta(hours=1)
    return sum(1 for t in sent_times if t > cutoff) >= policy.max_per_hour


# --------------------------------------------------------------------------- delivery
@dataclass(frozen=True)
class Delivery:
    ok: bool
    mode: str


# Development/test only: codes "sent" in "outbox" mode land here and nowhere else (never the log, never an API).
OUTBOX: list[tuple[str, str]] = []

_NON_PRODUCTION = {"development", "dev", "local", "test", "testing"}


def delivery_mode(env: Mapping[str, str] | None = None) -> str:
    """"email" | "outbox" | "console" | "none".

    * email: real SMTP, used when SMTP_HOST and SMTP_FROM are set (the default whenever they are).
    * outbox / console: for local development only. Refused unless APP_ENV is development/dev/local/test. APP_ENV
      defaults to "production", so forgetting to set it can never leak codes.
    * none: nothing can deliver a code; the API then says so honestly instead of pretending."""
    env = os.environ if env is None else env
    requested = (env.get("OTP_DELIVERY") or "").strip().lower()
    non_prod = (env.get("APP_ENV") or "production").strip().lower() in _NON_PRODUCTION
    if requested in ("outbox", "console"):
        return requested if non_prod else "none"
    if (env.get("SMTP_HOST") or "").strip() and (env.get("SMTP_FROM") or "").strip():
        return "email"
    return "none"


def _send_smtp(email: str, code: str, ttl_minutes: int, env: Mapping[str, str]) -> None:
    message = EmailMessage()
    message["Subject"] = "Your CareBridge verification code"
    message["From"] = env["SMTP_FROM"]
    message["To"] = email
    message.set_content(
        f"Your CareBridge verification code is {code}.\n\n"
        f"It expires in {ttl_minutes} minutes and works once. CareBridge will never ask you to share it.\n"
        "If you did not ask for it, you can ignore this message."
    )
    port = int(env.get("SMTP_PORT", "587"))
    with smtplib.SMTP(env["SMTP_HOST"], port, timeout=10) as client:
        if str(env.get("SMTP_STARTTLS", "true")).lower() == "true":
            client.starttls()
        if env.get("SMTP_USERNAME") and env.get("SMTP_PASSWORD"):
            client.login(env["SMTP_USERNAME"], env["SMTP_PASSWORD"])
        client.send_message(message)


def deliver(email: str, code: str, ttl_minutes: int, env: Mapping[str, str] | None = None) -> Delivery:
    """Send a code. `ok` is True only after the provider accepted it (SMTP completed without an error): we never
    claim delivery on a failure. The code itself is never logged."""
    env = os.environ if env is None else env
    mode = delivery_mode(env)
    if mode == "none":
        return Delivery(False, mode)
    if mode == "outbox":
        OUTBOX.append((email.lower(), code))
        return Delivery(True, mode)
    if mode == "console":
        # The single, explicit exception to "never print codes": opt-in, non-production only, for local sign-in testing.
        print(f"[DEV ONLY] verification code for {email}: {code}", flush=True)
        return Delivery(True, mode)
    try:
        _send_smtp(email, code, ttl_minutes, env)
        return Delivery(True, mode)
    except (OSError, smtplib.SMTPException, ValueError, KeyError):
        logger.warning("OTP e-mail delivery failed")  # no address, no code
        return Delivery(False, mode)


def verification_required(env: Mapping[str, str] | None = None) -> bool:
    """Should NEW self-registrations have to verify their e-mail address before signing in?

    Only when it is switched on (REQUIRE_EMAIL_VERIFICATION=true) AND the server can actually deliver a code. If codes cannot be
    delivered, requiring verification would trap every new user, so it is treated as off (and the config endpoint says so)."""
    env = os.environ if env is None else env
    wanted = str(env.get("REQUIRE_EMAIL_VERIFICATION", "false")).strip().lower() in ("1", "true", "yes", "on")
    return wanted and delivery_mode(env) != "none"
