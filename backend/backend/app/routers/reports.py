"""Downloadable CSV reports built from real database rows. Permissions are enforced here, not in the UI.

* Administrators can export every report. Organizations can export only donation and need reports, always limited to
  their own organization (the organization filter is forced server-side).
* No child records are ever included. Cells are escaped against spreadsheet formula injection (services/csvsafe).
* Every export is written to the audit trail.
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_user
from ..services import audit, verification
from ..services.csvsafe import MAX_REPORT_ROWS, build_report
from .administration import ensure_admin_profile

router = APIRouter(prefix="/reports", tags=["reports"])

CATALOG = {
    "donation_summary": {"label": "Donation summary", "roles": ("admin", "organization"), "filters": ["date_from", "date_to", "status", "category", "organization_id"]},
    "need_fulfillment": {"label": "Need fulfillment", "roles": ("admin", "organization"), "filters": ["date_from", "date_to", "status", "category", "organization_id"]},
    "org_verification": {"label": "Organization verification", "roles": ("admin",), "filters": ["date_from", "date_to", "status"]},
    "anomaly_review": {"label": "Anomaly review", "roles": ("admin",), "filters": ["date_from", "date_to", "status"]},
}
NOT_AVAILABLE = {"fund_utilization": "No fund-utilization data is recorded yet.", "volunteer_activity": "Volunteer applications and service hours have no API yet."}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _caller(user: dict, db: Session) -> dict:
    if user["role"] not in ("admin", "organization"):
        raise HTTPException(status_code=403, detail="Reports are not available for this account")
    if user["role"] == "admin":
        profile = ensure_admin_profile(db, db.get(models.User, user["id"]))
        if not profile.is_active:
            raise HTTPException(status_code=403, detail="This administrator account has been deactivated")
        db.commit()
    return user


@router.get("/types")
def report_types(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    _caller(user, db)
    return {"reports": [{"key": k, "label": v["label"], "filters": v["filters"]} for k, v in CATALOG.items() if user["role"] in v["roles"]],
            "unavailable": [{"key": k, "reason": r} for k, r in NOT_AVAILABLE.items()]}


class _Window:
    def __init__(self, date_from: Optional[date], date_to: Optional[date]):
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status_code=422, detail="date_from must not be after date_to")
        self.start = datetime.combine(date_from, time.min) if date_from else None
        self.end = datetime.combine(date_to + timedelta(days=1), time.min) if date_to else None

    def apply(self, query, column):
        if self.start:
            query = query.filter(column >= self.start)
        if self.end:
            query = query.filter(column < self.end)
        return query


def _cap(rows: list) -> list:
    if len(rows) > MAX_REPORT_ROWS:
        raise HTTPException(status_code=413, detail=f"This report has more than {MAX_REPORT_ROWS:,} rows. Narrow the date range or filters.")
    return rows


def _donation_summary(db, user, win, status, category, org_id):
    q = (db.query(models.Donation, models.Need, models.Organization, models.Donor)
         .outerjoin(models.Need, models.Donation.need_id == models.Need.id)
         .outerjoin(models.Organization, models.Need.org_id == models.Organization.id)
         .outerjoin(models.Donor, models.Donation.donor_id == models.Donor.id))
    q = win.apply(q, models.Donation.timestamp)
    if status:
        q = q.filter(models.Donation.status == status)
    if category:
        q = q.filter(models.Need.category.ilike(category))
    if org_id:
        q = q.filter(models.Need.org_id == org_id)
    rows = _cap(q.order_by(models.Donation.timestamp.desc(), models.Donation.id.desc()).limit(MAX_REPORT_ROWS + 1).all())
    admin = user["role"] == "admin"
    headers = ["Donation ID", "Date", "Kind", "Status", "Amount", "Need ID", "Need category", "Organization", "Donor ID"] + (["Donor name"] if admin else [])
    out = [[d.id, d.timestamp, d.kind, d.status, d.amount, d.need_id, n.category if n else None, o.name if o else None, d.donor_id] + ([dn.name if dn else None] if admin else [])
           for d, n, o, dn in rows]
    return headers, out


def _need_fulfillment(db, user, win, status, category, org_id):
    q = db.query(models.Need, models.Organization).outerjoin(models.Organization, models.Need.org_id == models.Organization.id)
    q = win.apply(q, models.Need.created_at)
    if status:
        q = q.filter(models.Need.status == status)
    if category:
        q = q.filter(models.Need.category.ilike(category))
    if org_id:
        q = q.filter(models.Need.org_id == org_id)
    rows = _cap(q.order_by(models.Need.id.desc()).limit(MAX_REPORT_ROWS + 1).all())
    headers = ["Need ID", "Title", "Category", "Organization", "Urgency", "Quantity", "Status", "Created", "Required by", "Fulfilled", "Days to fulfil"]
    out = [[n.id, n.title, n.category, o.name if o else None, n.urgency, n.quantity, n.status, n.created_at, n.required_by, n.fulfilled_at,
            (n.fulfilled_at - n.created_at).days if n.fulfilled_at and n.created_at else None] for n, o in rows]
    return headers, out


def _org_verification(db, user, win, status, category, org_id):
    q = win.apply(db.query(models.Organization), models.Organization.created_at)
    orgs = _cap(q.order_by(models.Organization.id.desc()).limit(MAX_REPORT_ROWS + 1).all())
    latest = {}
    for a in db.query(models.AuditLog).filter(models.AuditLog.entity_type == "organization", models.AuditLog.action.like("organization.%")).order_by(models.AuditLog.id.desc()).all():
        latest.setdefault(a.entity_id, a)
    headers = ["Organization ID", "Name", "Registration number", "Status", "Submitted", "Verified at", "Last decision by", "Last decision at", "Reviewer note"]
    out = []
    for o in orgs:
        eff = verification.current_status(o.verification_status, o.verified)
        if status and eff != status:
            continue
        a = latest.get(o.id)
        out.append([o.id, o.name, o.registration_number, eff, o.verification_submitted_at or o.created_at, o.verified_at, a.actor_email if a else None, a.created_at if a else None, o.verification_note])
    return headers, out


def _anomaly_review(db, user, win, status, category, org_id):
    if status and status not in ("outstanding", "reviewed"):
        raise HTTPException(status_code=422, detail="status must be outstanding or reviewed for this report")
    out = []
    flags = win.apply(db.query(models.DonationFlag), models.DonationFlag.flagged_at).order_by(models.DonationFlag.id.desc()).limit(MAX_REPORT_ROWS + 1).all()
    alerts = win.apply(db.query(models.NeedAlert), models.NeedAlert.flagged_at).order_by(models.NeedAlert.id.desc()).limit(MAX_REPORT_ROWS + 1).all()
    emails = dict(db.query(models.User.id, models.User.email).all())
    for kind, rows, subject in (("Donation", flags, lambda r: r.donation_id), ("Need", alerts, lambda r: r.need_id)):
        for r in rows:
            if status and (status == "outstanding") != (r.review_decision is None):
                continue
            out.append([kind, r.id, subject(r), getattr(r, "anomaly_score", None) if kind == "Donation" else r.score, r.reasons, r.model_version,
                        r.flagged_at, r.review_decision or "outstanding", emails.get(r.reviewed_by), r.reviewed_at])
    _cap(out)
    headers = ["Type", "Alert ID", "Subject ID", "Model score", "Model reasons", "Model version", "Flagged at", "Review status", "Reviewed by", "Reviewed at"]
    return headers, out


BUILDERS = {"donation_summary": _donation_summary, "need_fulfillment": _need_fulfillment, "org_verification": _org_verification, "anomaly_review": _anomaly_review}


@router.get("/{report_type}")
def download(report_type: str, date_from: Optional[date] = None, date_to: Optional[date] = None, status: Optional[str] = Query(None, max_length=40),
             category: Optional[str] = Query(None, max_length=100), organization_id: Optional[int] = Query(None, ge=1), include_meta: bool = True,
             user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    _caller(user, db)
    spec = CATALOG.get(report_type)
    if spec is None:
        raise HTTPException(status_code=404, detail=NOT_AVAILABLE.get(report_type, "Unknown report"))
    if user["role"] not in spec["roles"]:
        raise HTTPException(status_code=403, detail="This report is not available for your account")
    if user["role"] == "organization":
        organization_id = user.get("organization_id")          # forced: an organization can only ever export its own data
        if organization_id is None:
            raise HTTPException(status_code=403, detail="Your account is not linked to an organization")
    headers, rows = BUILDERS[report_type](db, user, _Window(date_from, date_to), status, category, organization_id)
    filters = {"date_from": date_from, "date_to": date_to, "status": status, "category": category, "organization_id": organization_id}
    text = build_report(spec["label"], _now(), filters, headers, rows, include_meta)
    audit.record(db, user, "report.exported", "report", None, {"report": report_type, "rows": len(rows), "filters": {k: str(v) for k, v in filters.items() if v}})
    db.commit()
    name = f"carebridge-{report_type.replace('_', '-')}-{_now():%Y%m%d}.csv"
    return Response(content=text, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
