"""Demand forecast dashboard data. Combines two existing, real services; nothing is invented here:
  * ai.ml.forecast_models: monthly needs per category, a backtested method choice, and an empirical error range when enough history exists
  * services.forecast:     expected units, stock on hand, interested donors and the shortfall-risk rule"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..ai.ml import forecast_models
from ..database import get_db
from ..services import forecast as supply_forecast
from .administration import active_admin

router = APIRouter(prefix="/admin/forecast-dashboard", tags=["admin-forecast"])

RISK_METHOD = ("Shortfall risk is a rule, not a probability. Expected units for the next 30 days (damped-trend smoothing of past requested quantities) are compared with "
               "the available stock of matching resources. If expected units exceed stock the risk is medium, and high when there is also no stock or no donor whose "
               "preferences match the category. Expected future donations are not an input because the platform does not record pledges.")
LIMITATIONS = [
    "Forecasts use only the needs recorded on this platform, counted per 30-day period. They cannot know about events, funding changes or needs that were never entered.",
    "The method is chosen by backtesting past one-step forecasts, and must beat a simple 'same as last period' forecast to be used.",
    "The range shown is empirical: how far past forecasts were from what happened. It is not a statistical guarantee, and it appears only when at least 5 past forecasts exist.",
    "Categories with fewer than 6 periods of history get a simple recent average and no range.",
]


def _label(now: datetime, periods_ago: int) -> str:
    return (now - timedelta(days=30 * periods_ago)).strftime("%b %Y")


@router.get("")
def forecast_dashboard(admin: dict = Depends(active_admin), db: Session = Depends(get_db)):
    now = datetime.utcnow()
    supply = {str(r["category"]).strip().lower(): r for r in supply_forecast.forecast_categories(db, now)}
    categories = []
    for cat, series in forecast_models.category_series(db, now).items():
        f = forecast_models.forecast_series(series)
        n = len(series)
        s = supply.get(cat)
        categories.append({
            "category": cat,
            "history": [{"label": _label(now, n - 1 - i), "value": v} for i, v in enumerate(series)],
            "forecast": {"label": _label(now, -1), "value": f["forecast"], "band": f.get("band")},
            "method": f["method"], "confident": f.get("confident", False), "backtest_mae": f.get("mae"), "naive_mae": f.get("naive_mae"), "skill_vs_naive": f.get("skill_vs_naive"),
            "periods": n, "reason": f.get("reason"),
            "shortfall": ({"risk": s["risk"], "expected_units": s["forecast_units"], "stock_units": s["stock_units"], "gap_units": s["supply_gap_units"],
                           "matching_donors": s["matching_donors"], "notes": s["notes"]} if s else None),
        })
    categories.sort(key=lambda c: ({"high": 0, "medium": 1, "low": 2, None: 3}[(c["shortfall"] or {}).get("risk")], -c["forecast"]["value"]))
    return {"generated_at": now.isoformat(timespec="seconds"), "horizon": "next 30 days", "unit": "needs recorded per 30-day period", "categories": categories,
            "risk_method": RISK_METHOD, "limitations": LIMITATIONS}
