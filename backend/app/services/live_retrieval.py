"""Retrieval over live database records (the structured half of the RAG assistant).

The knowledge base holds written policy. This module makes the *rows* retrievable too: every visible
organization, need and donor becomes a short text record that is matched to the question (TF-IDF over
character n-grams, so typos and word forms still match). It also recognises organizations, donors and need
categories named in a question, and resolves short follow-ups ("and for Hope Home?") from the previous
question. Everything is scoped to what the asker's role may see.
"""
from __future__ import annotations

import re
from datetime import datetime

from sklearn.feature_extraction.text import TfidfVectorizer
from sqlalchemy.orm import Session

from ..models import AssistantMessage, Donation, Donor, Need, Organization
from . import donor_ml

GENERIC = {"home", "house", "foundation", "trust", "organization", "organisation", "children", "child", "care", "society",
           "centre", "center", "ngo", "welfare", "orphanage", "school", "team", "group", "donor", "donors"}
STOP = {"the", "and", "for", "are", "what", "which", "who", "how", "this", "that", "with", "our", "have", "need", "needs",
        "give", "tell", "show", "about", "does", "from", "right", "now", "should", "most", "can", "all", "any"}
FOLLOW_WORDS = ("and ", "what about", "how about", "those", "them", "that one", "same for", "also", "why", "which one",
                "more detail", "explain", "tell me more", "that organization", "this organization", "them?")


def donor_label(donor: Donor, viewer: dict) -> str:
    if viewer["role"] == "admin" or (viewer.get("organization_id") and donor.organization_id == viewer["organization_id"]):
        return donor.name
    focus = (donor.preferences or "general giving").split(",")[0].strip() or "general giving"
    return f"Donor #{donor.id} (interested in {focus})"


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def visible(db: Session, viewer: dict) -> dict:
    """Organizations, needs and donors this viewer is allowed to see."""
    role = viewer["role"]
    if role == "admin":
        return {"orgs": db.query(Organization).all(), "needs": db.query(Need).all(), "donors": db.query(Donor).all()}
    if role == "organization" and viewer.get("organization_id"):
        oid = viewer["organization_id"]
        org = db.get(Organization, oid)
        needs = db.query(Need).filter(Need.org_id == oid).all()
        ids = {n.id for n in needs}
        gave = {d.donor_id for d in db.query(Donation).filter(Donation.need_id.in_(ids)).all()} if ids else set()
        donors = [d for d in db.query(Donor).all() if d.organization_id == oid or d.id in gave]
        return {"orgs": [org] if org else [], "needs": needs, "donors": donors}
    if role == "donor" and viewer.get("donor_id"):
        orgs = db.query(Organization).filter(Organization.verified.is_(True)).all()
        ok = {o.id for o in orgs}
        needs = [n for n in db.query(Need).all() if n.org_id in ok and (n.status or "").lower() in donor_ml.OPEN_STATUSES]
        me = db.get(Donor, viewer["donor_id"])
        return {"orgs": orgs, "needs": needs, "donors": [me] if me else []}
    return {"orgs": [], "needs": [], "donors": []}


def build_records(db: Session, viewer: dict, now: datetime | None = None) -> list[dict]:
    now = now or datetime.utcnow()
    scope = visible(db, viewer)
    orgs = {o.id: o for o in scope["orgs"]}
    needs_by_org: dict[int, list[Need]] = {}
    for n in scope["needs"]:
        needs_by_org.setdefault(n.org_id, []).append(n)
    gifts: dict[int, list[Donation]] = {}
    for g in db.query(Donation).all():
        gifts.setdefault(g.donor_id, []).append(g)

    records = []
    for o in orgs.values():
        ns = needs_by_org.get(o.id, [])
        open_ns = [n for n in ns if (n.status or "").lower() in donor_ml.OPEN_STATUSES]
        cats = ", ".join(sorted({n.category for n in open_ns if n.category})[:6]) or "none"
        records.append({"kind": "organization", "ref_id": o.id, "title": f"Organization: {o.name}",
                        "text": f"{o.name} is a {'verified' if o.verified else 'unverified'} organization with {len(open_ns)} open need(s) "
                                f"({cats}) and {len(ns)} need(s) in total. Contact {o.contact or 'not given'}."})
    for n in scope["needs"]:
        org = orgs.get(n.org_id)
        info = donor_ml.score_need(n, now)
        age = f", open for {int(info['age_days'])} days" if info["age_days"] is not None else ""
        records.append({"kind": "need", "ref_id": n.id, "title": f"Need: {n.category} at {org.name if org else 'an organization'}",
                        "text": f"{n.category} needed by {org.name if org else 'an organization'}. Urgency {n.urgency}, status {n.status}, "
                                f"quantity {n.quantity}{age}. AI priority {info['score']} ({info['level']})."})
    for d in scope["donors"]:
        gs = gifts.get(d.id, [])
        last = max((g.timestamp for g in gs if g.timestamp), default=None)
        total = sum(float(g.amount or 0) for g in gs)
        records.append({"kind": "donor", "ref_id": d.id, "title": f"Donor: {donor_label(d, viewer)}",
                        "text": f"{donor_label(d, viewer)} supports {d.preferences or 'general giving'}. {len(gs)} gift(s) totalling {total:,.0f}"
                                f"{', last on ' + last.strftime('%d %b %Y') if last else ''}. Location {d.location or 'not given'}."})
    return records


def retrieve_records(db: Session, viewer: dict, question: str, k: int = 5, min_score: float = 0.22) -> list[dict]:
    recs = build_records(db, viewer)
    if not recs or not question.strip():
        return []
    docs = [f"{r['title']}. {r['text']}" for r in recs]
    try:
        matrix = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True).fit_transform(docs + [question])
    except ValueError:
        return []
    cos = (matrix[:-1] @ matrix[-1].T).toarray().ravel()
    q_tokens = {t for t in _tokens(question) if len(t) > 3 and t not in STOP}
    out = []
    for r, c, doc in zip(recs, cos, docs):
        overlap = (sum(1 for t in q_tokens if t in doc.lower()) / len(q_tokens)) if q_tokens else 0.0
        score = round(0.7 * float(c) + 0.3 * overlap, 3)
        if score >= min_score:
            out.append({"id": None, "title": r["title"], "content": r["text"], "source": f"live database ({r['kind']} records)",
                        "score": score, "live": True, "kind": r["kind"], "ref_id": r["ref_id"]})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:k]


def _mentions(name: str, q: str, q_tokens: set[str]) -> bool:
    n = (name or "").lower().strip()
    if len(n) < 3:
        return False
    if n in q:
        return True
    toks = [t for t in _tokens(n) if len(t) >= 3 and t not in GENERIC]
    return bool(toks) and all(t in q_tokens for t in toks)


def detect_entities(db: Session, viewer: dict, question: str) -> dict:
    q = question.lower()
    q_tokens = set(_tokens(q))
    scope = visible(db, viewer)
    cats = sorted({(n.category or "").strip() for n in scope["needs"] if n.category and len((n.category or "").strip()) >= 3})
    donors = scope["donors"] if viewer["role"] in ("admin", "organization") else []
    if viewer["role"] == "organization":
        donors = [d for d in donors if d.organization_id == viewer.get("organization_id")]
    return {
        "organizations": [o for o in scope["orgs"] if _mentions(o.name, q, q_tokens)] if viewer["role"] == "admin" else [],
        "donors": [d for d in donors if _mentions(d.name, q, q_tokens)],
        "categories": [c for c in cats if c.lower() in q],
    }


def has_entities(entities: dict) -> bool:
    return any(entities.values())


def resolve_follow_up(db: Session, user: dict, question: str) -> str | None:
    """A short, signal-free question with a follow-up cue ("and for them?") inherits the previous question."""
    q = f" {question.lower().strip()}"
    if len(question.split()) > 9 or not any(w in q if w.endswith(" ") else w in q for w in FOLLOW_WORDS):
        return None
    last = (db.query(AssistantMessage).filter(AssistantMessage.user_id == user["id"])
            .order_by(AssistantMessage.id.desc()).first())
    return last.question if last else None


def focus_names(entities: dict) -> list[str]:
    return ([o.name for o in entities["organizations"]] + [d.name for d in entities["donors"]] + list(entities["categories"]))
