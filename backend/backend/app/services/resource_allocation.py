"""Resource allocation suggestions: which available resources can cover an open need?

Score = 0.6 x category relevance + 0.3 x how much of the remaining need the resource can cover
        + 0.1 if the resource belongs to the same organization as the need.
The AI only proposes; an administrator approves, then the resource is delivered.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Need, Resource, ResourceAllocation
from .matching_rules import _normalize, _tag_match_score

MODEL_VERSION = "resource-alloc-1.0.0"
COMMITTED = ("approved", "delivered")


def committed_quantity(db: Session, need_id: int) -> int:
    return int(db.query(func.coalesce(func.sum(ResourceAllocation.quantity), 0))
               .filter(ResourceAllocation.need_id == need_id, ResourceAllocation.status.in_(COMMITTED)).scalar() or 0)


def delivered_quantity(db: Session, need_id: int) -> int:
    return int(db.query(func.coalesce(func.sum(ResourceAllocation.quantity), 0))
               .filter(ResourceAllocation.need_id == need_id, ResourceAllocation.status == "delivered").scalar() or 0)


def suggest_allocations(db: Session, need: Need, top_n: int = 3) -> list[dict]:
    remaining = max(0, (need.quantity or 0) - committed_quantity(db, need.id))
    if remaining <= 0:
        return []
    out = []
    for r in db.query(Resource).filter(Resource.status == "available", Resource.quantity_available > 0).all():
        relevance = max(_tag_match_score(need.category, r.category or ""), _tag_match_score(need.category, r.name or ""))
        if relevance <= 0:
            continue
        qty = min(r.quantity_available, remaining)
        coverage = qty / remaining
        same_org = 1.0 if r.organization_id and r.organization_id == need.org_id else 0.0
        score = round(0.6 * relevance + 0.3 * coverage + 0.1 * same_org, 3)
        reasons = [f"'{r.name}' matches the need '{need.category}' (relevance {round(relevance, 2)})",
                   f"Can cover {qty} of the {remaining} still needed ({int(coverage * 100)}%)"]
        if same_org:
            reasons.append("Held by the same organization, so no transfer is needed")
        out.append({"resource_id": r.id, "quantity": qty, "score": score, "reasons": reasons, "_name": _normalize(r.name)})
    out.sort(key=lambda c: c["score"], reverse=True)
    for c in out:
        c.pop("_name")
    return out[:top_n]


def save_proposals(db: Session, need: Need, candidates: list[dict], user_id: int | None) -> list[ResourceAllocation]:
    saved = []
    for c in candidates:
        row = (db.query(ResourceAllocation).filter_by(need_id=need.id, resource_id=c["resource_id"], status="proposed").first())
        if row is None:
            row = ResourceAllocation(need_id=need.id, resource_id=c["resource_id"], quantity=c["quantity"], score=c["score"],
                                     reasons=c["reasons"], status="proposed", proposed_by=user_id)
            db.add(row)
        else:
            row.quantity, row.score, row.reasons = c["quantity"], c["score"], c["reasons"]
        saved.append(row)
    db.flush()
    return saved
