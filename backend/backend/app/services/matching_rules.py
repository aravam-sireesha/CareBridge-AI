from sqlalchemy.orm import Session
from app.models import Donor, Volunteer, Need

MODEL_VERSION = "matching-rules-1.2.0"

CATEGORY_GROUPS = {
    "education": {"school supplies", "tutoring", "books", "mentoring", "scholarship"},
    "food": {"groceries", "meals", "nutrition"},
    "medical": {"healthcare", "medicine", "clinic", "checkup"},
    "clothing": {"clothes", "shoes", "uniforms"},
}


def _normalize(text: str | None) -> str:
    return (text or "").strip().lower()


def _same_group(a: str, b: str) -> bool:
    for group, members in CATEGORY_GROUPS.items():
        if (a == group or a in members) and (b == group or b in members):
            return True
    return False


def _tag_match_score(need_category: str | None, other_text: str | None) -> float:
    """Score exact, partial, or mapped category matches from 0.0 to 1.0."""
    a, b = _normalize(need_category), _normalize(other_text)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.6
    if _same_group(a, b):
        return 0.4
    return 0.0

def _urgency_weight(urgency: str | None) -> float:
    return {"high": 1.0, "medium": 0.6, "low": 0.3}.get(_normalize(urgency), 0.5)

def score_donor_match(need: Need, donor: Donor) -> dict:
    tag_score = _tag_match_score(need.category, donor.preferences)
    urgency = _urgency_weight(need.urgency)
    score = round((tag_score * 0.65) + (urgency * 0.35), 3)
    reasons = []
    if tag_score > 0:
        label = "Category-group match" if tag_score == 0.4 else "Preference match"
        reasons.append(f"{label}: '{donor.preferences}' vs need '{need.category}' ({tag_score})")
    if need.urgency:
        reasons.append(f"Need urgency: {need.urgency}")
    return {"score": score, "category_score": tag_score, "reasons": reasons}

def score_volunteer_match(need: Need, volunteer: Volunteer) -> dict:
    tag_score = _tag_match_score(need.category, volunteer.skills)
    urgency = _urgency_weight(need.urgency)
    available = 1.0 if _normalize(volunteer.availability) not in ("", "unavailable", "none") else 0.0
    score = round((tag_score * 0.55) + (urgency * 0.25) + (available * 0.2), 3)
    reasons = []
    if tag_score > 0:
        label = "Category-group skill match" if tag_score == 0.4 else "Skill match"
        reasons.append(f"{label}: '{volunteer.skills}' vs need '{need.category}' ({tag_score})")
    if available:
        reasons.append(f"Availability: {volunteer.availability}")
    if need.urgency:
        reasons.append(f"Need urgency: {need.urgency}")
    return {"score": score, "category_score": tag_score, "reasons": reasons}

def suggest_matches(db: Session, need: Need, top_n: int = 3) -> list[dict]:
    candidates = []
    for donor in db.query(Donor).all():
        result = score_donor_match(need, donor)
        if result["category_score"] > 0:
            candidates.append({"donor_id": donor.id, "volunteer_id": None, **result})
    for volunteer in db.query(Volunteer).all():
        result = score_volunteer_match(need, volunteer)
        if result["category_score"] > 0:
            candidates.append({"donor_id": None, "volunteer_id": volunteer.id, **result})
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:top_n]