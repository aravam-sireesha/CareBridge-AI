"""One recommendation engine for the four things an administrator coordinates:
organizations, needs, donors and volunteers (plus the resources that connect them).

    need          -> best donors, volunteers, resources, partner organizations that hold matching resources
    donor         -> best needs to support, best organizations to support
    volunteer     -> best needs to help with, best organizations to join
    organization  -> its needs ranked by priority, best donors, volunteers and resources for those needs, health

Every item has a 0-1 score and plain-language reasons. Scores come from the models in donor_ml, volunteer_ml,
resource_allocation, org_health and forecast; nothing is invented here. The administrator decides.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Donor, Need, Organization, Resource, Volunteer
from . import donor_ml, forecast, org_health, resource_allocation, volunteer_ml

ENTITIES = ("organization", "need", "donor", "volunteer")


def _item(kind: str, id_: int, label: str, sublabel: str, score: float, reasons: list[str], **extra) -> dict:
    return {"kind": kind, "id": id_, "label": label, "sublabel": sublabel, "score": round(float(score), 3), "reasons": reasons, "extra": extra}


def _open(n: Need) -> bool:
    return (n.status or "").lower() in donor_ml.OPEN_STATUSES


def entity_options(db: Session) -> dict:
    orgs = {o.id: o for o in db.query(Organization).order_by(Organization.name).all()}
    needs = [n for n in db.query(Need).all() if _open(n)]
    needs.sort(key=lambda n: -donor_ml.score_need(n)["score"])
    return {
        "organization": [{"id": o.id, "label": o.name, "sublabel": "verified" if o.verified else "not verified"} for o in orgs.values()],
        "need": [{"id": n.id, "label": f"{n.category} · {orgs[n.org_id].name if n.org_id in orgs else 'Organization'}", "sublabel": f"{n.urgency} urgency, qty {n.quantity}"} for n in needs],
        "donor": [{"id": d.id, "label": d.name, "sublabel": d.preferences or "no interests recorded"} for d in db.query(Donor).order_by(Donor.name).all()],
        "volunteer": [{"id": v.id, "label": v.name, "sublabel": v.skills or "no skills recorded"} for v in db.query(Volunteer).order_by(Volunteer.name).all()],
    }


def _forecast_for(db: Session, categories: set[str]) -> list[dict]:
    wanted = {c.lower() for c in categories if c}
    return [f for f in forecast.forecast_categories(db) if f["category"] in wanted]


def _org_rollup(db: Session, ranked: list[tuple[Need, float, str]], top_n: int) -> list[dict]:
    """ranked = (need, priority_score, reason). Roll needs up to the organizations that own them."""
    by_org: dict[int, list[tuple[Need, float, str]]] = defaultdict(list)
    for need, score, reason in ranked:
        if need.org_id:
            by_org[need.org_id].append((need, score, reason))
    out = []
    for org_id, rows in by_org.items():
        org = db.get(Organization, org_id)
        if org is None:
            continue
        health = org_health.organization_health(db, org)
        rows.sort(key=lambda r: -r[1])
        top = rows[:3]
        score = 0.6 * top[0][1] + 0.2 * (sum(r[1] for r in top) / len(top)) + 0.2 * (health["score"] / 100) * (1.0 if org.verified else 0.5)
        reasons = [f"Best match: '{top[0][0].category}' ({top[0][0].urgency} urgency). {top[0][2]}",
                   f"{len(rows)} open need(s) fit; organization health {health['score']}/100 ({health['grade']})"]
        if not org.verified:
            reasons.append("Not verified yet, so an administrator should verify it before it is promoted")
        out.append(_item("organization", org.id, org.name, f"{len(rows)} matching need(s)", score, reasons,
                         health=health["score"], verified=bool(org.verified), need_ids=[r[0].id for r in rows]))
    out.sort(key=lambda i: -i["score"])
    return out[:top_n]


def recommend(db: Session, entity: str, entity_id: int, top_n: int = 5) -> dict:
    now = datetime.utcnow()
    orgs = {o.id: o for o in db.query(Organization).all()}
    open_needs = [n for n in db.query(Need).all() if _open(n)]
    donor_ctx, vol_ctx = donor_ml.DonorContext(db, now), volunteer_ml.VolunteerContext(db, now)
    donor_model, vol_model = donor_ml.train_learned_model(db), volunteer_ml.train_learned_model(db)
    donors_by_id = {d.id: d for d in donor_ctx.donors}
    vols_by_id = {v.id: v for v in vol_ctx.volunteers}
    resources_by_id = {r.id: r for r in db.query(Resource).all()}

    def donor_items(cands):
        return [_item("donor", c["donor_id"], donors_by_id[c["donor_id"]].name, donors_by_id[c["donor_id"]].preferences or "", c["fit_score"], c["reasons"][:3],
                      priority=c["priority_score"]) for c in cands]

    def volunteer_items(cands):
        return [_item("volunteer", c["volunteer_id"], vols_by_id[c["volunteer_id"]].name, vols_by_id[c["volunteer_id"]].skills or "", c["fit_score"], c["reasons"][:3],
                      priority=c["priority_score"]) for c in cands]

    def resource_items(cands):
        out = []
        for c in cands:
            r = resources_by_id[c["resource_id"]]
            out.append(_item("resource", r.id, r.name, f"{c['quantity']} {r.unit or 'units'} available · held by {orgs[r.organization_id].name if r.organization_id in orgs else 'platform / partner'}",
                             c["score"], c["reasons"][:3], quantity=c["quantity"], organization_id=r.organization_id))
        return out

    if entity == "need":
        need = db.get(Need, entity_id)
        if need is None:
            raise LookupError("Need not found")
        info = donor_ml.score_need(need, now)
        cands = resource_allocation.suggest_allocations(db, need, top_n=20)
        partner: dict[int, dict] = {}
        for c in cands:
            r = resources_by_id[c["resource_id"]]
            if r.organization_id and r.organization_id != need.org_id and (r.organization_id not in partner or c["score"] > partner[r.organization_id]["score"]):
                partner[r.organization_id] = {**c, "resource": r.name}
        return {
            "entity": {"kind": "need", "id": need.id, "label": f"{need.category} · {orgs[need.org_id].name if need.org_id in orgs else 'Organization'}",
                       "sublabel": f"{need.urgency} urgency, quantity {need.quantity}, AI priority {info['score']} ({info['level']})", "score": info["score"], "reasons": info["reasons"]},
            "sections": {
                "donors": donor_items(donor_ml.suggest_donors(db, need, top_n, donor_ctx, donor_model)),
                "volunteers": volunteer_items(volunteer_ml.suggest_volunteers(db, need, top_n, vol_ctx, vol_model)),
                "resources": resource_items(cands[:top_n]),
                "organizations": [_item("organization", oid, orgs[oid].name, f"holds '{p['resource']}'", p["score"], p["reasons"][:2]) for oid, p in
                                  sorted(partner.items(), key=lambda kv: -kv[1]["score"])[:top_n] if oid in orgs],
            },
            "forecast": _forecast_for(db, {need.category}),
        }

    if entity in ("donor", "volunteer"):
        person = db.get(Donor if entity == "donor" else Volunteer, entity_id)
        if person is None:
            raise LookupError(f"{entity.title()} not found")
        needs_by_id = {n.id: n for n in open_needs}
        if entity == "donor":
            ranked = donor_ml.rank_needs_for_donor(db, person, open_needs, donor_ctx)
            sub = person.preferences or ""
        else:
            ranked = volunteer_ml.rank_needs_for_volunteer(db, person, open_needs, vol_ctx)
            sub = person.skills or ""
        need_items = [_item("need", r["need_id"], f"{needs_by_id[r['need_id']].category} · {orgs[needs_by_id[r['need_id']].org_id].name if needs_by_id[r['need_id']].org_id in orgs else 'Organization'}",
                            f"{needs_by_id[r['need_id']].urgency} urgency, qty {needs_by_id[r['need_id']].quantity}", r["priority_score"], r["reasons"][:3], fit=r["fit_score"])
                      for r in ranked[:top_n]]
        rollup = _org_rollup(db, [(needs_by_id[r["need_id"]], r["priority_score"], r["reasons"][0]) for r in ranked], top_n)
        label = person.name
        return {"entity": {"kind": entity, "id": person.id, "label": label, "sublabel": sub, "score": None, "reasons": []},
                "sections": {"needs": need_items, "organizations": rollup}, "forecast": _forecast_for(db, {needs_by_id[r["need_id"]].category for r in ranked[:top_n]})}

    if entity == "organization":
        org = orgs.get(entity_id)
        if org is None:
            raise LookupError("Organization not found")
        mine = [n for n in open_needs if n.org_id == org.id]
        health = org_health.organization_health(db, org, now)
        mine.sort(key=lambda n: -donor_ml.score_need(n, now)["score"])
        need_items = []
        for n in mine[:top_n]:
            info = donor_ml.score_need(n, now)
            need_items.append(_item("need", n.id, n.category or f"Need {n.id}", f"{n.urgency} urgency, qty {n.quantity}", info["score"], info["reasons"], level=info["level"]))
        agg_d: dict[int, dict] = {}
        agg_v: dict[int, dict] = {}
        agg_r: dict[int, dict] = {}
        for n in mine[:10]:
            for c in donor_ml.suggest_donors(db, n, 3, donor_ctx, donor_model):
                if c["donor_id"] not in agg_d or c["fit_score"] > agg_d[c["donor_id"]]["fit_score"]:
                    agg_d[c["donor_id"]] = {**c, "need": n.category}
            for c in volunteer_ml.suggest_volunteers(db, n, 3, vol_ctx, vol_model):
                if c["volunteer_id"] not in agg_v or c["fit_score"] > agg_v[c["volunteer_id"]]["fit_score"]:
                    agg_v[c["volunteer_id"]] = {**c, "need": n.category}
            for c in resource_allocation.suggest_allocations(db, n, 2):
                if c["resource_id"] not in agg_r or c["score"] > agg_r[c["resource_id"]]["score"]:
                    agg_r[c["resource_id"]] = {**c, "need": n.category}
        top = lambda d, key: sorted(d.values(), key=lambda c: -c[key])[:top_n]  # noqa: E731
        d_items = donor_items(top(agg_d, "fit_score"))
        for it, c in zip(d_items, top(agg_d, "fit_score")):
            it["sublabel"] = f"best for '{c['need']}'"
        v_items = volunteer_items(top(agg_v, "fit_score"))
        for it, c in zip(v_items, top(agg_v, "fit_score")):
            it["sublabel"] = f"best for '{c['need']}'"
        return {"entity": {"kind": "organization", "id": org.id, "label": org.name, "sublabel": f"health {health['score']}/100 ({health['grade']}) · {len(mine)} open need(s)",
                           "score": health["score"] / 100, "reasons": [r["title"] for r in health["recommendations"][:3]]},
                "sections": {"needs": need_items, "donors": d_items, "volunteers": v_items, "resources": resource_items(top(agg_r, "score"))},
                "health": health, "forecast": _forecast_for(db, {n.category for n in mine})}
    raise ValueError("entity must be one of: " + ", ".join(ENTITIES))
