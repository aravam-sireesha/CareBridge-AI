from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user, require_admin
from ..models import DeliveryTask, Donor, Match, Need, Organization, Volunteer
from ..services import audit, delivery_flow, geo, locations
from ..services.matching_rules import MODEL_VERSION, explain_unmatched, fit_band, rank_candidates, suggest_matches

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


@router.get("/center/{need_id}")
def matching_center(need_id: int, when: Optional[str] = Query(None, max_length=40), weight_kg: Optional[float] = Query(None, gt=0, le=5000),
                    user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """The Matching Center for one need: ranked donors and volunteers with reasons, or an honest explanation of why not.

    An organization sees its OWN donors and volunteers plus anyone an administrator has recommended for this need.
    Nothing here assigns, commits or approves anyone: a recommendation is only a suggestion to review."""
    if user["role"] not in ("organization", "admin"):
        raise HTTPException(status_code=403, detail="Only organizations and administrators can use the Matching Center")
    need = db.get(Need, need_id)
    if need is None or (user["role"] == "organization" and need.org_id != user.get("organization_id")):
        raise HTTPException(status_code=404, detail="Need not found")
    organization = db.get(Organization, need.org_id) if need.org_id else None
    origin = geo.need_point(need, organization)

    donors = {d.id: d for d in locations.people_visible_to(db, user, "donor")}
    volunteers = {v.id: v for v in locations.people_visible_to(db, user, "volunteer")}
    for m in db.query(Match).filter(Match.need_id == need_id).all():      # administrator recommendations
        if m.donor_id and m.donor_id not in donors and (d := db.get(Donor, m.donor_id)):
            donors[d.id] = d
        if m.volunteer_id and m.volunteer_id not in volunteers and (v := db.get(Volunteer, m.volunteer_id)):
            volunteers[v.id] = v

    context = None
    if when or weight_kg:                                      # optional: check declared availability and carrying capacity
        moment = None
        if when:
            try:
                moment = datetime.fromisoformat(when.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(status_code=422, detail="Enter the pickup time as a date and time, for example 2026-11-02T10:30.")
            if moment.tzinfo is not None:
                moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
        context = {"when": moment, "weight_kg": weight_kg}
    ranked = rank_candidates(need, list(donors.values()), list(volunteers.values()), origin, context)
    tasks = [(t.status, t.quantity, t.received_quantity) for t in db.query(DeliveryTask).filter(DeliveryTask.need_id == need_id).all()]
    remaining = delivery_flow.remaining_for_need(need.quantity, tasks)

    def shape(c, kind):
        person = (donors if kind == "donor" else volunteers)[c["donor_id"] if kind == "donor" else c["volunteer_id"]]
        return {"id": person.id, "name": person.name, "score": c["score"], "fit": fit_band(c["score"]), "reasons": c["reasons"],
                "distance_label": c.get("distance_label"),
                "source": "your organization" if person.organization_id == need.org_id else "recommended by an administrator"}

    out_donors = [shape(c, "donor") for c in ranked["candidates"] if c["donor_id"]]
    out_vols = [shape(c, "volunteer") for c in ranked["candidates"] if c["volunteer_id"]]
    unmatched = [] if (out_donors and out_vols) else explain_unmatched(need, ranked["stats"], remaining, origin is not None)
    return {
        "need": {"id": need.id, "title": need.title, "category": need.category, "urgency": need.urgency, "quantity": need.quantity},
        "remaining_quantity": remaining, "donors": out_donors, "volunteers": out_vols,
        "unmatched": [u for u in unmatched if (u["kind"] == "general" or (u["kind"] == "donor" and not out_donors) or (u["kind"] == "volunteer" and not out_vols))],
        "stats": ranked["stats"], "model_version": MODEL_VERSION,
        "note": "These are suggestions from transparent rules, not approvals. Fit bands are thresholds on a weighted score, not probabilities. The donor must commit and the volunteer must accept.",
    }
