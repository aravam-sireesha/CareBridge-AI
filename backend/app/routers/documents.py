"""Verification documents and delivery proof, kept in PRIVATE object storage (services/storage.py).

* Uploads are JSON (base64) like the rest of this API, capped by UPLOAD_MAX_MB, and validated by their real bytes, not their name.
* Nothing is served from this app: `GET /documents/{id}/url` returns a short-lived signed download link, and EVERY link issued is audited.
* "Uploaded" is not "verified": documents start `pending` and only an administrator's review changes that. Approving a document does NOT
  by itself verify an organization or a volunteer: that remains the administrator's decision in the existing verification workflow.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_user
from ..services import audit, document_access as access, ratelimit, storage
from ..services.notify import notify, notify_organization

router = APIRouter(prefix="/documents", tags=["documents"])
MAX_PER_OWNER = 30


class UploadBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    owner_type: Literal["organization", "volunteer", "delivery"]
    owner_id: int = Field(ge=1)
    kind: str = Field(max_length=30)
    filename: str = Field(max_length=200)
    content_type: str = Field(max_length=80)
    data_base64: str = Field(max_length=28_000_000)


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    decision: Literal["approved", "rejected"]
    note: Optional[str] = Field(default=None, max_length=300)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _store():
    try:
        s = storage.get_storage(os.environ)
    except storage.StorageUnavailable:
        raise HTTPException(status_code=503, detail="File storage is not available right now. Please try again later.") from None
    if s is None:
        raise HTTPException(status_code=503, detail="File storage is not set up on this server yet.")
    return s


def _task(db: Session, owner_type: str, owner_id: int) -> Optional[dict]:
    if owner_type != "delivery":
        return None
    t = db.get(models.DeliveryTask, owner_id)
    return None if t is None else {"id": t.id, "org_id": t.org_id, "volunteer_id": t.volunteer_id, "status": t.status}


def _meta(d: models.StoredDocument) -> dict:
    return {"id": d.id, "owner_type": d.owner_type, "owner_id": d.owner_id, "kind": d.kind, "original_name": d.original_name, "content_type": d.content_type,
            "size_bytes": d.size_bytes, "review_status": d.review_status, "review_note": d.review_note, "created_at": d.created_at.isoformat() if d.created_at else None}


def _doc_or_404(db: Session, user: dict, doc_id: int) -> tuple[models.StoredDocument, Optional[dict]]:
    d = db.get(models.StoredDocument, doc_id)
    task = _task(db, d.owner_type, d.owner_id) if d else None
    if d is None or d.deleted_at is not None or not access.read_allowed(user, d.owner_type, d.owner_id, task):
        raise HTTPException(status_code=404, detail="Document not found")          # not-found for both "missing" and "not yours"
    return d, task


@router.post("", dependencies=[Depends(ratelimit.rate_limit("doc_upload", 20, 3600))])
def upload(body: UploadBody, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    task = _task(db, body.owner_type, body.owner_id)
    if body.owner_type == "delivery" and task is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    if not access.upload_allowed(user, body.owner_type, body.owner_id, body.kind, task):
        raise HTTPException(status_code=403, detail="You cannot add this kind of document here.")
    store = _store()
    try:
        data = base64.b64decode(body.data_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="The file could not be read.") from None
    try:
        ctype, name = storage.validate_upload(body.filename, body.content_type, data, storage.max_bytes(os.environ))
    except storage.UploadError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    existing = db.query(models.StoredDocument).filter(models.StoredDocument.owner_type == body.owner_type, models.StoredDocument.owner_id == body.owner_id, models.StoredDocument.deleted_at.is_(None)).count()
    if existing >= MAX_PER_OWNER:
        raise HTTPException(status_code=409, detail="There are already too many documents here. Remove one first.")
    key = storage.object_key(body.owner_type, body.owner_id, body.kind, ctype)
    try:
        store.put(key, data, ctype)
    except storage.StorageUnavailable:
        raise HTTPException(status_code=503, detail="File storage is not available right now. Please try again later.") from None
    doc = models.StoredDocument(owner_type=body.owner_type, owner_id=body.owner_id, kind=body.kind, object_key=key, original_name=name, content_type=ctype,
                                size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), uploaded_by=user["id"], review_status="pending")
    try:
        db.add(doc); db.flush()
        audit.record(db, user, "document.uploaded", "document", doc.id, {"owner_type": body.owner_type, "owner_id": body.owner_id, "kind": body.kind, "size": len(data)})
        db.commit()
    except Exception:
        db.rollback()
        try: store.delete(key)                                            # do not leave an orphaned file behind
        except storage.StorageUnavailable: pass
        raise
    return _meta(doc)


@router.get("")
def list_documents(owner_type: Literal["organization", "volunteer", "delivery"], owner_id: int = Query(..., ge=1), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    task = _task(db, owner_type, owner_id)
    if not access.read_allowed(user, owner_type, owner_id, task):
        raise HTTPException(status_code=404, detail="Not found")
    rows = (db.query(models.StoredDocument).filter(models.StoredDocument.owner_type == owner_type, models.StoredDocument.owner_id == owner_id, models.StoredDocument.deleted_at.is_(None))
            .order_by(models.StoredDocument.id.desc()).all())
    return {"documents": [_meta(d) for d in rows]}


@router.get("/{doc_id}/url", dependencies=[Depends(ratelimit.rate_limit("doc_url", 30, 60))])
def download_url(doc_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    d, _ = _doc_or_404(db, user, doc_id)
    store = _store()
    seconds = storage.signed_url_seconds(os.environ)
    try:
        url = store.signed_url(d.object_key, seconds, d.original_name or "document")
    except storage.StorageUnavailable:
        raise HTTPException(status_code=503, detail="File storage is not available right now. Please try again later.") from None
    audit.record(db, user, "document.url_issued", "document", d.id, {"owner_type": d.owner_type, "owner_id": d.owner_id, "kind": d.kind})     # who looked at what, always
    db.commit()
    return {"url": url, "expires_in": seconds}


@router.delete("/{doc_id}")
def delete_document(doc_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    d, task = _doc_or_404(db, user, doc_id)
    if not access.delete_allowed(user, {"owner_type": d.owner_type, "owner_id": d.owner_id, "uploaded_by": d.uploaded_by, "review_status": d.review_status}, task):
        raise HTTPException(status_code=409, detail="An approved document stays on record. Ask an administrator if it must be removed.")
    d.deleted_at = _now()
    audit.record(db, user, "document.deleted", "document", d.id, {"owner_type": d.owner_type, "kind": d.kind})
    db.commit()
    try:
        _store().delete(d.object_key)
    except (HTTPException, storage.StorageUnavailable):
        pass                                                              # the record is gone either way; an operator can sweep orphaned objects
    return {"deleted": True}


@router.post("/{doc_id}/review")
def review(doc_id: int, body: ReviewBody, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Administrators only. Rejecting needs a reason the owner can act on."""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrators only")
    d = db.get(models.StoredDocument, doc_id)
    if d is None or d.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    if body.decision == "rejected" and not (body.note or "").strip():
        raise HTTPException(status_code=422, detail="Please say why the document is not accepted.")
    d.review_status, d.reviewed_by, d.reviewed_at = body.decision, user["id"], _now()
    d.review_note = (body.note or "").strip()[:300] or None
    audit.record(db, user, f"document.{body.decision}", "document", d.id, {"owner_type": d.owner_type, "owner_id": d.owner_id, "kind": d.kind})
    title = f"A document was {'accepted' if body.decision == 'approved' else 'not accepted'}"
    text = d.review_note or "An administrator reviewed it."
    if d.owner_type == "organization":
        notify_organization(db, d.owner_id, "verification", title, text, "/settings?tab=documents")
    elif d.owner_type == "volunteer":
        for u in db.query(models.User).filter(models.User.volunteer_id == d.owner_id).all():
            notify(db, u.id, "verification", title, text, "/settings?tab=documents")
    db.commit()
    return _meta(d)
