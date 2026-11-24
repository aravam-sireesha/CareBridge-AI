"""Administrator alert panel: calculated from stored records (see services/alerts.py)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_admin
from ..services import alerts

router = APIRouter(prefix="/admin/alerts", tags=["admin-alerts"])


@router.get("")
def list_alerts(admin: dict = Depends(require_admin), db: Session = Depends(get_db)):
    return alerts.build_alerts(db)
