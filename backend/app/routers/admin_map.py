"""Administrator map overview. Read-only, administrators only. The rules live in services/map_overview.py."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services import geo, map_overview
from .administration import active_admin

router = APIRouter(prefix="/admin", tags=["administration"])


@router.get("/map")
def map_overview_data(
    radius_km: Optional[float] = Query(None, gt=0, le=geo.MAX_RADIUS_KM, description="How close a volunteer must be to count as able to help"),
    admin: dict = Depends(active_admin),
    db: Session = Depends(get_db),
):
    """Pins for organizations, open needs, donors, volunteers and live deliveries, plus needs with no volunteer in range."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)   # the schema stores naive UTC
    live_rows = (
        db.query(models.DeliveryLocation, models.DeliveryTask, models.Need)
        .join(models.DeliveryTask, models.DeliveryLocation.task_id == models.DeliveryTask.id)
        .outerjoin(models.Need, models.DeliveryTask.need_id == models.Need.id)
        .filter(models.DeliveryLocation.stopped_at.is_(None), models.DeliveryLocation.latitude.isnot(None))
        .all()
    )
    live = [
        {"task_id": task.id, "status": task.status, "need_title": (need.title or need.category) if need else None,
         "latitude": loc.latitude, "longitude": loc.longitude, "accuracy_m": loc.accuracy_m, "recorded_at": loc.recorded_at}
        for loc, task, need in live_rows
    ]
    return map_overview.build_overview(
        db.query(models.Organization).all(), db.query(models.Need).all(),
        db.query(models.Donor).all(), db.query(models.Volunteer).all(),
        live, radius_km, now,
    )
