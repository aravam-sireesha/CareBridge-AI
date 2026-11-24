"""Account-recovery codes: request a code by e-mail, then trade it for a short-lived password-reset grant.

    POST /auth/otp/request  {email}        -> always the same generic answer (never reveals whether an account exists)
    POST /auth/otp/verify   {email, code}  -> {reset_token}; use it with the existing POST /auth/password-reset/complete

The decisions (length, expiry, attempts, cooldown, hourly cap) live in services/otp.py and are unit-tested there.
"""
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services import audit, otp, security

logger = logging.getLogger("carebridge.otp")
router = APIRouter(prefix="/auth/otp", tags=["auth"])

RESET_GRANT_MINUTES = 10
BAD_CODE = "The code is incorrect or has expired. Check it, or request a new one."


class OtpRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class OtpVerify(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=1, max_length=32)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _secret() -> str:
    value = (os.getenv("SECRET_KEY") or "").strip()
    if not value:
        raise HTTPException(status_code=503, detail="The server is not configured for verification codes")
    return value


def _user_by_email(db: Session, email: str):
    return db.query(models.User).filter(func.lower(models.User.email) == email.strip().lower()).first()


@router.post("/request", dependencies=[Depends(security.auth_rate_limit)])
def request_code(body: OtpRequest, db: Session = Depends(get_db)):
    policy = otp.policy_from_env()
    base = {"resend_in_seconds": policy.resend_cooldown_seconds, "code_length": policy.length}
    if otp.delivery_mode() == "none":
        # A property of the server, not of any account, so saying it reveals nothing about who is registered.
        return {**base, "delivery": "not_configured",
                "message": "This server cannot send verification codes. Ask a CareBridge administrator to issue a reset code."}
    generic = {**base, "delivery": "requested",
               "message": "If an account exists for this email, a verification code is on its way. It can take a minute to arrive."}

    secret = _secret()
    user = _user_by_email(db, body.email)
    if user is None or user.is_active is False:
        security.burn_time(body.email)          # similar timing whether or not the account exists
        return generic
    now = _now()
    recent = db.query(models.OtpChallenge).filter(
        models.OtpChallenge.user_id == user.id, models.OtpChallenge.purpose == otp.PURPOSE_PASSWORD_RESET,
        models.OtpChallenge.sent_at > now - timedelta(hours=1)).order_by(models.OtpChallenge.sent_at.desc()).all()
    if recent and otp.seconds_until_resend(recent[0].sent_at, now, policy) > 0:
        return generic                          # too soon: silently ignored, same answer
    if otp.over_hourly_limit([r.sent_at for r in recent], now, policy):
        audit.record_now(db, None, "otp.rate_limited", "user", user.id, {"purpose": otp.PURPOSE_PASSWORD_RESET})
        return generic

    # only one live code per account: retire earlier ones
    db.query(models.OtpChallenge).filter(
        models.OtpChallenge.user_id == user.id, models.OtpChallenge.purpose == otp.PURPOSE_PASSWORD_RESET,
        models.OtpChallenge.used_at.is_(None)).update({models.OtpChallenge.used_at: now}, synchronize_session=False)
    code, salt = otp.generate_code(policy.length), otp.new_salt()
    challenge = models.OtpChallenge(
        user_id=user.id, purpose=otp.PURPOSE_PASSWORD_RESET, salt=salt, attempts=0, sent_at=now,
        code_hash=otp.hash_code(code, salt, secret, otp.PURPOSE_PASSWORD_RESET, user.id),
        expires_at=now + timedelta(minutes=policy.ttl_minutes))
    db.add(challenge)
    db.commit()
    result = otp.deliver(user.email, code, policy.ttl_minutes)
    if not result.ok:                           # never leave a usable code behind that nobody received
        db.delete(challenge)
        db.commit()
    else:
        audit.record_now(db, None, "otp.sent", "user", user.id, {"purpose": otp.PURPOSE_PASSWORD_RESET, "via": result.mode})
    return generic


@router.post("/verify", dependencies=[Depends(security.auth_rate_limit)])
def verify_code(body: OtpVerify, db: Session = Depends(get_db)):
    policy = otp.policy_from_env()
    secret = _secret()
    user = _user_by_email(db, body.email)
    challenge = None
    if user is not None:
        # lock the row so two parallel guesses cannot both read the same attempt count
        challenge = (db.query(models.OtpChallenge)
                     .filter(models.OtpChallenge.user_id == user.id, models.OtpChallenge.purpose == otp.PURPOSE_PASSWORD_RESET,
                             models.OtpChallenge.used_at.is_(None))
                     .order_by(models.OtpChallenge.sent_at.desc()).with_for_update().first())
    if user is None or challenge is None:
        security.burn_time(body.code)
        raise HTTPException(status_code=400, detail=BAD_CODE)

    now = _now()
    right = otp.code_matches(body.code, challenge.salt, challenge.code_hash, secret, otp.PURPOSE_PASSWORD_RESET, user.id)
    outcome, attempts = otp.evaluate_attempt(otp.ChallengeState(challenge.expires_at, challenge.attempts, challenge.used_at), right, now, policy)
    challenge.attempts = attempts
    if outcome != "ok":
        if outcome in ("expired", "locked", "used"):
            challenge.used_at = now             # burned: a new code must be requested
            audit.record(db, None, f"otp.{outcome}", "user", user.id, {"purpose": otp.PURPOSE_PASSWORD_RESET})
        db.commit()                             # persist the attempt count BEFORE refusing
        raise HTTPException(status_code=400, detail=BAD_CODE)

    challenge.used_at = now
    token = secrets.token_urlsafe(32)
    db.query(models.PasswordResetToken).filter(models.PasswordResetToken.user_id == user.id, models.PasswordResetToken.used_at.is_(None)).update({models.PasswordResetToken.used_at: now}, synchronize_session=False)
    db.add(models.PasswordResetToken(user_id=user.id, token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=now + timedelta(minutes=RESET_GRANT_MINUTES)))
    audit.record(db, None, "otp.verified", "user", user.id, {"purpose": otp.PURPOSE_PASSWORD_RESET})
    db.commit()
    return {"reset_token": token, "expires_in_minutes": RESET_GRANT_MINUTES}
