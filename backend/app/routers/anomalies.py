"""Anomaly Detection: one filterable, read-only view over donation flags and need alerts.

A flag is a signal for a person to investigate, never a finding. Scores and reasons are shown exactly as the models stored
them (no severity labels are invented: the two models score on different scales). Decisions reuse the existing review
endpoints (/fraud/flags/{id}/review and /needs/alerts/{id}/review), so there is a single place where reviews are recorded.
"""
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services.paging import page_meta
from .administration import active_admin

router = APIRouter(prefix="/admin/anomalies", tags=["administration"])
SCAN_CAP = 2000


@router.get("/")
def list_anomalies(kind: Literal["all", "donation", "need"] = "all", state: Literal["all", "outstanding", "reviewed"] = "all",
                   min_score: Optional[float] = Query(None, ge=0), date_from: Optional[date] = None, date_to: Optional[date] = None,
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to")
    start = datetime.combine(date_from, time.min) if date_from else None
    end = datetime.combine(date_to + timedelta(days=1), time.min) if date_to else None
    emails = {}
    items: list[dict] = []
    capped = False

    def keep(score, flagged_at, decision) -> bool:
        if min_score is not None and (score or 0) < min_score:
            return False
        if start and (flagged_at is None or flagged_at < start) or end and (flagged_at is None or flagged_at >= end):
            return False
        return state == "all" or (state == "outstanding") == (decision is None)

    if kind in ("all", "donation"):
        rows = (db.query(models.DonationFlag, models.Donation, models.Need, models.Organization)
                .outerjoin(models.Donation, models.DonationFlag.donation_id == models.Donation.id)
                .outerjoin(models.Need, models.Donation.need_id == models.Need.id)
                .outerjoin(models.Organization, models.Need.org_id == models.Organization.id)
                .order_by(models.DonationFlag.flagged_at.desc()).limit(SCAN_CAP).all())
        capped = capped or len(rows) >= SCAN_CAP
        for f, d, n, o in rows:
            if keep(f.anomaly_score, f.flagged_at, f.review_decision):
                items.append({"kind": "donation", "id": f.id, "subject": f"Donation #{f.donation_id}", "donation_id": f.donation_id,
                              "need_id": d.need_id if d else None, "organization": o.name if o else None, "amount": d.amount if d else None,
                              "score": f.anomaly_score, "reasons": f.reasons or [], "model_version": f.model_version, "flagged_at": f.flagged_at,
                              "decision": f.review_decision, "reviewed_by": f.reviewed_by, "reviewed_at": f.reviewed_at})
    if kind in ("all", "need"):
        rows = (db.query(models.NeedAlert, models.Need, models.Organization)
                .join(models.Need, models.NeedAlert.need_id == models.Need.id)
                .outerjoin(models.Organization, models.Need.org_id == models.Organization.id)
                .order_by(models.NeedAlert.flagged_at.desc()).limit(SCAN_CAP).all())
        capped = capped or len(rows) >= SCAN_CAP
        for a, n, o in rows:
            if keep(a.score, a.flagged_at, a.review_decision):
                items.append({"kind": "need", "id": a.id, "subject": f"Need #{a.need_id}: {n.title or n.category}", "donation_id": None,
                              "need_id": a.need_id, "organization": o.name if o else None, "amount": None,
                              "score": a.score, "reasons": a.reasons or [], "model_version": a.model_version, "flagged_at": a.flagged_at,
                              "decision": a.review_decision, "reviewed_by": a.reviewed_by, "reviewed_at": a.reviewed_at})
    items.sort(key=lambda i: i["flagged_at"] or datetime.min, reverse=True)
    total = len(items)
    window = items[(page - 1) * page_size: page * page_size]
    reviewer_ids = {i["reviewed_by"] for i in window if i["reviewed_by"]}
    if reviewer_ids:
        emails = dict(db.query(models.User.id, models.User.email).filter(models.User.id.in_(reviewer_ids)).all())
    for i in window:
        i["reviewed_by"] = emails.get(i["reviewed_by"])
        i["status"] = i["decision"] or "outstanding"
    return {"items": window, "capped": capped, **page_meta(page, page_size, total)}
