"""Genetic Algorithm and Particle Swarm Optimisation for the allocation problem.

These are included as comparisons and for objectives that are not linear. For the linear problem solved in allocation.py the MILP
is exact and faster, so it stays the production solver; `compare_solvers` reports how close each heuristic gets (the 'gap')."""
from __future__ import annotations

import numpy as np

from .allocation import Demand, Supply, solve_allocation, greedy_allocation


class _Problem:
    def __init__(self, supplies, demands, compat, fairness_weight=0.5):
        self.S = [s for s in supplies if s.units > 0]
        self.D = [d for d in demands if d.units > 0]
        self.pairs = [(i, j) for i, s in enumerate(self.S) for j, d in enumerate(self.D) if compat.get((s.id, d.id), 0) > 0]
        self.rel = np.array([compat[(self.S[i].id, self.D[j].id)] for i, j in self.pairs]) if self.pairs else np.array([])
        self.w = np.array([self.D[j].weight for _, j in self.pairs]) if self.pairs else np.array([])
        self.fw = fairness_weight

    def repair(self, x):
        """Make any non-negative vector feasible: scale down over-used stock, then over-served needs."""
        x = np.maximum(x, 0.0)
        for _ in range(2):
            for i, s in enumerate(self.S):
                mask = np.array([p[0] == i for p in self.pairs])
                tot = x[mask].sum() if mask.any() else 0
                if tot > s.units:
                    x[mask] *= s.units / tot
            for j, d in enumerate(self.D):
                mask = np.array([p[1] == j for p in self.pairs])
                tot = x[mask].sum() if mask.any() else 0
                if tot > d.units:
                    x[mask] *= d.units / tot
        return x

    def coverage(self, x):
        cov = np.zeros(len(self.D))
        for k, (_, j) in enumerate(self.pairs):
            cov[j] += x[k]
        return cov / np.array([d.units for d in self.D])

    def fitness(self, x):
        util = float((self.w * self.rel * x).sum())
        cov = self.coverage(x)
        servable = np.array([any(p[1] == j for p in self.pairs) for j in range(len(self.D))])
        floor = float(cov[servable].min()) if servable.any() else 0.0
        return util + self.fw * floor * float(sum(d.units for d in self.D) / max(1, len(self.D)))

    def report(self, x, compat, method):
        alloc = [{"supply_id": self.S[i].id, "demand_id": self.D[j].id, "units": float(np.floor(v * 1000) / 1000), "relevance": float(compat[(self.S[i].id, self.D[j].id)])} for (i, j), v in zip(self.pairs, x) if v > 1e-6]
        from .allocation import _report
        return _report({s.id: s for s in self.S}, {d.id: d for d in self.D}, alloc, compat, [], [method], None, [], False, method)


def genetic_algorithm(supplies, demands, compat, pop=70, generations=200, seed=7, fairness_weight=0.5) -> dict:
    P = _Problem(supplies, demands, compat, fairness_weight)
    if not P.pairs:
        return greedy_allocation(supplies, demands, compat)
    rng = np.random.default_rng(seed)
    ub = np.array([min(P.S[i].units, P.D[j].units) for i, j in P.pairs])
    popu = [P.repair(rng.random(len(ub)) * ub * rng.random()) for _ in range(pop)]
    fit = np.array([P.fitness(x) for x in popu])
    for _ in range(generations):
        children = [popu[int(np.argmax(fit))].copy()]                                  # elitism
        while len(children) < pop:
            a = max(rng.choice(pop, 3, replace=False), key=lambda i: fit[i])           # tournament selection
            b = max(rng.choice(pop, 3, replace=False), key=lambda i: fit[i])
            alpha = rng.random(len(ub))
            child = alpha * popu[a] + (1 - alpha) * popu[b]                              # blend crossover
            mask = rng.random(len(ub)) < 0.08
            child[mask] += rng.normal(0, 0.25, mask.sum()) * ub[mask]                    # gaussian mutation
            children.append(P.repair(np.clip(child, 0, ub)))
        popu = children
        fit = np.array([P.fitness(x) for x in popu])
    return P.report(popu[int(np.argmax(fit))], compat, "genetic algorithm")


def particle_swarm(supplies, demands, compat, particles=50, iterations=250, seed=7, fairness_weight=0.5) -> dict:
    P = _Problem(supplies, demands, compat, fairness_weight)
    if not P.pairs:
        return greedy_allocation(supplies, demands, compat)
    rng = np.random.default_rng(seed)
    ub = np.array([min(P.S[i].units, P.D[j].units) for i, j in P.pairs])
    pos = np.array([P.repair(rng.random(len(ub)) * ub) for _ in range(particles)])
    vel = rng.normal(0, 0.1, pos.shape) * ub
    pbest, pfit = pos.copy(), np.array([P.fitness(x) for x in pos])
    g = pbest[int(np.argmax(pfit))].copy()
    gfit = pfit.max()
    for it in range(iterations):
        w = 0.9 - 0.5 * it / iterations                                                  # inertia decays: explore, then exploit
        r1, r2 = rng.random(pos.shape), rng.random(pos.shape)
        vel = w * vel + 1.6 * r1 * (pbest - pos) + 1.6 * r2 * (g - pos)
        pos = np.array([P.repair(np.clip(p, 0, ub)) for p in pos + vel])
        f = np.array([P.fitness(x) for x in pos])
        better = f > pfit
        pbest[better], pfit[better] = pos[better], f[better]
        if pfit.max() > gfit:
            gfit, g = pfit.max(), pbest[int(np.argmax(pfit))].copy()
    return P.report(g, compat, "particle swarm")


def compare_solvers(supplies, demands, compat, seed=7) -> dict:
    """Two like-for-like comparisons.
    utility_only : every method maximises the same linear utility; the LP relaxation is the upper bound, so 'vs_bound' <= 1.
    fairness     : the methods that can use a fairness objective, scored on min coverage and Jain's index."""
    bound = solve_allocation(supplies, demands, compat, fairness="none", urgent_first=False, integer=False)
    exact = solve_allocation(supplies, demands, compat, fairness="none", urgent_first=False, integer=True)
    runs = {"lp relaxation (upper bound)": bound, "milp (exact, integer)": exact, "greedy": greedy_allocation(supplies, demands, compat),
            "genetic algorithm": genetic_algorithm(supplies, demands, compat, seed=seed, fairness_weight=0.0),
            "particle swarm": particle_swarm(supplies, demands, compat, seed=seed, fairness_weight=0.0)}
    ub = bound["metrics"]["utility"] or 1.0
    util = {k: {"utility": v["metrics"]["utility"], "vs_bound": round(v["metrics"]["utility"] / ub, 4)} for k, v in runs.items()}
    fair = {"milp maxmin": solve_allocation(supplies, demands, compat, fairness="maxmin", urgent_first=False),
            "milp floor (alpha 0.8)": solve_allocation(supplies, demands, compat, fairness="floor", urgent_first=False),
            "milp utility only": exact, "greedy": runs["greedy"],
            "genetic algorithm (fairness-aware)": genetic_algorithm(supplies, demands, compat, seed=seed, fairness_weight=0.6),
            "particle swarm (fairness-aware)": particle_swarm(supplies, demands, compat, seed=seed, fairness_weight=0.6)}
    return {"utility_only": util, "fairness": {k: {m: v["metrics"][m] for m in ("utility", "min_coverage", "jain", "gini")} for k, v in fair.items()}}
