"""Time-series forecasting with a proper backtest. Candidates: naive (last value), moving average, damped-trend Holt, ARIMA.

Each category's monthly demand series is forecast one step ahead many times (rolling origin) and the method with the lowest
mean absolute error on those backtests is used for that category. A method must beat the naive forecast to be chosen.
LSTM is deliberately not included: it needs a deep-learning framework (PyTorch/TensorFlow) and thousands of observations per
series, while a child-welfare platform typically has a few dozen monthly points. ARIMA/Holt are the right size for this data."""
from __future__ import annotations

import warnings
from datetime import datetime

import numpy as np

from ...services.forecast import _fit_holt


def _naive(h):
    return float(h[-1])


def _ma3(h):
    return float(np.mean(h[-3:]))


def _holt(h):
    return float(_fit_holt(list(h))[0]) if len(h) >= 3 else _naive(h)


def _arima(h):
    from statsmodels.tsa.arima.model import ARIMA
    if len(h) < 8:
        raise ValueError("too short for ARIMA")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for order in ((1, 1, 1), (0, 1, 1), (1, 0, 0)):
            try:
                return max(0.0, float(ARIMA(np.asarray(h, dtype=float), order=order).fit().forecast(1)[0]))
            except Exception:
                continue
    raise ValueError("ARIMA did not converge")


METHODS = {"naive": _naive, "moving average (3)": _ma3, "holt (damped trend)": _holt, "arima": _arima}


def backtest(series: list[float], min_train: int = 5) -> dict:
    """Rolling-origin one-step-ahead errors. All methods are scored on the SAME origins so the comparison is fair; ARIMA needs
    at least 8 observations, so series shorter than 11 points are compared without it."""
    s = [float(x) for x in series]
    start = max(min_train, 8) if len(s) >= 11 else min_train
    out = {}
    for name, fn in METHODS.items():
        if name == "arima" and len(s) < 11:
            continue
        errs = []
        for t in range(start, len(s)):
            try:
                errs.append(abs(fn(s[:t]) - s[t]))
            except Exception:
                errs = []
                break
        if errs:
            out[name] = {"mae": round(float(np.mean(errs)), 3), "n": len(errs)}
    return out


def forecast_series(series: list[float]) -> dict:
    s = [float(x) for x in series]
    if len(s) < 6:
        pred = _ma3(s) if s else 0.0
        return {"method": "moving average (3)", "forecast": round(pred, 2), "backtest": {}, "reason": "fewer than 6 periods: no backtest is possible", "confident": False}
    bt = backtest(s)
    best = min(bt, key=lambda k: bt[k]["mae"])
    if best != "naive" and bt[best]["mae"] >= bt["naive"]["mae"]:
        best = "naive"
    pred = METHODS[best](s)
    return {"method": best, "forecast": round(max(0.0, pred), 2), "backtest": bt, "mae": bt[best]["mae"], "naive_mae": bt["naive"]["mae"],
            "skill_vs_naive": round(1 - bt[best]["mae"] / bt["naive"]["mae"], 3) if bt["naive"]["mae"] else 0.0, "confident": True}


def category_series(db, now: datetime | None = None, periods: int = 12) -> dict[str, list[float]]:
    """Monthly (30-day) count of needs per category, oldest first, for categories with at least one need."""
    from ... import models as m
    now = now or datetime.utcnow()
    buckets: dict[str, dict[int, float]] = {}
    for n in db.query(m.Need).all():
        if not n.category or not n.created_at:
            continue
        age = (now - n.created_at).days // 30
        if 0 <= age < periods:
            buckets.setdefault(n.category.strip().lower(), {})[age] = buckets.get(n.category.strip().lower(), {}).get(age, 0.0) + 1
    return {c: [by.get(a, 0.0) for a in range(max(by), -1, -1)] for c, by in buckets.items()}


def synthetic_series(n_series: int = 40, length: int = 24, seed: int = 7) -> list[list[float]]:
    """Benchmark series: trend + yearly seasonality + noise, with different strengths."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n_series):
        base, trend, amp = rng.uniform(4, 20), rng.uniform(-0.15, 0.4), rng.uniform(0, 5)
        phase = rng.uniform(0, 2 * np.pi)
        t = np.arange(length)
        out.append([max(0.0, float(base + trend * i + amp * np.sin(2 * np.pi * i / 12 + phase) + rng.normal(0, 1.5))) for i in t])
    return out


def benchmark(n_series: int = 40, length: int = 24, seed: int = 7) -> dict:
    """Average backtest MAE of each method over many series, and how often each wins."""
    series = synthetic_series(n_series, length, seed)
    maes: dict[str, list[float]] = {}
    wins: dict[str, int] = {}
    for s in series:
        bt = backtest(s)
        for k, v in bt.items():
            maes.setdefault(k, []).append(v["mae"])
        if bt:
            wins[min(bt, key=lambda k: bt[k]["mae"])] = wins.get(min(bt, key=lambda k: bt[k]["mae"]), 0) + 1
    return {"series": n_series, "length": length, "mean_mae": {k: round(float(np.mean(v)), 3) for k, v in maes.items()}, "wins": wins}
