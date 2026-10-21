"""Predictive need analysis: how many needs, and how many units, will each category see next period?

For every category the history of needs is bucketed into 30-day periods (oldest to newest, up to 12 periods).
A damped-trend exponential smoothing model (Holt, with damping phi) is fitted per category: alpha, beta and phi
are chosen from a small grid by the lowest one-step-ahead squared error. The next period is then forecast and
compared with what is on hand (available resource units and donors/volunteers whose interests match), so the
administrator can see where supply is likely to fall short *before* the requests arrive.

With fewer than three periods of history the model falls back to the recent average and says so (low confidence).
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Donor, Need, Resource, Volunteer
from .matching_rules import _normalize, _tag_match_score

PERIOD_DAYS = 30
MAX_PERIODS = 12
GRID = [0.2, 0.4, 0.6, 0.8]
PHIS = [0.8, 0.9, 1.0]


def _fit_holt(series: list[float]) -> tuple[float, float, float]:
    """Return (next_value, one-step RMSE, trend per period) for a damped Holt model."""
    best = None
    for a in GRID:
        for b in GRID:
            for phi in PHIS:
                level, trend, sse = series[0], series[1] - series[0], 0.0
                for y in series[1:]:
                    pred = level + phi * trend
                    sse += (y - pred) ** 2
                    new_level = a * y + (1 - a) * pred
                    trend = b * (new_level - level) + (1 - b) * phi * trend
                    level = new_level
                if best is None or sse < best[0]:
                    best = (sse, level + phi * trend, trend)
    sse, nxt, trend = best
    return max(0.0, nxt), math.sqrt(sse / max(1, len(series) - 1)), trend


def forecast_categories(db: Session, now: datetime | None = None) -> list[dict]:
    now = now or datetime.utcnow()
    buckets: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for n in db.query(Need).all():
        if not n.category or n.created_at is None:
            continue
        created = n.created_at.replace(tzinfo=None) if n.created_at.tzinfo else n.created_at
        age = int((now - created).days // PERIOD_DAYS)
        if 0 <= age < MAX_PERIODS:
            b = buckets[_normalize(n.category)][age]
            b[0] += 1
            b[1] += n.quantity or 0
    resources = db.query(Resource).filter(Resource.status == "available").all()
    donors, vols = db.query(Donor).all(), db.query(Volunteer).all()
    out = []
    for cat, by_age in buckets.items():
        oldest = max(by_age)
        counts = [by_age[a][0] if a in by_age else 0.0 for a in range(oldest, -1, -1)]   # oldest -> newest
        units = [by_age[a][1] if a in by_age else 0.0 for a in range(oldest, -1, -1)]
        if len(counts) >= 3:
            nxt_c, rmse, trend = _fit_holt(counts)
            nxt_u, _, _ = _fit_holt(units)
            method, conf = "damped-trend smoothing", round(max(0.15, min(0.9, 0.35 + 0.05 * len(counts) - 0.15 * rmse)), 2)
        else:
            tail = counts[-3:]
            nxt_c, nxt_u = sum(tail) / len(tail), sum(units[-3:]) / len(units[-3:])
            trend, method, conf = 0.0, "recent average (short history)", 0.2
        mean = sum(counts) / len(counts)
        direction = "rising" if trend > 0.15 * max(mean, 1) else "falling" if trend < -0.15 * max(mean, 1) else "steady"
        stock = sum(r.quantity_available for r in resources if max(_tag_match_score(cat, r.category or ""), _tag_match_score(cat, r.name or "")) > 0)
        d_match = sum(1 for d in donors if _tag_match_score(cat, d.preferences) > 0)
        v_match = sum(1 for v in vols if _tag_match_score(cat, v.skills) > 0)
        gap = max(0, round(nxt_u) - stock)
        risk = "high" if gap > 0 and (d_match == 0 or stock == 0) else "medium" if gap > 0 else "low"
        notes = []
        if gap > 0:
            notes.append(f"About {round(nxt_u)} unit(s) expected but only {stock} in stock")
        if d_match == 0:
            notes.append("No donor is interested in this category yet")
        if v_match == 0:
            notes.append("No volunteer lists a matching skill")
        out.append({"category": cat, "history": counts, "periods": len(counts), "forecast_needs": round(nxt_c, 1), "forecast_units": round(nxt_u),
                    "trend": direction, "confidence": conf, "method": method, "stock_units": stock, "matching_donors": d_match,
                    "matching_volunteers": v_match, "supply_gap_units": gap, "risk": risk, "notes": notes})
    out.sort(key=lambda r: ({"high": 0, "medium": 1, "low": 2}[r["risk"]], -r["forecast_units"]))
    return out
