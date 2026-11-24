from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_user

router = APIRouter()


@router.post("/", response_model=schemas.DonorOut)
def create_donor(
    donor: schemas.DonorCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user["role"] not in ("organization", "admin"):
        raise HTTPException(status_code=403, detail="Only organization and admin accounts can add donor records")
    db_donor = models.Donor(**donor.model_dump(), organization_id=user.get("organization_id"))
    db.add(db_donor)
    db.commit()
    db.refresh(db_donor)
    return db_donor


@router.get("/", response_model=List[schemas.DonorOut])
def list_donors(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(models.Donor)
    if user["role"] == "organization":
        query = query.filter(models.Donor.organization_id == user.get("organization_id"))
    elif user["role"] == "donor":
        query = query.filter(models.Donor.id == user.get("donor_id"))
    elif user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Donor directory is unavailable")
    return query.all()
