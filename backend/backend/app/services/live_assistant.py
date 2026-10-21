"""Live-data layer for the RAG assistant.

The knowledge base answers *policy* questions. This module answers *situation* questions
("which needs are most urgent?", "who should we ask to donate?", "how is our organization doing?")
from the live database, at the moment the question is asked, and always within the asker's role scope:

  administrator  - every organization, all donors by name
  organization   - its own organization; donors outside the organization are shown anonymously
  donor          - verified open needs ranked for the donor's own interests
  volunteer      - policy answers only

The analysis is deterministic and every number comes from a table row. A language model, when configured,
may only rephrase these facts (see rag.generate_grounded_answer).
"""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Donation, Donor, Need, Organization
from . import donor_ml, org_health
from .live_retrieval import donor_label as _label

# Only situation / action phrasing triggers live data. Bare words such as "need", "donor" or "match" also
# appear in plain policy questions ("Do volunteers need a background check?") and must stay on the knowledge base.
INTENT_WORDS = {
    "health": ("organization health", "organisation health", "healthy", "how are we doing", "how is my organization",
               "how is our organization", "how is my org", "how is our org", "improve", "improvement", "development",
               "develop ", "grow ", "growth", "performance", "strengths", "weaknesses", "sustainab",
               "advice for my organization", "advice for our organization"),
    "compare": ("compare", "comparison", "ranking", "rank the", "all organizations", "each organization",
                "different organization", "which organization", "organization comparison"),
    "selection": ("which donor", "best donor", "right donor", "suggest donor", "select donor", "find donor", "donors for",
                  "who should donate", "who should we ask", "who should we contact", "who can fund", "donor suggestion",
                  "most urgent", "urgent need", "urgent", "priority", "priorities", "critical need", "which need",
                  "top need", "needs first", "support first", "what should we fund", "what should i fund", "what should i support"),
    "donors": ("lapsed", "inactive donor", "not donated", "haven't donated", "have not donated", "stopped giving", "top donor",
               "biggest donor", "best donors", "donor retention", "donor list", "donor activity", "donor analysis",
               "donor engagement", "donors who", "donor gap", "no donor", "without donor", "interest gap", "coverage"),
    "snapshot": ("right now", "real time", "real-time", "latest", "currently", "today", "live data", "how many needs",
                 "how many donors", "how many organizations", "how many open", "current status", "overview of"),
}


def classify(question: str) -> list[str]:
    q = f" {question.lower()} "
    found = [intent for intent, words in INTENT_WORDS.items() if any(w in q for w in words)]
    if "compare" in found and "health" not in found:
        found.append("health")
    return found


def _visible_org_ids(viewer: dict) -> list[int] | None:
    if viewer["role"] == "admin":
        return None
    if viewer["role"] == "organization" and viewer.get("organization_id"):
        return [viewer["organization_id"]]
    return []


def build_analysis(db: Session, viewer: dict, intents: list[str] | None = None, top_needs: int = 5, top_donors: int = 3,
                   focus: dict | None = None) -> dict:
    """Return structured, role-scoped, real-time analysis. `intents` None means everything useful."""
    now = datetime.utcnow()
    role = viewer["role"]
    wanted = set(intents or ["health", "selection", "snapshot"])
    focus = focus or {}
    result: dict = {"generated_at": now.isoformat(timespec="seconds") + "Z", "scope": role, "intents": sorted(wanted),
                    "health": [], "selection": [], "snapshot": None, "sources": [], "donor_insights": None,
                    "donor_profiles": [], "focus": [o.name for o in focus.get("organizations", [])]
                    + [d.name for d in focus.get("donors", [])] + list(focus.get("categories", []))}

    org_ids = _visible_org_ids(viewer)
    if focus.get("organizations") and org_ids is None:  # administrators can zoom in on named organizations
        org_ids = [o.id for o in focus["organizations"]]
    categories = [c.lower() for c in focus.get("categories", [])]
    if role in ("admin", "organization"):
        if org_ids == []:
            return result
        health = org_health.all_organization_health(db, now, org_ids)
        by_org = {h["organization_id"]: h for h in health}
        if "health" in wanted or "compare" in wanted:
            result["health"] = sorted(health, key=lambda h: h["score"]) if role == "admin" else health
            result["sources"].append({"title": "Organization health (live)", "source": "organizations, needs, donations, children tables",
                                      "content": f"{len(health)} organization(s) scored at {now:%H:%M} UTC."})

        needs_q = db.query(Need)
        if org_ids is not None:
            needs_q = needs_q.filter(Need.org_id.in_(org_ids))
        open_needs = [n for n in needs_q.all() if (n.status or "").lower() in donor_ml.OPEN_STATUSES]
        if categories:
            open_needs = [n for n in open_needs if (n.category or "").lower() in categories]
        orgs = {o.id: o for o in db.query(Organization).all()}
        result["snapshot"] = {
            "organizations": (len(org_ids) if org_ids is not None else len(orgs)) if role == "admin" else 1,
            "open_needs": len(open_needs),
            "urgent_open": sum(1 for n in open_needs if (n.urgency or "").lower() in org_health.URGENT),
            "donors": db.query(Donor).count() if role == "admin" else None,
        }
        if "selection" in wanted:
            ctx = donor_ml.DonorContext(db, now)
            learned = donor_ml.train_learned_model(db)
            ranked = []
            for n in open_needs:
                org = orgs.get(n.org_id)
                h = by_org.get(n.org_id)
                if role != "admin" and org is not None and not org.verified:
                    pass  # an organization still sees its own needs
                info = donor_ml.score_need(n, now)
                reliability = 0.5 * (1.0 if org and org.verified else 0.0) + 0.5 * ((h["score"] / 100) if h else 0.5)
                gap = 1 - ((h["subscores"]["funding"] / 100) if h else 0.5)
                sel = round(0.75 * info["score"] + 0.15 * reliability + 0.10 * gap, 3)
                ranked.append((sel, n, org, h, info, reliability, gap))
            ranked.sort(key=lambda r: r[0], reverse=True)
            for sel, n, org, h, info, reliability, gap in ranked[:top_needs]:
                picks = donor_ml.suggest_donors(db, n, top_n=top_donors, ctx=ctx, learned=learned)
                donor_by_id = {d.id: d for d in ctx.donors}
                reasons = list(info["reasons"])
                if org is not None and not org.verified:
                    reasons.append("Organization is not verified yet; verify before asking donors")
                if h and h["subscores"]["funding"] <= 30:
                    reasons.append("Organization has had little recent funding, so this need is more likely to stay unmet")
                result["selection"].append({
                    "need_id": n.id, "category": n.category, "urgency": n.urgency, "quantity": n.quantity,
                    "organization_id": n.org_id, "organization": org.name if org else None,
                    "organization_verified": bool(org.verified) if org else False,
                    "organization_health": h["score"] if h else None,
                    "selection_score": sel, "priority_score": info["score"], "priority_level": info["level"], "reasons": reasons,
                    "donors": [{"donor_id": p["donor_id"], "label": _label(donor_by_id[p["donor_id"]], viewer),
                                "fit_score": p["fit_score"], "reasons": p["reasons"][:2]} for p in picks],
                })
            result["sources"].append({"title": "Needs and donor ranking (live)", "source": "needs, donors, donations tables + donor-ml",
                                      "content": f"{len(open_needs)} open need(s) ranked at {now:%H:%M} UTC; model {donor_ml.MODEL_VERSION}-{learned[1]['mode']}."})
        if "donors" in wanted or focus.get("donors"):
            ctx2 = donor_ml.DonorContext(db, now)
            scope_donors = ctx2.donors if role == "admin" else [d for d in ctx2.donors if d.organization_id == viewer.get("organization_id")]
            stats = _gift_stats(db)
            if "donors" in wanted:
                result["donor_insights"] = _donor_insights(db, viewer, scope_donors, stats, open_needs, ctx2.donors, orgs, now)
                result["sources"].append({"title": "Donor analytics (live)", "source": "donors, donations tables",
                                          "content": f"{len(scope_donors)} donor(s) analysed at {now:%H:%M} UTC."})
            for d in focus.get("donors", [])[:3]:
                result["donor_profiles"].append(_donor_profile(db, d, viewer, stats, open_needs, ctx2, now))
    elif role == "donor" and viewer.get("donor_id"):
        donor = db.get(Donor, viewer["donor_id"])
        if donor is not None:
            orgs = {o.id: o for o in db.query(Organization).filter(Organization.verified.is_(True)).all()}
            open_needs = [n for n in db.query(Need).all()
                          if n.org_id in orgs and (n.status or "").lower() in donor_ml.OPEN_STATUSES]
            result["snapshot"] = {"organizations": len(orgs), "open_needs": len(open_needs),
                                  "urgent_open": sum(1 for n in open_needs if (n.urgency or "").lower() in org_health.URGENT), "donors": None}
            need_by_id = {n.id: n for n in open_needs}
            for r in donor_ml.rank_needs_for_donor(db, donor, open_needs)[:top_needs]:
                n = need_by_id[r["need_id"]]
                result["selection"].append({
                    "need_id": n.id, "category": n.category, "urgency": n.urgency, "quantity": n.quantity,
                    "organization_id": n.org_id, "organization": orgs[n.org_id].name, "organization_verified": True,
                    "organization_health": None, "selection_score": r["priority_score"], "priority_score": r["priority_score"],
                    "priority_level": donor_ml.score_need(n, now)["level"], "reasons": r["reasons"], "donors": [],
                })
            result["sources"].append({"title": "Needs that suit you (live)", "source": "needs table (verified organizations only)",
                                      "content": f"{len(open_needs)} open verified need(s) ranked for your interests at {now:%H:%M} UTC."})
    return result


def _gift_stats(db: Session) -> dict[int, dict]:
    stats: dict[int, dict] = {}
    for g in db.query(Donation).all():
        s = stats.setdefault(g.donor_id, {"gifts": 0, "total": 0.0, "last": None, "needs": []})
        s["gifts"] += 1
        s["total"] += float(g.amount or 0)
        s["needs"].append(g.need_id)
        if g.timestamp and (s["last"] is None or g.timestamp > s["last"]):
            s["last"] = g.timestamp
    return stats


def _days(ts, now):
    if ts is None:
        return None
    return int(((now - (ts.replace(tzinfo=None) if ts.tzinfo else ts)).total_seconds()) / 86400)


def _donor_insights(db, viewer, scope_donors, stats, open_needs, all_donors, orgs, now) -> dict:
    rows = []
    for d in scope_donors:
        s = stats.get(d.id)
        rows.append({"donor_id": d.id, "label": _label(d, viewer), "gifts": s["gifts"] if s else 0,
                     "total": round(s["total"], 2) if s else 0.0, "days_since_last": _days(s["last"], now) if s else None})
    given = [r for r in rows if r["gifts"]]
    lapsed = sorted([r for r in given if r["days_since_last"] is not None and r["days_since_last"] > 90], key=lambda r: -r["total"])
    gaps = []
    for n in open_needs:
        matches = sum(1 for d in all_donors if any(donor_ml._tag_match_score(n.category, p) > 0 for p in donor_ml._split_prefs(d.preferences)))
        if matches <= 1:
            gaps.append({"category": n.category, "urgency": n.urgency, "organization": orgs[n.org_id].name if n.org_id in orgs else None,
                         "matching_donors": matches, "_rank": donor_ml.URGENCY_BASE.get((n.urgency or "").lower(), 0.5)})
    gaps.sort(key=lambda g: -g["_rank"])
    for g in gaps:
        g.pop("_rank")
    return {"total": len(rows), "active_90d": sum(1 for r in given if r["days_since_last"] is not None and r["days_since_last"] <= 90),
            "lapsed": lapsed[:5], "lapsed_count": len(lapsed), "never_given": len(rows) - len(given),
            "top_donors": sorted(given, key=lambda r: -r["total"])[:5], "interest_gaps": gaps[:5]}


def _donor_profile(db, donor, viewer, stats, open_needs, ctx, now) -> dict:
    s = stats.get(donor.id)
    days = _days(s["last"], now) if s else None
    need_by_id = {n.id: n for n in db.query(Need).all()}
    cats = sorted({need_by_id[i].category for i in (s["needs"] if s else []) if i in need_by_id and need_by_id[i].category})
    orgs = {o.id: o for o in db.query(Organization).all()}
    best = []
    for r in donor_ml.rank_needs_for_donor(db, donor, open_needs, ctx)[:3]:
        n = need_by_id[r["need_id"]]
        best.append({"need_id": n.id, "category": n.category, "organization": orgs[n.org_id].name if n.org_id in orgs else None,
                     "urgency": n.urgency, "priority_score": r["priority_score"], "fit_score": r["fit_score"]})
    status = "new" if not s else ("lapsed" if days is not None and days > 90 else "active")
    return {"donor_id": donor.id, "label": _label(donor, viewer), "preferences": donor.preferences, "location": donor.location,
            "gifts": s["gifts"] if s else 0, "total_given": round(s["total"], 2) if s else 0.0, "days_since_last": days,
            "status": status, "categories_given": cats, "best_needs": best}


def has_content(analysis: dict) -> bool:
    return bool(analysis["health"] or analysis["selection"] or analysis["snapshot"]
                or analysis.get("donor_insights") or analysis.get("donor_profiles"))


def follow_ups(analysis: dict) -> list[str]:
    out: list[str] = []
    if analysis["selection"]:
        top = analysis["selection"][0]
        out.append(f"Which donors fit {top['category']} best?")
    if analysis["health"] and analysis["scope"] == "admin" and len(analysis["health"]) > 1:
        out.append(f"How can {analysis['health'][0]['name']} improve?")
    if analysis["scope"] == "admin" and not analysis.get("donor_insights"):
        out.append("Which donors have stopped giving?")
    if analysis.get("donor_insights") and analysis["donor_insights"]["interest_gaps"]:
        out.append("What should we do about needs with no matching donors?")
    if analysis["scope"] == "organization" and not analysis["health"]:
        out.append("How can our organization improve its health and development?")
    return out[:3]


def compose_answer(analysis: dict, intents: list[str]) -> str:
    """Plain-language summary built only from the analysis numbers (used without an LLM and as LLM context)."""
    when = analysis["generated_at"][11:16]
    lines = [f"Live data as of {when} UTC."]
    snap = analysis.get("snapshot")
    health = analysis["health"]
    sel = analysis["selection"]
    wants_health = "health" in intents or "compare" in intents
    wants_sel = "selection" in intents
    if snap and ("snapshot" in intents or (not wants_health and not wants_sel)):
        extra = f", {snap['urgent_open']} of them urgent" if snap["urgent_open"] else ""
        lines.append(f"There are {snap['open_needs']} open need(s){extra}"
                     + (f" across {snap['organizations']} organization(s)." if snap["organizations"] and analysis["scope"] != "organization" else "."))
    if wants_health and health:
        if analysis["scope"] == "admin" and len(health) > 1:
            avg = round(sum(h["score"] for h in health) / len(health))
            lines.append(f"Average organization health is {avg}/100. Needing the most attention: "
                         + "; ".join(f"{h['name']} {h['score']} ({h['grade']})" for h in health[:3]) + ".")
        else:
            h = health[0]
            lines.append(f"{h['name']} scores {h['score']}/100 ({h['grade']}).")
            tops = h["recommendations"][:3]
            if tops:
                lines.append("Suggested next steps: " + " ".join(f"{i}) {r['title']}." for i, r in enumerate(tops, 1)))
    if wants_sel and sel:
        lines.append("Needs to act on first:")
        for i, s in enumerate(sel[:3], 1):
            who = f" at {s['organization']}" if s["organization"] else ""
            donors = (" Best donors: " + ", ".join(f"{d['label']} (fit {d['fit_score']})" for d in s["donors"]) + ".") if s["donors"] else ""
            lines.append(f"{i}. {s['category'] or 'Need'}{who} - {s['priority_level']} priority ({s['priority_score']}).{donors}")
    elif wants_sel:
        lines.append("There are no open needs to rank right now.")
    di = analysis.get("donor_insights")
    if di:
        lines.append(f"Donors: {di['total']} in scope, {di['active_90d']} gave in the last 90 days, {di['lapsed_count']} lapsed, {di['never_given']} have never given.")
        if di["lapsed"]:
            lines.append("Lapsed donors worth contacting: " + "; ".join(f"{r['label']} ({r['total']:,.0f} given, {r['days_since_last']} days ago)" for r in di["lapsed"][:3]) + ".")
        if di["interest_gaps"]:
            lines.append("Needs with no or one matching donor: " + "; ".join(f"{g['category']} ({g['urgency']}, {g['matching_donors']} match)" for g in di["interest_gaps"][:3]) + ".")
    for p in analysis.get("donor_profiles", []):
        lines.append(f"{p['label']} is {p['status']}: {p['gifts']} gift(s), {p['total_given']:,.0f} given"
                     + (f", last {p['days_since_last']} days ago" if p["days_since_last"] is not None else "")
                     + (f". Best open needs: " + ", ".join(f"{b['category']} at {b['organization']}" for b in p["best_needs"]) if p["best_needs"] else "") + ".")
    if analysis.get("focus"):
        lines.insert(1, "Focused on: " + ", ".join(analysis["focus"]) + ".")
    lines.append("These are suggestions from live data; an administrator makes the final decision.")
    return "\n".join(lines)


def live_context_text(analysis: dict) -> str:
    """Compact facts handed to an LLM (when configured) so it cannot invent numbers."""
    parts = [compose_answer(analysis, analysis["intents"])]
    di = analysis.get("donor_insights")
    if di:
        parts.append(f"DONOR INSIGHTS: {di}")
    for p in analysis.get("donor_profiles", []):
        parts.append(f"DONOR PROFILE: {p}")
    for h in analysis["health"][:5]:
        parts.append(f"ORG {h['name']}: score {h['score']}, subscores {h['subscores']}, metrics {h['metrics']}, "
                     f"recommendations: " + " | ".join(f"{r['title']} - {r['detail']}" for r in h["recommendations"][:4]))
    for s in analysis["selection"]:
        parts.append(f"NEED #{s['need_id']} {s['category']} ({s['urgency']}, qty {s['quantity']}) at {s['organization']}: "
                     f"priority {s['priority_score']}; donors " + ", ".join(f"{d['label']} fit {d['fit_score']}" for d in s["donors"]))
    return "\n".join(parts)


def compose_records_answer(records: list[dict]) -> str:
    """Answer built only from retrieved live records (used when no analysis intent matched)."""
    when = datetime.utcnow().strftime("%H:%M")
    lines = [f"Live data as of {when} UTC. The most relevant records I found:"]
    for i, r in enumerate(records[:4], 1):
        lines.append(f"{i}. {r['content']}")
    lines.append("These come straight from the database; an administrator makes the final decision.")
    return "\n".join(lines)
