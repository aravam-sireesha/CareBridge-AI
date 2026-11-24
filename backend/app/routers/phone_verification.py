"""Mobile-number verification for NEW accounts (REQUIRE_PHONE_VERIFICATION=true, and only when an SMS code can really be delivered).

    GET  /auth/phone-verification/config       what the sign-up screen needs to know (public)
    POST /auth/verify-phone/request {email}    send a code by SMS to a pending account (same generic answer for everyone)
    POST /auth/verify-phone/confirm {email, code}   trade the code for a verified number (the person then signs in normally)

Same audited code path as e-mail verification (services/otp.py): cryptographic codes, keyed hashes, expiry, attempt limits, resend
cooldown, hourly cap, no code in any response or log. The account is looked up by e-mail, never by phone, so these endpoints cannot
be used to find out which phone numbers are registered. Requesting a code never activates an account; only a correct code does.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services import audit, otp, security, sms
from .otp import BAD_CODE, OtpRequest, OtpVerify, _now, _secret, _user_by_email

router = APIRouter(tags=["auth"])
PURPOSE = otp.PURPOSE_PHONE_VERIFICATION


@router.get("/auth/phone-verification/config")
def phone_verification_config():
    return {"required": sms.verification_required(), "can_send_sms": sms.delivery_mode() != "none", "code_length": otp.policy_from_env().length}


@router.post("/auth/verify-phone/request", dependencies=[Depends(security.auth_rate_limit)])
def request_phone_verification(body: OtpRequest, db: Session = Depends(get_db)):
    policy = otp.policy_from_env()
    base = {"resend_in_seconds": policy.resend_cooldown_seconds, "code_length": policy.length}
    if sms.delivery_mode() == "none":
        return {**base, "delivery": "not_configured", "message": "This server cannot send text messages right now. Please contact a CareBridge administrator."}
    generic = {**base, "delivery": "requested", "message": "If this account is waiting for mobile verification, a code is on its way. It can take a minute to arrive."}
    secret = _secret()
    user = _user_by_email(db, body.email)
    if user is None or not user.phone_verification_pending or not user.phone_e164 or user.is_active is False:
        security.burn_time(body.email)                      # same answer and similar timing for everyone else
        return generic
    now = _now()
    recent = db.query(models.OtpChallenge).filter(models.OtpChallenge.user_id == user.id, models.OtpChallenge.purpose == PURPOSE,
                                                  models.OtpChallenge.sent_at > now - timedelta(hours=1)).order_by(models.OtpChallenge.sent_at.desc()).all()
    if (recent and otp.seconds_until_resend(recent[0].sent_at, now, policy) > 0) or otp.over_hourly_limit([r.sent_at for r in recent], now, policy):
        return generic
    db.query(models.OtpChallenge).filter(models.OtpChallenge.user_id == user.id, models.OtpChallenge.purpose == PURPOSE,
                                         models.OtpChallenge.used_at.is_(None)).update({models.OtpChallenge.used_at: now}, synchronize_session=False)
    code, salt = otp.generate_code(policy.length), otp.new_salt()
    challenge = models.OtpChallenge(user_id=user.id, purpose=PURPOSE, salt=salt, attempts=0, sent_at=now,
                                    code_hash=otp.hash_code(code, salt, secret, PURPOSE, user.id), expires_at=now + timedelta(minutes=policy.ttl_minutes))
    db.add(challenge)
    db.commit()
    result = sms.send_code(user.phone_e164, code, policy.ttl_minutes)
    if not result.ok:
        db.delete(challenge)                                # never leave a usable code that nobody received
        db.commit()
    else:
        audit.record_now(db, None, "otp.sent", "user", user.id, {"purpose": PURPOSE, "via": result.mode})
    return generic


@router.post("/auth/verify-phone/confirm", dependencies=[Depends(security.auth_rate_limit)])
def confirm_phone_verification(body: OtpVerify, db: Session = Depends(get_db)):
    policy = otp.policy_from_env()
    secret = _secret()
    user = _user_by_email(db, body.email)
    challenge = None
    if user is not None and user.phone_verification_pending:
        challenge = (db.query(models.OtpChallenge).filter(models.OtpChallenge.user_id == user.id, models.OtpChallenge.purpose == PURPOSE,
                                                          models.OtpChallenge.used_at.is_(None))
                     .order_by(models.OtpChallenge.sent_at.desc()).with_for_update().first())
    if user is None or challenge is None:
        security.burn_time(body.code)
        raise HTTPException(status_code=400, detail=BAD_CODE)
    now = _now()
    right = otp.code_matches(body.code, challenge.salt, challenge.code_hash, secret, PURPOSE, user.id)
    outcome, attempts = otp.evaluate_attempt(otp.ChallengeState(challenge.expires_at, challenge.attempts, challenge.used_at), right, now, policy)
    challenge.attempts = attempts
    if outcome != "ok":
        if outcome in ("expired", "locked", "used"):
            challenge.used_at = now
            audit.record(db, None, f"otp.{outcome}", "user", user.id, {"purpose": PURPOSE})
        db.commit()
        raise HTTPException(status_code=400, detail=BAD_CODE)
    challenge.used_at = now
    user.phone_verification_pending = False
    user.phone_verified_at = now
    audit.record(db, None, "auth.phone_verified", "user", user.id, {})
    db.commit()
    return {"verified": True}
