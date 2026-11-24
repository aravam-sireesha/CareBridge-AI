"""Organization health: a transparent 0-100 score plus evidence-based development suggestions.

Everything is computed from the live database on every call (no cache), so the numbers always reflect
the current state of needs, donations, children and verification.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Child, ChildProfile, Donation, DonorSuggestion, KnowledgeBase, Need, Organization

OPEN = {"open", "pending"}
URGENT = {"critical", "high"}
WEIGHTS = {"verification": 10, "responsiveness": 25, "fulfilment": 20, "funding": 15, "donor_diversity": 15, "child_data": 15}
STALE_DAYS = 30


def _naive(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=None) if value is not None and value.tzinfo else value


def _grade(score: int) -> str:
    return "Thriving" if score >= 80 else "Healthy" if score >= 60 else "Needs attention" if score >= 40 else "At risk"


def organization_health(db: Session, org: Organization, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    needs = db.query(Need).filter(Need.org_id == org.id).all()
    open_needs = [n for n in needs if (n.status or "").lower() in OPEN]
    fulfilled = [n for n in needs if (n.status or "").lower() == "fulfilled"]
    need_ids = [n.id for n in needs]

    def age(n: Need) -> float:
        created = _naive(n.created_at)
        return (now - created).total_seconds() / 86400 if created else 0.0

    stale = [n for n in open_needs if age(n) > STALE_DAYS]
    urgent_open = [n for n in open_needs if (n.urgency or "").lower() in URGENT]

    donations = db.query(Donation).filter(Donation.need_id.in_(need_ids)).all() if need_ids else []
    covered = {d.need_id for d in donations}
    if need_ids:
        covered |= {s.need_id for s in db.query(DonorSuggestion).filter(
            DonorSuggestion.need_id.in_(need_ids), DonorSuggestion.status.in_(("approved", "contacted"))).all()}
    unmatched_urgent = [n for n in urgent_open if n.id not in covered]

    last30 = prior30 = 0.0
    last30_count = 0
    per_donor: dict[int, float] = defaultdict(float)
    donors_90 = set()
    for d in donations:
        ts = _naive(d.timestamp)
        days = (now - ts).total_seconds() / 86400 if ts else 9999
        amount = float(d.amount or 0)
        if days <= 30:
            last30 += amount
            last30_count += 1
        elif days <= 60:
            prior30 += amount
        if days <= 90 and d.donor_id is not None:
            donors_90.add(d.donor_id)
        if d.donor_id is not None:
            per_donor[d.donor_id] += amount
    total_given = sum(per_donor.values())
    top_share = (max(per_donor.values()) / total_given) if total_given > 0 else 0.0

    children = db.query(Child).filter(Child.org_id == org.id).all()
    child_ids = [c.id for c in children]
    profiled = db.query(ChildProfile).filter(ChildProfile.child_id.in_(child_ids)).count() if child_ids else 0
    kb_entries = db.query(KnowledgeBase).filter(KnowledgeBase.organization_id == org.id).count()
    categories = len({(n.category or "").strip().lower() for n in needs if n.category})

    # ---- sub-scores (0..1)
    if open_needs:
        responsiveness = max(0.0, 1 - min(1.0, (len(stale) + 0.5 * len(unmatched_urgent)) / len(open_needs)))
    else:
        responsiveness = 1.0
    closed_total = len(fulfilled) + len(open_needs)
    fulfilment = len(fulfilled) / closed_total if closed_total else 0.5
    if not donations:
        funding = 0.2
    elif last30 == 0:
        funding = 0.2
    elif prior30 == 0:
        funding = 0.8
    else:
        funding = min(1.0, 0.5 + 0.5 * min(1.0, last30 / prior30))
    donor_diversity = (min(1.0, len(per_donor) / 5) * 0.6 + (1 - top_share) * 0.4) if donations else 0.3
    child_data = (profiled / len(children)) if children else 0.5
    sub = {"verification": 1.0 if org.verified else 0.0, "responsiveness": responsiveness, "fulfilment": fulfilment,
           "funding": funding, "donor_diversity": donor_diversity, "child_data": child_data}
    score = int(round(sum(sub[k] * w for k, w in WEIGHTS.items())))

    # ---- recommendations (every one cites evidence from the tables)
    recs: list[dict] = []

    def rec(priority, area, title, detail):
        recs.append({"priority": priority, "area": area, "title": title, "detail": detail})

    if not org.verified:
        rec("high", "Trust", "Complete verification",
            "Unverified organizations are hidden from donors and volunteers, so your needs cannot receive help yet.")
    if unmatched_urgent:
        names = ", ".join(sorted({(n.category or "need") for n in unmatched_urgent})[:3])
        rec("high", "Needs", f"{len(unmatched_urgent)} urgent need(s) have no donor lined up",
            f"Ask an administrator to run donor suggestions for: {names}.")
    if stale:
        rec("medium", "Needs", f"{len(stale)} open need(s) are older than {STALE_DAYS} days",
            "Re-confirm the quantity and urgency, split large requests into smaller ones, or close needs that are no longer real.")
    if donations and last30 == 0:
        rec("high", "Funding", "No donations in the last 30 days",
            "Share your most urgent needs with donors and volunteers, and review whether the requests are specific enough.")
    elif prior30 > 0 and last30 < prior30 * 0.6:
        rec("medium", "Funding", "Giving is slowing down",
            f"Donations fell from {prior30:,.0f} to {last30:,.0f} compared with the previous 30 days.")
    if not donations and open_needs:
        rec("medium", "Funding", "No donations recorded yet", "Record every gift as it arrives so progress and fraud checks stay accurate.")
    if per_donor and top_share >= 0.6 and len(per_donor) > 1:
        rec("medium", "Donors", f"One donor gives {int(top_share * 100)}% of all funds",
            "Depending on a single supporter is risky. Invite a wider group of donors and thank repeat givers.")
    if len(per_donor) == 1:
        rec("medium", "Donors", "Only one donor so far", "Aim for at least five regular donors to protect against sudden gaps.")
    if children and profiled < len(children):
        rec("medium", "Children", f"{len(children) - profiled} of {len(children)} children have no career profile",
            "Complete profiles so career guidance and education needs can be planned early.")
    if not children:
        rec("low", "Children", "No children recorded", "Add child records (with consent) so needs can be tied to real support plans.")
    if closed_total and fulfilment < 0.3 and len(needs) >= 4:
        rec("medium", "Needs", "Few needs reach fulfilment", "Fewer, clearer needs are usually fulfilled faster than a long open list.")
    if kb_entries == 0:
        rec("low", "Knowledge", "Add your own policies to the assistant", "Upload safeguarding and volunteer policies so staff get answers specific to your organization.")
    if not recs:
        rec("low", "Growth", "Keep the momentum", "No problems detected. Consider documenting what works and mentoring newer organizations.")
    recs.sort(key=lambda r: {"high": 0, "medium": 1, "low": 2}[r["priority"]])

    return {
        "organization_id": org.id, "name": org.name, "verified": bool(org.verified),
        "score": score, "grade": _grade(score),
        "subscores": {k: round(v * 100) for k, v in sub.items()},
        "weights": WEIGHTS,
        "metrics": {
            "needs_total": len(needs), "open_needs": len(open_needs), "urgent_open": len(urgent_open),
            "stale_open": len(stale), "unmatched_urgent": len(unmatched_urgent), "fulfilled": len(fulfilled),
            "fulfilment_rate": round(fulfilment, 2) if closed_total else None,
            "donations_30d": last30_count, "amount_30d": round(last30, 2), "amount_prev_30d": round(prior30, 2),
            "donors_90d": len(donors_90), "top_donor_share": round(top_share, 2),
            "children": len(children), "children_profiled": profiled, "categories": categories,
        },
        "recommendations": recs,
    }


def all_organization_health(db: Session, now: datetime | None = None, org_ids: list[int] | None = None) -> list[dict]:
    q = db.query(Organization)
    if org_ids is not None:
        q = q.filter(Organization.id.in_(org_ids))
    return [organization_health(db, o, now) for o in q.order_by(Organization.id).all()]
