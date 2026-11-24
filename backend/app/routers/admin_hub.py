"""Administrator as the centre: the AI suggestion hub, demand forecast, and volunteer management."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services import audit, donor_ml, forecast, recommender, volunteer_ml
from .administration import active_admin

router = APIRouter(prefix="/admin", tags=["administration"])


# --------------------------------------------------------------------------- AI suggestion hub
@router.get("/entities")
def entities(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    """Compact lists of organizations, open needs, donors and volunteers for the hub's pickers."""
    return recommender.entity_options(db)


@router.get("/recommend")
def recommend(entity: str = Query(...), id: int = Query(...), top_n: int = Query(default=5, ge=1, le=15),
              admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    if entity not in recommender.ENTITIES:
        raise HTTPException(status_code=422, detail="entity must be one of: " + ", ".join(recommender.ENTITIES))
    try:
        return recommender.recommend(db, entity, id, top_n)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/forecast")
def demand_forecast(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    items = forecast.forecast_categories(db)
    return {"periods_days": forecast.PERIOD_DAYS, "items": items,
            "summary": {"categories": len(items), "high_risk": sum(1 for i in items if i["risk"] == "high"),
                        "rising": sum(1 for i in items if i["trend"] == "rising")}}


@router.get("/models")
def model_status(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    """Which ML models are in use, and whether they are still rule-based or already learning from decisions."""
    return {"donor": donor_ml.model_info(db), "volunteer": volunteer_ml.model_info(db)}


# --------------------------------------------------------------------------- volunteer suggestions
def _sug_out(s: models.VolunteerSuggestion, vol, need, org) -> dict:
    return {"id": s.id, "need_id": s.need_id, "need_category": need.category if need else None, "need_urgency": need.urgency if need else None,
            "organization_name": org.name if org else None, "volunteer_id": s.volunteer_id, "volunteer_name": vol.name if vol else None,
            "volunteer_contact": vol.contact if vol else None, "volunteer_skills": vol.skills if vol else None,
            "volunteer_availability": vol.availability if vol else None, "fit_score": s.fit_score, "urgency_score": s.urgency_score,
            "priority_score": s.priority_score, "rank_in_need": s.rank_in_need, "reasons": s.reasons or [], "model_version": s.model_version,
            "status": s.status, "created_at": s.created_at, "reviewed_at": s.reviewed_at}


def _sug_rows(db: Session):
    return (db.query(models.VolunteerSuggestion, models.Volunteer, models.Need, models.Organization)
            .outerjoin(models.Volunteer, models.VolunteerSuggestion.volunteer_id == models.Volunteer.id)
            .outerjoin(models.Need, models.VolunteerSuggestion.need_id == models.Need.id)
            .outerjoin(models.Organization, models.Need.org_id == models.Organization.id))


@router.post("/needs/{need_id}/suggest-volunteers")
def suggest_volunteers(need_id: int, top_n: int = Query(default=5, ge=1, le=20), admin: dict = Depends(active_admin),
                       db: Session = Depends(get_db)):
    need = db.get(models.Need, need_id)
    if need is None:
        raise HTTPException(status_code=404, detail="Need not found")
    if (need.status or "").lower() not in donor_ml.OPEN_STATUSES:
        raise HTTPException(status_code=409, detail="Volunteers can only be suggested for open or pending needs")
    cands = volunteer_ml.suggest_volunteers(db, need, top_n)
    volunteer_ml.save_suggestions(db, need, cands, admin["id"])
    db.commit()
    rows = _sug_rows(db).filter(models.VolunteerSuggestion.need_id == need_id).order_by(models.VolunteerSuggestion.rank_in_need).all()
    return {"need_id": need_id, "model_version": cands[0]["model_version"] if cands else None,
            "suggestions": [_sug_out(*r) for r in rows if r[0].status != "rejected"]}


@router.get("/volunteer-suggestions")
def list_volunteer_suggestions(status_filter: str | None = Query(default=None, alias="status"), admin: dict = Depends(active_admin),
                               db: Session = Depends(get_db)):
    q = _sug_rows(db)
    if status_filter:
        q = q.filter(models.VolunteerSuggestion.status == status_filter)
    return [_sug_out(*r) for r in q.order_by(models.VolunteerSuggestion.priority_score.desc()).all()]


# --------------------------------------------------------------------------- volunteers of every organization
class VolunteerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact: Optional[str] = Field(default=None, max_length=200)
    skills: Optional[str] = Field(default=None, max_length=2000)
    availability: Optional[str] = Field(default=None, max_length=200)
    location: Optional[str] = Field(default=None, max_length=200)
    organization_id: Optional[int] = None


class VolunteerPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    contact: Optional[str] = Field(default=None, max_length=200)
    skills: Optional[str] = Field(default=None, max_length=2000)
    availability: Optional[str] = Field(default=None, max_length=200)
    location: Optional[str] = Field(default=None, max_length=200)
    organization_id: Optional[int] = None
    clear_organization: bool = False


def _vol_row(v: models.Volunteer, org, matches: int, pending: int, email: str | None) -> dict:
    return {"id": v.id, "name": v.name, "contact": v.contact, "skills": v.skills, "availability": v.availability, "location": v.location,
            "organization_id": v.organization_id, "organization_name": org.name if org else None, "account_email": email,
            "matches": matches, "pending_suggestions": pending}


def _check_org(db: Session, org_id: int | None) -> None:
    if org_id is not None and db.get(models.Organization, org_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")


@router.get("/volunteers")
def list_volunteers(organization_id: int | None = None, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    orgs = {o.id: o for o in db.query(models.Organization).all()}
    matches: dict[int, int] = {}
    for m in db.query(models.Match).filter(models.Match.volunteer_id.isnot(None)).all():
        matches[m.volunteer_id] = matches.get(m.volunteer_id, 0) + 1
    pending: dict[int, int] = {}
    for s in db.query(models.VolunteerSuggestion).filter_by(status="suggested").all():
        pending[s.volunteer_id] = pending.get(s.volunteer_id, 0) + 1
    emails = {u.volunteer_id: u.email for u in db.query(models.User).filter(models.User.volunteer_id.isnot(None)).all()}
    q = db.query(models.Volunteer)
    if organization_id:
        q = q.filter(models.Volunteer.organization_id == organization_id)
    return [_vol_row(v, orgs.get(v.organization_id), matches.get(v.id, 0), pending.get(v.id, 0), emails.get(v.id)) for v in q.order_by(models.Volunteer.id.desc()).all()]


@router.post("/volunteers", status_code=status.HTTP_201_CREATED)
def create_volunteer(body: VolunteerIn, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    _check_org(db, body.organization_id)
    v = models.Volunteer(name=body.name.strip(), contact=body.contact, skills=body.skills, availability=body.availability,
                         location=body.location, organization_id=body.organization_id)
    db.add(v)
    db.flush()
    audit.record(db, admin, "volunteer.created", "volunteer", v.id, {"name": v.name})
    db.commit()
    db.refresh(v)
    return _vol_row(v, db.get(models.Organization, v.organization_id) if v.organization_id else None, 0, 0, None)


@router.get("/volunteers/{volunteer_id}")
def volunteer_detail(volunteer_id: int, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    v = db.get(models.Volunteer, volunteer_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Volunteer not found")
    orgs = {o.id: o for o in db.query(models.Organization).all()}
    needs = {n.id: n for n in db.query(models.Need).all()}
    mrows = db.query(models.Match).filter_by(volunteer_id=volunteer_id).order_by(models.Match.id.desc()).all()
    email = db.query(models.User.email).filter(models.User.volunteer_id == volunteer_id).scalar()
    row = _vol_row(v, orgs.get(v.organization_id), len(mrows), db.query(models.VolunteerSuggestion).filter_by(volunteer_id=volunteer_id, status="suggested").count(), email)
    open_needs = [n for n in needs.values() if (n.status or "").lower() in donor_ml.OPEN_STATUSES]
    recommended = []
    for r in volunteer_ml.rank_needs_for_volunteer(db, v, open_needs)[:5]:
        n = needs[r["need_id"]]
        recommended.append({"need_id": n.id, "category": n.category, "urgency": n.urgency, "quantity": n.quantity,
                            "organization_name": orgs[n.org_id].name if n.org_id in orgs else None,
                            "priority_score": r["priority_score"], "fit_score": r["fit_score"], "reasons": r["reasons"]})
    return {**row, "matches_history": [{"id": m.id, "need_category": needs[m.need_id].category if m.need_id in needs else None,
                                        "status": m.status, "score": m.score, "created_at": m.created_at} for m in mrows[:20]],
            "recommended_needs": recommended}


@router.patch("/volunteers/{volunteer_id}")
def update_volunteer(volunteer_id: int, body: VolunteerPatch, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    v = db.get(models.Volunteer, volunteer_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Volunteer not found")
    data = body.model_dump(exclude_unset=True)
    clear = data.pop("clear_organization", False)
    if data.get("organization_id") is not None:
        _check_org(db, data["organization_id"])
    for k, val in data.items():
        if k == "organization_id" and val is None:
            continue
        setattr(v, k, val.strip() if isinstance(val, str) and k == "name" else val)
    if clear:
        v.organization_id = None
    audit.record(db, admin, "volunteer.updated", "volunteer", volunteer_id, {"fields": sorted(list(data) + (["organization_id"] if clear else []))})
    db.commit()
    email = db.query(models.User.email).filter(models.User.volunteer_id == volunteer_id).scalar()
    return _vol_row(v, db.get(models.Organization, v.organization_id) if v.organization_id else None, 0, 0, email)


@router.delete("/volunteers/{volunteer_id}")
def delete_volunteer(volunteer_id: int, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    v = db.get(models.Volunteer, volunteer_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Volunteer not found")
    if db.query(models.Match).filter_by(volunteer_id=volunteer_id).count():
        raise HTTPException(status_code=409, detail="This volunteer appears in match records, so the record is kept for the audit trail")
    if db.query(models.User).filter(models.User.volunteer_id == volunteer_id).count():
        raise HTTPException(status_code=409, detail="This volunteer has a sign-in account. Remove or change the account first")
    db.query(models.VolunteerSuggestion).filter_by(volunteer_id=volunteer_id).delete()
    audit.record(db, admin, "volunteer.deleted", "volunteer", volunteer_id, {"name": v.name})
    db.delete(v)
    db.commit()
    return {"deleted": volunteer_id}
