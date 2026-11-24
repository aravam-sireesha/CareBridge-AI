"""Users & Roles (administrators only): searchable account list, activation, and per-account audit history.
Never returns password hashes, tokens or lockout internals."""
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services import audit, verification
from ..services.paging import like_pattern, page_meta
from .administration import active_admin

router = APIRouter(prefix="/admin/users", tags=["administration"])
ROLES = ("admin", "organization", "donor", "volunteer")


def _row(user, org, donor_name, volunteer_name, admin_name, now) -> dict:
    name = (org.name if org else None) or donor_name or volunteer_name or admin_name or user.email.split("@", 1)[0]
    return {
        "id": user.id, "email": user.email, "role": user.role, "name": name, "is_active": user.is_active is not False,
        "created_at": user.created_at, "last_login_at": user.last_login_at,
        "locked": bool(user.locked_until and user.locked_until > now),
        "organization_id": user.organization_id, "donor_id": user.donor_id, "volunteer_id": user.volunteer_id,
        "verification_status": verification.current_status(org.verification_status, org.verified) if org else None,
    }


@router.get("/")
def list_users(q: Optional[str] = Query(None, max_length=100), role: Optional[str] = Query(None),
               state: Optional[Literal["active", "inactive"]] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    if role and role not in ROLES:
        raise HTTPException(status_code=422, detail="Unknown role filter")
    query = (db.query(models.User, models.Organization, models.Donor.name, models.Volunteer.name, models.Administrator.full_name)
             .outerjoin(models.Organization, models.User.organization_id == models.Organization.id)
             .outerjoin(models.Donor, models.User.donor_id == models.Donor.id)
             .outerjoin(models.Volunteer, models.User.volunteer_id == models.Volunteer.id)
             .outerjoin(models.Administrator, models.Administrator.user_id == models.User.id))
    if q:
        pat = like_pattern(q)
        query = query.filter(or_(*(col.ilike(pat, escape="\\") for col in (
            models.User.email, models.Organization.name, models.Donor.name, models.Volunteer.name, models.Administrator.full_name))))
    if role:
        query = query.filter(models.User.role == role)
    if state == "active":
        query = query.filter(models.User.is_active.isnot(False))
    elif state == "inactive":
        query = query.filter(models.User.is_active.is_(False))
    total = query.count()
    rows = query.order_by(models.User.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return {"items": [_row(u, o, d, v, a, now) for u, o, d, v, a in rows], **page_meta(page, page_size, total)}


class StatusIn(BaseModel):
    is_active: bool
    reason: Optional[str] = Field(default=None, max_length=500)


@router.patch("/{user_id}/status")
def set_status(user_id: int, body: StatusIn, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == admin["id"]:
        raise HTTPException(status_code=409, detail="You cannot change the status of your own account.")
    if target.role == "admin":
        raise HTTPException(status_code=409, detail="Administrator accounts are managed under Administrators, which protects the last active administrator.")
    if (target.is_active is not False) == body.is_active:
        return {"id": target.id, "is_active": body.is_active, "changed": False}
    target.is_active = body.is_active
    if not body.is_active:
        target.token_version = (target.token_version or 0) + 1      # sign the account out everywhere immediately
    reason = (body.reason or "").strip() or None
    audit.record(db, admin, "user.reactivated" if body.is_active else "user.deactivated", "user", target.id,
                 {"email": target.email, "role": target.role, "reason": reason})
    db.commit()
    return {"id": target.id, "is_active": body.is_active, "changed": True}


@router.get("/{user_id}/audit")
def user_audit(user_id: int, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    if db.get(models.User, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    rows = (db.query(models.AuditLog).filter(or_(models.AuditLog.actor_user_id == user_id,
                                                  (models.AuditLog.entity_type == "user") & (models.AuditLog.entity_id == user_id)))
            .order_by(models.AuditLog.id.desc()).limit(50).all())
    return [{"action": r.action, "at": r.created_at, "by": r.actor_email, "ip": r.ip, "detail": r.detail} for r in rows]
