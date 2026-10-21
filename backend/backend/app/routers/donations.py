import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_user
from ..services.notify import notify_organization

router = APIRouter(prefix="/donations", tags=["donations"])
logger = logging.getLogger(__name__)


def _can_access_need(user: dict, need: models.Need | None, db: Session) -> bool:
    if need is None:
        return False
    if user["role"] == "admin" or need.org_id == user.get("organization_id"):
        return True
    if user["role"] == "donor":
        organization = db.get(models.Organization, need.org_id)
        return bool(organization and organization.verified)
    return False


def _decorate(db: Session, rows: list) -> list[dict]:
    donor_ids = {r.donor_id for r in rows if r.donor_id}
    need_ids = {r.need_id for r in rows if r.need_id}
    donors = {d.id: d.name for d in db.query(models.Donor).filter(models.Donor.id.in_(donor_ids)).all()} if donor_ids else {}
    needs = {n.id: n.category for n in db.query(models.Need).filter(models.Need.id.in_(need_ids)).all()} if need_ids else {}
    return [
        {
            "id": r.id,
            "donor_id": r.donor_id,
            "need_id": r.need_id,
            "amount": r.amount,
            "resource_description": r.resource_description,
            "timestamp": r.timestamp,
            "donor_name": donors.get(r.donor_id),
            "need_name": needs.get(r.need_id),
        }
        for r in rows
    ]


@router.get("/", response_model=List[schemas.DonationOut])
def list_donations(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(models.Donation)
    if user["role"] == "organization":
        query = query.join(models.Need).filter(models.Need.org_id == user["organization_id"])
    elif user["role"] == "donor":
        query = query.filter(models.Donation.donor_id == user.get("donor_id"))
    elif user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Donation access is not available for this role")
    return _decorate(db, query.order_by(models.Donation.timestamp.desc(), models.Donation.id.desc()).all())


@router.post("/", response_model=schemas.DonationOut, status_code=status.HTTP_201_CREATED)
def create_donation(
    donation: schemas.DonationCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user["role"] == "donor":
        donor_id = user.get("donor_id")
        if donation.donor_id not in (None, donor_id):
            raise HTTPException(status_code=403, detail="Donors can only create records for their own account")
    elif user["role"] not in ("admin", "organization"):
        raise HTTPException(status_code=403, detail="Donation access is not available for this role")
    else:
        donor_id = donation.donor_id

    need = db.get(models.Need, donation.need_id) if donation.need_id else None
    if donation.need_id and not _can_access_need(user, need, db):
        raise HTTPException(status_code=404, detail="Need not found")
    if user["role"] == "organization" and not donation.need_id:
        raise HTTPException(status_code=422, detail="Organization donations must be linked to a need")
    donor = db.get(models.Donor, donor_id) if donor_id is not None else None
    if donor_id is not None and donor is None:
        raise HTTPException(status_code=404, detail="Donor not found")
    if user["role"] == "organization" and donor and donor.organization_id != user.get("organization_id"):
        raise HTTPException(status_code=404, detail="Donor not found")

    record = models.Donation(
        donor_id=donor_id,
        need_id=donation.need_id,
        amount=donation.amount,
        resource_description=donation.resource_description,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    if need is not None and need.org_id:        # a failed notification must never break recording a donation
        try:
            notify_organization(db, need.org_id, "donation", "New donation recorded", f"A donation was recorded for “{need.title or need.category}”.", "/donations")
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Could not create the donation notification")
    return _decorate(db, [record])[0]
