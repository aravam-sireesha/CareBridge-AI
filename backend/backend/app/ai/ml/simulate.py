"""Monte Carlo simulation of supply against demand.

Demand is uncertain (forecast mean and spread), pledged supply is uncertain (not every pledge arrives; modelled as a Beta
distribution fitted to the observed delivery rate), and deliveries can be late. Thousands of scenarios are simulated to give the
probability of a shortfall and an interval for the unmet amount, plus the effect of a proposed extra allocation. Seeded, so results
are reproducible."""
from __future__ import annotations

import numpy as np


def beta_from_rate(delivered: int, pledged: int, strength: float = 4.0) -> tuple[float, float]:
    """Beta(a, b) for the share of pledges that arrive, with a weak prior of `strength` pseudo-pledges at 80 percent."""
    a = delivered + 0.8 * strength
    b = (pledged - delivered) + 0.2 * strength
    return max(a, 0.5), max(b, 0.5)


def simulate_supply(demand_mean: float, demand_sd: float, stock: float, pledged_units: float = 0.0, pledge_a: float = 8.0, pledge_b: float = 2.0,
                    late_prob: float = 0.15, extra_allocation: float = 0.0, n: int = 10000, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    demand = np.maximum(0.0, rng.normal(demand_mean, max(demand_sd, 1e-9), n))
    arrive = rng.beta(pledge_a, pledge_b, n) * pledged_units
    late = rng.random(n) < late_prob
    supply = stock + extra_allocation + np.where(late, 0.0, arrive)   # a late pledge does not help this period
    unmet = np.maximum(0.0, demand - supply)
    return {"p_shortfall": round(float((unmet > 0).mean()), 4), "expected_unmet": round(float(unmet.mean()), 2),
            "unmet_p10": round(float(np.percentile(unmet, 10)), 2), "unmet_p50": round(float(np.percentile(unmet, 50)), 2), "unmet_p90": round(float(np.percentile(unmet, 90)), 2),
            "expected_demand": round(float(demand.mean()), 2), "expected_supply": round(float(supply.mean()), 2), "scenarios": n,
            "unmet_samples": [round(float(x), 1) for x in unmet[:200]]}


def compare_allocation(demand_mean, demand_sd, stock, extra_units: list[float], **kw) -> list[dict]:
    """How much does each candidate extra allocation reduce the chance and size of a shortfall?"""
    base = simulate_supply(demand_mean, demand_sd, stock, **kw)
    out = [{"extra": 0.0, **{k: base[k] for k in ("p_shortfall", "expected_unmet", "unmet_p90")}}]
    for x in extra_units:
        r = simulate_supply(demand_mean, demand_sd, stock, extra_allocation=x, **kw)
        out.append({"extra": float(x), **{k: r[k] for k in ("p_shortfall", "expected_unmet", "unmet_p90")}})
    return out
