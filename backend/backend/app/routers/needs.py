from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_user

router = APIRouter()


def _need_dict(need: models.Need, organization_name: str | None) -> dict:
    return {
        "id": need.id,
        "org_id": need.org_id,
        "category": need.category,
        "quantity": need.quantity,
        "urgency": need.urgency,
        "status": need.status,
        "created_at": need.created_at,
        "organization_name": organization_name,
        "title": need.title,
        "description": need.description,
        "required_by": need.required_by,
        "location": need.location,
        "beneficiaries": need.beneficiaries,
        "fulfilled_at": need.fulfilled_at,
        "latitude": need.latitude,
        "longitude": need.longitude,
    }


@router.post("/", response_model=schemas.NeedOut, status_code=201)
def create_need(
    need: schemas.NeedCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user["role"] not in ("admin", "organization"):
        raise HTTPException(status_code=403, detail="Only organization and admin accounts can manage needs")
    # organizations always write to their own organization; admins choose one explicitly
    org_id = need.org_id if user["role"] == "admin" else user.get("organization_id")
    if org_id is None:
        raise HTTPException(status_code=422, detail="org_id is required")
    if user["role"] == "organization" and need.org_id not in (None, org_id):
        raise HTTPException(status_code=404, detail="Organization not found")
    organization = db.get(models.Organization, org_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    data = need.model_dump()
    data["org_id"] = org_id
    db_need = models.Need(**data, status="open")
    db.add(db_need)
    db.commit()
    db.refresh(db_need)
    return _need_dict(db_need, organization.name)


@router.get("/", response_model=List[schemas.NeedOut])
def list_needs(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(models.Need, models.Organization.name).outerjoin(
        models.Organization, models.Need.org_id == models.Organization.id
    )
    if user["role"] == "organization":
        query = query.filter(models.Need.org_id == user.get("organization_id"))
    elif user["role"] in ("donor", "volunteer"):
        query = query.filter(models.Organization.verified.is_(True))
    elif user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Needs are not available for this account")
    rows = query.order_by(models.Need.id.desc()).all()
    return [_need_dict(need, name) for need, name in rows]


@router.patch("/{need_id}", response_model=schemas.NeedOut)
def update_need(
    need_id: int,
    updates: schemas.NeedUpdate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    need = db.get(models.Need, need_id)
    if need is None or (user["role"] != "admin" and need.org_id != user.get("organization_id")):
        raise HTTPException(status_code=404, detail="Need not found")
    if user["role"] not in ("admin", "organization"):
        raise HTTPException(status_code=403, detail="Only organization and admin accounts can update needs")
    was_fulfilled = (need.status or "").lower() == "fulfilled"
    for key, value in updates.model_dump(exclude_unset=True).items():
        setattr(need, key, value)
    if (need.status or "").lower() == "fulfilled" and not was_fulfilled:
        need.fulfilled_at = datetime.now(timezone.utc).replace(tzinfo=None)   # the outcome time the prediction model learns from
    elif (need.status or "").lower() != "fulfilled":
        need.fulfilled_at = None
    db.commit()
    db.refresh(need)
    organization = db.get(models.Organization, need.org_id) if need.org_id else None
    return _need_dict(need, organization.name if organization else None)
