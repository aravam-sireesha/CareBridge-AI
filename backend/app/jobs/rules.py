"""Pure decisions for the scheduled jobs. They take plain dicts and a clock, so they are unit-tested without a database."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

DELAYED_AFTER_HOURS = 6              # in transit longer than this: an administrator is alerted (same threshold the map shows)
RECEIPT_REMINDER_AFTER_HOURS = 24    # delivered but the organization has not confirmed what it received
OTP_KEEP_DAYS = 1                    # expired/used one-time codes and reset tokens are deleted after this long


def stale_actions(sessions: list[dict], now: datetime, stale_seconds: int) -> list[dict]:
    """Decide what to do with ACTIVE tracking sessions. Each input: {session_id, task_id, expires_at, last_fix_at, started_at, stale_notified_at}.
    -> [{session_id, task_id, action}] where action is 'expire' (past its time limit: stop it) or 'stale' (no fix lately: tell viewers once)."""
    out = []
    for s in sessions:
        if s.get("expires_at") is not None and now >= s["expires_at"]:
            out.append({"session_id": s["session_id"], "task_id": s["task_id"], "action": "expire"})
            continue
        last = s.get("last_fix_at") or s.get("started_at")
        if last is not None and (now - last).total_seconds() > stale_seconds and s.get("stale_notified_at") is None and s.get("last_fix_at") is not None:
            out.append({"session_id": s["session_id"], "task_id": s["task_id"], "action": "stale"})
    return out


def receipt_reminders(deliveries: list[dict], now: datetime, after_hours: int = RECEIPT_REMINDER_AFTER_HOURS) -> list[dict]:
    """Deliveries marked delivered long ago whose receipt nobody confirmed. Input: {id, status, delivered_at}."""
    cut = now - timedelta(hours=after_hours)
    return [d for d in deliveries if d.get("status") == "delivered" and d.get("delivered_at") is not None and d["delivered_at"] <= cut]


def overdue_transits(deliveries: list[dict], now: datetime, after_hours: int = DELAYED_AFTER_HOURS) -> list[dict]:
    cut = now - timedelta(hours=after_hours)
    return [d for d in deliveries if d.get("status") == "in_transit" and d.get("in_transit_at") is not None and d["in_transit_at"] <= cut]


def reminder_key(kind: str, task_id: int, now: datetime) -> str:
    """One reminder per delivery per kind per calendar day (UTC): the queue's idempotency key makes a second scan a no-op."""
    return f"{kind}:{int(task_id)}:{now:%Y%m%d}"


def otp_cutoff(now: datetime, keep_days: int = OTP_KEEP_DAYS) -> datetime:
    return now - timedelta(days=keep_days)


def email_job(user: dict, title: str, link: Optional[str], base_url: str) -> Optional[dict]:
    """Payload for an e-mail notification, or None if this person must not be e-mailed (inactive, unverified, no address)."""
    if not user.get("is_active") or not user.get("email") or user.get("email_verified_at") is None:
        return None
    return {"to": user["email"], "template": "generic", "ctx": {"title": (title or "")[:120]}, "link": link, "base_url": base_url}
