"""Phase 1 - reliable data. Verifies relationships, consistency and the calculation rules the AI depends on.

Every model downstream (RAG over live records, prediction, optimization) is only as good as the rows it reads, so this
runs first: it reports broken relationships (SQLite does not enforce foreign keys; PostgreSQL does), impossible values,
inventory that does not add up, duplicated records, and checks that the scoring rules stay inside their documented ranges.
Safe, deterministic problems can be repaired with `repair`; everything else is reported for a person to resolve."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from .. import models as m
from ..services import donor_ml, org_health

VALID_ROLES = {"organization", "donor", "volunteer", "admin"}
VALID_URGENCY = {"low", "medium", "high", "critical"}
VALID_STATUS = {"open", "pending", "fulfilled", "closed"}
REPAIRABLE = ("resource_stock", "verification_flags")


def _issue(code, severity, title, items, hint, fixable=False, category="consistency"):
    return {"code": code, "severity": severity, "category": category, "title": title, "count": len(items),
            "examples": items[:5], "hint": hint, "auto_fixable": fixable}


def _ids(model, db):
    return {r[0] for r in db.query(model.id).all()}


def check(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    issues: list[dict] = []
    orgs, donors, vols, needs = _ids(m.Organization, db), _ids(m.Donor, db), _ids(m.Volunteer, db), _ids(m.Need, db)
    resources = _ids(m.Resource, db)

    # ----------------------------------------------------------------- relationships (orphans)
    def orphans(code, title, rows, fk_attr, valid, extra=""):
        bad = [f"{type(r).__name__} #{r.id} -> {fk_attr}={getattr(r, fk_attr)}" for r in rows if getattr(r, fk_attr) is not None and getattr(r, fk_attr) not in valid]
        if bad:
            issues.append(_issue(code, "error", title, bad, "Restore the missing parent row or clear the link. " + extra, category="relationship"))

    needs_rows = db.query(m.Need).all()
    orphans("need_org", "Needs that point to a missing organization", needs_rows, "org_id", orgs)
    donation_rows = db.query(m.Donation).all()
    orphans("donation_need", "Donations that point to a missing need", donation_rows, "need_id", needs)
    orphans("donation_donor", "Donations that point to a missing donor", donation_rows, "donor_id", donors)
    alloc_rows = db.query(m.ResourceAllocation).all()
    orphans("alloc_need", "Allocations that point to a missing need", alloc_rows, "need_id", needs)
    orphans("alloc_resource", "Allocations that point to a missing resource", alloc_rows, "resource_id", resources)
    orphans("child_org", "Children that point to a missing organization", db.query(m.Child).all(), "org_id", orgs)
    for model, fk, valid, code in ((m.DonorSuggestion, "need_id", needs, "dsug_need"), (m.DonorSuggestion, "donor_id", donors, "dsug_donor"),
                                   (m.VolunteerSuggestion, "volunteer_id", vols, "vsug_vol"), (m.Match, "need_id", needs, "match_need")):
        orphans(code, f"{model.__name__} rows that point to a missing {fk[:-3]}", db.query(model).all(), fk, valid)
    user_rows = db.query(m.User).all()
    for fk, valid in (("organization_id", orgs), ("donor_id", donors), ("volunteer_id", vols)):
        orphans(f"user_{fk}", f"Users linked to a missing {fk[:-3]}", user_rows, fk, valid)
    bad_link = []
    for u in user_rows:
        if u.role == "organization" and not u.organization_id or u.role == "donor" and not u.donor_id or u.role == "volunteer" and not u.volunteer_id:
            bad_link.append(f"{u.email} ({u.role}) has no linked profile")
        if u.role not in VALID_ROLES:
            bad_link.append(f"{u.email} has unknown role '{u.role}'")
    if bad_link:
        issues.append(_issue("user_profile", "error", "Users whose role and profile do not match", bad_link, "Link the account to its profile or correct the role.", category="relationship"))

    # ----------------------------------------------------------------- values
    bad = [f"Need #{n.id} quantity={n.quantity}" for n in needs_rows if n.quantity is None or n.quantity < 0]
    if bad:
        issues.append(_issue("need_quantity", "error", "Needs with a missing or negative quantity", bad, "Quantities drive priority, allocation and forecasts. Correct them."))
    bad = [f"Need #{n.id} urgency={n.urgency!r}" for n in needs_rows if (n.urgency or "").lower() not in VALID_URGENCY]
    bad += [f"Need #{n.id} status={n.status!r}" for n in needs_rows if (n.status or "").lower() not in VALID_STATUS]
    if bad:
        issues.append(_issue("need_vocab", "warning", "Needs with an unknown urgency or status", bad, "Use low/medium/high/critical and open/pending/fulfilled/closed."))
    bad = [f"Donation #{d.id}" for d in donation_rows if (d.amount is not None and d.amount < 0) or (not d.amount and not (d.resource_description or "").strip())]
    if bad:
        issues.append(_issue("donation_value", "error", "Donations with a negative amount, or with neither an amount nor a description", bad, "Record an amount or describe the in-kind gift."))
    bad = [f"Need #{n.id} created {n.created_at}" for n in needs_rows if n.created_at and (n.created_at - now).total_seconds() > 86400]
    if bad:
        issues.append(_issue("future_dates", "warning", "Records dated in the future", bad, "Check the system clock and imported dates."))

    # ----------------------------------------------------------------- inventory and allocation accounting
    committed: dict[int, int] = defaultdict(int)
    by_need: dict[int, int] = defaultdict(int)
    delivered_by_need: dict[int, int] = defaultdict(int)
    for a in alloc_rows:
        if a.status in ("approved", "delivered"):
            committed[a.resource_id] += a.quantity or 0
            by_need[a.need_id] += a.quantity or 0
        if a.status == "delivered":
            delivered_by_need[a.need_id] += a.quantity or 0
    res_rows = db.query(m.Resource).all()
    bad = [f"Resource #{r.id} '{r.name}': available={r.quantity_available}, expected {r.quantity_total - committed.get(r.id, 0)}"
           for r in res_rows if r.quantity_available != r.quantity_total - committed.get(r.id, 0)]
    if bad:
        issues.append(_issue("resource_stock", "error", "Inventory does not add up (available must equal total minus approved and delivered allocations)", bad,
                             "Run the repair 'resource_stock' to recompute availability from allocations.", fixable=True, category="inventory"))
    bad = [f"Resource #{r.id} '{r.name}': total={r.quantity_total}, available={r.quantity_available}" for r in res_rows
           if r.quantity_total < 0 or r.quantity_available < 0 or r.quantity_available > r.quantity_total]
    if bad:
        issues.append(_issue("resource_range", "error", "Resources with negative stock or more available than the total", bad, "Correct the quantities.", category="inventory"))
    need_by_id = {n.id: n for n in needs_rows}
    bad = [f"Need #{nid}: {q} allocated for a need of {need_by_id[nid].quantity}" for nid, q in by_need.items() if nid in need_by_id and q > (need_by_id[nid].quantity or 0)]
    if bad:
        issues.append(_issue("over_allocation", "error", "Needs that received more resource units than they asked for", bad, "Cancel the surplus allocation so stock returns to inventory.", category="inventory"))
    bad = [f"Need #{n.id} is fulfilled but only {delivered_by_need.get(n.id, 0)} of {n.quantity} units are recorded as delivered" for n in needs_rows
           if (n.status or "").lower() == "fulfilled" and delivered_by_need.get(n.id, 0) < (n.quantity or 0) and n.id in by_need]
    if bad:
        issues.append(_issue("fulfilled_without_delivery", "warning", "Fulfilled needs whose allocations were not all delivered", bad, "Mark the allocations delivered, or reopen the need."))

    # ----------------------------------------------------------------- flags and duplicates
    bad = [f"Organization #{o.id} verified={o.verified} status={o.verification_status}" for o in db.query(m.Organization).all()
           if bool(o.verified) != ((o.verification_status or "pending") == "verified")]
    if bad:
        issues.append(_issue("verification_flags", "warning", "Organizations whose verified flag and verification status disagree", bad,
                             "Run the repair 'verification_flags' to set the status from the verified flag.", fixable=True))
    donor_rows = db.query(m.Donor).all()
    dup = [k for k, c in Counter(((d.name or "").strip().lower(), (d.contact or "").strip().lower()) for d in donor_rows if (d.name or "").strip()).items() if c > 1]
    if dup:
        issues.append(_issue("duplicate_donors", "warning", "Possible duplicate donors (same name and contact)", [f"{n} / {c}" for n, c in dup], "Merge the duplicates so giving history and suggestions are not split."))
    keyed = Counter((n.org_id, (n.category or "").strip().lower(), (n.title or "").strip().lower()) for n in needs_rows if (n.status or "").lower() in ("open", "pending"))
    dup = [f"org {k[0]}: {k[1]} {k[2]}".strip() for k, c in keyed.items() if c > 1]
    if dup:
        issues.append(_issue("duplicate_needs", "warning", "Open needs that look duplicated", dup, "Merge or close the repeated requests."))

    # ----------------------------------------------------------------- calculation rules stay inside their documented ranges
    rule_problems = []
    for n in needs_rows:
        if (n.status or "").lower() in donor_ml.OPEN_STATUSES:
            sc = donor_ml.score_need(n, now)["score"]
            if not 0.0 <= sc <= 1.0:
                rule_problems.append(f"priority of need #{n.id} = {sc}")
    if sum(org_health.WEIGHTS.values()) != 100:
        rule_problems.append(f"organization health weights add up to {sum(org_health.WEIGHTS.values())}, not 100")
    for o in db.query(m.Organization).limit(200).all():
        h = org_health.organization_health(db, o, now)
        if not 0 <= h["score"] <= 100 or any(not 0 <= v <= 100 for v in h["subscores"].values()):
            rule_problems.append(f"health of organization #{o.id} = {h['score']}")
    for model in (m.DonorSuggestion, m.VolunteerSuggestion):
        for s in db.query(model).all():
            if not all(0.0 <= v <= 1.0 for v in (s.fit_score, s.urgency_score, s.priority_score)):
                rule_problems.append(f"{model.__name__} #{s.id} has a score outside 0-1")
            elif abs(s.priority_score - (0.5 * s.urgency_score + 0.5 * s.fit_score)) > 0.002:
                rule_problems.append(f"{model.__name__} #{s.id}: priority {s.priority_score} is not 0.5 x urgency + 0.5 x fit")
    if rule_problems:
        issues.append(_issue("rule_ranges", "error", "Calculation rules produced out-of-range or inconsistent values", rule_problems, "Fix the inputs, or re-run the scans so stored scores are recomputed.", category="calculation"))

    counts = Counter(i["severity"] for i in issues)
    tables = {"organizations": len(orgs), "needs": len(needs), "donors": len(donors), "volunteers": len(vols), "donations": len(donation_rows), "resources": len(resources),
              "allocations": len(alloc_rows), "users": len(user_rows)}
    return {"checked_at": now.isoformat(timespec="seconds") + "Z", "ok": counts.get("error", 0) == 0, "errors": counts.get("error", 0), "warnings": counts.get("warning", 0),
            "tables": tables, "issues": sorted(issues, key=lambda i: (i["severity"] != "error", -i["count"]))}


def repair(db: Session, fixes: list[str]) -> dict:
    """Apply only deterministic, safe repairs. Returns how many rows each one changed."""
    changed: dict[str, int] = {}
    for fix in fixes:
        if fix not in REPAIRABLE:
            raise ValueError(f"'{fix}' cannot be repaired automatically")
        n = 0
        if fix == "resource_stock":
            used: dict[int, int] = defaultdict(int)
            for a in db.query(m.ResourceAllocation).filter(m.ResourceAllocation.status.in_(("approved", "delivered"))).all():
                used[a.resource_id] += a.quantity or 0
            for r in db.query(m.Resource).all():
                expected = max(0, (r.quantity_total or 0) - used.get(r.id, 0))
                if r.quantity_available != expected:
                    r.quantity_available, n = expected, n + 1
        elif fix == "verification_flags":
            for o in db.query(m.Organization).all():
                want = "verified" if o.verified else ("rejected" if o.verification_status == "rejected" else "pending")
                if (o.verification_status or "pending") != want:
                    o.verification_status, n = want, n + 1
        changed[fix] = n
    db.commit()
    return changed
