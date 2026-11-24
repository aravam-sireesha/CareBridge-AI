"""A volunteer's weekly availability, timezone, transport mode and declared carrying capacity.

    GET /availability/me        current values (plus the old free text, shown only as a reminder)
    PUT /availability/me        save a validated schedule
    GET /availability/suggest   slots PROPOSED from the old free text; nothing is saved until the volunteer saves them

Capacity is self-declared and unverified, and means the weight of donated items carried in one trip (not passenger seats).
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..services import audit, availability, locations

router = APIRouter(prefix="/availability", tags=["availability"])
CAPACITY_NOTE = "Self-declared by the volunteer and not verified. It means the weight of donated items you can carry in one trip, not passenger seats."


class AvailabilityIn(BaseModel):
    slots: list[dict[str, Any]] = Field(default_factory=list, max_length=availability.MAX_SLOTS)
    timezone: Optional[str] = Field(default=None, max_length=60)
    transport_mode: Optional[str] = Field(default=None, max_length=20)
    carry_capacity_kg: Optional[float] = None


def _me(db: Session, user: dict):
    if user["role"] != "volunteer":
        raise HTTPException(status_code=403, detail="Only volunteers have an availability profile")
    kind, volunteer = locations.profile_for(db, user)
    if volunteer is None:
        raise HTTPException(status_code=404, detail="No volunteer profile is linked to this account yet")
    return volunteer


def _describe(v) -> dict:
    slots = v.availability_slots if isinstance(v.availability_slots, list) else []
    return {"slots": slots, "has_schedule": bool(slots), "timezone": v.availability_timezone or availability.default_timezone(),
            "timezone_is_default": not v.availability_timezone, "transport_mode": v.transport_mode, "carry_capacity_kg": v.carry_capacity_kg,
            "capacity_note": CAPACITY_NOTE, "transport_modes": list(availability.TRANSPORT_MODES), "legacy_text": v.availability}


@router.get("/me")
def get_mine(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return _describe(_me(db, user))


@router.put("/me")
def save_mine(body: AvailabilityIn, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    v = _me(db, user)
    try:
        slots = availability.validate_slots(body.slots)
        tz, mode, cap = availability.validate_profile(body.timezone, body.transport_mode, body.carry_capacity_kg)
    except availability.AvailabilityError as e:
        raise HTTPException(status_code=422, detail=str(e))
    v.availability_slots, v.availability_timezone, v.transport_mode, v.carry_capacity_kg = (slots or None), tz, mode, cap
    audit.record(db, user, "availability.updated", "volunteer", v.id, {"slots": len(slots), "capacity_declared": cap is not None})
    db.commit()
    db.refresh(v)
    return _describe(v)


@router.get("/suggest")
def suggest(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return availability.suggest_from_text(_me(db, user).availability)
