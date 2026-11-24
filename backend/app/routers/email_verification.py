"""E-mail verification for NEW accounts (switched on with REQUIRE_EMAIL_VERIFICATION=true, and only when e-mail can be delivered).

    GET  /auth/verification/config            what the sign-up screen needs to know (public)
    POST /auth/verify-email/request {email}   send a code to a pending account (same generic answer for everyone)
    POST /auth/verify-email/confirm {email, code}   trade the code for a verified account (the person then signs in normally)
    POST /auth/verify-email/admin/{user_id}   an administrator vouches for an account (for servers that cannot send e-mail)

It reuses the same audited helpers as password recovery (services/otp.py): cryptographic codes, keyed hashes, expiry, attempt limits,
resend cooldown, hourly cap, and no code in any response or log. Only accounts marked `email_verification_pending` are affected.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_user, require_admin
from ..services import audit, otp, security
from .otp import BAD_CODE, OtpRequest, OtpVerify, _now, _secret, _user_by_email

router = APIRouter(tags=["auth"])
PURPOSE = otp.PURPOSE_EMAIL_VERIFICATION


@router.get("/auth/verification/config")
def verification_config():
    mode = otp.delivery_mode()
    return {"required": otp.verification_required(), "can_send_email": mode != "none", "code_length": otp.policy_from_env().length}


@router.post("/auth/verify-email/request", dependencies=[Depends(security.auth_rate_limit)])
def request_verification(body: OtpRequest, db: Session = Depends(get_db)):
    policy = otp.policy_from_env()
    base = {"resend_in_seconds": policy.resend_cooldown_seconds, "code_length": policy.length}
    if otp.delivery_mode() == "none":
        return {**base, "delivery": "not_configured",
                "message": "This server cannot send verification codes. Ask a CareBridge administrator to verify your account."}
    generic = {**base, "delivery": "requested", "message": "If this account is waiting to be verified, a code is on its way. It can take a minute to arrive."}
    secret = _secret()
    user = _user_by_email(db, body.email)
    if user is None or not user.email_verification_pending or user.is_active is False:
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
    result = otp.deliver(user.email, code, policy.ttl_minutes)
    if not result.ok:
        db.delete(challenge)                                # never leave a usable code that nobody received
        db.commit()
    else:
        audit.record_now(db, None, "otp.sent", "user", user.id, {"purpose": PURPOSE, "via": result.mode})
    return generic


@router.post("/auth/verify-email/confirm", dependencies=[Depends(security.auth_rate_limit)])
def confirm_verification(body: OtpVerify, db: Session = Depends(get_db)):
    policy = otp.policy_from_env()
    secret = _secret()
    user = _user_by_email(db, body.email)
    challenge = None
    if user is not None and user.email_verification_pending:
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
    user.email_verification_pending = False
    user.email_verified_at = now
    audit.record(db, None, "auth.email_verified", "user", user.id, {})
    db.commit()
    return {"verified": True}


@router.post("/auth/verify-email/admin/{user_id}")
def verify_by_admin(user_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """For servers without e-mail: an administrator confirms they know this person. Recorded as such (not as a verified address)."""
    require_admin(user)
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    target.email_verification_pending = False
    audit.record(db, user, "auth.email_verification_waived_by_admin", "user", target.id, {})
    db.commit()
    return {"verified": False, "pending": False, "note": "Marked as allowed to sign in. The address itself was not verified."}
