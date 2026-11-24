"""Administrator map overview: where organizations, open needs, donors, volunteers and live deliveries are, and
which needs have nobody close enough to help.

Pure Python (no database, no web framework), so the rules are unit-tested without services. The router in
routers/admin_map.py loads the rows and calls build_overview().

Privacy rules (the same level the rest of the app already uses):
* Organizations and needs are places the organization chose to publish: pins at 4 decimals (about 11 m).
* Donors and volunteers are private individuals: pins snapped to about 1 km, exactly like the "within N km" labels.
* Live delivery positions follow services/tracking.py: shown only while a delivery is picked up / in transit,
  rounded to about 11 m, and flagged stale when old. Nothing is simulated or guessed.
* A record with no valid position is counted, never placed at a default point.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

from . import geo, tracking

URGENCY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
OPEN_NEED_STATES = (None, "open", "pending")
PLACE_DECIMALS = 4


def _urgency_rank(value: Optional[str]) -> int:
    return URGENCY_ORDER.get((value or "").lower(), 4)


def _pin(point: geo.Point, decimals: int) -> dict:
    return geo.approx_position(point.lat, point.lon, decimals)


def helpers_in_range(origin: geo.Point, people: Iterable[Any], kind: str, radius_km: float) -> tuple[int, Optional[float]]:
    """(how many could reach this place, the nearest located person in km or None).

    A volunteer who set a travel range counts only when the place is inside BOTH the search radius and their own range
    (the same eligibility rule as geo.apply_to_candidate). People with no position are skipped. `nearest` ignores the
    radius and travel range on purpose: for a need nobody can reach it tells the administrator how far recruiting would
    have to go."""
    count, nearest = 0, None
    for person in people:
        place = geo.point_of(person)
        if place is None:
            continue
        km = geo.haversine_km(origin.lat, origin.lon, place.lat, place.lon)
        nearest = km if nearest is None else min(nearest, km)
        if kind == "volunteer":
            own = getattr(person, "service_radius_km", None)
            if own is not None and km > float(own):
                continue
        if km > radius_km:
            continue
        count += 1
    return count, nearest


def build_overview(
    organizations: list[Any],
    needs: list[Any],
    donors: list[Any],
    volunteers: list[Any],
    live: list[dict],
    radius_km: Optional[float],
    now: datetime,
) -> dict:
    radius = geo.clamp_radius(radius_km)
    org_by_id = {o.id: o for o in organizations}

    org_pins, orgs_unplaced = [], 0
    for o in organizations:
        place = geo.point_of(o, "organization")
        if place is None:
            orgs_unplaced += 1
            continue
        org_pins.append({
            "id": o.id, "name": o.name, "verified": bool(o.verified),
            "status": getattr(o, "verification_status", None), "address": getattr(o, "address", None),
            "position": _pin(place, PLACE_DECIMALS),
        })

    need_pins, gaps, needs_unplaced = [], [], 0
    for n in needs:
        if getattr(n, "status", None) not in OPEN_NEED_STATES:
            continue
        org = org_by_id.get(n.org_id)
        place = geo.need_point(n, org)
        if place is None:
            needs_unplaced += 1
            continue
        vol_count, vol_nearest = helpers_in_range(place, volunteers, "volunteer", radius)
        donor_count, donor_nearest = helpers_in_range(place, donors, "donor", radius)
        pin = {
            "id": n.id, "org_id": n.org_id, "organization_name": getattr(org, "name", None),
            "title": getattr(n, "title", None) or getattr(n, "category", None) or "Need",
            "category": getattr(n, "category", None), "urgency": getattr(n, "urgency", None),
            "status": getattr(n, "status", None) or "open", "quantity": getattr(n, "quantity", None),
            "verified_org": bool(getattr(org, "verified", False)), "located_via": place.source,
            "position": _pin(place, PLACE_DECIMALS),
            "volunteers_in_range": vol_count, "donors_in_range": donor_count,
        }
        need_pins.append(pin)
        if vol_count == 0:
            gaps.append({
                "need_id": n.id, "title": pin["title"], "organization_name": pin["organization_name"],
                "urgency": pin["urgency"], "donors_in_range": donor_count, "position": pin["position"],
                "nearest_volunteer_km": None if vol_nearest is None else geo.coarse_distance(vol_nearest)[0],
            })
    gaps.sort(key=lambda g: (_urgency_rank(g["urgency"]), g["need_id"]))

    def people(rows: list[Any], kind: str):
        pins, unplaced = [], 0
        for p in rows:
            place = geo.point_of(p)
            if place is None:
                unplaced += 1
                continue
            item = {"id": p.id, "name": getattr(p, "name", None), "organization_id": getattr(p, "organization_id", None),
                    "position": _pin(place, geo.APPROX_DECIMALS)}
            if kind == "volunteer":
                item["service_radius_km"] = getattr(p, "service_radius_km", None)
            pins.append(item)
        return pins, unplaced

    donor_pins, donors_unplaced = people(donors, "donor")
    volunteer_pins, volunteers_unplaced = people(volunteers, "volunteer")

    live_pins = []
    for row in live:
        if row.get("status") not in tracking.VIEWER_STATUSES:
            continue   # an administrator may watch only during the delivery leg, like everyone else
        fix = tracking.present(row, now, {"admin"})
        if not fix.get("has_position"):
            continue
        live_pins.append({
            "task_id": row["task_id"], "status": row["status"], "need_title": row.get("need_title"),
            "position": {"lat": fix["latitude"], "lon": fix["longitude"]},
            "age_seconds": fix["age_seconds"], "stale": fix["stale"],
        })

    return {
        "radius_km": radius,
        "organizations": org_pins, "needs": need_pins, "donors": donor_pins, "volunteers": volunteer_pins,
        "live_deliveries": live_pins, "gaps": gaps,
        "unplaced": {"organizations": orgs_unplaced, "needs": needs_unplaced,
                     "donors": donors_unplaced, "volunteers": volunteers_unplaced},
        "precision_note": "Organization and need pins are exact to about 11 m. Donor and volunteer pins are snapped to about 1 km. "
                          "Live delivery positions appear only while a delivery is picked up or in transit.",
        "generated_at": now.isoformat(),
    }
