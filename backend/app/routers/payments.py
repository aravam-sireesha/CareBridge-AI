"""Donations by Razorpay: OFF unless PAYMENTS_ENABLED=true (see services/payments.py for what must happen first).

Flow: donor -> POST /payments/orders (the SERVER fixes the amount and creates the Razorpay order) -> checkout in the browser -> POST
/payments/verify (signature checked) -> and independently POST /payments/webhook (signed by Razorpay; the authority for refunds/failures).
A payment's status moves only through a verified signature. Receipts are payment acknowledgements, NOT 80G tax receipts.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_user
from ..services import audit, payments, ratelimit
from ..services.maps_http import MapsError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["payments"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _require_on() -> None:
    if not payments.enabled(os.environ):
        raise HTTPException(status_code=503, detail="Online donations are not switched on yet.")


class OrderBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    amount_rupees: float = Field(gt=0)
    organization_id: int = Field(ge=1)


class VerifyBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    razorpay_order_id: str = Field(max_length=40)
    razorpay_payment_id: str = Field(max_length=40)
    razorpay_signature: str = Field(max_length=128)


def _view(t: models.PaymentTransaction) -> dict:
    return {"id": t.id, "receipt": t.receipt, "order_id": t.razorpay_order_id, "amount_paise": t.amount_paise, "currency": t.currency, "status": t.status,
            "organization_id": t.organization_id, "created_at": t.created_at.isoformat() if t.created_at else None}


@router.get("/config")
def config(user: dict = Depends(get_current_user)):
    on = payments.enabled(os.environ)
    return {"enabled": on, "key_id": os.environ["RAZORPAY_KEY_ID"].strip() if on else None}       # the key ID is public by design; the secret never leaves the server


@router.post("/orders", dependencies=[Depends(ratelimit.rate_limit("pay_order", 10, 3600))])
def create_order(body: OrderBody, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_on()
    if user["role"] != "donor":
        raise HTTPException(status_code=403, detail="Only donors can make online donations.")
    org = db.get(models.Organization, body.organization_id)
    if org is None or org.verified is not True:
        raise HTTPException(status_code=404, detail="That organization cannot receive online donations.")
    try:
        paise = payments.rupees_to_paise(body.amount_rupees, os.environ)
    except payments.PaymentError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    receipt = payments.new_receipt()
    try:
        order = payments.create_order(paise, receipt, {"organization_id": org.id, "user_id": user["id"]}, os.environ)
    except MapsError as e:
        raise HTTPException(status_code={"unavailable": 503, "rejected": 502}.get(e.code, 502), detail=e.message) from None
    t = models.PaymentTransaction(user_id=user["id"], organization_id=org.id, razorpay_order_id=order["order_id"], receipt=receipt, amount_paise=paise, currency="INR", status="created")
    db.add(t); db.flush()
    audit.record(db, user, "payment.order_created", "payment", t.id, {"organization_id": org.id, "amount_paise": paise})
    db.commit()
    return {**_view(t), "key_id": os.environ["RAZORPAY_KEY_ID"].strip()}


@router.post("/verify", dependencies=[Depends(ratelimit.rate_limit("pay_verify", 20, 3600))])
def verify(body: VerifyBody, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_on()
    t = db.query(models.PaymentTransaction).filter(models.PaymentTransaction.razorpay_order_id == body.razorpay_order_id, models.PaymentTransaction.user_id == user["id"]).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    if not payments.verify_payment_signature(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature, os.environ["RAZORPAY_KEY_SECRET"].strip()):
        audit.record(db, user, "payment.signature_rejected", "payment", t.id, {})
        db.commit()
        raise HTTPException(status_code=400, detail="The payment could not be confirmed.")
    if t.razorpay_payment_id and t.razorpay_payment_id != body.razorpay_payment_id:
        raise HTTPException(status_code=409, detail="This order already has a different payment.")
    t.razorpay_payment_id = body.razorpay_payment_id
    t.status, t.updated_at = payments.next_status(t.status, "payment.captured"), _now()
    audit.record(db, user, "payment.verified", "payment", t.id, {"amount_paise": t.amount_paise})
    db.commit()
    return _view(t)


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    """Called by Razorpay, not by a browser. The signature over the RAW body is the only authentication; an unsigned or wrongly signed call changes nothing."""
    secret = (os.environ.get("RAZORPAY_WEBHOOK_SECRET") or "").strip()
    if not payments.enabled(os.environ) or not secret:
        raise HTTPException(status_code=503, detail="Not enabled")
    raw = await request.body()
    if len(raw) > 200_000 or not payments.verify_webhook_signature(raw, request.headers.get("x-razorpay-signature"), secret):
        raise HTTPException(status_code=400, detail="Invalid signature")
    eid = payments.event_id(request.headers.get("x-razorpay-event-id"), raw)
    try:
        ev = payments.parse_event(json.loads(raw))
    except (ValueError, payments.PaymentError):
        return {"ok": True, "ignored": "unreadable"}                      # signed but not something we use: acknowledge so Razorpay stops retrying
    db.add(models.PaymentEvent(event_id=eid, event_type=ev["type"], razorpay_order_id=ev["order_id"]))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"ok": True, "duplicate": True}                            # already processed: a re-delivery is a no-op
    t = db.query(models.PaymentTransaction).filter(models.PaymentTransaction.razorpay_order_id == ev["order_id"]).first() if ev["order_id"] else None
    if t is not None:
        if ev["payment_id"] and not t.razorpay_payment_id:
            t.razorpay_payment_id = ev["payment_id"]
        if ev["amount"] is not None and ev["amount"] != t.amount_paise:
            logger.error("Razorpay amount mismatch on payment %s", t.id)   # never auto-mark a payment whose amount we did not set
        else:
            t.status, t.updated_at = payments.next_status(t.status, ev["type"]), _now()
    db.commit()
    return {"ok": True}


@router.get("")
def my_payments(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(models.PaymentTransaction).filter(models.PaymentTransaction.user_id == user["id"]).order_by(models.PaymentTransaction.id.desc()).limit(50).all()
    return {"payments": [_view(t) for t in rows]}


@router.get("/{payment_id}/receipt")
def receipt(payment_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    t = db.get(models.PaymentTransaction, payment_id)
    if t is None or (t.user_id != user["id"] and user["role"] != "admin"):
        raise HTTPException(status_code=404, detail="Payment not found")
    if t.status not in ("captured", "refunded"):
        raise HTTPException(status_code=409, detail="A receipt is available once the payment is confirmed.")
    org = db.get(models.Organization, t.organization_id) if t.organization_id else None
    return {"receipt_number": t.receipt, "amount_rupees": t.amount_paise / 100, "currency": t.currency, "status": t.status,
            "organization": org.name if org else None, "payment_reference": f"\u2026{t.razorpay_payment_id[-6:]}" if t.razorpay_payment_id else None,
            "date": (t.updated_at or t.created_at).date().isoformat() if (t.updated_at or t.created_at) else None,
            "notice": "This is an acknowledgement of a payment through CareBridge. It is NOT a tax-exemption (80G) receipt."}
