"""Resources (materials, services, funds). Organizations manage their own; administrators see and manage all."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_user
from ..services import audit

router = APIRouter(prefix="/resources", tags=["resources"])


class ResourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["material", "service", "funds"] = "material"
    category: Optional[str] = Field(default=None, max_length=200)
    quantity_total: int = Field(default=0, ge=0, le=10_000_000)
    unit: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None, max_length=2000)
    organization_id: Optional[int] = None  # administrators only


class ResourcePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    kind: Optional[Literal["material", "service", "funds"]] = None
    category: Optional[str] = Field(default=None, max_length=200)
    quantity_total: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    unit: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[Literal["available", "unavailable"]] = None


def _out(r: models.Resource, org_name: str | None, allocated: int = 0) -> dict:
    return {"id": r.id, "organization_id": r.organization_id, "organization_name": org_name, "name": r.name, "kind": r.kind,
            "category": r.category, "quantity_total": r.quantity_total, "quantity_available": r.quantity_available,
            "allocated": allocated, "unit": r.unit, "description": r.description, "status": r.status, "created_at": r.created_at}


def _allocated_map(db: Session) -> dict[int, int]:
    out: dict[int, int] = {}
    for a in db.query(models.ResourceAllocation).filter(models.ResourceAllocation.status.in_(("approved", "delivered"))).all():
        out[a.resource_id] = out.get(a.resource_id, 0) + a.quantity
    return out


def _scope(user: dict) -> int | None:
    if user["role"] == "admin":
        return None
    if user["role"] == "organization" and user.get("organization_id"):
        return user["organization_id"]
    raise HTTPException(status_code=403, detail="Resources are managed by organizations and administrators")


def _own(db: Session, user: dict, resource_id: int) -> models.Resource:
    org_id = _scope(user)
    r = db.get(models.Resource, resource_id)
    if r is None or (org_id is not None and r.organization_id != org_id):
        raise HTTPException(status_code=404, detail="Resource not found")
    return r


@router.get("/")
def list_resources(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    org_id = _scope(user)
    q = db.query(models.Resource)
    if org_id is not None:
        q = q.filter(models.Resource.organization_id == org_id)
    orgs = {o.id: o.name for o in db.query(models.Organization).all()}
    alloc = _allocated_map(db)
    return [_out(r, orgs.get(r.organization_id), alloc.get(r.id, 0)) for r in q.order_by(models.Resource.id.desc()).all()]


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_resource(body: ResourceIn, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    org_id = _scope(user)
    owner = org_id if org_id is not None else body.organization_id
    if owner is not None and db.get(models.Organization, owner) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    r = models.Resource(organization_id=owner, name=body.name.strip(), kind=body.kind, category=body.category, unit=body.unit,
                        description=body.description, quantity_total=body.quantity_total, quantity_available=body.quantity_total,
                        status="available", created_by=user["id"])
    db.add(r)
    db.flush()
    audit.record(db, user, "resource.created", "resource", r.id, {"name": r.name, "quantity": r.quantity_total})
    db.commit()
    db.refresh(r)
    return _out(r, db.get(models.Organization, owner).name if owner else None)


@router.patch("/{resource_id}")
def update_resource(resource_id: int, body: ResourcePatch, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    r = _own(db, user, resource_id)
    data = body.model_dump(exclude_unset=True)
    if "quantity_total" in data:
        allocated = _allocated_map(db).get(r.id, 0)
        if data["quantity_total"] < allocated:
            raise HTTPException(status_code=409, detail=f"{allocated} unit(s) are already allocated, so the total cannot be lower")
        r.quantity_available = data["quantity_total"] - allocated
    for k, v in data.items():
        setattr(r, k, v.strip() if isinstance(v, str) and k == "name" else v)
    audit.record(db, user, "resource.updated", "resource", r.id, {"fields": sorted(data)})
    db.commit()
    org = db.get(models.Organization, r.organization_id) if r.organization_id else None
    return _out(r, org.name if org else None, _allocated_map(db).get(r.id, 0))


@router.delete("/{resource_id}")
def delete_resource(resource_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    r = _own(db, user, resource_id)
    if db.query(models.ResourceAllocation).filter(models.ResourceAllocation.resource_id == r.id,
                                                  models.ResourceAllocation.status.in_(("approved", "delivered"))).count():
        raise HTTPException(status_code=409, detail="This resource has approved or delivered allocations. Mark it unavailable instead")
    db.query(models.ResourceAllocation).filter_by(resource_id=r.id).delete()
    audit.record(db, user, "resource.deleted", "resource", r.id, {"name": r.name})
    db.delete(r)
    db.commit()
    return {"deleted": resource_id}
