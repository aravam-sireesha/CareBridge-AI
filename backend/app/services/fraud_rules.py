from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Donation

MODEL_VERSION = "fraud-rules-1.0.0"


def score_donation(db: Session, donation: Donation) -> dict | None:
    """Return a rules-based anomaly score, or None when no rule is triggered."""
    reasons = []
    score = 0.0

    if donation.donor_id is None:
        reasons.append("No donor_id linked to this donation")
        score += 0.3

    if donation.donor_id is not None:
        history = (
            db.query(Donation.amount)
            .filter(Donation.donor_id == donation.donor_id, Donation.id != donation.id)
            .all()
        )
        amounts = [row[0] for row in history if row[0] is not None]

        if not amounts:
            if donation.amount and donation.amount > 50000:
                reasons.append(
                    f"First donation from donor, unusually large amount ({donation.amount})"
                )
                score += 0.4
        else:
            average = sum(amounts) / len(amounts)
            if average > 0 and donation.amount and donation.amount > average * 5:
                reasons.append(
                    f"Amount {donation.amount} is 5x+ this donor's average ({average:.2f})"
                )
                score += 0.5

        if donation.timestamp:
            recent_cutoff = donation.timestamp - timedelta(hours=1)
            recent_count = (
                db.query(func.count(Donation.id))
                .filter(
                    Donation.donor_id == donation.donor_id,
                    Donation.timestamp >= recent_cutoff,
                    Donation.timestamp <= donation.timestamp,
                )
                .scalar()
            )
            if recent_count and recent_count >= 4:
                reasons.append(f"{recent_count} donations from this donor within 1 hour")
                score += 0.4

    if not reasons:
        return None
    return {"score": min(score, 1.0), "reasons": reasons}