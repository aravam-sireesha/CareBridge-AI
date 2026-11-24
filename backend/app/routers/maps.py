"""Map services: address search, geocoding, and road route + traffic-aware ETA for a delivery.

Privacy rules (the point of this file):
* Route endpoints reuse the delivery serializer's `points`, so a destination is usable only at the stages and by the people the
  delivery view already shows it to. A request for a place the person may not see is answered "not found", like a missing delivery.
* A volunteer routes from their OWN position. Everyone else (organization, donor, administrator) routes from the volunteer's
  position ROUNDED to ~11 m, exactly what they can already see, and only while the volunteer is sharing and the position is fresh.
* The response never contains the origin coordinates, only distance, durations, arrival time and the route line.
* Search/route calls are rate-limited per account, because each one is billable.
"""
from __future__ import annotations

import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_user
from ..services import delivery_flow as flow, geocoding, ratelimit, routing, tracking
from ..services.maps_http import MapsError
from .deliveries import _actor, _now, _scoped, _serialize, _view

router = APIRouter(prefix="/maps", tags=["maps"])

_STATUS = {"not_configured": 503, "unavailable": 503, "rejected": 502, "no_route": 404, "invalid": 422}


def _http(e: MapsError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(e.code, 502), detail=e.message)


@router.get("/config")
def config(user: dict = Depends(get_current_user)):
    """Which server-side map services are switched on. (3D tiles use a browser key configured in the frontend, not here.)"""
    return {"geocoding": geocoding.enabled(os.environ), "routes": routing.enabled(os.environ)}


@router.get("/autocomplete", dependencies=[Depends(ratelimit.rate_limit("maps_ac", 40, 60))])
def autocomplete(q: str = Query(..., max_length=200), session: Optional[str] = Query(None, max_length=64),
                 lat: Optional[float] = Query(None, ge=-90, le=90), lon: Optional[float] = Query(None, ge=-180, le=180),
                 user: dict = Depends(get_current_user)):
    try:
        bias = (lat, lon) if lat is not None and lon is not None else None
        return {"suggestions": geocoding.autocomplete(q, os.environ, session_token=session, bias=bias)}
    except MapsError as e:
        raise _http(e) from None


@router.get("/place/{place_id}", dependencies=[Depends(ratelimit.rate_limit("maps_place", 20, 60))])
def place(place_id: str, session: Optional[str] = Query(None, max_length=64), user: dict = Depends(get_current_user)):
    try:
        return geocoding.place_location(place_id, os.environ, session_token=session)
    except MapsError as e:
        raise _http(e) from None


@router.get("/geocode", dependencies=[Depends(ratelimit.rate_limit("maps_geocode", 20, 60))])
def geocode(address: str = Query(..., max_length=200), user: dict = Depends(get_current_user)):
    try:
        return geocoding.geocode_address(address, os.environ)
    except MapsError as e:
        raise _http(e) from None


@router.get("/route", dependencies=[Depends(ratelimit.rate_limit("maps_route", 30, 60))])
def route(delivery_id: int = Query(..., ge=1), leg: Literal["pickup", "delivery"] = "delivery",
          mode: Literal["drive", "two_wheeler", "walk"] = "drive",
          lat: Optional[float] = Query(None, ge=-90, le=90), lon: Optional[float] = Query(None, ge=-180, le=180),
          user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Road distance, travel time and traffic-aware ETA from the volunteer's position to the pickup or delivery place."""
    task = _scoped(db, user).filter(models.DeliveryTask.id == delivery_id).first()
    rel = flow.relations(_view(task), _actor(user)) if task else set()
    if task is None or not rel:
        raise HTTPException(status_code=404, detail="Delivery not found")
    dest = _serialize(db, task, _actor(user))["points"].get(leg)             # the SAME stage rules as the delivery view
    if not dest:
        raise HTTPException(status_code=404, detail="That place is not available to you at this stage of the delivery.")
    now = _now()
    if "assigned_volunteer" in rel:
        if task.status not in tracking.HOLDING_STATUSES:
            raise HTTPException(status_code=409, detail="Routes are available while you are carrying out this delivery.")
        origin = (lat, lon) if lat is not None and lon is not None else None
        if origin is None:
            row = db.query(models.DeliveryLocation).filter(models.DeliveryLocation.task_id == task.id).first()
            if row is None or row.latitude is None:
                raise HTTPException(status_code=422, detail="Your position is needed. Turn on location sharing or allow location in your browser.")
            origin = (row.latitude, row.longitude)
    else:
        if not tracking.can_view(task.status, rel):
            raise HTTPException(status_code=404, detail="That place is not available to you at this stage of the delivery.")
        row = db.query(models.DeliveryLocation).filter(models.DeliveryLocation.task_id == task.id).first()
        if row is None or row.stopped_at is not None or row.latitude is None:
            raise HTTPException(status_code=409, detail="The volunteer is not sharing a live location, so an arrival time cannot be worked out.")
        shown = tracking.present({"latitude": row.latitude, "longitude": row.longitude, "accuracy_m": row.accuracy_m, "recorded_at": row.recorded_at}, now, rel)
        if shown.get("stale"):
            raise HTTPException(status_code=409, detail="The volunteer's last position is out of date, so an arrival time would be unreliable.")
        origin = (shown["latitude"], shown["longitude"])                       # rounded: never more exact than the viewer already sees
    try:
        result = routing.compute_route(origin, (dest["latitude"], dest["longitude"]), os.environ, mode=mode)
    except MapsError as e:
        raise _http(e) from None
    return {**result.to_dict(), "delivery_id": task.id, "leg": leg}
