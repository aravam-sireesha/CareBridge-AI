from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user, require_admin
from ..models import Donor, Match, Need, Volunteer
from ..services import audit
from ..services.matching_rules import MODEL_VERSION, suggest_matches

router = APIRouter(prefix="/matching", tags=["matching"])


@router.get("/")
def list_matches(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(Match, Need, Donor, Volunteer).outerjoin(Need, Match.need_id == Need.id).outerjoin(
        Donor, Match.donor_id == Donor.id
    ).outerjoin(Volunteer, Match.volunteer_id == Volunteer.id)
    if user["role"] == "organization":
        query = query.filter(Need.org_id == user.get("organization_id"))
    elif user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Match review is not available for this account")
    return [
        {
            "match_id": match.id,
            "need_id": match.need_id,
            "need_category": need.category if need else None,
            "need_urgency": need.urgency if need else None,
            "donor_id": match.donor_id,
            "donor_name": donor.name if donor else None,
            "volunteer_id": match.volunteer_id,
            "volunteer_name": volunteer.name if volunteer else None,
            "score": match.score,
            "reasons": match.reasons or [],
            "status": match.status,
            "created_at": match.created_at,
        }
        for match, need, donor, volunteer in query.order_by(Match.created_at.desc()).all()
    ]


@router.post("/suggest/{need_id}")
def suggest(
    need_id: int,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    need = db.get(Need, need_id)
    if need is None:
        raise HTTPException(status_code=404, detail="Need not found")

    candidates = suggest_matches(db, need)
    saved = []
    for candidate in candidates:
        existing = (
            db.query(Match)
            .filter(
                Match.need_id == need_id,
                Match.donor_id == candidate["donor_id"],
                Match.volunteer_id == candidate["volunteer_id"],
                Match.status == "suggested",
            )
            .first()
        )
        if existing is not None:
            existing.score = candidate["score"]
            existing.reasons = candidate["reasons"]
            saved.append(
                {
                    "match_id": existing.id,
                    "score": candidate["score"],
                    "reasons": candidate["reasons"],
                    "donor_id": candidate["donor_id"],
                    "volunteer_id": candidate["volunteer_id"],
                }
            )
            continue

        match = Match(
            need_id=need_id,
            donor_id=candidate["donor_id"],
            volunteer_id=candidate["volunteer_id"],
            score=candidate["score"],
            reasons=candidate["reasons"],
            status="suggested",
        )
        db.add(match)
        db.flush()
        saved.append(
            {
                "match_id": match.id,
                "score": candidate["score"],
                "reasons": candidate["reasons"],
                "donor_id": candidate["donor_id"],
                "volunteer_id": candidate["volunteer_id"],
            }
        )
    db.commit()
    return {"need_id": need_id, "model_version": MODEL_VERSION, "suggestions": saved}


class ReviewIn(BaseModel):
    status: Literal["confirmed", "rejected"]


@router.post("/{match_id}/review")
def review(
    match_id: int,
    body: ReviewIn,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    match.status = body.status
    audit.record(db, admin, "match.reviewed", "match", match_id, {"decision": body.status, "need_id": match.need_id})
    db.commit()
    return {"status": "updated"}