"""Location helpers: validation, distance, privacy rounding and ranking.

Pure Python on purpose (no database, no web framework), so every rule here is unit-tested without services.

Privacy rules this module enforces:
* Exact coordinates are never returned by the ranking helpers. Callers get a distance that is rounded UP to a
  whole kilometre ("within 5 km"). A finer number would let someone who can create needs at chosen points
  work out a donor's or volunteer's position by comparing several distances (trilateration).
* A missing or invalid coordinate means "location is not a factor". It is never guessed or defaulted.
"""
from __future__ import annotations

import math
import os
from typing import Any, Iterable, NamedTuple, Optional

EARTH_RADIUS_KM = 6371.0088
MAX_RADIUS_KM = 500.0
FALLBACK_RADIUS_KM = 25.0


class Point(NamedTuple):
    lat: float
    lon: float
    source: str  # which record the position came from: "need" | "organization" | "profile"


def default_radius_km() -> float:
    """Search radius used when nobody chose one. Configurable with GEO_DEFAULT_RADIUS_KM, clamped to 1..500 km."""
    try:
        value = float(os.getenv("GEO_DEFAULT_RADIUS_KM", str(FALLBACK_RADIUS_KM)))
    except ValueError:
        value = FALLBACK_RADIUS_KM
    if not math.isfinite(value):
        value = FALLBACK_RADIUS_KM
    return min(max(value, 1.0), MAX_RADIUS_KM)


def is_valid_coordinate(lat: Any, lon: Any) -> bool:
    """True for a real position. Rejects None, text, NaN/infinity, out-of-range values and exactly (0, 0),
    which is the usual sign of 'no data' rather than a place in the Gulf of Guinea."""
    if isinstance(lat, bool) or isinstance(lon, bool):
        return False
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(la) and math.isfinite(lo)):
        return False
    if not (-90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0):
        return False
    return not (la == 0.0 and lo == 0.0)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle ("as the crow flies") distance in kilometres. This is NOT a road distance or travel time."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def point_of(obj: Any, source: str = "profile") -> Optional[Point]:
    """The position stored on a record (anything with latitude/longitude attributes), or None."""
    if obj is None:
        return None
    lat, lon = getattr(obj, "latitude", None), getattr(obj, "longitude", None)
    return Point(float(lat), float(lon), source) if is_valid_coordinate(lat, lon) else None


def need_point(need: Any, organization: Any = None) -> Optional[Point]:
    """Where a need is. The need's own coordinates win; otherwise the organization's, because the need form
    does not ask for coordinates. Returns None when neither is known."""
    return point_of(need, "need") or point_of(organization, "organization")


def distance_between(a: Optional[Point], b: Optional[Point]) -> Optional[float]:
    if a is None or b is None:
        return None
    return haversine_km(a.lat, a.lon, b.lat, b.lon)


def coarse_distance(km: float) -> tuple[int, str]:
    """Privacy-safe distance: rounded UP to whole km, with a label that reads as an upper bound."""
    whole = max(1, math.ceil(km))
    return whole, ("within 1 km" if whole == 1 else f"within {whole} km")


# Map pins for people other than the owner are snapped to a ~1 km grid (2 decimals): the same precision as the
# "within N km" labels, so a map reveals no more than the list already does.
APPROX_DECIMALS = 2


def approx_position(lat: float, lon: float, decimals: int = APPROX_DECIMALS) -> dict:
    """A rounded pin position {lat, lon}. 2 decimals is about 1.1 km, 4 decimals about 11 m."""
    return {"lat": round(float(lat), decimals), "lon": round(float(lon), decimals)}


def clamp_radius(value: Optional[float]) -> float:
    """A caller-supplied radius, bounded to something sensible; the default when absent or invalid."""
    if value is None:
        return default_radius_km()
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default_radius_km()
    if not math.isfinite(value) or value <= 0:
        return default_radius_km()
    return min(value, MAX_RADIUS_KM)


# --------------------------------------------------------------------------- ranking (donor / volunteer view)
def rank_nearby_needs(rows: Iterable[tuple[Any, Any]], origin: Point, radius_km: float, limit: int = 20, include_position: bool = False) -> list[dict]:
    """rows = (need, organization) pairs. Needs inside the radius, nearest first. Needs with no known position are
    skipped (they cannot be placed). No addresses are returned. Coordinates are returned only when include_position is
    set (for the map view), and then only snapped to a ~1 km grid."""
    found: list[tuple[float, dict]] = []
    for need, org in rows:
        place = need_point(need, org)
        if place is None:
            continue
        km = haversine_km(origin.lat, origin.lon, place.lat, place.lon)
        if km > radius_km:
            continue
        whole, label = coarse_distance(km)
        item = {
            "need_id": need.id,
            "title": getattr(need, "title", None) or getattr(need, "category", None),
            "category": getattr(need, "category", None),
            "urgency": getattr(need, "urgency", None),
            "quantity": getattr(need, "quantity", None),
            "organization_name": getattr(org, "name", None),
            "distance_km": whole,
            "distance_label": label,
            "distance_basis": place.source,
        }
        if include_position:
            item["position"] = approx_position(place.lat, place.lon)
        found.append((km, item))
    found.sort(key=lambda t: (t[0], t[1]["need_id"]))
    return [item for _, item in found[: max(0, limit)]]


# --------------------------------------------------------------------------- ranking (organization / admin view)
def rank_nearby_people(origin: Point, people: Iterable[Any], kind: str, radius_km: float, limit: int = 20, include_position: bool = False) -> tuple[list[dict], int]:
    """People (donors or volunteers) near a need. Returns (ranked list, number with no location).

    A volunteer who set a service radius is flagged `within_service_radius`; None means they did not set one.
    The caller decides visibility (organizations pass only their own people)."""
    found: list[tuple[float, dict]] = []
    unlocated = 0
    for person in people:
        place = point_of(person)
        if place is None:
            unlocated += 1
            continue
        km = haversine_km(origin.lat, origin.lon, place.lat, place.lon)
        if km > radius_km:
            continue
        whole, label = coarse_distance(km)
        item = {"id": person.id, "name": getattr(person, "name", None), "distance_km": whole, "distance_label": label}
        if include_position:
            item["position"] = approx_position(place.lat, place.lon)
        if kind == "volunteer":
            own = getattr(person, "service_radius_km", None)
            item["service_radius_km"] = own
            item["within_service_radius"] = None if own is None else km <= float(own)
        found.append((km, item))
    found.sort(key=lambda t: (t[0], t[1]["id"]))
    return [item for _, item in found[: max(0, limit)]], unlocated


# --------------------------------------------------------------------------- matching integration
def apply_to_candidate(candidate: dict, origin: Optional[Point], person: Any, kind: str) -> bool:
    """Add distance information to a match candidate IN PLACE. Returns False when the person must be left out.

    * No usable position on either side -> unchanged, returns True (location is simply not a factor).
    * Volunteer who set a service radius and is outside it -> returns False (an eligibility rule, not a score).
    * Otherwise a rounded distance and a human-readable reason are added. The numeric `score` is never changed,
      so existing ranking stays identical; distance only breaks ties between equal scores.
    """
    km = distance_between(origin, point_of(person))
    if km is None:
        return True
    if kind == "volunteer":
        own = getattr(person, "service_radius_km", None)
        if own is not None and km > float(own):
            return False
    whole, label = coarse_distance(km)
    candidate["distance_km"] = whole
    candidate["distance_label"] = label
    reasons = list(candidate.get("reasons") or [])
    if kind == "volunteer" and getattr(person, "service_radius_km", None) is not None:
        reasons.append(f"Location: {label}, inside their {float(person.service_radius_km):g} km service radius")
    else:
        reasons.append(f"Location: {label} (straight-line distance, not a road route)")
    candidate["reasons"] = reasons
    return True
