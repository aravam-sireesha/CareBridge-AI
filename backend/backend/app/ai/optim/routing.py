"""Delivery routing: Dijkstra, A*, and a Vehicle Routing Problem (capacitated) heuristic.

Needs coordinates (latitude/longitude on organizations and needs). Without them these tools are not used.
* dijkstra  shortest paths on a weighted graph (e.g. a road network or a graph of delivery points)
* a_star    shortest path with a straight-line (haversine) heuristic, so fewer nodes are explored
* solve_vrp capacitated VRP by Clarke-Wright savings, improved with 2-opt inside every route (a heuristic, not an exact optimum)"""
from __future__ import annotations

import heapq
import math

R_EARTH_KM = 6371.0088


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dphi, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH_KM * math.asin(min(1.0, math.sqrt(h)))


def dijkstra(graph: dict, source, target=None) -> tuple[dict, dict]:
    """graph = {node: {neighbour: weight}} with non-negative weights. Returns (distance, previous)."""
    dist = {source: 0.0}
    prev: dict = {}
    heap = [(0.0, 0, source)]
    counter = 1
    done = set()
    while heap:
        d, _, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        if u == target:
            break
        for v, w in graph.get(u, {}).items():
            if w < 0:
                raise ValueError("Dijkstra needs non-negative weights")
            nd = d + w
            if nd < dist.get(v, math.inf):
                dist[v], prev[v] = nd, u
                heapq.heappush(heap, (nd, counter, v))
                counter += 1
    return dist, prev


def path_from(prev: dict, source, target) -> list:
    if target != source and target not in prev:
        return []
    path = [target]
    while path[-1] != source:
        path.append(prev[path[-1]])
    return path[::-1]


def a_star(graph: dict, coords: dict, source, target) -> dict:
    """A* with the haversine distance as an admissible heuristic (edge weights must be >= straight-line distance, e.g. road km)."""
    h = lambda n: haversine(coords[n], coords[target])  # noqa: E731
    g = {source: 0.0}
    prev: dict = {}
    heap = [(h(source), 0, source)]
    counter, expanded = 1, 0
    closed = set()
    while heap:
        _, _, u = heapq.heappop(heap)
        if u in closed:
            continue
        closed.add(u)
        expanded += 1
        if u == target:
            return {"path": path_from(prev, source, target), "distance": g[u], "expanded": expanded}
        for v, w in graph.get(u, {}).items():
            ng = g[u] + w
            if ng < g.get(v, math.inf):
                g[v], prev[v] = ng, u
                heapq.heappush(heap, (ng + h(v), counter, v))
                counter += 1
    return {"path": [], "distance": math.inf, "expanded": expanded}


def _route_len(route, dist):
    return sum(dist[route[i]][route[i + 1]] for i in range(len(route) - 1))


def _two_opt(route, dist):
    best, improved = route[:], True
    while improved:
        improved = False
        for i in range(1, len(best) - 2):
            for j in range(i + 1, len(best) - 1):
                new = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                if _route_len(new, dist) + 1e-9 < _route_len(best, dist):
                    best, improved = new, True
    return best


def solve_vrp(depot: tuple[float, float], stops: list[dict], vehicles: int, capacity: float) -> dict:
    """stops = [{"id", "lat", "lon", "demand"}]. Returns routes starting and ending at the depot (index 0)."""
    if capacity <= 0 or vehicles <= 0:
        raise ValueError("vehicles and capacity must be positive")
    too_big = [s["id"] for s in stops if s["demand"] > capacity]
    stops = [s for s in stops if s["demand"] <= capacity]
    pts = [depot] + [(s["lat"], s["lon"]) for s in stops]
    n = len(pts)
    dist = [[haversine(pts[i], pts[j]) for j in range(n)] for i in range(n)]
    routes = {i: [0, i, 0] for i in range(1, n)}
    load = {i: stops[i - 1]["demand"] for i in range(1, n)}
    where = {i: i for i in range(1, n)}                       # stop -> route key
    for _, i, j in sorted(((dist[0][i] + dist[0][j] - dist[i][j], i, j) for i in range(1, n) for j in range(i + 1, n)), reverse=True):
        a, b = where[i], where[j]
        if a == b or load[a] + load[b] > capacity:
            continue
        ra, rb = routes[a], routes[b]
        if ra[-2] == i and rb[1] == j:
            merged = ra[:-1] + rb[1:]
        elif ra[1] == i and rb[-2] == j:
            merged = rb[:-1] + ra[1:]
        elif ra[-2] == i and rb[-2] == j:
            merged = ra[:-1] + rb[1:-1][::-1] + [0]
        elif ra[1] == i and rb[1] == j:
            merged = ra[::-1][:-1] + rb[1:]
        else:
            continue
        routes[a], load[a] = merged, load[a] + load[b]
        for node in merged[1:-1]:
            where[node] = a
        del routes[b], load[b]
    final = [_two_opt(r, dist) for r in routes.values()]
    final.sort(key=lambda r: -sum(stops[k - 1]["demand"] for k in r[1:-1]))
    notes = []
    if len(final) > vehicles:
        notes.append(f"{len(final)} routes are needed for {vehicles} vehicle(s); the extra routes need more vehicles or capacity")
    if too_big:
        notes.append(f"stops {too_big} exceed one vehicle's capacity and were not routed")
    out = [{"stops": [stops[k - 1]["id"] for k in r[1:-1]], "distance_km": round(_route_len(r, dist), 3), "load": sum(stops[k - 1]["demand"] for k in r[1:-1])} for r in final]
    return {"routes": out, "total_km": round(sum(r["distance_km"] for r in out), 3), "vehicles_needed": len(out), "feasible": len(out) <= vehicles and not too_big, "notes": notes}


def nearest_neighbour_baseline(depot, stops, capacity) -> float:
    """Baseline total distance: each vehicle repeatedly drives to the nearest unvisited stop that still fits."""
    left = list(stops)
    total = 0.0
    while left:
        pos, cap = depot, capacity
        while True:
            fits = [s for s in left if s["demand"] <= cap]
            if not fits:
                break
            nxt = min(fits, key=lambda s: haversine(pos, (s["lat"], s["lon"])))
            total += haversine(pos, (nxt["lat"], nxt["lon"]))
            pos, cap = (nxt["lat"], nxt["lon"]), cap - nxt["demand"]
            left.remove(nxt)
        total += haversine(pos, depot)
        if all(s["demand"] > capacity for s in left):
            break
    return round(total, 3)
