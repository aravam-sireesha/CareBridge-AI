"""Administration module: admin sign-up / sign-in, organization-need management and ML donor suggestions."""
import hashlib
import logging
import os
import secrets
from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .. import auth as auth_service
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_user, require_admin
from ..services import audit, donor_ml, security
from .auth import _user_payload

router = APIRouter(prefix="/admin", tags=["administration"])
logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _profile(admin: models.Administrator) -> dict:
    return {
        "id": admin.id, "user_id": admin.user_id, "full_name": admin.full_name, "phone": admin.phone,
        "designation": admin.designation, "is_active": admin.is_active,
        "last_login_at": admin.last_login_at, "created_at": admin.created_at,
    }


def ensure_admin_profile(db: Session, user: models.User) -> models.Administrator:
    """Administrators created with scripts/create_admin.py have no profile row yet; create it lazily."""
    admin = db.query(models.Administrator).filter(models.Administrator.user_id == user.id).first()
    if admin is None:
        admin = models.Administrator(user_id=user.id, full_name=user.email.split("@", 1)[0], is_active=True)
        db.add(admin)
        db.flush()
    return admin


def active_admin(user: dict = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    db_user = db.get(models.User, user["id"])
    admin = ensure_admin_profile(db, db_user)
    if not admin.is_active:
        raise HTTPException(status_code=403, detail="This administrator account has been deactivated")
    db.commit()
    return {**user, "admin_id": admin.id}


# --------------------------------------------------------------------------- sign up / sign in
def _admin_exists(db: Session) -> bool:
    return db.query(models.User.id).filter(models.User.role == "admin").first() is not None


def _create_admin(db: Session, body) -> models.User:
    if db.query(models.User).filter(func.lower(models.User.email) == body.email.lower()).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    try:
        user = models.User(email=body.email, hashed_password=auth_service.hash_password(body.password), role="admin")
        db.add(user)
        db.flush()
        db.add(models.Administrator(user_id=user.id, full_name=body.full_name.strip(), phone=body.phone,
                                    designation=body.designation, is_active=True))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Admin creation failed")
        raise HTTPException(status_code=500, detail=f"Database error: {getattr(exc, 'orig', exc)}") from exc
    db.refresh(user)
    return user


SETUP_LOCK_KEY = 724_018_001   # PostgreSQL advisory lock: only one setup request runs at a time
MIN_SETUP_TOKEN_LENGTH = 24


def _setup_token() -> str:
    """The one-time setup token lives only in backend/.env (never in the database). Too short = setup stays closed."""
    token = (os.getenv("ADMIN_SETUP_TOKEN") or "").strip()
    if token and len(token) < MIN_SETUP_TOKEN_LENGTH:
        logger.warning("ADMIN_SETUP_TOKEN is shorter than %d characters; first-administrator setup is disabled", MIN_SETUP_TOKEN_LENGTH)
        return ""
    return token


@router.get("/setup-status", dependencies=[Depends(security.auth_rate_limit)])
def setup_status(db: Session = Depends(get_db)):
    """Lets the setup page know whether it may be used: needs a configured token and NO administrator yet."""
    return {"setup_open": bool(_setup_token()) and not _admin_exists(db)}


@router.post("/setup", status_code=status.HTTP_201_CREATED, dependencies=[Depends(security.auth_rate_limit)])
def setup_first_admin(body: schemas.AdminSetup, request: Request, db: Session = Depends(get_db)):
    """Create the very first administrator. Single use: once any administrator exists this returns 404 forever.
    Further administrators are added by a signed-in administrator (POST /admin/administrators)."""
    expected = _setup_token()
    if not expected:
        raise HTTPException(status_code=404, detail="Not found")
    if db.get_bind().dialect.name == "postgresql":
        # Held until commit/rollback: a second concurrent request waits here, then finds the admin and stops.
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SETUP_LOCK_KEY})
    if _admin_exists(db):
        raise HTTPException(status_code=404, detail="Not found")
    given = hashlib.sha256(body.setup_token.strip().encode()).digest()
    if not secrets.compare_digest(given, hashlib.sha256(expected.encode()).digest()):
        audit.record_now(db, None, "admin.setup_failed", detail={"reason": "invalid setup token"})
        raise HTTPException(status_code=403, detail="Invalid setup token")
    if body.password != body.confirm_password:
        raise HTTPException(status_code=422, detail="The two passwords do not match")
    problems = security.password_problems(body.password, body.email)
    if problems:
        raise HTTPException(status_code=422, detail="Password is too weak: " + "; ".join(problems))
    user = _create_admin(db, body)
    created = db.query(models.Administrator).filter_by(user_id=user.id).one()
    audit.record_now(db, _actor_of(user), "admin.setup_completed", "administrator", created.id, {"email": user.email})
    return {"message": "Administrator created. Setup is now closed; remove ADMIN_SETUP_TOKEN from backend/.env.",
            "email": user.email, "role": "admin"}


@router.post("/logout")
def logout_admin(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Signs out THIS session: its token is rejected from now on, even before it would have expired."""
    revoked = security.revoke_session(db, user)
    audit.record(db, user, "admin.logout" if user.get("role") == "admin" else "auth.logout", "user", user["id"])
    db.commit()
    return {"message": "Signed out", "revoked": revoked}


def _actor_of(user: models.User) -> dict:
    return {"id": user.id, "email": user.email, "role": user.role}


def _admin_token_minutes() -> int:
    """Administrator sessions are shorter than ordinary ones (default 8 hours; ADMIN_TOKEN_MINUTES to change)."""
    try:
        return max(5, min(int(os.getenv("ADMIN_TOKEN_MINUTES") or 480), 60 * 24))
    except ValueError:
        return 480


def _complete_admin_login(db: Session, user: models.User, admin: models.Administrator) -> dict:
    security.record_success(db, user)
    admin.last_login_at = _now()
    audit.record(db, _actor_of(user), "admin.login", "administrator", admin.id)
    db.commit()
    try:
        token = auth_service.create_access_token(
            {"sub": user.email, "user_id": user.id, "role": "admin", "token_version": user.token_version or 0},
            expires_minutes=_admin_token_minutes(),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"access_token": token, "token_type": "bearer", "user": _user_payload(db, user), "admin": _profile(admin)}


def _second_factor_ok(admin: models.Administrator, code: str) -> str | None:
    """Accept a current authenticator code or an unused recovery code. Returns which kind matched."""
    secret = security.decrypt_secret(admin.totp_secret)
    if secret:
        step = security.verify_totp(secret, code, admin.totp_last_step)
        if step is not None:
            admin.totp_last_step = step
            return "totp"
    remaining = security.consume_recovery_code(admin.recovery_codes, code)
    if remaining is not None:
        admin.recovery_codes = remaining
        return "recovery"
    return None


@router.post("/login", dependencies=[Depends(security.auth_rate_limit)])
def login_admin(body: schemas.UserLogin, db: Session = Depends(get_db)):
    email = body.email.strip()
    user = db.query(models.User).filter(func.lower(models.User.email) == email.lower()).first()
    bad = HTTPException(status_code=401, detail="Invalid email or password", headers={"WWW-Authenticate": "Bearer"})
    if user is None:
        security.burn_time(body.password)
        audit.record_now(db, None, "admin.login_failed", detail={"email": email[:200], "reason": "unknown account"})
        raise bad
    security.check_not_locked(user)
    if not auth_service.verify_password(body.password, user.hashed_password):
        locked = security.record_failure(db, user)
        audit.record_now(db, _actor_of(user), "auth.account_locked" if locked else "admin.login_failed", detail={"reason": "wrong password"})
        if locked:
            security.check_not_locked(user)
        raise bad
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="This account is not an administrator account. Use the normal sign-in page.")
    admin = ensure_admin_profile(db, user)
    if not admin.is_active:
        raise HTTPException(status_code=403, detail="This administrator account has been deactivated")
    if admin.totp_enabled:  # password is right; the second step finishes the sign-in
        db.commit()
        return {"mfa_required": True, "mfa_token": security.create_mfa_token(user.id)}
    return _complete_admin_login(db, user, admin)


class MfaVerify(BaseModel):
    mfa_token: str = Field(min_length=10, max_length=2000)
    code: str = Field(min_length=6, max_length=20)


@router.post("/login/verify", dependencies=[Depends(security.auth_rate_limit)])
def login_admin_verify(body: MfaVerify, db: Session = Depends(get_db)):
    user = db.get(models.User, security.read_mfa_token(body.mfa_token))
    admin = db.query(models.Administrator).filter_by(user_id=user.id).first() if user else None
    if user is None or admin is None or not admin.totp_enabled or user.role != "admin":
        raise HTTPException(status_code=401, detail="Invalid verification token")
    if not admin.is_active:
        raise HTTPException(status_code=403, detail="This administrator account has been deactivated")
    security.check_not_locked(user)
    kind = _second_factor_ok(admin, body.code)
    if kind is None:
        db.rollback()
        locked = security.record_failure(db, user)
        audit.record_now(db, _actor_of(user), "auth.account_locked" if locked else "admin.mfa_failed")
        if locked:
            security.check_not_locked(user)
        raise HTTPException(status_code=401, detail="That code is not correct. Check the time on your phone and try again.")
    if kind == "recovery":
        audit.record(db, _actor_of(user), "admin.recovery_code_used", "administrator", admin.id,
                     {"codes_left": len(admin.recovery_codes or [])})
    return _complete_admin_login(db, user, admin)


# --------------------------------------------------------------------------- two-step verification (TOTP)
class CodeBody(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class PasswordBody(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class DisableBody(PasswordBody):
    code: str = Field(min_length=6, max_length=20)


def _me(db: Session, admin: dict) -> tuple[models.User, models.Administrator]:
    return db.get(models.User, admin["id"]), db.get(models.Administrator, admin["admin_id"])


@router.get("/2fa/status")
def twofa_status(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    _, profile = _me(db, admin)
    return {"enabled": bool(profile.totp_enabled), "recovery_codes_left": len(profile.recovery_codes or [])}


@router.post("/2fa/setup")
def twofa_setup(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    user, profile = _me(db, admin)
    if profile.totp_enabled:
        raise HTTPException(status_code=409, detail="Two-step verification is already on. Turn it off first to set it up again.")
    secret = security.new_totp_secret()
    profile.totp_secret = security.encrypt_secret(secret)
    db.commit()
    return {"secret": secret, "otpauth_uri": security.provisioning_uri(secret, user.email)}


@router.post("/2fa/enable")
def twofa_enable(body: CodeBody, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    user, profile = _me(db, admin)
    secret = security.decrypt_secret(profile.totp_secret)
    if profile.totp_enabled or not secret:
        raise HTTPException(status_code=409, detail="Start the setup first")
    step = security.verify_totp(secret, body.code)
    if step is None:
        raise HTTPException(status_code=400, detail="That code is not correct. Check the time on your phone and try again.")
    plain, hashed = security.new_recovery_codes()
    profile.totp_enabled, profile.totp_last_step, profile.recovery_codes = True, step, hashed
    audit.record(db, _actor_of(user), "admin.2fa_enabled", "administrator", profile.id)
    db.commit()
    return {"enabled": True, "recovery_codes": plain}


@router.post("/2fa/disable")
def twofa_disable(body: DisableBody, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    user, profile = _me(db, admin)
    if not auth_service.verify_password(body.password, user.hashed_password) or _second_factor_ok(profile, body.code) is None:
        db.rollback()
        security.record_failure(db, user)
        audit.record_now(db, _actor_of(user), "admin.2fa_disable_failed")
        raise HTTPException(status_code=400, detail="Your password or code is not correct")
    profile.totp_enabled, profile.totp_secret, profile.totp_last_step, profile.recovery_codes = False, None, None, None
    audit.record(db, _actor_of(user), "admin.2fa_disabled", "administrator", profile.id)
    db.commit()
    return {"enabled": False}


@router.post("/2fa/recovery-codes")
def twofa_new_recovery_codes(body: PasswordBody, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    user, profile = _me(db, admin)
    if not profile.totp_enabled:
        raise HTTPException(status_code=409, detail="Turn on two-step verification first")
    if not auth_service.verify_password(body.password, user.hashed_password):
        security.record_failure(db, user)
        raise HTTPException(status_code=400, detail="Your password is not correct")
    plain, hashed = security.new_recovery_codes()
    profile.recovery_codes = hashed
    audit.record(db, _actor_of(user), "admin.recovery_codes_regenerated", "administrator", profile.id)
    db.commit()
    return {"recovery_codes": plain}


@router.get("/me")
def me(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    return _profile(db.get(models.Administrator, admin["admin_id"]))


# --------------------------------------------------------------------------- helpers
def _suggestion_out(s: models.DonorSuggestion, donor: models.Donor | None, need: models.Need | None,
                    org: models.Organization | None) -> dict:
    return {
        "id": s.id, "need_id": s.need_id, "need_category": need.category if need else None,
        "need_urgency": need.urgency if need else None, "need_quantity": need.quantity if need else None,
        "organization_name": org.name if org else None,
        "donor_id": s.donor_id, "donor_name": donor.name if donor else None,
        "donor_contact": donor.contact if donor else None, "donor_preferences": donor.preferences if donor else None,
        "fit_score": s.fit_score, "urgency_score": s.urgency_score, "priority_score": s.priority_score,
        "rank_in_need": s.rank_in_need, "reasons": s.reasons or [], "model_version": s.model_version,
        "status": s.status, "created_at": s.created_at, "reviewed_at": s.reviewed_at,
    }


def _suggestion_rows(db: Session):
    return (
        db.query(models.DonorSuggestion, models.Donor, models.Need, models.Organization)
        .outerjoin(models.Donor, models.DonorSuggestion.donor_id == models.Donor.id)
        .outerjoin(models.Need, models.DonorSuggestion.need_id == models.Need.id)
        .outerjoin(models.Organization, models.Need.org_id == models.Organization.id)
    )


def _ranked_needs(db: Session, only_open: bool = False) -> list[dict]:
    now = _now()
    rows = db.query(models.Need, models.Organization).outerjoin(
        models.Organization, models.Need.org_id == models.Organization.id).all()
    counts = Counter()
    best: dict[int, float] = {}
    for sug in db.query(models.DonorSuggestion).filter(models.DonorSuggestion.status != "rejected").all():
        counts[sug.need_id] += 1
        best[sug.need_id] = max(best.get(sug.need_id, 0.0), sug.fit_score)
    out = []
    for need, org in rows:
        is_open = (need.status or "").lower() in donor_ml.OPEN_STATUSES
        if only_open and not is_open:
            continue
        info = donor_ml.score_need(need, now)
        out.append({
            "id": need.id, "org_id": need.org_id, "organization_name": org.name if org else None,
            "organization_verified": bool(org.verified) if org else False,
            "category": need.category, "quantity": need.quantity, "urgency": need.urgency, "status": need.status,
            "created_at": need.created_at, "priority_score": info["score"], "priority_level": info["level"],
            "priority_reasons": info["reasons"], "suggestion_count": counts.get(need.id, 0),
            "best_fit": best.get(need.id), "is_open": is_open,
        })
    out.sort(key=lambda n: (n["is_open"], n["priority_score"]), reverse=True)
    return out


# --------------------------------------------------------------------------- overview / needs / organizations
@router.get("/overview")
def overview(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    needs = _ranked_needs(db)
    open_needs = [n for n in needs if n["is_open"]]
    sug_status = dict(db.query(models.DonorSuggestion.status, func.count(models.DonorSuggestion.id))
                      .group_by(models.DonorSuggestion.status).all())
    orgs = db.query(models.Organization).all()
    return {
        "totals": {
            "organizations": len(orgs),
            "unverified_organizations": sum(1 for o in orgs if not o.verified),
            "needs": len(needs), "open_needs": len(open_needs),
            "critical_needs": sum(1 for n in open_needs if n["priority_level"] in ("critical", "high")),
            "donors": db.query(func.count(models.Donor.id)).scalar() or 0,
            "suggestions_waiting": sug_status.get("suggested", 0),
        },
        "suggestions_by_status": sug_status,
        "needs_by_priority": dict(Counter(n["priority_level"] for n in open_needs)),
        "top_needs": open_needs[:6],
        "model": donor_ml.model_info(db),
    }


@router.get("/needs")
def list_needs(
    status_filter: str | None = Query(default=None, alias="status"),
    urgency: str | None = None,
    organization_id: int | None = None,
    admin: dict = Depends(active_admin), db: Session = Depends(get_db),
):
    needs = _ranked_needs(db)
    if status_filter:
        needs = [n for n in needs if (n["status"] or "").lower() == status_filter.lower()]
    if urgency:
        needs = [n for n in needs if (n["urgency"] or "").lower() == urgency.lower()]
    if organization_id:
        needs = [n for n in needs if n["org_id"] == organization_id]
    return needs


@router.get("/organizations")
def list_organizations(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    need_counts = Counter()
    open_counts = Counter()
    for n in db.query(models.Need).all():
        need_counts[n.org_id] += 1
        if (n.status or "").lower() in donor_ml.OPEN_STATUSES:
            open_counts[n.org_id] += 1
    return [
        {"id": o.id, "name": o.name, "contact": o.contact, "verified": bool(o.verified), "created_at": o.created_at,
         "needs": need_counts.get(o.id, 0), "open_needs": open_counts.get(o.id, 0)}
        for o in db.query(models.Organization).order_by(models.Organization.id.desc()).all()
    ]


# --------------------------------------------------------------------------- ML donor suggestions
@router.get("/model")
def model(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    return donor_ml.model_info(db)


@router.post("/needs/{need_id}/suggest-donors")
def suggest_for_need(need_id: int, top_n: int = Query(default=5, ge=1, le=20),
                     admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    need = db.get(models.Need, need_id)
    if need is None:
        raise HTTPException(status_code=404, detail="Need not found")
    if (need.status or "").lower() not in donor_ml.OPEN_STATUSES:
        raise HTTPException(status_code=409, detail="Donors can only be suggested for open or pending needs")
    candidates = donor_ml.suggest_donors(db, need, top_n=top_n)
    donor_ml.save_suggestions(db, need, candidates, admin["id"])
    db.commit()
    org = db.get(models.Organization, need.org_id) if need.org_id else None
    rows = _suggestion_rows(db).filter(models.DonorSuggestion.need_id == need_id).order_by(
        models.DonorSuggestion.rank_in_need).all()
    return {"need_id": need_id, "model_version": candidates[0]["model_version"] if candidates else None,
            "suggestions": [_suggestion_out(*r) for r in rows if r[0].status != "rejected"], "organization_name": org.name if org else None}


@router.post("/suggestions/generate")
def generate_all(limit: int = Query(default=25, ge=1, le=100), top_n: int = Query(default=3, ge=1, le=10),
                 admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    """Score every open need by priority, then suggest donors for the most urgent ones."""
    ranked = _ranked_needs(db, only_open=True)[:limit]
    ctx = donor_ml.DonorContext(db)
    learned = donor_ml.train_learned_model(db)
    created = 0
    for item in ranked:
        need = db.get(models.Need, item["id"])
        cands = donor_ml.suggest_donors(db, need, top_n=top_n, ctx=ctx, learned=learned)
        created += len(donor_ml.save_suggestions(db, need, cands, admin["id"]))
    db.commit()
    return {"needs_scanned": len(ranked), "suggestions": created, "model_version": f"{donor_ml.MODEL_VERSION}-{learned[1]['mode']}"}


@router.get("/suggestions")
def list_suggestions(status_filter: str | None = Query(default=None, alias="status"), need_id: int | None = None,
                     admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    q = _suggestion_rows(db)
    if status_filter:
        q = q.filter(models.DonorSuggestion.status == status_filter)
    if need_id:
        q = q.filter(models.DonorSuggestion.need_id == need_id)
    rows = q.order_by(models.DonorSuggestion.priority_score.desc(), models.DonorSuggestion.id.desc()).all()
    return [_suggestion_out(*r) for r in rows]


@router.post("/suggestions/{suggestion_id}/review")
def review_suggestion(suggestion_id: int, body: schemas.SuggestionReview,
                      admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    row = db.get(models.DonorSuggestion, suggestion_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    row.status = body.decision
    row.reviewed_by = admin["id"]
    row.reviewed_at = _now()
    audit.record(db, admin, "suggestion.reviewed", "donor_suggestion", row.id, {"decision": body.decision, "need_id": row.need_id, "donor_id": row.donor_id})
    db.commit()
    return {"id": row.id, "status": row.status}


# --------------------------------------------------------------------------- administrator team
@router.get("/administrators")
def list_administrators(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    rows = (db.query(models.Administrator, models.User)
            .join(models.User, models.Administrator.user_id == models.User.id)
            .order_by(models.Administrator.id).all())
    return [{**_profile(a), "email": u.email, "is_you": u.id == admin["id"]} for a, u in rows]


@router.post("/administrators", status_code=status.HTTP_201_CREATED)
def add_administrator(body: schemas.AdminCreate, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    problems = security.password_problems(body.password, body.email)
    if problems:
        raise HTTPException(status_code=422, detail="Password is too weak: " + "; ".join(problems))
    user = _create_admin(db, body)
    created = db.query(models.Administrator).filter_by(user_id=user.id).one()
    audit.record_now(db, admin, "admin.created", "administrator", created.id, {"email": user.email})
    return {**_profile(created), "email": user.email, "is_you": False}


@router.patch("/administrators/{admin_id}")
def set_administrator_active(admin_id: int, body: schemas.AdminActive, admin: dict = Depends(active_admin),
                             db: Session = Depends(get_db)):
    target = db.get(models.Administrator, admin_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Administrator not found")
    if target.user_id == admin["id"] and not body.is_active:
        raise HTTPException(status_code=409, detail="You cannot deactivate your own account")
    if not body.is_active and db.query(models.Administrator).filter(
            models.Administrator.is_active.is_(True), models.Administrator.id != admin_id).count() == 0:
        raise HTTPException(status_code=409, detail="At least one active administrator must remain")
    target.is_active = body.is_active
    audit.record(db, admin, "admin.reactivated" if body.is_active else "admin.deactivated", "administrator", admin_id)
    db.commit()
    return _profile(target)


# --------------------------------------------------------------------------- donors of every organization
def _donor_stats(db: Session) -> dict[int, dict]:
    stats: dict[int, dict] = {}
    for d in db.query(models.Donation).all():
        s = stats.setdefault(d.donor_id, {"gifts": 0, "total": 0.0, "last": None})
        s["gifts"] += 1
        s["total"] += float(d.amount or 0)
        if d.timestamp and (s["last"] is None or d.timestamp > s["last"]):
            s["last"] = d.timestamp
    return stats


def _donor_row(donor: models.Donor, org, stats: dict, pending: int, email: str | None) -> dict:
    s = stats.get(donor.id) or {"gifts": 0, "total": 0.0, "last": None}
    return {
        "id": donor.id, "name": donor.name, "contact": donor.contact, "preferences": donor.preferences,
        "location": donor.location, "organization_id": donor.organization_id,
        "organization_name": org.name if org else None, "account_email": email,
        "gifts": s["gifts"], "total_given": round(s["total"], 2), "last_gift": s["last"], "pending_suggestions": pending,
    }


@router.get("/donors")
def list_donors(organization_id: int | None = None, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    orgs = {o.id: o for o in db.query(models.Organization).all()}
    stats = _donor_stats(db)
    pending = Counter(s.donor_id for s in db.query(models.DonorSuggestion).filter_by(status="suggested").all())
    emails = {u.donor_id: u.email for u in db.query(models.User).filter(models.User.donor_id.isnot(None)).all()}
    q = db.query(models.Donor)
    if organization_id:
        q = q.filter(models.Donor.organization_id == organization_id)
    return [_donor_row(d, orgs.get(d.organization_id), stats, pending.get(d.id, 0), emails.get(d.id))
            for d in q.order_by(models.Donor.id.desc()).all()]


def _check_org(db: Session, organization_id: int | None):
    if organization_id is not None and db.get(models.Organization, organization_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")


@router.post("/donors", status_code=status.HTTP_201_CREATED)
def create_donor(body: schemas.AdminDonorIn, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    _check_org(db, body.organization_id)
    donor = models.Donor(name=body.name.strip(), contact=body.contact, preferences=body.preferences,
                         location=body.location, organization_id=body.organization_id)
    db.add(donor)
    db.flush()
    audit.record(db, admin, "donor.created", "donor", donor.id, {"name": donor.name})
    db.commit()
    db.refresh(donor)
    org = db.get(models.Organization, donor.organization_id) if donor.organization_id else None
    return _donor_row(donor, org, {}, 0, None)


@router.get("/donors/{donor_id}")
def donor_detail(donor_id: int, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    donor = db.get(models.Donor, donor_id)
    if donor is None:
        raise HTTPException(status_code=404, detail="Donor not found")
    orgs = {o.id: o for o in db.query(models.Organization).all()}
    needs = {n.id: n for n in db.query(models.Need).all()}
    gifts = db.query(models.Donation).filter_by(donor_id=donor_id).order_by(models.Donation.timestamp.desc()).all()
    email = db.query(models.User.email).filter(models.User.donor_id == donor_id).scalar()
    pending = db.query(models.DonorSuggestion).filter_by(donor_id=donor_id, status="suggested").count()
    row = _donor_row(donor, orgs.get(donor.organization_id), _donor_stats(db), pending, email)
    open_needs = [n for n in needs.values() if (n.status or "").lower() in donor_ml.OPEN_STATUSES]
    recommended = []
    for r in donor_ml.rank_needs_for_donor(db, donor, open_needs)[:5]:
        n = needs[r["need_id"]]
        recommended.append({"need_id": n.id, "category": n.category, "urgency": n.urgency, "quantity": n.quantity,
                            "organization_name": orgs[n.org_id].name if n.org_id in orgs else None,
                            "priority_score": r["priority_score"], "fit_score": r["fit_score"], "reasons": r["reasons"]})
    return {**row, "donations": [
        {"id": g.id, "amount": g.amount, "description": g.resource_description, "timestamp": g.timestamp,
         "need_category": needs[g.need_id].category if g.need_id in needs else None,
         "organization_name": orgs[needs[g.need_id].org_id].name if g.need_id in needs and needs[g.need_id].org_id in orgs else None}
        for g in gifts[:25]], "recommended_needs": recommended}


@router.patch("/donors/{donor_id}")
def update_donor(donor_id: int, body: schemas.AdminDonorPatch, admin: dict = Depends(active_admin),
                 db: Session = Depends(get_db)):
    donor = db.get(models.Donor, donor_id)
    if donor is None:
        raise HTTPException(status_code=404, detail="Donor not found")
    data = body.model_dump(exclude_unset=True)
    clear = data.pop("clear_organization", False)
    if "organization_id" in data and data["organization_id"] is not None:
        _check_org(db, data["organization_id"])
    for key, value in data.items():
        if key == "organization_id" and value is None:
            continue
        setattr(donor, key, value.strip() if isinstance(value, str) and key == "name" else value)
    if clear:
        donor.organization_id = None
    audit.record(db, admin, "donor.updated", "donor", donor_id, {"fields": sorted(list(data.keys()) + (["organization_id"] if clear else []))})
    db.commit()
    org = db.get(models.Organization, donor.organization_id) if donor.organization_id else None
    email = db.query(models.User.email).filter(models.User.donor_id == donor_id).scalar()
    return _donor_row(donor, org, _donor_stats(db), 0, email)


@router.delete("/donors/{donor_id}")
def delete_donor(donor_id: int, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    donor = db.get(models.Donor, donor_id)
    if donor is None:
        raise HTTPException(status_code=404, detail="Donor not found")
    if db.query(models.Donation).filter_by(donor_id=donor_id).count():
        raise HTTPException(status_code=409, detail="This donor has recorded donations, so the record is kept for the audit trail")
    if db.query(models.User).filter(models.User.donor_id == donor_id).count():
        raise HTTPException(status_code=409, detail="This donor has a sign-in account. Remove or change the account first")
    db.query(models.DonorSuggestion).filter_by(donor_id=donor_id).delete()
    audit.record(db, admin, "donor.deleted", "donor", donor_id, {"name": donor.name})
    db.delete(donor)
    db.commit()
    return {"deleted": donor_id}


# --------------------------------------------------------------------------- remove a need
@router.delete("/needs/{need_id}")
def delete_need(need_id: int, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    need = db.get(models.Need, need_id)
    if need is None:
        raise HTTPException(status_code=404, detail="Need not found")
    if db.query(models.Donation).filter_by(need_id=need_id).count():
        raise HTTPException(status_code=409, detail="This need has recorded donations. Mark it closed instead of deleting it")
    try:
        db.query(models.DonorSuggestion).filter_by(need_id=need_id).delete()
        audit.record(db, admin, "need.deleted", "need", need_id, {"category": need.category})
        db.delete(need)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This need is referenced by other records. Mark it closed instead") from exc
    return {"deleted": need_id}
