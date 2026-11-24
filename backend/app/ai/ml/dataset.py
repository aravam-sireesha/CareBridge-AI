"""Datasets for the prediction problem.

PROBLEM (the only one in Phase 3):  will an open need be fulfilled within `horizon_days` (14) of being posted?
Label 1 = fulfilled within the horizon.  Label 0 = fulfilled later, or still unfulfilled after the horizon.
Needs younger than the horizon that are not fulfilled are censored (unknown yet) and are left out - never counted as 0.
Every feature is known when the need is posted, so there is no leakage from the outcome.

`training_frame` builds the table from the real database. `synthetic` builds a labelled benchmark with a KNOWN generating
process, used to compare models when the real history is too small. Numbers measured on synthetic data describe the method,
not CareBridge's real-world accuracy."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from ... import models as m
from ...services.matching_rules import CATEGORY_GROUPS, _normalize, _tag_match_score
from ...services.donor_ml import _split_prefs

URGENCY = {"low": 0, "medium": 1, "high": 2, "critical": 3}
GROUPS = list(CATEGORY_GROUPS)
FEATURES = ["urgency", "log_qty", "log_beneficiaries", "deadline_days", "org_verified", "org_prior_needs", "org_prior_fulfil_rate",
            "donor_coverage", "resource_coverage", "category_group", "month_sin", "month_cos"]


def _group_code(category: str | None) -> int:
    c = _normalize(category)
    for i, (g, members) in enumerate(CATEGORY_GROUPS.items()):
        if c == g or c in members:
            return i
    return len(GROUPS)


def _fulfilled_time(db: Session, need: m.Need) -> datetime | None:
    if need.fulfilled_at:
        return need.fulfilled_at
    if (need.status or "").lower() != "fulfilled":
        return None
    times = [a.reviewed_at for a in db.query(m.ResourceAllocation).filter_by(need_id=need.id, status="delivered").all() if a.reviewed_at]
    times += [d.timestamp for d in db.query(m.Donation).filter_by(need_id=need.id).all() if d.timestamp]
    return max(times) if times else None


def need_features(db: Session, need: m.Need, now: datetime, ctx: dict | None = None) -> dict:
    ctx = ctx or build_context(db)
    created = need.created_at or now
    deadline = (need.required_by - created).days if need.required_by else -1
    prior = [n for n in ctx["needs_by_org"].get(need.org_id, []) if n.created_at and n.created_at < created and n.id != need.id]
    done = sum(1 for n in prior if (n.status or "").lower() == "fulfilled")
    rate = (done + 1) / (len(prior) + 2)          # Laplace-smoothed: a new organization starts at 0.5
    cat = need.category or ""
    donors = sum(1 for d in ctx["donors"] if max((_tag_match_score(cat, p) for p in _split_prefs(d.preferences)), default=0.0) > 0)
    stock = sum(r.quantity_available for r in ctx["resources"] if max(_tag_match_score(cat, r.category or ""), _tag_match_score(cat, r.name or "")) > 0)
    qty = max(need.quantity or 0, 0)
    return {"urgency": URGENCY.get((need.urgency or "").lower(), 1), "log_qty": math.log1p(qty), "log_beneficiaries": math.log1p(need.beneficiaries or 0),
            "deadline_days": min(max(deadline, -1), 120), "org_verified": int(bool(ctx["orgs"].get(need.org_id) and ctx["orgs"][need.org_id].verified)),
            "org_prior_needs": min(len(prior), 50), "org_prior_fulfil_rate": rate, "donor_coverage": min(donors, 20),
            "resource_coverage": min(1.0, stock / qty) if qty else 1.0, "category_group": _group_code(cat),
            "month_sin": math.sin(2 * math.pi * created.month / 12), "month_cos": math.cos(2 * math.pi * created.month / 12)}


def build_context(db: Session) -> dict:
    by_org: dict[int, list] = {}
    for n in db.query(m.Need).all():
        by_org.setdefault(n.org_id, []).append(n)
    return {"needs_by_org": by_org, "orgs": {o.id: o for o in db.query(m.Organization).all()}, "donors": db.query(m.Donor).all(),
            "resources": db.query(m.Resource).filter(m.Resource.status == "available").all()}


def training_frame(db: Session, now: datetime | None = None, horizon_days: int = 14) -> pd.DataFrame:
    """Real labelled needs. Columns: FEATURES + label, created_at, days_to_fulfil (NaN when unknown)."""
    now = now or datetime.utcnow()
    ctx = build_context(db)
    rows = []
    for need in db.query(m.Need).all():
        if need.created_at is None:
            continue
        done_at = _fulfilled_time(db, need)
        age = (now - need.created_at).days
        if done_at is not None:
            days = max(0.0, (done_at - need.created_at).total_seconds() / 86400)
            label = int(days <= horizon_days)
        elif (need.status or "").lower() in ("open", "pending") and age >= horizon_days:
            days, label = float("nan"), 0
        else:
            continue  # censored (too young) or closed without fulfilment
        rows.append({**need_features(db, need, now, ctx), "label": label, "created_at": need.created_at, "days_to_fulfil": days})
    return pd.DataFrame(rows, columns=FEATURES + ["label", "created_at", "days_to_fulfil"])


def synthetic(n: int = 1500, seed: int = 7, horizon_days: int = 14) -> pd.DataFrame:
    """Labelled benchmark with a known process: more urgency, donor/stock coverage and a good organization track record raise the
    chance of a quick fulfilment; large requests lower it; coverage matters most for urgent needs (an interaction that linear models
    cannot express); there is a mild seasonal effect and noise."""
    rng = np.random.default_rng(seed)
    urg = rng.choice(4, n, p=[0.2, 0.4, 0.28, 0.12])
    qty = np.clip(rng.lognormal(3.0, 0.9, n), 1, 600)
    ben = np.clip(rng.lognormal(2.3, 0.8, n), 1, 300)
    deadline = np.where(rng.random(n) < 0.4, -1, rng.integers(3, 60, n))
    verified = (rng.random(n) < 0.8).astype(int)
    prior = rng.integers(0, 30, n)
    rate = np.clip(rng.beta(4, 3, n), 0.05, 0.95)
    donors = rng.poisson(2.2, n)
    stock = np.clip(rng.beta(1.6, 2.4, n), 0, 1)
    group = rng.integers(0, len(GROUPS) + 1, n)
    month = rng.integers(1, 13, n)
    ms, mc = np.sin(2 * math.pi * month / 12), np.cos(2 * math.pi * month / 12)
    logit = (-1.3 + 0.35 * urg - 0.45 * (np.log1p(qty) - 3.5) + 0.25 * np.minimum(donors, 6) + 1.6 * stock + 1.4 * (rate - 0.5)
             + 0.55 * verified + 0.45 * urg * np.minimum(donors, 4) / 3.0 * (stock > 0.4) + 0.3 * ms - 0.002 * np.maximum(deadline, 0)
             + rng.normal(0, 0.5, n))
    p = 1 / (1 + np.exp(-logit))
    label = (rng.random(n) < p).astype(int)
    days = np.where(label == 1, rng.uniform(1, horizon_days, n), horizon_days + rng.gamma(2.0, 6.0, n))
    t0 = datetime(2025, 1, 1)
    return pd.DataFrame({"urgency": urg, "log_qty": np.log1p(qty), "log_beneficiaries": np.log1p(ben), "deadline_days": deadline, "org_verified": verified,
                         "org_prior_needs": prior, "org_prior_fulfil_rate": rate, "donor_coverage": donors, "resource_coverage": stock,
                         "category_group": group, "month_sin": ms, "month_cos": mc, "label": label,
                         "created_at": [t0 + timedelta(hours=int(i * 24 * 540 / n)) for i in range(n)], "days_to_fulfil": days,
                         "true_probability": p})
