"""Organization verification workflow (administrators only). Decisions are audited and keep the verified flag in sync."""
from collections import Counter
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services import audit, verification
from ..services.notify import notify_organization
from ..services.paging import like_pattern, page_meta
from .administration import active_admin

router = APIRouter(prefix="/admin/verifications", tags=["administration"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _item(org: models.Organization, needs_count: int = 0) -> dict:
    return {
        "id": org.id, "name": org.name, "contact": org.contact, "registration_number": org.registration_number,
        "address": org.address, "website": org.website, "description": org.description,
        "status": verification.current_status(org.verification_status, org.verified), "verified": bool(org.verified),
        "note": org.verification_note, "submitted_at": org.verification_submitted_at or org.created_at,
        "verified_at": org.verified_at, "created_at": org.created_at, "needs_count": needs_count,
        "documents": [], "documents_supported": False,     # no document storage exists yet; the UI says so instead of faking one
    }


@router.get("/")
def list_verifications(q: Optional[str] = Query(None, max_length=100), status_filter: Optional[str] = Query(None, alias="status"),
                       page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                       admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    if status_filter and status_filter not in verification.STATUSES:
        raise HTTPException(status_code=422, detail="Unknown status filter")
    query = db.query(models.Organization)
    if q:
        pat = like_pattern(q)
        query = query.filter(or_(models.Organization.name.ilike(pat, escape="\\"), models.Organization.contact.ilike(pat, escape="\\"),
                                 models.Organization.registration_number.ilike(pat, escape="\\")))
    if status_filter == "verified":
        query = query.filter(models.Organization.verified.is_(True))
    elif status_filter:
        query = query.filter(models.Organization.verified.isnot(True), models.Organization.verification_status == status_filter)
    total = query.count()
    orgs = (query.order_by(func.coalesce(models.Organization.verification_submitted_at, models.Organization.created_at).desc(),
                           models.Organization.id.desc()).offset((page - 1) * page_size).limit(page_size).all())
    ids = [o.id for o in orgs]
    needs = dict(db.query(models.Need.org_id, func.count(models.Need.id)).filter(models.Need.org_id.in_(ids)).group_by(models.Need.org_id).all()) if ids else {}
    counts: Counter = Counter()
    for verified, status, n in db.query(models.Organization.verified, models.Organization.verification_status, func.count(models.Organization.id)) \
            .group_by(models.Organization.verified, models.Organization.verification_status).all():
        counts[verification.current_status(status, verified)] += n
    return {"items": [_item(o, needs.get(o.id, 0)) for o in orgs], "counts": dict(counts), **page_meta(page, page_size, total)}


@router.get("/{org_id}")
def verification_detail(org_id: int, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    org = db.get(models.Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    needs = db.query(func.count(models.Need.id)).filter(models.Need.org_id == org_id).scalar() or 0
    history = (db.query(models.AuditLog).filter(models.AuditLog.entity_type == "organization", models.AuditLog.entity_id == org_id,
                                                models.AuditLog.action.like("organization.%"))
               .order_by(models.AuditLog.id.desc()).limit(25).all())
    return {**_item(org, needs), "history": [{"action": h.action, "by": h.actor_email, "at": h.created_at, "detail": h.detail} for h in history]}


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "request_info", "under_review"]
    note: Optional[str] = Field(default=None, max_length=5000)
    expected_status: Optional[str] = Field(default=None, max_length=30)   # guards against two reviewers deciding at once


_MESSAGES = {
    "approve": ("Your organization is verified", "Your organization can now publish needs that donors and volunteers can see."),
    "reject": ("Verification was not approved", None),
    "request_info": ("More information needed for verification", None),
    "under_review": ("Your verification is under review", "An administrator is reviewing your organization."),
}


@router.post("/{org_id}/decision")
def decide(org_id: int, body: DecisionIn, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    org = db.get(models.Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    before = verification.current_status(org.verification_status, org.verified)
    if body.expected_status and body.expected_status != before:
        raise HTTPException(status_code=409, detail=f"This organization is now “{before.replace('_', ' ')}”. Refresh and review again.")
    try:
        outcome = verification.plan_decision(org.verification_status, org.verified, body.decision, body.note)
    except verification.DecisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    org.verification_status, org.verified, org.verification_note = outcome.new_status, outcome.verified, outcome.note
    if outcome.verified:
        org.verified_at = _now()
    elif before == "verified":
        org.verified_at = None
    audit.record(db, admin, f"organization.verification.{body.decision}", "organization", org.id,
                 {"name": org.name, "from": before, "to": outcome.new_status, "note": outcome.note})
    title, default_body = _MESSAGES[body.decision]
    notify_organization(db, org.id, "verification", title, outcome.note or default_body, "/dashboard")
    db.commit()
    db.refresh(org)
    return _item(org)
