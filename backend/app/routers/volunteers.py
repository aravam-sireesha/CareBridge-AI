from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_user

router = APIRouter()


@router.post("/", response_model=schemas.VolunteerOut)
def create_volunteer(
    volunteer: schemas.VolunteerCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user["role"] not in ("organization", "admin"):
        raise HTTPException(status_code=403, detail="Only organization and admin accounts can add volunteer records")
    db_volunteer = models.Volunteer(**volunteer.model_dump(), organization_id=user.get("organization_id"))
    db.add(db_volunteer)
    db.commit()
    db.refresh(db_volunteer)
    return db_volunteer


@router.get("/", response_model=List[schemas.VolunteerOut])
def list_volunteers(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(models.Volunteer)
    if user["role"] == "organization":
        query = query.filter(models.Volunteer.organization_id == user.get("organization_id"))
    elif user["role"] == "volunteer":
        query = query.filter(models.Volunteer.id == user.get("volunteer_id"))
    elif user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Volunteer directory is unavailable")
    return query.all()
