"""Reading and writing the position a person or organization chose to share, and the queries that feed the
nearby-needs / nearby-helpers screens. The maths and privacy rounding live in services/geo.py.

Who can see what (enforced here and in routers/locations.py):
* Exact coordinates: only the owner, through GET /locations/me.
* Everyone else: a distance rounded up to whole km, never coordinates.
* An organization sees only its own donors and volunteers (the same rule as /donors and /volunteers);
  an administrator sees all.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from . import geo


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # the schema stores naive UTC


def profile_for(db: Session, user: dict) -> tuple[str, Any]:
    """(kind, record) for the signed-in account. record is None for administrators or an unlinked account."""
    role = user.get("role")
    if role == "organization" and user.get("organization_id"):
        return role, db.get(models.Organization, user["organization_id"])
    if role == "donor" and user.get("donor_id"):
        return role, db.get(models.Donor, user["donor_id"])
    if role == "volunteer" and user.get("volunteer_id"):
        return role, db.get(models.Volunteer, user["volunteer_id"])
    return role or "", None


def describe(kind: str, entity: Any) -> dict:
    """The owner's own view, the only place exact coordinates are returned."""
    place = geo.point_of(entity)
    return {
        "role": kind,
        "has_location": place is not None,
        "latitude": place.lat if place else None,
        "longitude": place.lon if place else None,
        "label": entity.address if kind == "organization" else entity.location,
        "service_radius_km": entity.service_radius_km if kind == "volunteer" else None,
        "updated_at": getattr(entity, "location_updated_at", None),
    }


def save(entity: Any, kind: str, lat: float, lon: float, radius: Optional[float], label: Optional[str]) -> None:
    """Write the position. `label` None leaves the existing text alone; an empty string clears it."""
    entity.latitude = round(float(lat), 6)
    entity.longitude = round(float(lon), 6)
    if label is not None:
        text = label.strip() or None
        if kind == "organization":
            entity.address = text
        else:
            entity.location = text
    if kind == "volunteer" and radius is not None:
        entity.service_radius_km = float(radius)
    if hasattr(entity, "location_updated_at"):
        entity.location_updated_at = _now()


def clear(entity: Any, kind: str, clear_label: bool = False) -> None:
    """Remove the shared position (and the travel range). The free-text label stays unless asked to go too."""
    entity.latitude = None
    entity.longitude = None
    if kind == "volunteer":
        entity.service_radius_km = None
    if hasattr(entity, "location_updated_at"):
        entity.location_updated_at = None
    if clear_label:
        if kind == "organization":
            entity.address = None
        else:
            entity.location = None


def open_verified_needs(db: Session) -> list[tuple[Any, Any]]:
    """(need, organization) pairs a donor or volunteer may browse: open needs of verified organizations.
    A NULL status counts as open, matching how hand-entered rows behave elsewhere in the app."""
    return (
        db.query(models.Need, models.Organization)
        .join(models.Organization, models.Need.org_id == models.Organization.id)
        .filter(models.Organization.verified.is_(True))
        .filter(or_(models.Need.status.is_(None), models.Need.status == "open"))
        .all()
    )


def people_visible_to(db: Session, user: dict, kind: str) -> list[Any]:
    """Donors or volunteers this account may see: all for an administrator, only its own for an organization."""
    model = models.Donor if kind == "donor" else models.Volunteer
    role = user.get("role")
    if role == "admin":
        return db.query(model).all()
    if role == "organization":
        org_id = user.get("organization_id")
        if not org_id:  # never filter on `organization_id IS NULL`: that would expose every unowned record
            return []
        return db.query(model).filter(model.organization_id == org_id).all()
    return []
