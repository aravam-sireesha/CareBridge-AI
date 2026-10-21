import hashlib
import logging
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .. import auth as auth_service
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_user, require_admin
from ..services import audit, security

router = APIRouter()
logger = logging.getLogger(__name__)


def _display_name(db: Session, user: models.User) -> str:
    """Friendly name for the UI: organization / donor / volunteer name, else the email."""
    try:
        if user.role == "admin":
            admin = db.query(models.Administrator).filter(models.Administrator.user_id == user.id).first()
            if admin and admin.full_name:
                return admin.full_name
        if user.organization_id:
            org = db.get(models.Organization, user.organization_id)
            if org and org.name:
                return org.name
        if user.donor_id:
            donor = db.get(models.Donor, user.donor_id)
            if donor and donor.name:
                return donor.name
        if user.volunteer_id:
            volunteer = db.get(models.Volunteer, user.volunteer_id)
            if volunteer and volunteer.name:
                return volunteer.name
    except Exception:  # never let a profile lookup break login
        logger.exception("Could not resolve display name for user %s", user.id)
    return user.email.split("@", maxsplit=1)[0]


def _user_payload(db: Session, user: models.User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role or "organization",
        "display_name": _display_name(db, user),
        "organization_id": user.organization_id,
        "donor_id": user.donor_id,
        "volunteer_id": user.volunteer_id,
        "created_at": user.created_at,
    }


@router.post("/register", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(security.auth_rate_limit)])
def register(user: schemas.UserRegister, db: Session = Depends(get_db)):
    existing_user = db.query(models.User).filter(models.User.email == user.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    db_user = models.User(
        email=user.email,
        hashed_password=auth_service.hash_password(user.password),
        role=user.role,
    )
    try:
        if user.role == "organization":
            organization = models.Organization(
                name=user.organization_name or user.email.split("@", maxsplit=1)[0],
                contact=user.contact or user.email,
            )
            db.add(organization)
            db.flush()
            db_user.organization_id = organization.id
        elif user.role == "donor":
            donor = models.Donor(
                name=user.name,
                contact=user.contact or user.email,
                preferences=user.preferences,
                location=user.location,
            )
            db.add(donor)
            db.flush()
            db_user.donor_id = donor.id
        else:
            volunteer = models.Volunteer(
                name=user.name,
                contact=user.contact or user.email,
                skills=user.skills,
                availability=user.availability,
                location=user.location,
            )
            db.add(volunteer)
            db.flush()
            db_user.volunteer_id = volunteer.id
        db.add(db_user)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.exception("Registration integrity error for %s", user.email)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email or profile already exists",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("DATABASE ERROR during registration for %s", user.email)
        original_error = getattr(exc, "orig", None)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {original_error if original_error else exc}",
        ) from exc
    db.refresh(db_user)
    return _user_payload(db, db_user)


def _actor(u: models.User) -> dict:
    return {"id": u.id, "email": u.email, "role": u.role}


def find_user_by_email(db: Session, email: str):
    db_user = db.query(models.User).filter(models.User.email == email).first()
    if db_user is None:  # tolerate accounts that were stored with a different e-mail casing
        db_user = db.query(models.User).filter(func.lower(models.User.email) == email.lower()).first()
    return db_user


@router.post("/login", response_model=schemas.LoginResponse, dependencies=[Depends(security.auth_rate_limit)])
def login(user: schemas.UserLogin, db: Session = Depends(get_db)):
    email = user.email.strip()
    db_user = find_user_by_email(db, email)
    if db_user is None:
        security.burn_time(user.password)
        audit.record_now(db, None, "auth.login_failed", detail={"email": email[:200], "reason": "unknown account"})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password",
                            headers={"WWW-Authenticate": "Bearer"})
    security.check_not_locked(db_user)
    if not auth_service.verify_password(user.password, db_user.hashed_password):
        locked = security.record_failure(db, db_user)
        audit.record_now(db, _actor(db_user), "auth.account_locked" if locked else "auth.login_failed", detail={"reason": "wrong password"})
        if locked:
            security.check_not_locked(db_user)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password",
                            headers={"WWW-Authenticate": "Bearer"})
    if db_user.is_active is False:
        audit.record_now(db, _actor(db_user), "auth.login_blocked", detail={"reason": "account deactivated"})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="This account has been deactivated. Please contact an administrator.")
    if security.admin_requires_mfa(db, db_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="This administrator account uses two-step verification. Please use the Administrator sign-in page.")
    security.record_success(db, db_user)

    try:
        access_token = auth_service.create_access_token(
            {
                "sub": db_user.email,
                "user_id": db_user.id,
                "role": db_user.role or "organization",
                "token_version": db_user.token_version or 0,
            }
        )
    except RuntimeError as exc:  # SECRET_KEY missing
        logger.error("Login failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    audit.record_now(db, _actor(db_user), "auth.login")
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": _user_payload(db, db_user),
    }


class ChangePassword(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


def _fresh_token(db_user: models.User) -> str:
    return auth_service.create_access_token({"sub": db_user.email, "user_id": db_user.id, "role": db_user.role or "organization",
                                             "token_version": db_user.token_version or 0})


@router.post("/change-password", dependencies=[Depends(security.auth_rate_limit)])
def change_password(body: ChangePassword, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Change your own password. All other devices are signed out; this one stays signed in."""
    db_user = db.get(models.User, user["id"])
    if not auth_service.verify_password(body.current_password, db_user.hashed_password):
        security.record_failure(db, db_user)
        audit.record_now(db, _actor(db_user), "auth.password_change_failed")
        raise HTTPException(status_code=400, detail="Your current password is not correct")
    problems = security.password_problems(body.new_password, db_user.email)
    if problems:
        raise HTTPException(status_code=422, detail="Choose a stronger password: " + "; ".join(problems) + ".")
    if auth_service.verify_password(body.new_password, db_user.hashed_password):
        raise HTTPException(status_code=422, detail="The new password must be different from the current one")
    db_user.hashed_password = auth_service.hash_password(body.new_password)
    db_user.password_changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db_user.token_version = (db_user.token_version or 0) + 1
    audit.record(db, _actor(db_user), "auth.password_changed")
    db.commit()
    return {"access_token": _fresh_token(db_user), "token_type": "bearer", "detail": "Password changed. Other devices were signed out."}


@router.post("/logout-all")
def logout_everywhere(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Sign out every other device and browser. This session continues with a fresh token."""
    db_user = db.get(models.User, user["id"])
    db_user.token_version = (db_user.token_version or 0) + 1
    audit.record(db, _actor(db_user), "auth.logout_all")
    db.commit()
    return {"access_token": _fresh_token(db_user), "token_type": "bearer", "detail": "Signed out of all other devices."}


def _send_reset_email(email: str, token: str) -> None:
    host = os.getenv("SMTP_HOST")
    sender = os.getenv("SMTP_FROM")
    if not host or not sender:
        raise RuntimeError("Password reset email is not configured")

    message = EmailMessage()
    message["Subject"] = "Reset your CareBridge password"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "A password reset was requested for your CareBridge account. "
        "Enter the following one-time code in the password reset form. "
        "It expires in 30 minutes:\n\n"
        f"{token}\n\nIf you did not request this, you can ignore this message."
    )
    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=10) as client:
        if os.getenv("SMTP_STARTTLS", "true").lower() == "true":
            client.starttls()
        username = os.getenv("SMTP_USERNAME")
        password = os.getenv("SMTP_PASSWORD")
        if username and password:
            client.login(username, password)
        client.send_message(message)


@router.post("/password-reset/request", dependencies=[Depends(security.auth_rate_limit)])
def request_password_reset(
    body: schemas.PasswordResetRequest,
    db: Session = Depends(get_db),
):
    if not os.getenv("SMTP_HOST") or not os.getenv("SMTP_FROM"):
        return {"message": "Password reset email is not configured. Contact your system administrator."}
    generic_response = {"message": "If an account exists for this email, a reset code will be sent."}
    user = db.query(models.User).filter(func.lower(models.User.email) == body.email.lower()).first()
    if user is None:
        return generic_response

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.user_id == user.id,
        models.PasswordResetToken.used_at.is_(None),
    ).update({models.PasswordResetToken.used_at: now})
    db.add(models.PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=now + timedelta(minutes=30),
    ))
    db.commit()
    try:
        _send_reset_email(user.email, token)
    except (OSError, RuntimeError, smtplib.SMTPException, ValueError):
        logger.warning("Password reset email delivery failed")
        db.rollback()
        db.query(models.PasswordResetToken).filter(
            models.PasswordResetToken.token_hash == token_hash
        ).delete()
        db.commit()
    return generic_response


@router.post("/users/{user_id}/reset-code")
def issue_reset_code(
    user_id: int,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Administrator-issued one-time reset code for deployments without e-mail delivery.

    The code is shown once to the administrator, who passes it to the account owner.
    It is stored hashed, expires in 30 minutes and can be used only once."""
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.user_id == user.id,
        models.PasswordResetToken.used_at.is_(None),
    ).update({models.PasswordResetToken.used_at: now})
    db.add(models.PasswordResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=now + timedelta(minutes=30),
    ))
    db.commit()
    return {"email": user.email, "token": token, "expires_in_minutes": 30}


@router.post("/password-reset/complete", dependencies=[Depends(security.auth_rate_limit)])
def complete_password_reset(
    body: schemas.PasswordResetComplete,
    db: Session = Depends(get_db),
):
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    reset = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token_hash == token_hash,
        models.PasswordResetToken.used_at.is_(None),
        models.PasswordResetToken.expires_at > now,
    ).first()
    if reset is None:
        raise HTTPException(status_code=400, detail="Reset token is invalid or expired")

    user = db.get(models.User, reset.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Reset token is invalid or expired")
    user.hashed_password = auth_service.hash_password(body.new_password)
    user.token_version += 1
    reset.used_at = now
    db.commit()
    return {"message": "Password updated. You can now sign in."}


@router.get("/me", response_model=schemas.UserOut)
def current_user(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    db_user = db.get(models.User, user["id"])
    if db_user is None:
        raise HTTPException(status_code=401, detail="User account no longer exists")
    return _user_payload(db, db_user)


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(admin: dict = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(models.User).order_by(models.User.created_at.desc()).all()
    return [_user_payload(db, u) for u in users]


@router.patch("/users/{user_id}/role", response_model=schemas.UserOut)
def update_user_role(
    user_id: int,
    body: schemas.UserRoleUpdate,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin["id"] and body.role != "admin":
        raise HTTPException(status_code=409, detail="Administrators cannot remove their own admin role")
    profile_name = user.email.split("@", maxsplit=1)[0]
    if body.role == "organization" and user.organization_id is None:
        organization = models.Organization(name=profile_name, contact=user.email)
        db.add(organization)
        db.flush()
        user.organization_id = organization.id
    elif body.role == "donor" and user.donor_id is None:
        donor = models.Donor(name=profile_name, contact=user.email)
        db.add(donor)
        db.flush()
        user.donor_id = donor.id
    elif body.role == "volunteer" and user.volunteer_id is None:
        volunteer = models.Volunteer(name=profile_name, contact=user.email)
        db.add(volunteer)
        db.flush()
        user.volunteer_id = volunteer.id
    old_role = user.role
    if body.role == "admin" and db.query(models.Administrator).filter(models.Administrator.user_id == user.id).first() is None:
        db.add(models.Administrator(user_id=user.id, full_name=profile_name, is_active=True))
    user.role = body.role
    if old_role != body.role:
        user.token_version = (user.token_version or 0) + 1      # the person signs in again with the new role
        audit.record(db, admin, "user.role_changed", "user", user.id, {"email": user.email, "from": old_role, "to": body.role})
    db.commit()
    db.refresh(user)
    return _user_payload(db, user)
