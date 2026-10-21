"""Admin dashboard KPIs that /dashboard/summary does not already provide. Read-only, administrators only."""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from .administration import active_admin

router = APIRouter(prefix="/admin", tags=["administration"])
OPEN_STATES = ("pending", "under_review", "info_requested")


def _count(db: Session, *filters, column=None) -> int:
    column = column if column is not None else models.User.id
    return db.query(func.count(column)).filter(*filters).scalar() or 0


@router.get("/kpis")
def kpis(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    U, O, D, N = models.User, models.Organization, models.Donation, models.Need
    pending_filter = (O.verified.isnot(True), O.verification_status.in_(OPEN_STATES))
    queue = db.query(O).filter(*pending_filter).order_by(func.coalesce(O.verification_submitted_at, O.created_at).asc()).limit(5).all()
    activity = db.query(models.AuditLog).order_by(models.AuditLog.id.desc()).limit(8).all()
    return {
        "users_total": _count(db),
        "users_active": _count(db, U.is_active.isnot(False)),
        "pending_verifications": _count(db, *pending_filter, column=O.id),
        "active_organizations": _count(db, O.verified.is_(True), column=O.id),
        "active_donors": _count(db, U.role == "donor", U.is_active.isnot(False)),
        "active_volunteers": _count(db, U.role == "volunteer", U.is_active.isnot(False)),
        "active_needs": _count(db, N.status.in_(("open", "pending")), column=N.id),
        "donations_in_progress": _count(db, D.status.in_(("pledged", "in_transit")), column=D.id),
        "donations_completed": _count(db, D.status.in_(("delivered", "confirmed")), column=D.id),
        "anomalies_outstanding": _count(db, models.DonationFlag.review_decision.is_(None), column=models.DonationFlag.id)
        + _count(db, models.NeedAlert.review_decision.is_(None), column=models.NeedAlert.id),
        "verification_queue": [{"id": o.id, "name": o.name, "status": o.verification_status, "submitted_at": o.verification_submitted_at or o.created_at} for o in queue],
        "recent_activity": [{"action": a.action, "by": a.actor_email, "entity_type": a.entity_type, "entity_id": a.entity_id, "at": a.created_at} for a in activity],
    }
