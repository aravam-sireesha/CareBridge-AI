from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Need

MODEL_VERSION = "need-alerts-rules-1.0.0"

STALE_DAYS_BY_URGENCY = {"high": 2, "medium": 5, "low": 10}
LARGE_QUANTITY_THRESHOLD = 50
ACTIVE_NEED_STATUSES = ("open", "pending")


def evaluate_need(need: Need) -> dict | None:
    reasons = []
    score = 0.0

    if (need.status or "").lower() in ACTIVE_NEED_STATUSES:
        urgency = (need.urgency or "").lower()
        if urgency == "high":
            reasons.append("Marked high urgency and still open")
            score += 0.5

        if need.created_at:
            now = datetime.now(timezone.utc)
            created_at = need.created_at
            if created_at.tzinfo is None:
                now = now.replace(tzinfo=None)
            age_days = (now - created_at).days
            stale_limit = STALE_DAYS_BY_URGENCY.get(urgency, 7)
            if age_days >= stale_limit:
                reasons.append(
                    f"Open for {age_days} days, exceeds {stale_limit}-day limit for its urgency"
                )
                score += 0.4

        if need.quantity and need.quantity >= LARGE_QUANTITY_THRESHOLD:
            reasons.append(f"Large quantity requested: {need.quantity}")
            score += 0.3

    if not reasons:
        return None
    return {"score": round(min(score, 1.0), 3), "reasons": reasons}


def evaluate_all_open_needs(db: Session) -> list[dict]:
    results = []
    for need in db.query(Need).filter(func.lower(Need.status).in_(ACTIVE_NEED_STATUSES)).all():
        result = evaluate_need(need)
        if result:
            results.append({"need_id": need.id, **result})
    return results