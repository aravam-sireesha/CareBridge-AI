"""Phase 4: constrained optimisation (LP / MILP), heuristics, routing - with edge cases."""
import math

import pytest

from app.ai.optim import allocation as al
from app.ai.optim import metaheuristics as mh
from app.ai.optim import routing as rt
from app.ai.optim.allocation import Demand, Supply


def units(res, supply=None, demand=None):
    return sum(a["units"] for a in res["allocations"] if (supply is None or a["supply_id"] == supply) and (demand is None or a["demand_id"] == demand))


# ----------------------------------------------------------------------------- allocation: hard constraints
@pytest.mark.parametrize("seed", [1, 2, 3, 7, 11, 23])
def test_inventory_and_demand_limits_always_hold(seed):
    S, D, C = al.random_instance(seed=seed)
    for fairness in ("none", "floor", "maxmin"):
        for integer in (True, False):
            res = al.solve_allocation(S, D, C, fairness=fairness, integer=integer)
            assert al.check_feasibility(S, D, res) == [], (seed, fairness, integer)
            if integer:
                assert all(float(a["units"]).is_integer() for a in res["allocations"])


def test_urgent_first_serves_critical_needs_before_anything_else():
    S = [Supply(1, 10)]
    D = [Demand(1, 10, weight=1.5), Demand(2, 10, weight=4.0, critical=True)]
    C = {(1, 1): 1.0, (1, 2): 0.2}  # the medium need is a MUCH better match (1.5 x 1.0 vs 4.0 x 0.2), yet the critical one must come first
    res = al.solve_allocation(S, D, C, urgent_first=True, fairness="none")
    assert units(res, demand=2) == 10 and units(res, demand=1) == 0
    no_priority = al.solve_allocation(S, D, C, urgent_first=False, fairness="none")
    assert units(no_priority, demand=1) >= units(no_priority, demand=2)  # utility alone would not do this


def test_maxmin_fairness_shares_scarce_stock_while_utility_alone_does_not():
    S = [Supply(1, 10)]
    D = [Demand(1, 10, org_id=1), Demand(2, 10, org_id=2)]
    C = {(1, 1): 1.0, (1, 2): 0.5}
    greedy_like = al.solve_allocation(S, D, C, fairness="none", urgent_first=False)
    fair = al.solve_allocation(S, D, C, fairness="maxmin", urgent_first=False)
    assert units(greedy_like, demand=2) == 0 and fair["metrics"]["min_coverage"] == 0.5
    assert units(fair, demand=1) == 5 and units(fair, demand=2) == 5 and fair["metrics"]["jain"] == 1.0
    floor = al.solve_allocation(S, D, C, fairness="floor", fairness_alpha=0.6, urgent_first=False)
    assert floor["metrics"]["min_coverage"] >= 0.6 * floor["metrics"]["best_possible_min_coverage"] - 1e-6


def test_fairness_costs_some_utility_but_never_breaks_constraints():
    S, D, C = al.random_instance(seed=7)
    u = al.solve_allocation(S, D, C, fairness="none", urgent_first=False)
    f = al.solve_allocation(S, D, C, fairness="maxmin", urgent_first=False)
    assert f["metrics"]["utility"] <= u["metrics"]["utility"] + 1e-6
    assert f["metrics"]["min_coverage"] >= u["metrics"]["min_coverage"] and f["metrics"]["jain"] >= u["metrics"]["jain"] - 1e-9


def test_organization_cap_limits_any_single_organizations_share():
    S = [Supply(1, 20)]
    D = [Demand(1, 20, org_id=1), Demand(2, 20, org_id=2)]
    C = {(1, 1): 1.0, (1, 2): 0.2}
    res = al.solve_allocation(S, D, C, fairness="none", urgent_first=False, org_cap=0.6)
    assert res["metrics"]["org_units"][1] <= 12 + 1e-6 and al.check_feasibility(S, D, res) == []


# ----------------------------------------------------------------------------- allocation: edge cases
def test_edge_cases_empty_zero_and_unserved():
    for S, D, C in (([], [Demand(1, 5)], {}), ([Supply(1, 5)], [], {}), ([Supply(1, 0)], [Demand(1, 5)], {(1, 1): 1.0}), ([Supply(1, 5)], [Demand(1, 0)], {(1, 1): 1.0}),
                    ([Supply(1, 5)], [Demand(1, 5)], {})):
        res = al.solve_allocation(S, D, C)
        assert res["allocations"] == [] and res["notes"] and res["metrics"]["utility"] == 0.0
    S, D = [Supply(1, 10)], [Demand(1, 10), Demand(2, 10)]
    res = al.solve_allocation(S, D, {(1, 1): 1.0})   # nobody can serve need 2
    assert res["unserved_needs"] == [2] and any("no compatible stock" in n for n in res["notes"]) and units(res, demand=1) == 10
    assert al.solve_allocation(S, D, {(1, 1): 1.0, (1, 2): 0.0})["unserved_needs"] == [2]  # zero relevance is not compatibility
    with pytest.raises(ValueError):
        al.solve_allocation(S, D, {(1, 1): 1.0}, fairness="equalise-everything")


def test_abundant_stock_meets_every_need_and_leaves_the_rest():
    S = [Supply(1, 100), Supply(2, 100)]
    D = [Demand(1, 10), Demand(2, 20)]
    C = {(1, 1): 0.9, (2, 1): 0.5, (1, 2): 0.4, (2, 2): 0.8}
    res = al.solve_allocation(S, D, C)
    assert res["metrics"]["unmet_units"] == 0 and res["metrics"]["min_coverage"] == 1.0 and sum(res["supply_left"].values()) == 170


def test_results_are_deterministic_and_lp_relaxation_is_an_upper_bound():
    S, D, C = al.random_instance(seed=5)
    a = al.solve_allocation(S, D, C, fairness="none", urgent_first=False)
    b = al.solve_allocation(S, D, C, fairness="none", urgent_first=False)
    lp = al.solve_allocation(S, D, C, fairness="none", urgent_first=False, integer=False)
    assert a["allocations"] == b["allocations"] and lp["metrics"]["utility"] >= a["metrics"]["utility"] - 1e-6


def test_the_independent_checker_catches_violations():
    S, D = [Supply(1, 5)], [Demand(1, 4)]
    bad = {"allocations": [{"supply_id": 1, "demand_id": 1, "units": 6}]}
    msgs = al.check_feasibility(S, D, bad)
    assert any("over-used" in m for m in msgs) and any("over-served" in m for m in msgs)


# ----------------------------------------------------------------------------- donor matching
def test_matching_respects_capacity_covers_needs_and_beats_greedy_on_coverage():
    donors = [{"id": 1, "capacity": 1}, {"id": 2, "capacity": 1}, {"id": 3, "capacity": 2}]
    needs = [{"id": 1, "weight": 2.0, "org_id": 1}, {"id": 2, "weight": 1.0, "org_id": 2}, {"id": 3, "weight": 1.0, "org_id": 2}]
    fit = {(1, 1): 0.95, (1, 2): 0.9, (2, 1): 0.9, (3, 1): 0.3, (3, 2): 0.3, (3, 3): 0.35, (2, 3): 0.1}
    res = al.solve_matching(donors, needs, fit, max_donors_per_need=1)
    load = res["donor_load"]
    assert all(load[d["id"]] <= d["capacity"] for d in donors if d["id"] in load)
    assert res["metrics"]["needs_covered"] == 3 and res["metrics"]["orgs_covered"] == 2 and res["uncovered_needs"] == []
    greedy = al.greedy_matching(donors, needs, fit, max_donors_per_need=1)
    assert res["metrics"]["needs_covered"] >= greedy["metrics"]["needs_covered"]
    per_need = {}
    for a in res["assignments"]:
        per_need[a["need_id"]] = per_need.get(a["need_id"], 0) + 1
    assert max(per_need.values()) <= 1


def test_matching_edge_cases():
    assert al.solve_matching([], [{"id": 1}], {})["notes"] == ["no feasible pairs"]
    res = al.solve_matching([{"id": 1, "capacity": 1}], [{"id": 1, "weight": 1.0, "org_id": 1}, {"id": 2, "weight": 1.0, "org_id": 2}], {(1, 1): 0.8, (1, 2): 0.7})
    assert res["metrics"]["needs_covered"] == 1 and len(res["uncovered_needs"]) == 1       # one donor, one slot: honest about it
    excl = al.solve_matching([{"id": 1, "capacity": 2}], [{"id": 1, "weight": 1.0}], {(1, 1): 0.05}, min_fit=0.1)
    assert excl["assignments"] == []                                                       # a poor fit is not forced


# ----------------------------------------------------------------------------- GA and PSO
def test_metaheuristics_are_feasible_reproducible_and_close_to_the_bound():
    S, D, C = al.random_instance(seed=7)
    bound = al.solve_allocation(S, D, C, fairness="none", urgent_first=False, integer=False)["metrics"]["utility"]
    for fn in (mh.genetic_algorithm, mh.particle_swarm):
        a = fn(S, D, C, seed=3, fairness_weight=0.0)
        assert al.check_feasibility(S, D, a) == []
        assert a["metrics"]["utility"] <= bound + 1e-6 and a["metrics"]["utility"] >= 0.8 * bound
        assert fn(S, D, C, seed=3, fairness_weight=0.0)["allocations"] == a["allocations"]
    cmp_ = mh.compare_solvers(S, D, C)
    assert cmp_["utility_only"]["lp relaxation (upper bound)"]["vs_bound"] == 1.0
    assert all(v["vs_bound"] <= 1.0 + 1e-6 for v in cmp_["utility_only"].values())
    assert cmp_["fairness"]["milp maxmin"]["min_coverage"] >= cmp_["fairness"]["greedy"]["min_coverage"]


def test_metaheuristics_handle_empty_problems():
    assert mh.genetic_algorithm([], [Demand(1, 5)], {})["allocations"] == []
    assert mh.particle_swarm([Supply(1, 5)], [Demand(1, 5)], {})["allocations"] == []


# ----------------------------------------------------------------------------- routing
def test_haversine_and_dijkstra():
    delhi, mumbai = (28.6139, 77.2090), (19.0760, 72.8777)
    assert 1100 < rt.haversine(delhi, mumbai) < 1200 and rt.haversine(delhi, delhi) == 0
    g = {"A": {"B": 4, "C": 1}, "C": {"B": 2, "D": 7}, "B": {"D": 1}, "D": {}}
    dist, prev = rt.dijkstra(g, "A")
    assert dist["D"] == 4 and rt.path_from(prev, "A", "D") == ["A", "C", "B", "D"]
    assert rt.path_from(prev, "A", "Z") == [] and rt.dijkstra({"A": {"B": 1}, "B": {}}, "B")[0] == {"B": 0.0}
    with pytest.raises(ValueError):
        rt.dijkstra({"A": {"B": -1}, "B": {}}, "A")


def test_a_star_matches_dijkstra_and_explores_fewer_nodes():
    coords = {(x, y): (10 + x * 0.1, 70 + y * 0.1) for x in range(12) for y in range(12)}
    graph = {}
    for (x, y), a in coords.items():
        graph[(x, y)] = {}
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nb = (x + dx, y + dy)
            if nb in coords:
                graph[(x, y)][nb] = rt.haversine(a, coords[nb]) * 1.2   # roads are never shorter than the straight line
    res = rt.a_star(graph, coords, (0, 0), (11, 11))
    dist, _ = rt.dijkstra(graph, (0, 0), (11, 11))
    assert math.isclose(res["distance"], dist[(11, 11)], rel_tol=1e-9) and res["path"][0] == (0, 0) and res["path"][-1] == (11, 11)
    assert res["expanded"] <= len(coords)
    assert rt.a_star({"A": {}, "B": {}}, {"A": (0, 0), "B": (1, 1)}, "A", "B")["path"] == []


def test_vrp_serves_every_stop_once_within_capacity_and_beats_the_baseline():
    depot = (17.385, 78.4867)
    stops = [{"id": i, "lat": 17.385 + 0.05 * math.cos(i), "lon": 78.4867 + 0.05 * math.sin(i * 1.7), "demand": 3 + i % 4} for i in range(1, 15)]
    res = rt.solve_vrp(depot, stops, vehicles=4, capacity=20)
    served = [s for r in res["routes"] for s in r["stops"]]
    assert sorted(served) == sorted(s["id"] for s in stops) and all(r["load"] <= 20 for r in res["routes"])
    assert res["feasible"] and res["vehicles_needed"] <= 4
    assert res["total_km"] <= rt.nearest_neighbour_baseline(depot, stops, 20) * 1.05


def test_vrp_reports_oversized_stops_and_too_few_vehicles():
    depot = (0.0, 0.0)
    stops = [{"id": 1, "lat": 0.1, "lon": 0.0, "demand": 9}, {"id": 2, "lat": 0.0, "lon": 0.1, "demand": 9}, {"id": 3, "lat": 0.1, "lon": 0.1, "demand": 99}]
    res = rt.solve_vrp(depot, stops, vehicles=1, capacity=10)
    assert 3 not in [s for r in res["routes"] for s in r["stops"]] and not res["feasible"] and len(res["notes"]) == 2
    assert rt.solve_vrp(depot, [], 1, 10)["routes"] == []
    with pytest.raises(ValueError):
        rt.solve_vrp(depot, stops, 0, 10)
