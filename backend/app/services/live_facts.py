"""Read-only, role-scoped facts the chat can quote: organization verification, donation status, and needs that have waited.

Every function only SELECTs. A result always says whether a number is a real zero ("0 ... found") or not available to the asker's
role, so the assistant can never turn missing access into "nothing there"."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .. import models
from . import chat_intent
from .donor_ml import OPEN_STATUSES

TERMINAL_DONATION_STATUSES = {"delivered", "confirmed", "completed", "cancelled", "canceled", "rejected", "received"}
_AWAITING_VERIFY = ("pending", "under_review", "info_requested")
STALE_DAYS = 14


wants = chat_intent.facts_wanted


def _age_days(ts, now):
    return max(0, (now - ts).days) if ts else None


def verification_facts(db: Session, user: dict) -> dict:
    now = datetime.utcnow()
    if user["role"] != "admin":
        return {"title": "Organization verification", "available": False,
                "text": "Organization verification status is only available to administrators, so I cannot report it for your role."}
    orgs = db.query(models.Organization).all()
    counts = Counter((o.verification_status or ("verified" if o.verified else "unspecified")).lower() for o in orgs)
    waiting = sorted([o for o in orgs if (o.verification_status or "").lower() in _AWAITING_VERIFY], key=lambda o: o.verification_submitted_at or o.created_at or now)
    lines = [f"Organizations: {len(orgs)} in total. By verification status: " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none") + "."]
    if waiting:
        lines.append(f"{len(waiting)} awaiting a decision (pending, under review or information requested), oldest first:")
        for o in waiting[:8]:
            lines.append(f"- {o.name}: {(o.verification_status or '').replace('_', ' ')}, submitted {(o.verification_submitted_at or o.created_at or now).date().isoformat()} ({_age_days(o.verification_submitted_at or o.created_at, now)} days ago)")
    else:
        lines.append("0 organizations are awaiting verification (none pending, under review or info requested).")
    return {"title": "Organization verification", "available": True, "text": "\n".join(lines)}


def donation_facts(db: Session, user: dict) -> dict:
    now = datetime.utcnow()
    q = db.query(models.Donation)
    role = user["role"]
    if role == "organization" and user.get("organization_id"):
        q = q.join(models.Need, models.Need.id == models.Donation.need_id).filter(models.Need.org_id == user["organization_id"])
        scope = "donations to your organization's needs"
    elif role == "donor" and user.get("donor_id"):
        q = q.filter(models.Donation.donor_id == user["donor_id"])
        scope = "your donations"
    elif role == "admin":
        scope = "all donations"
    else:
        return {"title": "Donations", "available": False, "text": "Donation records are not available to your role, so I cannot report them."}
    rows = q.all()
    by_status = Counter((d.status or "unspecified").lower() for d in rows)
    waiting = sorted([d for d in rows if (d.status or "unspecified").lower() not in TERMINAL_DONATION_STATUSES], key=lambda d: d.timestamp or now)
    lines = [f"Scope: {scope}. {len(rows)} donation record(s)." + (" By status: " + ", ".join(f"{k} {v}" for k, v in sorted(by_status.items())) + "." if rows else "")]
    if not rows:
        lines.append("0 donations were found in the data you can access.")
    elif waiting:
        lines.append(f"{len(waiting)} not yet delivered or confirmed (any status other than delivered, confirmed, completed, cancelled, rejected or received), oldest first:")
        for d in waiting[:6]:
            what = d.resource_description or (f"amount {d.amount}" if d.amount else (d.kind or "donation"))
            lines.append(f"- donation #{d.id}: {what}, status {d.status or 'unspecified'}, {_age_days(d.timestamp, now)} days since it was made")
    else:
        lines.append("0 donations are waiting for delivery or confirmation.")
    return {"title": "Donations", "available": True, "text": "\n".join(lines)}


def attention_facts(db: Session, user: dict) -> dict:
    now = datetime.utcnow()
    q = db.query(models.Need)
    if user["role"] == "organization":
        if not user.get("organization_id"):
            return {"title": "Needs that need attention", "available": False, "text": "Your account is not linked to an organization, so I cannot list its needs."}
        q = q.filter(models.Need.org_id == user["organization_id"])
    open_needs = [n for n in q.all() if (n.status or "").lower() in OPEN_STATUSES]
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    flagged = []
    for n in open_needs:
        age = _age_days(n.created_at, now)
        overdue = bool(n.required_by and n.required_by < now)
        if (age is not None and age >= STALE_DAYS) or overdue:
            flagged.append((rank.get((n.urgency or "").lower(), 4), -(age or 0), n, age, overdue))
    flagged.sort(key=lambda t: (t[0], t[1]))
    lines = [f"{len(open_needs)} open need(s) in total."]
    if flagged:
        lines.append(f"{len(flagged)} have been open for {STALE_DAYS}+ days or are past their required-by date, most urgent first:")
        for _, _, n, age, overdue in flagged[:8]:
            lines.append(f"- need #{n.id} {n.title or n.category}: {n.quantity} x {n.category}, urgency {n.urgency}, open {age} days" + (", past its required-by date" if overdue else ""))
    else:
        lines.append(f"0 open needs have waited {STALE_DAYS}+ days or passed their required-by date.")
    return {"title": "Needs that need attention", "available": True, "text": "\n".join(lines)}


def build(db: Session, user: dict, question: str) -> dict | None:
    """Facts for whatever the question asks, or None when it asks for none of them."""
    wanted = wants(question)
    if not wanted:
        return None
    parts = []
    if "verification" in wanted:
        parts.append(verification_facts(db, user))
    if "attention" in wanted:
        parts.append(attention_facts(db, user))
    if "donations" in wanted:
        parts.append(donation_facts(db, user))
    if not parts:
        return None
    text = "\n\n".join(f"{p['title'].upper()}:\n{p['text']}" for p in parts)
    sources = [{"title": p["title"], "content": p["text"].split("\n")[0][:300], "source": "Live database", "kind": "facts", "live": True, "score": 1.0} for p in parts if p["available"]]
    return {"text": text, "sources": sources, "available": any(p["available"] for p in parts)}
