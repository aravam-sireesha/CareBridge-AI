"""Administrator workflow console: the five-stage CareBridge flow with live numbers, one review queue for every
decision the AI hands to a person, resource allocation, one-click scans and the audit trail."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services import audit, donor_ml, resource_allocation, volunteer_ml
from . import administration, fraud as fraud_router, needs_alerts as alerts_router
from .administration import active_admin

router = APIRouter(prefix="/admin", tags=["administration"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------- review queue
DECISIONS = {
    "organization": ("verify",),
    "fraud_flag": ("confirmed_fraud", "false_positive"),
    "need_alert": ("action_taken", "dismissed"),
    "match": ("confirmed", "rejected"),
    "donor_suggestion": ("approved", "contacted", "rejected"),
    "volunteer_suggestion": ("approved", "contacted", "rejected"),
    "allocation": ("approved", "rejected"),
}
RANK = {"fraud_flag": 0, "need_alert": 1, "organization": 2, "allocation": 3, "match": 4, "donor_suggestion": 5, "volunteer_suggestion": 6}


def _queue(db: Session) -> list[dict]:
    items: list[dict] = []
    needs = {n.id: n for n in db.query(models.Need).all()}
    orgs = {o.id: o for o in db.query(models.Organization).all()}
    donors = {d.id: d for d in db.query(models.Donor).all()}
    vols = {v.id: v for v in db.query(models.Volunteer).all()}

    def add(type_, id_, title, subtitle, score, reasons, created, severity="medium"):
        items.append({"type": type_, "id": id_, "key": f"{type_}:{id_}", "title": title, "subtitle": subtitle,
                      "score": round(float(score), 3) if score is not None else None, "reasons": reasons or [],
                      "created_at": created, "severity": severity, "decisions": list(DECISIONS[type_])})

    for o in orgs.values():
        if not o.verified:
            add("organization", o.id, f"Verify {o.name}", f"{o.contact or 'No contact'}. Needs stay hidden from donors until verified.",
                None, ["New organizations are reviewed by an administrator"], o.created_at, "low")
    for flag, donation in (db.query(models.DonationFlag, models.Donation).outerjoin(
            models.Donation, models.DonationFlag.donation_id == models.Donation.id)
            .filter(models.DonationFlag.review_decision.is_(None)).all()):
        d = donors.get(donation.donor_id) if donation else None
        amount = f"{donation.amount:,.0f}" if donation and donation.amount else (donation.resource_description if donation else "")
        add("fraud_flag", flag.id, f"Suspicious donation #{flag.donation_id}", f"{d.name if d else 'Unknown donor'} · {amount}",
            flag.anomaly_score, flag.reasons if isinstance(flag.reasons, list) else [], flag.flagged_at, "high")
    for alert in db.query(models.NeedAlert).filter(models.NeedAlert.review_decision.is_(None)).all():
        n = needs.get(alert.need_id)
        add("need_alert", alert.id, f"Predicted need: {n.category if n else alert.need_id}",
            f"{orgs[n.org_id].name if n and n.org_id in orgs else 'Organization'} · {n.urgency if n else ''} urgency",
            alert.score, alert.reasons if isinstance(alert.reasons, list) else [], alert.flagged_at, "high")
    for a in db.query(models.ResourceAllocation).filter_by(status="proposed").all():
        r, n = db.get(models.Resource, a.resource_id), needs.get(a.need_id)
        add("allocation", a.id, f"Allocate {a.quantity} × {r.name if r else 'resource'} → {n.category if n else 'need'}",
            f"{orgs[n.org_id].name if n and n.org_id in orgs else 'Organization'}", a.score, a.reasons, a.created_at)
    for m in db.query(models.Match).filter_by(status="suggested").all():
        n = needs.get(m.need_id)
        who = [x.name for x in (donors.get(m.donor_id), vols.get(m.volunteer_id)) if x]
        add("match", m.id, f"Match for {n.category if n else 'need'}", " + ".join(who) or "Donor / volunteer", m.score, m.reasons, m.created_at)
    for s in db.query(models.DonorSuggestion).filter_by(status="suggested").all():
        n, d = needs.get(s.need_id), donors.get(s.donor_id)
        add("donor_suggestion", s.id, f"{d.name if d else 'Donor'} → {n.category if n else 'need'}",
            f"{orgs[n.org_id].name if n and n.org_id in orgs else 'Organization'} · fit {int(s.fit_score * 100)}%", s.priority_score,
            s.reasons, s.created_at)
    vols_by_id = vols
    for s in db.query(models.VolunteerSuggestion).filter_by(status="suggested").all():
        n, v = needs.get(s.need_id), vols_by_id.get(s.volunteer_id)
        add("volunteer_suggestion", s.id, f"{v.name if v else 'Volunteer'} → {n.category if n else 'need'}",
            f"{orgs[n.org_id].name if n and n.org_id in orgs else 'Organization'} · fit {int(s.fit_score * 100)}%", s.priority_score, s.reasons, s.created_at)
    items.sort(key=lambda i: (RANK[i["type"]], -(i["score"] or 0)))
    return items


@router.get("/review-queue")
def review_queue(type: str | None = None, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    items = _queue(db)
    counts = dict(Counter(i["type"] for i in items))
    if type:
        items = [i for i in items if i["type"] == type]
    return {"total": sum(counts.values()), "counts": counts, "items": items}


class QueueDecision(BaseModel):
    decision: str


def _apply_allocation(db: Session, alloc: models.ResourceAllocation, decision: str, admin: dict) -> None:
    allowed = {"proposed": ("approved", "rejected"), "approved": ("delivered", "cancelled")}
    if decision not in allowed.get(alloc.status, ()):
        raise HTTPException(status_code=409, detail=f"A {alloc.status} allocation cannot be marked {decision}")
    resource = db.get(models.Resource, alloc.resource_id)
    need = db.get(models.Need, alloc.need_id)
    if decision == "approved":
        if resource is None or resource.quantity_available < alloc.quantity:
            raise HTTPException(status_code=409, detail="Not enough of this resource is available any more")
        resource.quantity_available -= alloc.quantity
    elif decision == "cancelled" and resource is not None:
        resource.quantity_available += alloc.quantity
    alloc.status, alloc.reviewed_by, alloc.reviewed_at = decision, admin["id"], _now()
    audit.record(db, admin, f"allocation.{decision}", "resource_allocation", alloc.id,
                 {"resource_id": alloc.resource_id, "need_id": alloc.need_id, "quantity": alloc.quantity})
    db.flush()
    if decision == "delivered" and need is not None and need.quantity and resource_allocation.delivered_quantity(db, need.id) >= need.quantity:
        need.status = "fulfilled"
        need.fulfilled_at = _now()
        audit.record(db, admin, "need.fulfilled", "need", need.id, {"by": "resource allocation"})


@router.post("/review-queue/{type}/{item_id}")
def decide(type: str, item_id: int, body: QueueDecision, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    """One endpoint for every decision the AI hands to an administrator. Each decision is written to the audit trail."""
    if type not in DECISIONS:
        raise HTTPException(status_code=404, detail="Unknown item type")
    if body.decision not in DECISIONS[type]:
        raise HTTPException(status_code=422, detail=f"decision must be one of: {', '.join(DECISIONS[type])}")
    now = _now()
    if type == "organization":
        row = db.get(models.Organization, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        row.verified = True
        audit.record(db, admin, "organization.verified", "organization", item_id, {"name": row.name, "via": "review queue"})
    elif type == "fraud_flag":
        row = db.get(models.DonationFlag, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Flag not found")
        row.reviewed_by, row.review_decision, row.reviewed_at = admin["id"], body.decision, now
        audit.record(db, admin, "fraud.reviewed", "donation_flag", item_id, {"decision": body.decision, "donation_id": row.donation_id})
    elif type == "need_alert":
        row = db.get(models.NeedAlert, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Alert not found")
        row.reviewed_by, row.review_decision, row.reviewed_at = admin["id"], body.decision, now
        audit.record(db, admin, "need_alert.reviewed", "need_alert", item_id, {"decision": body.decision, "need_id": row.need_id})
    elif type == "match":
        row = db.get(models.Match, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Match not found")
        row.status = body.decision
        audit.record(db, admin, "match.reviewed", "match", item_id, {"decision": body.decision, "need_id": row.need_id})
    elif type == "donor_suggestion":
        row = db.get(models.DonorSuggestion, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        row.status, row.reviewed_by, row.reviewed_at = body.decision, admin["id"], now
        audit.record(db, admin, "suggestion.reviewed", "donor_suggestion", item_id, {"decision": body.decision, "need_id": row.need_id, "donor_id": row.donor_id})
    elif type == "volunteer_suggestion":
        row = db.get(models.VolunteerSuggestion, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        row.status, row.reviewed_by, row.reviewed_at = body.decision, admin["id"], now
        audit.record(db, admin, "volunteer_suggestion.reviewed", "volunteer_suggestion", item_id, {"decision": body.decision, "need_id": row.need_id, "volunteer_id": row.volunteer_id})
    else:
        row = db.get(models.ResourceAllocation, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Allocation not found")
        _apply_allocation(db, row, body.decision, admin)
    db.commit()
    return {"status": "ok", "type": type, "id": item_id, "decision": body.decision}


# --------------------------------------------------------------------------- the five-stage workflow
@router.get("/workflow")
def workflow(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    now = _now()
    week_ago = now - timedelta(days=7)
    count = lambda model, *f: db.query(func.count(model.id)).filter(*f).scalar() or 0  # noqa: E731
    orgs = db.query(models.Organization).all()
    verified = sum(1 for o in orgs if o.verified)
    needs = db.query(models.Need).all()
    open_needs = [n for n in needs if (n.status or "").lower() in donor_ml.OPEN_STATUSES]
    fulfilled = sum(1 for n in needs if (n.status or "").lower() == "fulfilled")
    resources = db.query(models.Resource).all()
    units_total = sum(r.quantity_total for r in resources)
    units_free = sum(r.quantity_available for r in resources)
    queue = _queue(db)
    q_counts = Counter(i["type"] for i in queue)
    allocs = Counter(a.status for a in db.query(models.ResourceAllocation).all())
    matches = Counter(m.status for m in db.query(models.Match).all())
    sugg = Counter(s.status for s in db.query(models.DonorSuggestion).all())
    vsugg = Counter(s.status for s in db.query(models.VolunteerSuggestion).all())
    recs = count(models.CareerRecommendation)
    rec_fb = db.query(func.count(func.distinct(models.RecommendationFeedback.recommendation_id))).scalar() or 0
    total_donated = db.query(func.coalesce(func.sum(models.Donation.amount), 0)).scalar() or 0
    audit_week = count(models.AuditLog, models.AuditLog.created_at >= week_ago)
    asked_week = count(models.AssistantMessage, models.AssistantMessage.created_at >= week_ago)

    def item(key, label, detail, n, to):
        return {"key": key, "label": label, "detail": detail, "count": n, "to": to}

    pct = lambda a, b: int(round(100 * a / b)) if b else 0  # noqa: E731
    stages = [
        {"key": "input", "title": "Data Input", "items": [
            item("children", "Children", "Needs & profile", count(models.Child), "/children"),
            item("organizations", "Organizations", f"{verified} verified · programs & resources", len(orgs), "/admin/organizations"),
            item("donors", "Donors", "Interests & support", count(models.Donor), "/admin/donors"),
            item("volunteers", "Volunteers", "Skills & availability", count(models.Volunteer), "/people"),
            item("resources", "Resources", f"{units_free} of {units_total} units free", len(resources), "/admin/resources")]},
        {"key": "processing", "title": "AI Processing & Analysis", "items": [
            item("predict", "Predictive need analysis", "Find future needs", q_counts.get("need_alert", 0), "/ai/needs-alerts"),
            item("fraud", "Fraud / anomaly detection", "Suspicious donations", q_counts.get("fraud_flag", 0), "/ai/fraud"),
            item("matching", "Donor & volunteer matching", "Skills + interests + availability",
                 matches.get("suggested", 0) + sugg.get("suggested", 0) + vsugg.get("suggested", 0), "/admin/recommend"),
            item("career", "Career guidance", f"{rec_fb} of {recs} reviewed", max(0, recs - rec_fb), "/ai/career")]},
        {"key": "decision", "title": "Decision & Collaboration", "items": [
            item("assistant", "AI Assistant (RAG)", f"{asked_week} question(s) this week", count(models.KnowledgeBase), "/assistant"),
            item("review", "Administrator review & approve", "Waiting for a decision", len(queue), "/admin/review")]},
        {"key": "action", "title": "Action & Support", "items": [
            item("connect", "Connect donors & volunteers", "Confirmed or approved",
                 matches.get("confirmed", 0) + sugg.get("approved", 0) + sugg.get("contacted", 0) + vsugg.get("approved", 0) + vsugg.get("contacted", 0), "/ai/matching"),
            item("allocate", "Allocate resources", f"{allocs.get('delivered', 0)} delivered", allocs.get("approved", 0) + allocs.get("delivered", 0), "/admin/resources"),
            item("guidance", "Provide guidance", "Career decisions recorded", rec_fb, "/ai/career"),
            item("coordinate", "Coordinate with organizations", "Verified organizations", verified, "/admin/organizations")]},
        {"key": "outcomes", "title": "Better Outcomes", "items": [
            item("timely", "Timely support for children", f"{fulfilled} of {len(needs)} needs fulfilled", pct(fulfilled, len(needs)), "/admin/needs"),
            item("efficient", "Efficient resource utilization", f"{units_total - units_free} of {units_total} units in use", pct(units_total - units_free, units_total), "/admin/resources"),
            item("trust", "Transparency & trust", f"{audit_week} audited action(s) this week", pct(verified, len(orgs)), "/admin/audit"),
            item("impact", "Stronger social impact", f"{total_donated:,.0f} donated", count(models.Child), "/donations")]},
    ]
    return {"generated_at": now.isoformat(timespec="seconds") + "Z", "stages": stages,
            "pending": {"total": len(queue), "by_type": dict(q_counts)},
            "open_needs": len(open_needs)}


@router.post("/workflow/run-scans")
def run_scans(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    """Run every AI scan in one go: predicted needs, suspicious donations, donor suggestions, resource proposals."""
    needs_result = alerts_router.scan(admin=admin, db=db)
    fraud_result = fraud_router.scan_donations(admin=admin, db=db)
    donors_result = administration.generate_all(limit=25, top_n=3, admin=admin, db=db)
    ranked = administration._ranked_needs(db, only_open=True)[:25]
    proposals = vol_suggestions = 0
    vctx, vlearned = volunteer_ml.VolunteerContext(db), volunteer_ml.train_learned_model(db)
    for item in ranked:
        need = db.get(models.Need, item["id"])
        vol_suggestions += len(volunteer_ml.save_suggestions(db, need, volunteer_ml.suggest_volunteers(db, need, 3, vctx, vlearned), admin["id"]))
        proposals += len(resource_allocation.save_proposals(db, need, resource_allocation.suggest_allocations(db, need), admin["id"]))
    summary = {"predicted_needs": len(needs_result["alerts"]), "donations_scanned": fraud_result["scanned"],
               "new_fraud_flags": fraud_result["new_flags"], "donor_suggestions": donors_result["suggestions"],
               "volunteer_suggestions": vol_suggestions, "resource_proposals": proposals}
    audit.record(db, admin, "ai.scans_run", detail=summary)
    db.commit()
    return summary


# --------------------------------------------------------------------------- resource allocation
def _alloc_out(a, resources, needs, orgs):
    r, n = resources.get(a.resource_id), needs.get(a.need_id)
    return {"id": a.id, "resource_id": a.resource_id, "resource_name": r.name if r else None, "unit": r.unit if r else None,
            "resource_available": r.quantity_available if r else None, "need_id": a.need_id, "need_category": n.category if n else None,
            "need_urgency": n.urgency if n else None, "need_quantity": n.quantity if n else None,
            "organization_name": orgs.get(n.org_id) if n else None, "quantity": a.quantity, "score": a.score,
            "reasons": a.reasons or [], "status": a.status, "created_at": a.created_at, "reviewed_at": a.reviewed_at}


def _alloc_rows(db: Session, status_filter: str | None = None, need_id: int | None = None):
    q = db.query(models.ResourceAllocation)
    if status_filter:
        q = q.filter(models.ResourceAllocation.status == status_filter)
    if need_id:
        q = q.filter(models.ResourceAllocation.need_id == need_id)
    resources = {r.id: r for r in db.query(models.Resource).all()}
    needs = {n.id: n for n in db.query(models.Need).all()}
    orgs = {o.id: o.name for o in db.query(models.Organization).all()}
    return [_alloc_out(a, resources, needs, orgs) for a in q.order_by(models.ResourceAllocation.id.desc()).all()]


@router.get("/allocations")
def list_allocations(status_filter: str | None = Query(default=None, alias="status"), admin: dict = Depends(active_admin),
                     db: Session = Depends(get_db)):
    return _alloc_rows(db, status_filter)


@router.post("/needs/{need_id}/suggest-resources")
def suggest_resources(need_id: int, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    need = db.get(models.Need, need_id)
    if need is None:
        raise HTTPException(status_code=404, detail="Need not found")
    if (need.status or "").lower() not in donor_ml.OPEN_STATUSES:
        raise HTTPException(status_code=409, detail="Resources can only be suggested for open or pending needs")
    resource_allocation.save_proposals(db, need, resource_allocation.suggest_allocations(db, need), admin["id"])
    db.commit()
    return {"need_id": need_id, "model_version": resource_allocation.MODEL_VERSION,
            "allocations": [a for a in _alloc_rows(db, need_id=need_id) if a["status"] in ("proposed", "approved", "delivered")]}


class AllocationIn(BaseModel):
    resource_id: int
    need_id: int
    quantity: int


@router.post("/allocations", status_code=201)
def create_allocation(body: AllocationIn, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    """Manual allocation by an administrator. It is created as 'proposed' and goes through the same approval."""
    resource, need = db.get(models.Resource, body.resource_id), db.get(models.Need, body.need_id)
    if resource is None or need is None:
        raise HTTPException(status_code=404, detail="Resource or need not found")
    if body.quantity < 1 or body.quantity > resource.quantity_available:
        raise HTTPException(status_code=422, detail=f"Quantity must be between 1 and {resource.quantity_available}")
    a = models.ResourceAllocation(resource_id=resource.id, need_id=need.id, quantity=body.quantity, score=None,
                                  reasons=["Allocated manually by an administrator"], status="proposed", proposed_by=admin["id"])
    db.add(a)
    db.flush()
    audit.record(db, admin, "allocation.proposed", "resource_allocation", a.id, {"resource_id": resource.id, "need_id": need.id, "quantity": body.quantity})
    db.commit()
    return next(r for r in _alloc_rows(db) if r["id"] == a.id)


class AllocationReview(BaseModel):
    decision: Literal["approved", "rejected", "delivered", "cancelled"]


@router.post("/allocations/{allocation_id}/review")
def review_allocation(allocation_id: int, body: AllocationReview, admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    alloc = db.get(models.ResourceAllocation, allocation_id)
    if alloc is None:
        raise HTTPException(status_code=404, detail="Allocation not found")
    _apply_allocation(db, alloc, body.decision, admin)
    db.commit()
    return {"id": alloc.id, "status": alloc.status}


# --------------------------------------------------------------------------- audit trail
@router.get("/audit")
def audit_trail(action: str | None = None, search: str | None = None, limit: int = Query(default=50, ge=1, le=200),
                offset: int = Query(default=0, ge=0), admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    q = db.query(models.AuditLog)
    if action:
        q = q.filter(models.AuditLog.action.like(f"{action}%"))
    if search:
        like = f"%{search.strip().lower()}%"
        q = q.filter(func.lower(func.coalesce(models.AuditLog.actor_email, "")).like(like) |
                     func.lower(models.AuditLog.action).like(like))
    total = q.count()
    rows = q.order_by(models.AuditLog.id.desc()).offset(offset).limit(limit).all()
    actions = [a for (a,) in db.query(models.AuditLog.action).distinct().order_by(models.AuditLog.action).all()]
    return {"total": total, "actions": actions, "items": [
        {"id": r.id, "created_at": r.created_at, "actor_email": r.actor_email, "actor_role": r.actor_role, "action": r.action,
         "entity_type": r.entity_type, "entity_id": r.entity_id, "detail": r.detail, "ip": r.ip} for r in rows]}
