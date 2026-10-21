from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..dependencies import get_current_user, require_admin
from ..models import Donation, DonationFlag
from ..services import audit
from ..services.fraud_rules import MODEL_VERSION, score_donation


router = APIRouter()


@router.get("/flags")
def list_flags(admin: dict = Depends(require_admin), db: Session = Depends(get_db)):
    rows = (
        db.query(DonationFlag, Donation)
        .outerjoin(Donation, DonationFlag.donation_id == Donation.id)
        .order_by(DonationFlag.flagged_at.desc(), DonationFlag.id.desc())
        .all()
    )
    return [
        {
            "flag_id": flag.id,
            "donation_id": flag.donation_id,
            "amount": donation.amount if donation else None,
            "resource_description": donation.resource_description if donation else None,
            "donor_id": donation.donor_id if donation else None,
            "score": flag.anomaly_score,
            "reasons": flag.reasons,
            "model_version": flag.model_version,
            "flagged_at": flag.flagged_at,
            "status": flag.review_decision or "suggested",
        }
        for flag, donation in rows
    ]


@router.post("/scan")
def scan_donations(admin: dict = Depends(require_admin), db: Session = Depends(get_db)):
    """Score every donation that has no flag yet and store the unusual ones for review."""
    flagged_ids = {row[0] for row in db.query(DonationFlag.donation_id).all()}
    scanned = new_flags = 0
    for donation in db.query(Donation).order_by(Donation.id).all():
        if donation.id in flagged_ids:
            continue
        scanned += 1
        result = score_donation(db, donation)
        if result is None:
            continue
        db.add(
            DonationFlag(
                donation_id=donation.id,
                anomaly_score=result["score"],
                reasons=result["reasons"],
                model_version=MODEL_VERSION,
            )
        )
        new_flags += 1
    db.commit()
    return {"scanned": scanned, "new_flags": new_flags}


@router.post("/score", response_model=schemas.FraudScoreOut)
def score_transaction(
    payload: schemas.FraudScoreRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    detector = getattr(request.app.state, "fraud_detector", None)
    if detector is None:
        raise HTTPException(status_code=503, detail="Fraud detection model is unavailable")
    try:
        return detector.score(payload.features)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/score/{donation_id}")
def score_donation_endpoint(
    donation_id: int,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    donation = db.get(Donation, donation_id)
    if donation is None:
        raise HTTPException(status_code=404, detail="Donation not found")

    result = score_donation(db, donation)
    if result is None:
        return {"flagged": False}

    flag = DonationFlag(
        donation_id=donation_id,
        anomaly_score=result["score"],
        reasons=result["reasons"],
        model_version=MODEL_VERSION,
    )
    db.add(flag)
    db.commit()
    db.refresh(flag)
    return {
        "flagged": True,
        "flag_id": flag.id,
        "score": result["score"],
        "reasons": result["reasons"],
    }


@router.post("/flags/{flag_id}/review")
def review_donation_flag(
    flag_id: int,
    decision: str,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if decision not in ("confirmed_fraud", "false_positive"):
        raise HTTPException(
            status_code=422,
            detail="decision must be confirmed_fraud or false_positive",
        )

    flag = db.get(DonationFlag, flag_id)
    if flag is None:
        raise HTTPException(status_code=404, detail="Flag not found")

    flag.reviewed_by = admin["id"]
    flag.review_decision = decision
    flag.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    audit.record(db, admin, "fraud.reviewed", "donation_flag", flag_id, {"decision": decision, "donation_id": flag.donation_id})
    db.commit()
    return {"status": "reviewed"}