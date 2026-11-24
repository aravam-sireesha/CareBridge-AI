from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..services import audit
from ..dependencies import get_current_user, require_admin

router = APIRouter()


@router.post("/", response_model=schemas.OrganizationOut)
def create_organization(
    organization: schemas.OrganizationCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can create organizations")
    db_organization = models.Organization(**organization.model_dump())
    db.add(db_organization)
    db.commit()
    db.refresh(db_organization)
    return db_organization


@router.get("/", response_model=List[schemas.OrganizationOut])
def list_organizations(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(models.Organization)
    if user["role"] == "organization":
        query = query.filter(models.Organization.id == user.get("organization_id"))
    elif user["role"] in ("donor", "volunteer"):
        query = query.filter(models.Organization.verified.is_(True))
    elif user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Organization directory is unavailable")
    return query.all()


@router.put("/{organization_id}", response_model=schemas.OrganizationOut)
def update_organization(
    organization_id: int,
    payload: schemas.OrganizationCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user["role"] not in ("admin", "organization"):
        raise HTTPException(status_code=403, detail="Organization profile updates are not available for this account")
    if user["role"] == "organization" and user.get("organization_id") != organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")
    organization = db.get(models.Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    organization.name = payload.name
    organization.contact = payload.contact
    db.commit()
    db.refresh(organization)
    return organization


@router.patch("/{organization_id}/verification", response_model=schemas.OrganizationOut)
def verify_organization(
    organization_id: int,
    body: schemas.OrganizationVerification,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    organization = db.get(models.Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    organization.verified = body.verified
    organization.verification_status = "verified" if body.verified else "pending"
    organization.verified_at = datetime.now(timezone.utc).replace(tzinfo=None) if body.verified else None
    audit.record(db, admin, "organization.verified" if body.verified else "organization.unverified", "organization", organization_id, {"name": organization.name})
    db.commit()
    db.refresh(organization)
    return organization
