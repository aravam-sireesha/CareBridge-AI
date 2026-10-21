"""Role-scoped dashboard numbers, read live from the database tables."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _month_keys(count: int = 6) -> list[str]:
    today = datetime.utcnow().replace(day=1)
    keys = []
    year, month = today.year, today.month
    for _ in range(count):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return list(reversed(keys))


@router.get("/summary")
def summary(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    role = user["role"]
    org_id = user.get("organization_id")
    donor_id = user.get("donor_id")

    # ---- needs visible to this account -------------------------------------------------
    needs_q = db.query(models.Need)
    if role == "organization":
        needs_q = needs_q.filter(models.Need.org_id == org_id)
    elif role in ("donor", "volunteer"):
        needs_q = needs_q.join(models.Organization, models.Need.org_id == models.Organization.id).filter(
            models.Organization.verified.is_(True)
        )
    needs = needs_q.order_by(models.Need.id.desc()).all()
    open_needs = [n for n in needs if (n.status or "").lower() in ("open", "pending")]

    # ---- donations visible to this account ---------------------------------------------
    donations_q = db.query(models.Donation)
    if role == "organization":
        donations_q = donations_q.join(models.Need, models.Donation.need_id == models.Need.id).filter(
            models.Need.org_id == org_id
        )
    elif role == "donor":
        donations_q = donations_q.filter(models.Donation.donor_id == donor_id)
    elif role == "volunteer":
        donations_q = donations_q.filter(models.Donation.id == -1)
    donations = donations_q.order_by(models.Donation.timestamp.desc()).all()

    month_keys = _month_keys(6)
    by_month = defaultdict(lambda: {"amount": 0.0, "count": 0})
    for d in donations:
        if d.timestamp is None:
            continue
        key = d.timestamp.strftime("%Y-%m")
        by_month[key]["amount"] += float(d.amount or 0)
        by_month[key]["count"] += 1

    # ---- counts ------------------------------------------------------------------------
    totals = {
        "children": None,
        "open_needs": len(open_needs),
        "total_needs": len(needs),
        "donors": None,
        "volunteers": None,
        "donations": len(donations),
        "donation_amount": round(sum(float(d.amount or 0) for d in donations), 2),
        "organizations": None,
        "verified_organizations": None,
    }
    if role in ("admin", "organization"):
        child_q = db.query(func.count(models.Child.id))
        donor_q = db.query(func.count(models.Donor.id))
        vol_q = db.query(func.count(models.Volunteer.id))
        if role == "organization":
            child_q = child_q.filter(models.Child.org_id == org_id)
            donor_q = donor_q.filter(models.Donor.organization_id == org_id)
            vol_q = vol_q.filter(models.Volunteer.organization_id == org_id)
        totals["children"] = child_q.scalar() or 0
        totals["donors"] = donor_q.scalar() or 0
        totals["volunteers"] = vol_q.scalar() or 0
    if role == "admin":
        totals["organizations"] = db.query(func.count(models.Organization.id)).scalar() or 0
        totals["verified_organizations"] = (
            db.query(func.count(models.Organization.id)).filter(models.Organization.verified.is_(True)).scalar() or 0
        )

    # ---- AI review queues (admin sees all, organizations see their own) ----------------
    pending = {"fraud_flags": None, "need_alerts": None, "matches": None}
    if role in ("admin", "organization"):
        alerts_q = db.query(func.count(models.NeedAlert.id)).filter(models.NeedAlert.review_decision.is_(None))
        matches_q = db.query(func.count(models.Match.id)).filter(models.Match.status.in_(("suggested", "pending_review")))
        if role == "organization":
            alerts_q = alerts_q.join(models.Need, models.NeedAlert.need_id == models.Need.id).filter(
                models.Need.org_id == org_id
            )
            matches_q = matches_q.join(models.Need, models.Match.need_id == models.Need.id).filter(
                models.Need.org_id == org_id
            )
        pending["need_alerts"] = alerts_q.scalar() or 0
        pending["matches"] = matches_q.scalar() or 0
    if role == "admin":
        pending["fraud_flags"] = (
            db.query(func.count(models.DonationFlag.id)).filter(models.DonationFlag.review_decision.is_(None)).scalar() or 0
        )

    urgency = Counter((n.urgency or "unspecified").lower() for n in needs)
    category = Counter((n.category or "Other").strip().title() for n in needs)

    knowledge_total = db.query(func.count(models.KnowledgeBase.id)).scalar() or 0
    knowledge_embedded = (
        db.query(func.count(models.KnowledgeBase.id)).filter(models.KnowledgeBase.embedding.isnot(None)).scalar() or 0
    )

    return {
        "role": role,
        "totals": totals,
        "pending_reviews": pending,
        "needs_by_urgency": dict(urgency),
        "needs_by_category": [{"category": k, "count": v} for k, v in category.most_common(6)],
        "donations_by_month": [
            {"month": key, "amount": round(by_month[key]["amount"], 2), "count": by_month[key]["count"]}
            for key in month_keys
        ],
        "recent_donations": [
            {
                "id": d.id,
                "amount": d.amount,
                "resource_description": d.resource_description,
                "timestamp": d.timestamp,
            }
            for d in donations[:5]
        ],
        "recent_needs": [
            {
                "id": n.id,
                "category": n.category,
                "urgency": n.urgency,
                "status": n.status,
                "quantity": n.quantity,
                "created_at": n.created_at,
            }
            for n in needs[:5]
        ],
        "knowledge": {"entries": knowledge_total, "embedded": knowledge_embedded},
    }
