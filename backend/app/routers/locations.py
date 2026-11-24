"""Location: share where you are (optionally), find needs near you, find helpers near a need.

Everything here is opt-in and minimal:
* A person shares a position only by calling PUT /locations/me themselves, and can remove it at any time.
* Other people never receive coordinates, only a distance rounded UP to whole km.
* There is no background or continuous tracking. This is a saved position, not a live GPS feed.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, FiniteFloat, model_validator
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_user
from ..services import audit, geo, locations

router = APIRouter(prefix="/locations", tags=["locations"])

DISTANCE_NOTE = "Distances are straight-line and rounded up to whole kilometres. They are not road routes or travel times."


class LocationIn(BaseModel):
    latitude: FiniteFloat = Field(ge=-90, le=90)
    longitude: FiniteFloat = Field(ge=-180, le=180)
    service_radius_km: Optional[FiniteFloat] = Field(default=None, gt=0, le=geo.MAX_RADIUS_KM)
    label: Optional[str] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _real_position(self):
        if not geo.is_valid_coordinate(self.latitude, self.longitude):
            raise ValueError("Enter a real latitude and longitude (0, 0 is treated as 'no data').")
        return self


def _own_profile(db: Session, user: dict):
    if user["role"] not in ("organization", "donor", "volunteer"):
        raise HTTPException(status_code=403, detail="Administrator accounts do not have a location profile")
    kind, entity = locations.profile_for(db, user)
    if entity is None:
        raise HTTPException(status_code=404, detail="No profile record is linked to this account yet")
    return kind, entity


@router.get("/me")
def get_my_location(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    kind, entity = _own_profile(db, user)
    return locations.describe(kind, entity)


@router.put("/me")
def set_my_location(body: LocationIn, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    kind, entity = _own_profile(db, user)
    if body.service_radius_km is not None and kind != "volunteer":
        raise HTTPException(status_code=422, detail="A service radius applies to volunteers only")
    locations.save(entity, kind, body.latitude, body.longitude, body.service_radius_km, body.label)
    # The audit trail records THAT a location changed, never the coordinates themselves.
    audit.record(db, user, "location.updated", kind, entity.id, {"radius_set": body.service_radius_km is not None, "label_set": bool(body.label)})
    db.commit()
    db.refresh(entity)
    return locations.describe(kind, entity)


@router.delete("/me")
def clear_my_location(
    clear_label: bool = Query(False, description="Also remove the free-text place name"),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    kind, entity = _own_profile(db, user)
    locations.clear(entity, kind, clear_label=clear_label)
    audit.record(db, user, "location.cleared", kind, entity.id, {"label_cleared": clear_label})
    db.commit()
    db.refresh(entity)
    return locations.describe(kind, entity)


@router.get("/nearby-needs")
def nearby_needs(
    radius_km: Optional[float] = Query(None, gt=0, le=geo.MAX_RADIUS_KM),
    limit: int = Query(20, ge=1, le=50),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """For donors and volunteers: open needs of verified organizations near the position they shared."""
    if user["role"] not in ("donor", "volunteer"):
        raise HTTPException(status_code=403, detail="Only donor and volunteer accounts can search for needs near them")
    kind, entity = locations.profile_for(db, user)
    origin = geo.point_of(entity)
    if origin is None:
        return {"located": False, "radius_km": None, "count": 0, "needs": [],
                "message": "Share your location to see needs near you. You can remove it at any time."}
    own_radius = entity.service_radius_km if kind == "volunteer" else None
    radius = geo.clamp_radius(radius_km if radius_km is not None else own_radius)
    needs = geo.rank_nearby_needs(locations.open_verified_needs(db), origin, radius, limit, include_position=True)
    # `origin` is the caller's OWN saved position (they already see it in Settings); need pins are snapped to ~1 km.
    return {"located": True, "radius_km": radius, "count": len(needs), "needs": needs, "note": DISTANCE_NOTE,
            "origin": {"lat": origin.lat, "lon": origin.lon}, "pin_precision_km": 1}


@router.get("/needs/{need_id}/nearby")
def helpers_near_need(
    need_id: int,
    radius_km: Optional[float] = Query(None, gt=0, le=geo.MAX_RADIUS_KM),
    limit: int = Query(20, ge=1, le=50),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """For organizations (own needs) and administrators: donors and volunteers near one need."""
    if user["role"] not in ("organization", "admin"):
        raise HTTPException(status_code=403, detail="Only organization and administrator accounts can search for helpers near a need")
    need = db.get(models.Need, need_id)
    if need is None or (user["role"] == "organization" and need.org_id != user.get("organization_id")):
        raise HTTPException(status_code=404, detail="Need not found")  # 404, not 403: do not reveal other organizations' needs
    organization = db.get(models.Organization, need.org_id) if need.org_id else None
    origin = geo.need_point(need, organization)
    if origin is None:
        return {"need_id": need.id, "located": False, "radius_km": None, "donors": [], "volunteers": [],
                "donors_without_location": 0, "volunteers_without_location": 0,
                "message": "This need has no location yet. Set your organization's location (Settings > Location) so distances can be calculated."}
    radius = geo.clamp_radius(radius_km)
    donors, donors_missing = geo.rank_nearby_people(origin, locations.people_visible_to(db, user, "donor"), "donor", radius, limit)
    volunteers, volunteers_missing = geo.rank_nearby_people(origin, locations.people_visible_to(db, user, "volunteer"), "volunteer", radius, limit)
    return {
        "need_id": need.id, "located": True, "radius_km": radius, "distance_basis": origin.source,
        "donors": donors, "volunteers": volunteers,
        "donors_without_location": donors_missing, "volunteers_without_location": volunteers_missing,
        "origin": geo.approx_position(origin.lat, origin.lon, 4),   # the need's own place (its organization's choice); people are never pinned here
        "note": DISTANCE_NOTE,
    }
