from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user, require_admin
from ..models import Need, NeedAlert
from ..services import audit
from ..services.need_alerts import MODEL_VERSION, evaluate_all_open_needs

router = APIRouter(prefix="/needs", tags=["needs"])


@router.get("/alerts")
def list_alerts(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(NeedAlert, Need).join(Need, NeedAlert.need_id == Need.id)
    if user["role"] == "organization":
        query = query.filter(Need.org_id == user.get("organization_id"))
    elif user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Need alerts are not available for this account")
    return [
        {
            "alert_id": alert.id,
            "need_id": alert.need_id,
            "need_category": need.category,
            "need_urgency": need.urgency,
            "need_quantity": need.quantity,
            "need_status": need.status,
            "score": alert.score,
            "reasons": alert.reasons,
            "model_version": alert.model_version,
            "flagged_at": alert.flagged_at,
            "review_decision": alert.review_decision,
            "reviewed_at": alert.reviewed_at,
        }
        for alert, need in query.order_by(NeedAlert.flagged_at.desc()).all()
    ]


@router.post("/scan")
def scan(admin: dict = Depends(require_admin), db: Session = Depends(get_db)):
    results = evaluate_all_open_needs(db)
    saved = []
    for result in results:
        existing = (
            db.query(NeedAlert)
            .filter(
                NeedAlert.need_id == result["need_id"],
                NeedAlert.review_decision.is_(None),
            )
            .first()
        )
        if existing is not None:
            existing.score = result["score"]
            existing.reasons = result["reasons"]
            saved.append({"alert_id": existing.id, **result})
            continue

        alert = NeedAlert(
            need_id=result["need_id"],
            score=result["score"],
            reasons=result["reasons"],
            model_version=MODEL_VERSION,
        )
        db.add(alert)
        db.flush()
        saved.append({"alert_id": alert.id, **result})

    db.commit()
    return {"alerts": saved}


class ReviewIn(BaseModel):
    decision: Literal["action_taken", "dismissed"]


@router.post("/alerts/{alert_id}/review")
def review(
    alert_id: int,
    body: ReviewIn,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    alert = db.get(NeedAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.reviewed_by = admin["id"]
    alert.review_decision = body.decision
    alert.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    audit.record(db, admin, "need_alert.reviewed", "need_alert", alert_id, {"decision": body.decision, "need_id": alert.need_id})
    db.commit()
    return {"status": "reviewed"}