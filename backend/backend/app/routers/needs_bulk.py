"""Bulk need upload. Flow: download template -> validate (dry run, nothing saved) -> import.

The CSV travels as JSON text (the project has no multipart dependency). The import re-validates everything on the server;
a preview is never trusted. Counts are produced from what was really written to the database.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_user
from ..services import audit, bulk_needs
from ..services.notify import notify
from .administration import ensure_admin_profile

router = APIRouter(prefix="/needs/bulk", tags=["needs"])
logger = logging.getLogger(__name__)


class BulkIn(BaseModel):
    filename: Optional[str] = Field(default=None, max_length=200)
    csv: str = Field(min_length=1, max_length=1_100_000)
    default_organization_id: Optional[int] = Field(default=None, ge=1)
    strict: bool = False        # true: import nothing if any row is invalid


def _authorize(user: dict, db: Session) -> None:
    if user["role"] not in ("admin", "organization"):
        raise HTTPException(status_code=403, detail="Only organization and admin accounts can upload needs")
    if user["role"] == "admin":
        if not ensure_admin_profile(db, db.get(models.User, user["id"])).is_active:
            raise HTTPException(status_code=403, detail="This administrator account has been deactivated")
        db.commit()
    elif user.get("organization_id") is None or db.get(models.Organization, user["organization_id"]) is None:
        raise HTTPException(status_code=403, detail="Your account is not linked to an organization")


def _key(org_id, title, category, due) -> tuple:
    return (org_id, (title or "").lower(), (category or "").lower(), due.date() if due else None)


def _evaluate(body: BulkIn, user: dict, db: Session):
    _authorize(user, db)
    admin = user["role"] == "admin"
    try:
        _, records, info = bulk_needs.parse_csv(body.csv)
    except bulk_needs.BulkError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    known = {r[0] for r in db.query(models.Organization.id).all()} if admin else None
    if admin and body.default_organization_id and body.default_organization_id not in known:
        raise HTTPException(status_code=422, detail="The chosen default organization does not exist")
    results = bulk_needs.validate(records, is_admin=admin, own_org_id=user.get("organization_id"), default_org_id=body.default_organization_id, known_org_ids=known)
    orgs = {r.data["org_id"] for r in results if r.data}
    existing = set()
    if orgs:
        for n in db.query(models.Need).filter(models.Need.org_id.in_(orgs), models.Need.status.in_(("open", "pending"))).all():
            existing.add(_key(n.org_id, n.title, n.category, n.required_by))
    rows = []
    for r in results:
        data = r.data
        if r.errors:
            status, reason = "rejected", " ".join(r.errors)
        elif r.duplicate_of:
            status, reason = "skipped", f"Duplicate of row {r.duplicate_of} in this file."
        elif _key(data["org_id"], data["title"], data["category"], data["required_by"]) in existing:
            status, reason = "skipped", "An open need with the same title, category and date already exists."
        else:
            status, reason = "ready", None
        rows.append({"row": r.row, "line": r.line, "status": status, "errors": r.errors, "reason": reason, "need_id": None, "data": data,
                     "preview": {"title": (data or {}).get("title"), "category": (data or {}).get("category"), "quantity": (data or {}).get("quantity"),
                                 "urgency": (data or {}).get("urgency"), "required_by": (data or {}).get("required_by"), "organization_id": (data or {}).get("org_id")}})
    return rows, info


def _summary(rows, info, **extra) -> dict:
    payload = [{k: v for k, v in r.items() if k != "data"} for r in rows]
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("ready", "created", "rejected", "skipped")}
    return {"total": len(rows), "counts": counts, "rows": payload, "ignored_columns": info["ignored_columns"], "blank_rows_ignored": info["blank_rows_ignored"], **extra}


@router.get("/template")
def template(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    _authorize(user, db)
    return Response(content="\ufeff" + bulk_needs.template_csv(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="carebridge-needs-template.csv"'})


@router.post("/validate")
def validate_upload(body: BulkIn, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    rows, info = _evaluate(body, user, db)
    return _summary(rows, info, saved=False)


@router.post("/import")
def import_upload(body: BulkIn, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    rows, info = _evaluate(body, user, db)
    rejected = [r for r in rows if r["status"] == "rejected"]
    if body.strict and rejected:
        raise HTTPException(status_code=409, detail={"message": f"Nothing was imported: {len(rejected)} row(s) have errors and strict mode is on.", **_summary(rows, info, saved=False)})
    todo = [r for r in rows if r["status"] == "ready"]
    try:
        created = []
        for r in todo:
            need = models.Need(**r["data"], status="open")
            db.add(need)
            created.append((r, need))
        db.flush()
        for r, need in created:
            r["status"], r["need_id"] = "created", need.id
        audit.record(db, user, "needs.bulk_import", "need", None, {"filename": (body.filename or "")[:100], "created": len(created),
                                                                    "rejected": len(rejected), "skipped": sum(1 for r in rows if r["status"] == "skipped")})
        notify(db, user["id"], "need", "Bulk upload finished", f"{len(created)} need(s) created, {len(rejected)} rejected, {sum(1 for r in rows if r['status'] == 'skipped')} skipped.", "/needs")
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Bulk need import failed")
        raise HTTPException(status_code=500, detail="The import failed and nothing was saved. Please try again.")
    org_ids = {r["data"]["org_id"] for r, _ in created}
    unverified = db.query(models.Organization).filter(models.Organization.id.in_(org_ids), models.Organization.verified.isnot(True)).count() if org_ids else 0
    warnings = ["Some needs belong to an organization that is not verified yet. They stay hidden from donors and volunteers until it is verified."] if unverified else []
    return _summary(rows, info, saved=True, warnings=warnings)
