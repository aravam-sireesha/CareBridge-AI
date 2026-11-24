"""Razorpay payments: PREPARED AND DISABLED. Do NOT switch PAYMENTS_ENABLED=true before legal, tax, organisational and FCRA applicability
reviews are complete (receipts here are payment acknowledgements, NOT 80G tax receipts).

Safety rules implemented here:
* Money state changes only through a CRYPTOGRAPHIC check: a payment signature (order_id|payment_id, HMAC-SHA256 with the key secret) or a
  webhook body signature (HMAC-SHA256 with the webhook secret), both compared in constant time. The browser's word is never enough.
* Idempotent: each webhook event id is recorded once (payment_events, unique); a re-delivered webhook changes nothing.
* Out-of-order safe: a late 'failed' event cannot undo a captured payment, and nothing leaves 'refunded'.
* Amounts are integers in paise, bounded; the SERVER fixes the amount when it creates the order; the checkout cannot change it.
* Needs automatic capture enabled in the Razorpay dashboard (a verified signature is treated as a captured payment).
Configuration (environment only): PAYMENTS_ENABLED, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET, PAYMENT_MAX_RUPEES.
LIVE USE IS UNTESTED here (no Razorpay account); tests use a fake transport and known HMAC vectors.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, Optional

from . import maps_http
from .maps_http import MapsError

ORDERS_URL = "https://api.razorpay.com/v1/orders"
_ORDER_ID = re.compile(r"^order_[A-Za-z0-9]{8,30}$")
_PAYMENT_ID = re.compile(r"^pay_[A-Za-z0-9]{8,30}$")
MIN_PAISE = 100                                   # Rs 1
STATUSES = ("created", "captured", "failed", "refunded")


class PaymentError(ValueError):
    pass


def enabled(env: Mapping[str, str]) -> bool:
    return (str(env.get("PAYMENTS_ENABLED", "")).strip().lower() == "true" and bool((env.get("RAZORPAY_KEY_ID") or "").strip())
            and bool((env.get("RAZORPAY_KEY_SECRET") or "").strip()))


def max_paise(env: Mapping[str, str]) -> int:
    try:
        return int(max(1, min(1_000_000, Decimal(str(env.get("PAYMENT_MAX_RUPEES") or 50_000)))) * 100)
    except (InvalidOperation, ValueError):
        return 50_000 * 100


def rupees_to_paise(value: object, env: Mapping[str, str]) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise PaymentError("Enter an amount in rupees.")
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise PaymentError("Enter an amount in rupees.") from None
    if not d.is_finite() or d != d.quantize(Decimal("0.01")):
        raise PaymentError("Enter an amount with at most two decimal places.")
    paise = int(d * 100)
    if paise < MIN_PAISE:
        raise PaymentError("The smallest amount is Rs 1.")
    if paise > max_paise(env):
        raise PaymentError(f"The largest single payment is Rs {max_paise(env) // 100:,}.")
    return paise


def new_receipt() -> str:
    return "cb_" + uuid.uuid4().hex[:20]


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_payment_signature(order_id: str, payment_id: str, signature: str, secret: str) -> bool:
    if not (isinstance(order_id, str) and _ORDER_ID.match(order_id) and isinstance(payment_id, str) and _PAYMENT_ID.match(payment_id) and isinstance(signature, str) and secret):
        return False
    return hmac.compare_digest(_hmac_hex(secret, f"{order_id}|{payment_id}".encode()), signature.strip().lower())


def verify_webhook_signature(raw_body: bytes, signature: Optional[str], secret: str) -> bool:
    """The signature is over the RAW request bytes: re-serialising the JSON would change them."""
    if not secret or not signature or not isinstance(raw_body, (bytes, bytearray)):
        return False
    return hmac.compare_digest(_hmac_hex(secret, bytes(raw_body)), signature.strip().lower())


def next_status(current: str, event_type: str) -> str:
    """The status after a verified event. Late or duplicate events never move a payment backwards."""
    if current == "refunded":
        return "refunded"
    if event_type in ("payment.captured", "order.paid"):
        return "captured"
    if event_type in ("refund.processed", "refund.created") and current == "captured":
        return "refunded"
    if event_type == "payment.failed" and current == "created":
        return "failed"
    return current


def parse_event(payload: object) -> dict:
    """Pull the few fields we use out of a webhook payload; anything unexpected raises PaymentError (the caller still answers 200 once it is signed)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("event"), str):
        raise PaymentError("unreadable event")
    ent = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
    order_id = ent.get("order_id") or (((payload.get("payload") or {}).get("order") or {}).get("entity") or {}).get("id")
    pay_id = ent.get("id") if _PAYMENT_ID.match(str(ent.get("id") or "")) else None
    return {"type": payload["event"][:40], "order_id": order_id if _ORDER_ID.match(str(order_id or "")) else None, "payment_id": pay_id,
            "amount": ent.get("amount") if isinstance(ent.get("amount"), int) else None}


def event_id(header_value: Optional[str], raw_body: bytes) -> str:
    """Razorpay sends a unique id per event in X-Razorpay-Event-Id; without it, an identical redelivery still hashes to the same id."""
    v = (header_value or "").strip()
    return v[:80] if v and re.match(r"^[A-Za-z0-9_\-]{1,80}$", v) else "sha256:" + hashlib.sha256(raw_body).hexdigest()[:64]


def create_order(amount_paise: int, receipt: str, notes: dict, env: Mapping[str, str], transport: Optional[Callable] = None) -> dict:
    if not enabled(env):
        raise MapsError("not_configured", "Online donations are not switched on.")
    auth = base64.b64encode(f"{env['RAZORPAY_KEY_ID'].strip()}:{env['RAZORPAY_KEY_SECRET'].strip()}".encode()).decode()
    body = {"amount": int(amount_paise), "currency": "INR", "receipt": receipt, "notes": {str(k)[:30]: str(v)[:200] for k, v in (notes or {}).items()}}
    status, data = (transport or maps_http.request)("POST", ORDERS_URL, headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"}, json=body, timeout=10.0)
    maps_http.raise_for_status(status)
    if not isinstance(data, dict) or not _ORDER_ID.match(str(data.get("id") or "")) or data.get("amount") != int(amount_paise):
        raise MapsError("unavailable", "The payment service returned an unexpected answer.")
    return {"order_id": data["id"], "amount_paise": int(data["amount"]), "currency": "INR"}


def fetch_order_payments(order_id: str, env: Mapping[str, str], transport: Optional[Callable] = None) -> list[dict]:
    """The payments Razorpay has for an order: used to reconcile when a webhook was missed. [{id, status, amount}]"""
    if not enabled(env) or not _ORDER_ID.match(order_id or ""):
        raise MapsError("not_configured", "Online donations are not switched on.")
    auth = base64.b64encode(f"{env['RAZORPAY_KEY_ID'].strip()}:{env['RAZORPAY_KEY_SECRET'].strip()}".encode()).decode()
    status, data = (transport or maps_http.request)("GET", f"{ORDERS_URL}/{order_id}/payments", headers={"Authorization": f"Basic {auth}"}, timeout=10.0)
    maps_http.raise_for_status(status)
    items = data.get("items") if isinstance(data, dict) else None
    return [{"id": i.get("id"), "status": i.get("status"), "amount": i.get("amount")} for i in (items or []) if isinstance(i, dict) and _PAYMENT_ID.match(str(i.get("id") or ""))]
