"""In-app notifications. Every endpoint is scoped to the signed-in account; there is no way to read someone else's."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_user
from ..services import notify_rules
from ..services.paging import page_meta

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _out(n: models.Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "is_read": bool(n.is_read), "created_at": n.created_at}


def _unread(db: Session, user_id: int) -> int:
    return db.query(func.count(models.Notification.id)).filter(
        models.Notification.user_id == user_id, models.Notification.is_read.is_(False)).scalar() or 0


@router.get("/")
def list_notifications(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), unread_only: bool = False,
                       kind: Optional[str] = Query(None, max_length=30), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(models.Notification).filter(models.Notification.user_id == user["id"])
    if unread_only:
        query = query.filter(models.Notification.is_read.is_(False))
    if kind:
        query = query.filter(models.Notification.kind == kind)
    total = query.count()
    rows = (query.order_by(models.Notification.created_at.desc(), models.Notification.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return {"items": [_out(n) for n in rows], "unread": _unread(db, user["id"]), **page_meta(page, page_size, total)}


@router.get("/unread-count")
def unread_count(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"unread": _unread(db, user["id"])}


class PrefsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    in_app: Optional[bool] = None
    verification: Optional[bool] = None
    donation: Optional[bool] = None
    need: Optional[bool] = None
    volunteer: Optional[bool] = None
    admin: Optional[bool] = None


@router.get("/preferences")
def get_preferences(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(models.User, user["id"])
    return {"preferences": notify_rules.merge_prefs(row.notification_prefs, {}), "always_on": ["security"],
            "email_supported": False}


@router.put("/preferences")
def set_preferences(body: PrefsIn, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(models.User, user["id"])
    try:
        merged = notify_rules.merge_prefs(row.notification_prefs, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row.notification_prefs = merged
    db.commit()
    return {"preferences": merged, "always_on": ["security"], "email_supported": False}


@router.post("/read-all")
def mark_all_read(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    changed = db.query(models.Notification).filter(
        models.Notification.user_id == user["id"], models.Notification.is_read.is_(False)).update({models.Notification.is_read: True})
    db.commit()
    return {"marked": changed, "unread": 0}


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(models.Notification, notification_id)
    if row is None or row.user_id != user["id"]:      # same answer for "missing" and "not yours"
        raise HTTPException(status_code=404, detail="Notification not found")
    row.is_read = True
    db.commit()
    return {"id": row.id, "is_read": True, "unread": _unread(db, user["id"])}
