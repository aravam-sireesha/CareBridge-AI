"""Public landing-page data: aggregates and verified-organization needs only. No sign-in, so nothing personal is returned:
no names or contacts of people, no free-text descriptions, no children's data."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services import security

router = APIRouter(prefix="/public", tags=["public"], dependencies=[Depends(security.public_rate_limit)])
_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _cache(response: Response) -> None:
    response.headers["Cache-Control"] = "public, max-age=60"


@router.get("/stats")
def stats(response: Response, db: Session = Depends(get_db)):
    _cache(response)
    O, N = models.Organization, models.Need
    verified_needs = db.query(N).join(O, N.org_id == O.id).filter(O.verified.is_(True))
    return {
        "verified_organizations": db.query(func.count(O.id)).filter(O.verified.is_(True)).scalar() or 0,
        "open_needs": verified_needs.filter(N.status.in_(("open", "pending"))).count(),
        "fulfilled_needs": verified_needs.filter(N.status == "fulfilled").count(),
        "confirmed_donations": db.query(func.count(models.Donation.id)).filter(models.Donation.status.in_(("delivered", "confirmed"))).scalar() or 0,
        "registered_donors": db.query(func.count(models.Donor.id)).scalar() or 0,
        "registered_volunteers": db.query(func.count(models.Volunteer.id)).scalar() or 0,
        "beneficiaries_supported": verified_needs.with_entities(func.coalesce(func.sum(N.beneficiaries), 0)).filter(N.status == "fulfilled").scalar() or 0,
    }


@router.get("/needs")
def urgent_needs(response: Response, db: Session = Depends(get_db)):
    _cache(response)
    rows = (db.query(models.Need, models.Organization.name).join(models.Organization, models.Need.org_id == models.Organization.id)
            .filter(models.Organization.verified.is_(True), models.Need.status.in_(("open", "pending")))
            .order_by(models.Need.id.desc()).limit(60).all())
    rows.sort(key=lambda r: (_RANK.get((r[0].urgency or "medium").lower(), 2), r[0].required_by is None, r[0].required_by or 0))
    return [{"id": n.id, "title": n.title or n.category, "category": n.category, "urgency": n.urgency, "quantity": n.quantity,
             "organization": name, "required_by": n.required_by} for n, name in rows[:6]]


@router.get("/organizations")
def organizations(response: Response, db: Session = Depends(get_db)):
    _cache(response)
    orgs = db.query(models.Organization).filter(models.Organization.verified.is_(True)).order_by(models.Organization.name).limit(12).all()
    return [{"id": o.id, "name": o.name, "about": (o.description or "")[:300] or None,
             "website": o.website if (o.website or "").lower().startswith(("http://", "https://")) else None} for o in orgs]
