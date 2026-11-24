from sqlalchemy.orm import Session
from app.models import Donor, Organization, Volunteer, Need
from app.services import availability, geo

MODEL_VERSION = "matching-rules-1.5.0"

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

# Fit bands turn the weighted-rule score into words. They are thresholds on a transparent score, NOT probabilities and
# NOT a validated accuracy: say "strong fit", never "87% likely".
BAND_STRONG, BAND_GOOD = 0.70, 0.45


def fit_band(score: float) -> str:
    return "strong" if score >= BAND_STRONG else "good" if score >= BAND_GOOD else "partial"


def rank_candidates(need, donors, volunteers, origin=None, context=None) -> dict:
    """Score the people given, apply location rules, and sort. Returns {"candidates": [...], "stats": {...}}.

    Eligibility first: a person whose offer/skills share no category with the need is left out (and counted), and a
    volunteer outside the travel range they set is left out (and counted). Scores are never changed by location.

    `context` (optional) = {"when": naive-UTC datetime of the pickup, "weight_kg": load}. With it, a volunteer is also left out when
    they DECLARED hours that do not cover `when`, or a carrying capacity below the load. Missing information never excludes: it is
    reported as "not stated". Without a context nothing about availability or capacity is considered, exactly as before."""
    stats = {"donors_considered": 0, "volunteers_considered": 0, "donors_category_miss": 0, "volunteers_category_miss": 0, "volunteers_out_of_range": 0, "volunteers_unavailable": 0, "volunteers_over_capacity": 0}
    candidates = []
    for donor in donors:
        stats["donors_considered"] += 1
        result = score_donor_match(need, donor)
        if result["category_score"] <= 0:
            stats["donors_category_miss"] += 1
            continue
        candidate = {"donor_id": donor.id, "volunteer_id": None, **result}
        if geo.apply_to_candidate(candidate, origin, donor, "donor"):
            candidates.append(candidate)
    for volunteer in volunteers:
        stats["volunteers_considered"] += 1
        result = score_volunteer_match(need, volunteer)
        if result["category_score"] <= 0:
            stats["volunteers_category_miss"] += 1
            continue
        candidate = {"donor_id": None, "volunteer_id": volunteer.id, **result}
        if not geo.apply_to_candidate(candidate, origin, volunteer, "volunteer"):
            stats["volunteers_out_of_range"] += 1
            continue
        if context:
            fit = availability.assess(getattr(volunteer, "availability_slots", None), getattr(volunteer, "availability_timezone", None),
                                      getattr(volunteer, "carry_capacity_kg", None), context.get("when"), context.get("weight_kg"))
            if fit["exclude"]:
                stats["volunteers_over_capacity" if fit["capacity"] == "exceeds" else "volunteers_unavailable"] += 1
                continue
            candidate["reasons"] = list(candidate["reasons"]) + fit["reasons"]
        candidates.append(candidate)
    # Highest score first; nearer first only among equal scores. With no positions every distance is "unknown"
    # (infinite), so the stable sort keeps the original order exactly as before.
    candidates.sort(key=lambda c: (-c["score"], c.get("distance_km", float("inf"))))
    return {"candidates": candidates, "stats": stats}


def explain_unmatched(need, stats: dict, remaining_quantity: int | None = None, has_location: bool = True) -> list[dict]:
    """Why nothing was suggested, and what could change that. Every line is a fact about THIS search, never a guess."""
    out = []
    if remaining_quantity is not None and remaining_quantity <= 0:
        return [{"kind": "general", "reason": "Deliveries already cover the whole quantity this need asks for.", "suggestion": "Nothing more is needed. If the need grew, edit its quantity first."}]
    if stats["donors_considered"] == 0:
        out.append({"kind": "donor", "reason": "No donors are linked to your organization yet.", "suggestion": "Add the donors you work with under Donors & volunteers, or ask an administrator to run platform-wide suggestions."})
    elif stats["donors_category_miss"] == stats["donors_considered"]:
        out.append({"kind": "donor", "reason": f"None of your {stats['donors_considered']} donor(s) list '{need.category}' (or a related category) among what they give.", "suggestion": "Ask donors to update their preferences, or add a donor who gives this kind of item."})
    if stats["volunteers_considered"] == 0:
        out.append({"kind": "volunteer", "reason": "No volunteers are linked to your organization yet.", "suggestion": "Invite volunteers, or ask an administrator to suggest volunteers from the wider community."})
    elif stats["volunteers_category_miss"] and stats["volunteers_category_miss"] == stats["volunteers_considered"]:
        out.append({"kind": "volunteer", "reason": f"None of your {stats['volunteers_considered']} volunteer(s) list skills or interests that fit '{need.category}'.", "suggestion": "Ask volunteers to add their skills, or recruit someone who can help with this."})
    if stats["volunteers_out_of_range"]:
        out.append({"kind": "volunteer", "reason": f"{stats['volunteers_out_of_range']} volunteer(s) fit the category but live outside the travel range they set.", "suggestion": "Check that your organization's location is correct, or ask them to widen their travel range."})
    if stats.get("volunteers_unavailable"):
        out.append({"kind": "volunteer", "reason": f"{stats['volunteers_unavailable']} volunteer(s) fit the category but declared hours that do not cover that pickup time.", "suggestion": "Try another pickup time, or ask them to update their availability."})
    if stats.get("volunteers_over_capacity"):
        out.append({"kind": "volunteer", "reason": f"{stats['volunteers_over_capacity']} volunteer(s) fit the category but said they cannot carry a load that heavy in one trip.", "suggestion": "Split the delivery into lighter trips, or find a volunteer with a larger vehicle."})
    if not has_location:
        out.append({"kind": "general", "reason": "Your organization has no saved location, so distance could not be used.", "suggestion": "Set it in Settings, then Location. Distance then helps order and filter volunteers."})
    return out


def suggest_matches(db: Session, need: Need, top_n: int = 3) -> list[dict]:
    """Platform-wide ranking for one need (administrator tool). Same rules as the Matching Center, over every donor and volunteer."""
    organization = db.get(Organization, need.org_id) if getattr(need, "org_id", None) else None
    origin = geo.need_point(need, organization)
    ranked = rank_candidates(need, db.query(Donor).all(), db.query(Volunteer).all(), origin)
    return ranked["candidates"][:top_n]
