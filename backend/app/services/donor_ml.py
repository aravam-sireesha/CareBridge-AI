"""ML donor suggestions for the Administration module.

Two pieces work together:

1. Need priority  - how pressing is a need? (urgency level, how long it has been open, quantity)
2. Donor fit      - how well does a donor suit a need? Features per (need, donor) pair:
     text_sim     TF-IDF character n-gram cosine similarity between need and donor interests
     group_match  category / category-group match (reuses matching_rules)
     history      has the donor already given to similar needs?
     recency      how recently has the donor given at all?
     reliability  share of earlier suggestions for this donor that administrators approved

Cold start: while few administrator decisions exist, fit is a transparent weighted blend of the
features. Once at least MIN_TRAIN_ROWS reviewed suggestions (both approved and rejected) are stored in
`donor_suggestions`, a logistic-regression model is trained on them and averaged with the blend, so the
ranking adapts to what administrators actually approve. AI only recommends; administrators decide.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sqlalchemy.orm import Session

from ..models import Donation, Donor, DonorSuggestion, Need
from .matching_rules import CATEGORY_GROUPS, _normalize, _tag_match_score

MODEL_VERSION = "donor-ml-1.0.0"
MIN_TRAIN_ROWS = 20
LEARNED_FEATURES = ["text_sim", "group_match", "history", "recency"]

URGENCY_BASE = {"critical": 1.0, "high": 0.85, "medium": 0.55, "low": 0.25}
OPEN_STATUSES = {"open", "pending"}
POSITIVE = {"approved", "contacted"}


def _clip(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _days_since(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.replace(tzinfo=None)
    return max(0.0, (now - value).total_seconds() / 86400)


def urgency_level(score: float) -> str:
    return "critical" if score >= 0.85 else "high" if score >= 0.65 else "medium" if score >= 0.4 else "low"


# --------------------------------------------------------------------------- need priority
def score_need(need: Need, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    base = URGENCY_BASE.get(_normalize(need.urgency), 0.5)
    age_days = _days_since(need.created_at, now)
    age = _clip((age_days or 0) / 30.0)
    qty = _clip(math.log1p(max(need.quantity or 0, 0)) / math.log1p(200))
    score = round(_clip(0.65 * base + 0.20 * age + 0.15 * qty), 3)
    reasons = [f"Urgency set to {need.urgency or 'unspecified'}"]
    if age_days is not None and age_days >= 7:
        reasons.append(f"Open for {int(age_days)} days")
    if (need.quantity or 0) >= 50:
        reasons.append(f"Large request ({need.quantity} units)")
    return {"score": score, "level": urgency_level(score), "reasons": reasons, "age_days": age_days}


# --------------------------------------------------------------------------- donor context
class DonorContext:
    """Everything the model needs, loaded once per scoring run."""

    def __init__(self, db: Session, now: datetime | None = None):
        self.now = now or datetime.utcnow()
        self.donors = db.query(Donor).all()
        needs = {n.id: n for n in db.query(Need).all()}
        self.needs = needs
        self.history: dict[int, list[tuple[str, datetime | None]]] = defaultdict(list)
        for d in db.query(Donation).all():
            need = needs.get(d.need_id)
            self.history[d.donor_id].append((_normalize(need.category if need else ""), d.timestamp))
        self.outcomes: dict[int, list[int]] = defaultdict(lambda: [0, 0])  # donor -> [positive, reviewed]
        self.rejected_pairs: set[tuple[int, int]] = set()
        for s in db.query(DonorSuggestion).filter(DonorSuggestion.status != "suggested").all():
            self.outcomes[s.donor_id][1] += 1
            if s.status in POSITIVE:
                self.outcomes[s.donor_id][0] += 1
            else:
                self.rejected_pairs.add((s.need_id, s.donor_id))


def _need_text(need: Need) -> str:
    cat = _normalize(need.category)
    extra = []
    for group, members in CATEGORY_GROUPS.items():
        if cat == group or cat in members:
            extra.append(group)
            extra.extend(sorted(members))
    return " ".join([cat, *extra]).strip()


def _split_prefs(text: str | None) -> list[str]:
    return [p.strip() for p in re.split(r"[,;/&]|\band\b", _normalize(text)) if p.strip()]


def _text_similarity(need: Need, donors: list[Donor]) -> dict[int, float]:
    docs = [_need_text(need)] + [_normalize(d.preferences) for d in donors]
    if not docs[0] or not any(docs[1:]):
        return {d.id: 0.0 for d in donors}
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
    try:
        matrix = vec.fit_transform(docs)
    except ValueError:
        return {d.id: 0.0 for d in donors}
    sims = (matrix[1:] @ matrix[0].T).toarray().ravel()
    return {d.id: _clip(s) for d, s in zip(donors, sims)}


def _features(need: Need, donor: Donor, text_sim: float, ctx: DonorContext) -> dict:
    prefs = _split_prefs(donor.preferences) or [_normalize(donor.preferences)]
    group_match = max((_tag_match_score(need.category, p) for p in prefs), default=0.0)
    cat = _normalize(need.category)
    past = ctx.history.get(donor.id, [])
    similar = sum(1 for c, _ in past if c and _tag_match_score(cat, c) > 0)
    history = _clip(similar / 3.0)
    dates = [_days_since(ts, ctx.now) for _, ts in past if ts is not None]
    recency = math.exp(-min(dates) / 180.0) if dates else 0.0
    positive, reviewed = ctx.outcomes.get(donor.id, [0, 0])
    reliability = (positive + 1) / (reviewed + 2)
    return {
        "text_sim": round(text_sim, 3), "group_match": round(group_match, 3), "history": round(history, 3),
        "recency": round(recency, 3), "reliability": round(reliability, 3),
        "similar_gifts": similar, "reviewed": reviewed, "approved": positive,
    }


def _blend_fit(f: dict) -> float:
    relevance = 0.6 * f["group_match"] + 0.4 * f["text_sim"]
    return _clip(0.55 * relevance + 0.20 * f["history"] + 0.10 * f["recency"] + 0.15 * f["reliability"])


def _reasons(need: Need, donor: Donor, f: dict, need_info: dict) -> list[str]:
    out = []
    if f["group_match"] >= 1.0:
        out.append(f"Donor supports '{donor.preferences}', which is exactly this need ('{need.category}')")
    elif f["group_match"] > 0:
        out.append(f"Donor interest '{donor.preferences}' is related to '{need.category}' (category match {f['group_match']})")
    elif f["text_sim"] >= 0.15:
        out.append(f"Donor interests read similar to '{need.category}' (text similarity {f['text_sim']})")
    if f["similar_gifts"]:
        out.append(f"Has already given to {f['similar_gifts']} similar need(s)")
    if f["recency"] >= 0.5:
        out.append("Gave recently, so is likely still engaged")
    if f["reviewed"]:
        out.append(f"Administrators approved {f['approved']} of {f['reviewed']} earlier suggestions for this donor")
    out.append(f"Need priority is {need_info['level']} ({need_info['score']})")
    return out


# --------------------------------------------------------------------------- learning from decisions
def train_learned_model(db: Session) -> tuple[LogisticRegression | None, dict]:
    rows = (
        db.query(DonorSuggestion)
        .filter(DonorSuggestion.status != "suggested", DonorSuggestion.features.isnot(None))
        .all()
    )
    X = [[r.features.get(k, 0.0) for k in LEARNED_FEATURES] for r in rows if r.features]
    y = [1 if r.status in POSITIVE else 0 for r in rows if r.features]
    info = {"reviewed_rows": len(y), "needed": MIN_TRAIN_ROWS, "positives": int(sum(y)), "mode": "blend"}
    if len(y) < MIN_TRAIN_ROWS or len(set(y)) < 2:
        return None, info
    model = LogisticRegression(C=1.0, class_weight="balanced", max_iter=500)
    model.fit(np.array(X), np.array(y))
    info["mode"] = "learned"
    info["coefficients"] = {k: round(float(c), 3) for k, c in zip(LEARNED_FEATURES, model.coef_[0])}
    return model, info


def model_info(db: Session) -> dict:
    _, info = train_learned_model(db)
    info["model_version"] = f"{MODEL_VERSION}-{info['mode']}"
    info["features"] = ["text_sim", "group_match", "history", "recency", "reliability"]
    info["description"] = (
        "Weighted blend of TF-IDF similarity, category match, giving history and administrator-approval "
        "rate. Switches to logistic regression trained on administrator decisions once enough exist."
    )
    return info


# --------------------------------------------------------------------------- suggestions
def suggest_donors(db: Session, need: Need, top_n: int = 5, ctx: DonorContext | None = None,
                   learned: tuple | None = None) -> list[dict]:
    ctx = ctx or DonorContext(db)
    model, info = learned if learned is not None else train_learned_model(db)
    version = f"{MODEL_VERSION}-{info['mode']}"
    need_info = score_need(need, ctx.now)
    sims = _text_similarity(need, ctx.donors)
    out = []
    for donor in ctx.donors:
        if (need.id, donor.id) in ctx.rejected_pairs:
            continue
        f = _features(need, donor, sims.get(donor.id, 0.0), ctx)
        if f["group_match"] == 0 and f["text_sim"] < 0.15 and f["history"] == 0:
            continue  # nothing links this donor to this need
        fit = _blend_fit(f)
        if model is not None:
            proba = float(model.predict_proba(np.array([[f[k] for k in LEARNED_FEATURES]]))[0][1])
            fit = 0.5 * fit + 0.5 * proba
        fit = round(_clip(fit), 3)
        out.append({
            "donor_id": donor.id, "fit_score": fit, "urgency_score": need_info["score"],
            "priority_score": round(0.5 * need_info["score"] + 0.5 * fit, 3),
            "reasons": _reasons(need, donor, f, need_info), "features": f, "model_version": version,
        })
    out.sort(key=lambda c: c["fit_score"], reverse=True)
    for i, item in enumerate(out[:top_n], start=1):
        item["rank_in_need"] = i
    return out[:top_n]


def save_suggestions(db: Session, need: Need, candidates: list[dict], admin_user_id: int) -> list[DonorSuggestion]:
    """Upsert: refresh open suggestions, never overwrite a decision an administrator already made."""
    saved = []
    for c in candidates:
        row = db.query(DonorSuggestion).filter_by(need_id=need.id, donor_id=c["donor_id"]).first()
        if row is None:
            row = DonorSuggestion(need_id=need.id, donor_id=c["donor_id"], status="suggested", generated_by=admin_user_id,
                                  fit_score=c["fit_score"], urgency_score=c["urgency_score"],
                                  priority_score=c["priority_score"], reasons=c["reasons"], features=c["features"],
                                  model_version=c["model_version"], rank_in_need=c["rank_in_need"])
            db.add(row)
        elif row.status == "suggested":
            row.fit_score, row.urgency_score = c["fit_score"], c["urgency_score"]
            row.priority_score, row.reasons, row.features = c["priority_score"], c["reasons"], c["features"]
            row.model_version, row.rank_in_need = c["model_version"], c["rank_in_need"]
        saved.append(row)
    db.flush()
    return saved


def rank_needs_for_donor(db: Session, donor: Donor, needs: list[Need], ctx: DonorContext | None = None) -> list[dict]:
    """Donor-side view: which open needs suit this donor best (fit blended with need priority)."""
    ctx = ctx or DonorContext(db)
    out = []
    for need in needs:
        sim = _text_similarity(need, [donor]).get(donor.id, 0.0)
        f = _features(need, donor, sim, ctx)
        if f["group_match"] == 0 and f["text_sim"] < 0.15 and f["history"] == 0:
            continue
        info = score_need(need, ctx.now)
        fit = round(_clip(_blend_fit(f)), 3)
        out.append({"need_id": need.id, "fit_score": fit, "priority_score": round(0.5 * info["score"] + 0.5 * fit, 3),
                    "reasons": _reasons(need, donor, f, info)})
    out.sort(key=lambda r: r["priority_score"], reverse=True)
    return out
