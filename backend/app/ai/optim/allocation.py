"""Phase 4 - mathematical optimisation: resource allocation and donor matching under constraints.

RESOURCE ALLOCATION (LP / MILP, scipy's HiGHS solver)
  variables   x[r,n] = units of supply r given to demand n (integers, or continuous for the LP relaxation)
  constraints inventory   sum_n x[r,n] <= stock of r
              demand cap  sum_r x[r,n] <= units n still needs
              org cap     units going to one organization <= cap share of all usable supply   (optional)
              fairness    maxmin: every need with usable supply reaches coverage t, and t is as large as possible
                          floor : every such need reaches at least alpha * (the best achievable t)
              urgency     urgent_first: critical needs are served as fully as possible BEFORE anything else (lexicographic)
  objective   maximise sum  weight(n) * relevance(r,n) * x[r,n]       (weights come from urgency)
Stages are solved in order (urgent first, then fairness, then utility) and each stage's optimum is locked in before the next.

DONOR MATCHING (MILP)
  y[d,n] in {0,1}; a donor takes at most `capacity` needs; a need gets at most `max_donors`; every need is covered if feasible
  (and every organization has at least one covered need if feasible) before total fit is maximised.

Everything is deterministic. Edge cases (empty inputs, zero stock, needs nobody can serve, infeasible fairness) are handled and reported."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

EPS = 1e-6


@dataclass
class Supply:
    id: int
    units: float
    org_id: int | None = None


@dataclass
class Demand:
    id: int
    units: float
    weight: float = 1.0
    org_id: int | None = None
    critical: bool = False


URGENCY_WEIGHT = {"critical": 4.0, "high": 2.5, "medium": 1.5, "low": 1.0}


def jain(values) -> float:
    v = np.asarray([x for x in values if x is not None], dtype=float)
    return float(v.sum() ** 2 / (len(v) * (v ** 2).sum())) if len(v) and (v ** 2).sum() > 0 else 1.0


def gini(values) -> float:
    v = np.sort(np.asarray(values, dtype=float))
    n = len(v)
    if n == 0 or v.sum() == 0:
        return 0.0
    return float((2 * np.arange(1, n + 1) - n - 1).dot(v) / (n * v.sum()))


def _solve(c, A, lb, ub, integrality, bounds_ub, time_limit):
    cons = LinearConstraint(A.tocsr(), lb, ub) if A is not None and A.shape[0] else None
    res = milp(c=c, constraints=cons, integrality=integrality, bounds=Bounds(np.zeros(len(c)), bounds_ub), options={"time_limit": time_limit, "presolve": True})
    return res


def solve_allocation(supplies: list[Supply], demands: list[Demand], compat: dict[tuple[int, int], float], *, fairness: str = "maxmin", fairness_alpha: float = 0.8,
                     integer: bool = True, urgent_first: bool = True, org_cap: float | None = None, min_relevance: float = 0.0, time_limit: float = 20.0) -> dict:
    if fairness not in ("none", "floor", "maxmin"):
        raise ValueError("fairness must be 'none', 'floor' or 'maxmin'")
    S = {s.id: s for s in supplies if s.units > 0}
    D = {d.id: d for d in demands if d.units > 0}
    pairs = [(r, n) for (r, n), rel in compat.items() if r in S and n in D and rel > min_relevance]
    notes: list[str] = []
    if not S or not D or not pairs:
        why = "no stock" if not S else "no open demand" if not D else "no compatible stock and demand"
        return _empty(supplies, demands, why)

    idx = {p: i for i, p in enumerate(pairs)}
    nvar = len(pairs)
    servable = sorted({n for _, n in pairs})
    unserved = sorted(set(D) - set(servable))
    if unserved:
        notes.append(f"{len(unserved)} need(s) have no compatible stock: {unserved[:5]}")
    # variable layout: x[0..nvar-1], t at index nvar
    T = nvar
    ub_x = np.array([min(S[r].units, D[n].units) for r, n in pairs] + [1.0], dtype=float)
    integ = np.array([1 if integer else 0] * nvar + [0])

    def base_rows():
        rows, lb, ub = [], [], []
        for r in S:
            rows.append(({idx[(rr, n)]: 1.0 for (rr, n) in pairs if rr == r}, -np.inf, S[r].units))
        for n in servable:
            rows.append(({idx[(r, nn)]: 1.0 for (r, nn) in pairs if nn == n}, -np.inf, D[n].units))
        if org_cap is not None:
            usable = sum(min(S[r].units, sum(D[n].units for (rr, n) in pairs if rr == r)) for r in S)
            for org in {D[n].org_id for n in servable if D[n].org_id is not None}:
                rows.append(({idx[(r, n)]: 1.0 for (r, n) in pairs if D[n].org_id == org}, -np.inf, org_cap * usable))
        return rows

    def build(extra_rows):
        rows = base_rows() + extra_rows
        A = lil_matrix((len(rows), nvar + 1))
        lb, ub = np.empty(len(rows)), np.empty(len(rows))
        for i, (coefs, lo, hi) in enumerate(rows):
            for j, v in coefs.items():
                A[i, j] = v
            lb[i], ub[i] = lo, hi
        return A, lb, ub

    locked: list = []
    stages: list[dict] = []

    def run(name, c, extra=None):
        A, lb, ub = build(locked + (extra or []))
        res = _solve(c, A, lb, ub, integ, ub_x, time_limit)
        ok = res.status in (0, 1) and res.x is not None
        stages.append({"stage": name, "status": int(res.status), "objective": float(-res.fun) if ok else None})
        return res if ok else None

    crit = [n for n in servable if D[n].critical]
    if urgent_first and crit:
        c = np.zeros(nvar + 1)
        for (r, n), i in idx.items():
            if n in crit:
                c[i] = -1.0
        res = run("urgent-first", c)
        if res is not None:
            locked.append(({i: 1.0 for (r, n), i in idx.items() if n in crit}, np.floor(-res.fun + 0.5) - EPS, np.inf))
    t_star = None
    if fairness != "none":
        cov = [({**{i: -1.0 for (r, nn), i in idx.items() if nn == n}, T: D[n].units}, -np.inf, 0.0) for n in servable]   # D*t - sum x <= 0
        c = np.zeros(nvar + 1)
        c[T] = -1.0
        res = run("fairness (maximise the minimum coverage)", c, cov)
        if res is not None:
            t_star = float(res.x[T])
            target = t_star if fairness == "maxmin" else fairness_alpha * t_star
            locked.extend(cov)
            locked.append(({T: 1.0}, target - 1e-5, np.inf))
            if t_star <= EPS:
                notes.append("the worst-served need stays at zero coverage because stock is too scarce" + (" and critical needs were served first" if urgent_first and crit else ""))
        else:
            notes.append("fairness stage failed; relaxed")
    c = np.zeros(nvar + 1)
    for (r, n), i in idx.items():
        c[i] = -D[n].weight * compat[(r, n)]
    res = run("utility", c)
    if res is None:
        notes.append("solver failed; greedy fallback used")
        return {**greedy_allocation(supplies, demands, compat), "notes": notes}
    x = np.round(res.x[:nvar]) if integer else res.x[:nvar]
    alloc = [{"supply_id": r, "demand_id": n, "units": float(x[i]), "relevance": compat[(r, n)]} for (r, n), i in idx.items() if x[i] > EPS]
    return _report(S, D, alloc, compat, stages, notes, t_star, unserved, integer, "milp" if integer else "lp")


def greedy_allocation(supplies: list[Supply], demands: list[Demand], compat: dict[tuple[int, int], float]) -> dict:
    """Baseline: serve needs in urgency order, each from the most relevant stock that remains."""
    S = {s.id: s.units for s in supplies if s.units > 0}
    D = [d for d in sorted(demands, key=lambda d: (-d.critical, -d.weight, d.id)) if d.units > 0]
    alloc = []
    for d in D:
        need = d.units
        for r in sorted((r for r in S if (r, d.id) in compat and compat[(r, d.id)] > 0), key=lambda r: -compat[(r, d.id)]):
            give = min(S[r], need)
            if give > 0:
                alloc.append({"supply_id": r, "demand_id": d.id, "units": float(give), "relevance": compat[(r, d.id)]})
                S[r] -= give
                need -= give
            if need <= 0:
                break
    return _report({s.id: s for s in supplies}, {d.id: d for d in demands}, alloc, compat, [], ["greedy baseline"], None, [], True, "greedy")


def _empty(supplies, demands, why):
    return {"method": "none", "allocations": [], "metrics": {"utility": 0.0, "units_allocated": 0.0, "unmet_units": float(sum(d.units for d in demands)), "min_coverage": 0.0, "jain": 1.0, "gini": 0.0},
            "coverage": {}, "stages": [], "notes": [why], "unserved_needs": [], "supply_left": {s.id: s.units for s in supplies}}


def _report(S, D, alloc, compat, stages, notes, t_star, unserved, integer, method):
    got = {n: 0.0 for n in D}
    used = {r: 0.0 for r in S}
    util = 0.0
    for a in alloc:
        got[a["demand_id"]] += a["units"]
        used[a["supply_id"]] += a["units"]
        util += D[a["demand_id"]].weight * a["relevance"] * a["units"]
    serv = [n for n in D if n not in unserved and D[n].units > 0]
    cov = {n: round(got[n] / D[n].units, 4) for n in D if D[n].units > 0}
    cs = [cov[n] for n in serv]
    org_units: dict = {}
    for n in D:
        if D[n].org_id is not None:
            org_units[D[n].org_id] = org_units.get(D[n].org_id, 0.0) + got[n]
    return {"method": method, "allocations": sorted(alloc, key=lambda a: (a["demand_id"], a["supply_id"])), "coverage": cov, "stages": stages, "notes": notes, "unserved_needs": list(unserved),
            "metrics": {"utility": round(util, 4), "units_allocated": round(sum(got.values()), 4), "unmet_units": round(sum(max(0.0, D[n].units - got[n]) for n in D), 4),
                        "min_coverage": round(min(cs), 4) if cs else 0.0, "jain": round(jain(cs), 4), "gini": round(gini(cs), 4), "best_possible_min_coverage": round(t_star, 4) if t_star is not None else None,
                        "org_units": {int(k): round(v, 3) for k, v in org_units.items()}},
            "supply_left": {r: round(S[r].units - used[r], 4) for r in S}, "integer": integer}


def check_feasibility(supplies, demands, result) -> list[str]:
    """Independent verification that a result respects every hard constraint. Returns the violations (empty = valid)."""
    S = {s.id: s.units for s in supplies}
    D = {d.id: d.units for d in demands}
    bad = []
    used, got = {}, {}
    for a in result["allocations"]:
        if a["units"] < -EPS:
            bad.append("negative units")
        used[a["supply_id"]] = used.get(a["supply_id"], 0) + a["units"]
        got[a["demand_id"]] = got.get(a["demand_id"], 0) + a["units"]
    bad += [f"supply {r} over-used ({u} > {S.get(r, 0)})" for r, u in used.items() if u > S.get(r, 0) + 1e-4]
    bad += [f"demand {n} over-served ({u} > {D.get(n, 0)})" for n, u in got.items() if u > D.get(n, 0) + 1e-4]
    return bad


# ----------------------------------------------------------------------------- donor matching
def solve_matching(donors: list[dict], needs: list[dict], fit: dict[tuple[int, int], float], *, max_donors_per_need: int = 2, ensure_org_coverage: bool = True,
                   min_fit: float = 0.0, time_limit: float = 20.0) -> dict:
    """donors: [{"id", "capacity"}]  needs: [{"id", "weight", "org_id"}]  fit[(donor_id, need_id)] in 0..1."""
    cap = {d["id"]: int(d.get("capacity", 1)) for d in donors if int(d.get("capacity", 1)) > 0}
    N = {n["id"]: n for n in needs}
    pairs = [(d, n) for (d, n), f in fit.items() if d in cap and n in N and f > min_fit]
    if not pairs:
        return {"method": "none", "assignments": [], "metrics": {"needs_covered": 0, "needs_total": len(N), "orgs_covered": 0, "total_fit": 0.0}, "notes": ["no feasible pairs"], "uncovered_needs": sorted(N)}
    needs_with = sorted({n for _, n in pairs})
    orgs = sorted({N[n].get("org_id") for n in needs_with if N[n].get("org_id") is not None})
    nv = len(pairs)
    z = {n: nv + i for i, n in enumerate(needs_with)}          # need covered
    o = {g: nv + len(needs_with) + i for i, g in enumerate(orgs)}  # organization covered
    total = nv + len(needs_with) + len(orgs)
    rows = []
    for d in cap:
        rows.append(({i: 1.0 for i, (dd, _) in enumerate(pairs) if dd == d}, -np.inf, cap[d]))
    for n in needs_with:
        rows.append(({i: 1.0 for i, (_, nn) in enumerate(pairs) if nn == n}, -np.inf, max_donors_per_need))
        rows.append(({**{i: 1.0 for i, (_, nn) in enumerate(pairs) if nn == n}, z[n]: -1.0}, 0.0, np.inf))   # covered only if someone is assigned
    for g in orgs:
        rows.append(({**{z[n]: 1.0 for n in needs_with if N[n].get("org_id") == g}, o[g]: -1.0}, 0.0, np.inf))
    A = lil_matrix((len(rows), total))
    lb, ub = np.empty(len(rows)), np.empty(len(rows))
    for k, (coefs, lo, hi) in enumerate(rows):
        for j, v in coefs.items():
            A[k, j] = v
        lb[k], ub[k] = lo, hi
    c = np.zeros(total)
    big = 10.0
    for i, (d, n) in enumerate(pairs):
        c[i] = -N[n].get("weight", 1.0) * fit[(d, n)]
    for n in needs_with:
        c[z[n]] = -big * N[n].get("weight", 1.0)
    if ensure_org_coverage:
        for g in orgs:
            c[o[g]] = -big * 5
    res = milp(c=c, constraints=LinearConstraint(A.tocsr(), lb, ub), integrality=np.ones(total), bounds=Bounds(np.zeros(total), np.ones(total)), options={"time_limit": time_limit})
    if res.x is None:
        return {"method": "milp", "assignments": [], "metrics": {"needs_covered": 0, "needs_total": len(N), "orgs_covered": 0, "total_fit": 0.0}, "notes": ["solver failed"], "uncovered_needs": sorted(N)}
    x = np.round(res.x)
    assign = [{"donor_id": d, "need_id": n, "fit": fit[(d, n)]} for i, (d, n) in enumerate(pairs) if x[i] > 0.5]
    covered = {a["need_id"] for a in assign}
    org_cov = {N[n].get("org_id") for n in covered if N[n].get("org_id") is not None}
    load = {}
    for a in assign:
        load[a["donor_id"]] = load.get(a["donor_id"], 0) + 1
    return {"method": "milp", "assignments": sorted(assign, key=lambda a: (a["need_id"], a["donor_id"])),
            "metrics": {"needs_covered": len(covered), "needs_total": len(N), "orgs_covered": len(org_cov), "orgs_total": len(orgs), "total_fit": round(sum(a["fit"] for a in assign), 4),
                        "weighted_fit": round(sum(N[a["need_id"]].get("weight", 1.0) * a["fit"] for a in assign), 4), "max_donor_load": max(load.values()) if load else 0},
            "uncovered_needs": sorted(set(N) - covered), "donor_load": load, "notes": []}


def greedy_matching(donors, needs, fit, max_donors_per_need: int = 2) -> dict:
    cap = {d["id"]: int(d.get("capacity", 1)) for d in donors}
    N = {n["id"]: n for n in needs}
    cnt = {n: 0 for n in N}
    assign = []
    for (d, n), f in sorted(fit.items(), key=lambda kv: -kv[1] * N.get(kv[0][1], {}).get("weight", 1.0)):
        if d in cap and n in N and cap[d] > 0 and cnt[n] < max_donors_per_need and f > 0:
            assign.append({"donor_id": d, "need_id": n, "fit": f})
            cap[d] -= 1
            cnt[n] += 1
    covered = {a["need_id"] for a in assign}
    org_cov = {N[n].get("org_id") for n in covered if N[n].get("org_id") is not None}
    return {"method": "greedy", "assignments": assign, "metrics": {"needs_covered": len(covered), "needs_total": len(N), "orgs_covered": len(org_cov),
            "total_fit": round(sum(a["fit"] for a in assign), 4), "weighted_fit": round(sum(N[a["need_id"]].get("weight", 1.0) * a["fit"] for a in assign), 4)}, "uncovered_needs": sorted(set(N) - covered)}


def random_instance(n_supply=8, n_demand=14, n_orgs=4, seed=7, scarcity=0.55):
    """Reproducible benchmark instance: scarce stock, mixed urgency, partial compatibility."""
    rng = np.random.default_rng(seed)
    demands = [Demand(i, float(rng.integers(5, 40)), URGENCY_WEIGHT[rng.choice(list(URGENCY_WEIGHT), p=[.12, .28, .4, .2])], int(rng.integers(0, n_orgs))) for i in range(n_demand)]
    for d in demands:
        d.critical = d.weight == URGENCY_WEIGHT["critical"]
    total = sum(d.units for d in demands)
    supplies = [Supply(i, float(max(3, round(total * scarcity / n_supply * rng.uniform(0.5, 1.5))))) for i in range(n_supply)]
    compat = {(s.id, d.id): round(float(rng.uniform(0.3, 1.0)), 3) for s in supplies for d in demands if rng.random() < 0.45}
    return supplies, demands, compat
