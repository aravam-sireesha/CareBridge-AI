from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_user
from ..services.paging import age_group

router = APIRouter()


def _can_view_children(user: dict) -> bool:
    return user["role"] in ("admin", "organization")


@router.post("/", response_model=schemas.ChildOut, status_code=201)
def create_child(
    child: schemas.ChildCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _can_view_children(user):
        raise HTTPException(status_code=403, detail="Only organization and admin accounts can manage child records")
    # organizations always write to their own organization; admins choose one explicitly
    organization_id = child.org_id if user["role"] == "admin" else user.get("organization_id")
    if organization_id is None:
        raise HTTPException(status_code=422, detail="org_id is required")
    if user["role"] == "organization" and child.org_id not in (None, organization_id):
        raise HTTPException(status_code=404, detail="Organization not found")
    if db.get(models.Organization, organization_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    data = child.model_dump()
    data["org_id"] = organization_id
    db_child = models.Child(**data)
    db.add(db_child)
    db.commit()
    db.refresh(db_child)
    return db_child


@router.get("/", response_model=None)
def list_children(view: Literal["full", "summary"] = "full", user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """view=summary returns only an internal id, the organization and an age band: no interests, skills or school results."""
    if not _can_view_children(user):
        raise HTTPException(status_code=403, detail="Only organization and admin accounts can view child records")
    query = db.query(models.Child)
    if user["role"] == "organization":
        query = query.filter(models.Child.org_id == user.get("organization_id"))
    rows = query.order_by(models.Child.id.desc()).all()
    if view == "summary":
        return [{"id": c.id, "org_id": c.org_id, "age_group": age_group(c.age)} for c in rows]
    return [schemas.ChildOut.model_validate(c) for c in rows]


@router.get("/{child_id}", response_model=schemas.ChildOut)
def get_child(child_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if not _can_view_children(user):
        raise HTTPException(status_code=403, detail="Only organization and admin accounts can view child records")
    child = db.get(models.Child, child_id)
    if child is None or (user["role"] == "organization" and child.org_id != user.get("organization_id")):
        raise HTTPException(status_code=404, detail="Child not found")
    return child
