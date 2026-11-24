"""ML volunteer suggestions (the volunteer-side twin of donor_ml).

Features per (need, volunteer) pair
  text_sim     TF-IDF character n-gram similarity between the need's category (expanded with its category group)
               and the volunteer's skills
  group_match  category / category-group match of any listed skill (matching_rules)
  availability parsed from the free-text availability ("weekends", "full time", "evenings", ...)
  history      confirmed earlier matches with similar needs
  familiarity  the volunteer already belongs to the need's organization
  reliability  share of earlier suggestions for this volunteer that administrators approved (Laplace smoothed)

Cold start: a transparent weighted blend. After MIN_TRAIN_ROWS reviewed suggestions (both approved and rejected),
a logistic regression trained on the administrators' decisions is averaged in. AI recommends; people decide.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sqlalchemy.orm import Session

from ..models import Match, Need, Volunteer, VolunteerSuggestion
from .donor_ml import OPEN_STATUSES, POSITIVE, URGENCY_BASE, _clip, _need_text, _split_prefs, score_need
from .matching_rules import _normalize, _tag_match_score

MODEL_VERSION = "volunteer-ml-1.0.0"
MIN_TRAIN_ROWS = 20
LEARNED_FEATURES = ["text_sim", "group_match", "availability", "history", "familiarity"]
CONFIRMED = {"confirmed", "accepted", "approved"}


def availability_score(text: str | None) -> float:
    t = _normalize(text)
    if not t or t in {"unavailable", "none", "no", "not available"}:
        return 0.0
    if any(w in t for w in ("full", "anytime", "flexible", "always", "any time")):
        return 1.0
    if any(w in t for w in ("weekday", "weekend", "evening", "morning", "afternoon", "part")):
        return 0.7
    if any(w in t for w in ("hour", "occasional", "monthly", "rare")):
        return 0.4
    return 0.6


class VolunteerContext:
    def __init__(self, db: Session, now: datetime | None = None):
        self.now = now or datetime.utcnow()
        self.volunteers = db.query(Volunteer).all()
        needs = {n.id: n for n in db.query(Need).all()}
        self.needs = needs
        self.history: dict[int, list[str]] = defaultdict(list)
        for m in db.query(Match).filter(Match.volunteer_id.isnot(None)).all():
            if (m.status or "").lower() in CONFIRMED and m.need_id in needs:
                self.history[m.volunteer_id].append(_normalize(needs[m.need_id].category))
        self.outcomes: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        self.rejected_pairs: set[tuple[int, int]] = set()
        for s in db.query(VolunteerSuggestion).filter(VolunteerSuggestion.status != "suggested").all():
            self.outcomes[s.volunteer_id][1] += 1
            if s.status in POSITIVE:
                self.outcomes[s.volunteer_id][0] += 1
            else:
                self.rejected_pairs.add((s.need_id, s.volunteer_id))


def _skill_similarity(need: Need, volunteers: list[Volunteer]) -> dict[int, float]:
    docs = [_need_text(need)] + [_normalize(v.skills) for v in volunteers]
    if not docs[0] or not any(docs[1:]):
        return {v.id: 0.0 for v in volunteers}
    try:
        matrix = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True).fit_transform(docs)
    except ValueError:
        return {v.id: 0.0 for v in volunteers}
    sims = (matrix[1:] @ matrix[0].T).toarray().ravel()
    return {v.id: _clip(s) for v, s in zip(volunteers, sims)}


def _features(need: Need, vol: Volunteer, text_sim: float, ctx: VolunteerContext) -> dict:
    skills = _split_prefs(vol.skills) or [_normalize(vol.skills)]
    group_match = max((_tag_match_score(need.category, s) for s in skills), default=0.0)
    cat = _normalize(need.category)
    similar = sum(1 for c in ctx.history.get(vol.id, []) if c and _tag_match_score(cat, c) > 0)
    positive, reviewed = ctx.outcomes.get(vol.id, [0, 0])
    return {
        "text_sim": round(text_sim, 3), "group_match": round(group_match, 3), "availability": round(availability_score(vol.availability), 3),
        "history": round(_clip(similar / 3.0), 3), "familiarity": 1.0 if vol.organization_id and vol.organization_id == need.org_id else 0.0,
        "reliability": round((positive + 1) / (reviewed + 2), 3), "similar_tasks": similar, "reviewed": reviewed, "approved": positive,
    }


def _blend_fit(f: dict) -> float:
    relevance = 0.6 * f["group_match"] + 0.4 * f["text_sim"]
    return _clip(0.45 * relevance + 0.15 * f["availability"] + 0.15 * f["history"] + 0.10 * f["familiarity"] + 0.15 * f["reliability"])


def _reasons(need: Need, vol: Volunteer, f: dict, info: dict) -> list[str]:
    out = []
    if f["group_match"] >= 1.0:
        out.append(f"Volunteer's skill '{vol.skills}' is exactly what this need ('{need.category}') asks for")
    elif f["group_match"] > 0:
        out.append(f"Skills '{vol.skills}' are related to '{need.category}' (category match {f['group_match']})")
    elif f["text_sim"] >= 0.15:
        out.append(f"Skills read similar to '{need.category}' (text similarity {f['text_sim']})")
    if f["availability"] > 0:
        out.append(f"Available: {vol.availability or 'not stated'}")
    else:
        out.append("Availability is not stated, so confirm before asking")
    if f["similar_tasks"]:
        out.append(f"Has already helped with {f['similar_tasks']} similar task(s)")
    if f["familiarity"]:
        out.append("Already part of this organization")
    if f["reviewed"]:
        out.append(f"Administrators approved {f['approved']} of {f['reviewed']} earlier suggestions for this volunteer")
    out.append(f"Need priority is {info['level']} ({info['score']})")
    return out


def train_learned_model(db: Session) -> tuple[LogisticRegression | None, dict]:
    rows = db.query(VolunteerSuggestion).filter(VolunteerSuggestion.status != "suggested", VolunteerSuggestion.features.isnot(None)).all()
    X = [[r.features.get(k, 0.0) for k in LEARNED_FEATURES] for r in rows if r.features]
    y = [1 if r.status in POSITIVE else 0 for r in rows if r.features]
    info = {"reviewed_rows": len(y), "needed": MIN_TRAIN_ROWS, "positives": int(sum(y)), "mode": "blend"}
    if len(y) < MIN_TRAIN_ROWS or len(set(y)) < 2:
        return None, info
    model = LogisticRegression(C=1.0, class_weight="balanced", max_iter=500).fit(np.array(X), np.array(y))
    info["mode"] = "learned"
    info["coefficients"] = {k: round(float(c), 3) for k, c in zip(LEARNED_FEATURES, model.coef_[0])}
    return model, info


def model_info(db: Session) -> dict:
    _, info = train_learned_model(db)
    info["model_version"] = f"{MODEL_VERSION}-{info['mode']}"
    info["features"] = LEARNED_FEATURES + ["reliability"]
    return info


def suggest_volunteers(db: Session, need: Need, top_n: int = 5, ctx: VolunteerContext | None = None, learned: tuple | None = None) -> list[dict]:
    ctx = ctx or VolunteerContext(db)
    model, info = learned if learned is not None else train_learned_model(db)
    version = f"{MODEL_VERSION}-{info['mode']}"
    need_info = score_need(need, ctx.now)
    sims = _skill_similarity(need, ctx.volunteers)
    out = []
    for vol in ctx.volunteers:
        if (need.id, vol.id) in ctx.rejected_pairs:
            continue
        f = _features(need, vol, sims.get(vol.id, 0.0), ctx)
        if f["group_match"] == 0 and f["text_sim"] < 0.15 and f["history"] == 0:
            continue
        fit = _blend_fit(f)
        if model is not None:
            fit = 0.5 * fit + 0.5 * float(model.predict_proba(np.array([[f[k] for k in LEARNED_FEATURES]]))[0][1])
        fit = round(_clip(fit), 3)
        out.append({"volunteer_id": vol.id, "fit_score": fit, "urgency_score": need_info["score"],
                    "priority_score": round(0.5 * need_info["score"] + 0.5 * fit, 3), "reasons": _reasons(need, vol, f, need_info),
                    "features": f, "model_version": version})
    out.sort(key=lambda c: c["fit_score"], reverse=True)
    for i, item in enumerate(out[:top_n], start=1):
        item["rank_in_need"] = i
    return out[:top_n]


def save_suggestions(db: Session, need: Need, candidates: list[dict], user_id: int) -> list[VolunteerSuggestion]:
    saved = []
    for c in candidates:
        row = db.query(VolunteerSuggestion).filter_by(need_id=need.id, volunteer_id=c["volunteer_id"]).first()
        if row is None:
            row = VolunteerSuggestion(need_id=need.id, volunteer_id=c["volunteer_id"], status="suggested", generated_by=user_id,
                                      fit_score=c["fit_score"], urgency_score=c["urgency_score"], priority_score=c["priority_score"],
                                      reasons=c["reasons"], features=c["features"], model_version=c["model_version"], rank_in_need=c["rank_in_need"])
            db.add(row)
        elif row.status == "suggested":
            row.fit_score, row.urgency_score, row.priority_score = c["fit_score"], c["urgency_score"], c["priority_score"]
            row.reasons, row.features, row.model_version, row.rank_in_need = c["reasons"], c["features"], c["model_version"], c["rank_in_need"]
        saved.append(row)
    db.flush()
    return saved


def rank_needs_for_volunteer(db: Session, vol: Volunteer, needs: list[Need], ctx: VolunteerContext | None = None) -> list[dict]:
    ctx = ctx or VolunteerContext(db)
    out = []
    for need in needs:
        sim = _skill_similarity(need, [vol]).get(vol.id, 0.0)
        f = _features(need, vol, sim, ctx)
        if f["group_match"] == 0 and f["text_sim"] < 0.15 and f["history"] == 0:
            continue
        info = score_need(need, ctx.now)
        fit = round(_clip(_blend_fit(f)), 3)
        out.append({"need_id": need.id, "fit_score": fit, "priority_score": round(0.5 * info["score"] + 0.5 * fit, 3), "reasons": _reasons(need, vol, f, info)})
    out.sort(key=lambda r: r["priority_score"], reverse=True)
    return out
