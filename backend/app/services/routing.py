"""Road distance, travel time and traffic-aware ETA through the Google Routes API (computeRoutes).

* Only real road routes are returned. If routing is not configured or fails, callers get an error, never a straight-line number
  presented as a road distance.
* Configuration (environment only): GOOGLE_MAPS_SERVER_API_KEY and GOOGLE_ROUTES_ENABLED=true. The server key must be restricted
  by server IP and to the Routes API in Google Cloud Console.
* Results are not stored or cached beyond one request (Google's terms limit caching of Maps content).
* LIVE USE IS UNTESTED here: no Google credentials were available. The request shape follows Google's published Routes API;
  tests use a fake transport. Verify with a real key before relying on it (see MAP_AND_GPS_SETUP.md).
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional

from . import maps_http
from .geo import is_valid_coordinate
from .maps_http import MapsError

ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.duration,routes.staticDuration,routes.distanceMeters,routes.polyline.encodedPolyline"
MODES = {"drive": "DRIVE", "two_wheeler": "TWO_WHEELER", "walk": "WALK"}
_DURATION = re.compile(r"^(\d+(?:\.\d+)?)s$")


def _flag(env: Mapping[str, str], name: str) -> bool:
    return str(env.get(name, "")).strip().lower() == "true"


def enabled(env: Mapping[str, str]) -> bool:
    return _flag(env, "GOOGLE_ROUTES_ENABLED") and bool((env.get("GOOGLE_MAPS_SERVER_API_KEY") or "").strip())


@dataclass(frozen=True)
class RouteResult:
    distance_m: int
    duration_s: int                 # with live traffic where the mode supports it
    static_duration_s: int          # without traffic
    polyline: str                   # Google encoded polyline (precision 5)
    traffic_aware: bool
    mode: str
    arrival_at: str                 # UTC ISO-8601, now + duration_s
    provider: str = "google_routes"

    def to_dict(self) -> dict:
        return asdict(self)


def parse_duration(value: object) -> Optional[int]:
    """Google returns durations as strings like "1234s" (sometimes "1234.5s")."""
    m = _DURATION.match(str(value or "").strip())
    return int(round(float(m.group(1)))) if m else None


def parse_response(data: object, mode: str, traffic_aware: bool, now: Optional[datetime] = None) -> RouteResult:
    routes = data.get("routes") if isinstance(data, dict) else None
    if not routes or not isinstance(routes, list) or not isinstance(routes[0], dict):
        raise MapsError("no_route", "No driving route was found between these two places.")
    r = routes[0]
    distance, duration = r.get("distanceMeters"), parse_duration(r.get("duration"))
    poly = (r.get("polyline") or {}).get("encodedPolyline")
    if not isinstance(distance, (int, float)) or isinstance(distance, bool) or not math.isfinite(distance) or distance < 0 or duration is None or not isinstance(poly, str) or not poly:
        raise MapsError("unavailable", "The map service returned an unreadable route.")
    static = parse_duration(r.get("staticDuration"))
    now = now or datetime.now(timezone.utc)
    return RouteResult(int(distance), duration, static if static is not None else duration, poly, traffic_aware, mode,
                       (now + timedelta(seconds=duration)).replace(microsecond=0).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


def _waypoint(lat: float, lon: float) -> dict:
    return {"location": {"latLng": {"latitude": float(lat), "longitude": float(lon)}}}


def compute_route(origin: tuple[float, float], destination: tuple[float, float], env: Mapping[str, str], mode: str = "drive",
                  transport=None, now: Optional[datetime] = None) -> RouteResult:
    if not enabled(env):
        raise MapsError("not_configured", "Road routing is not set up on this server, so no road distance or arrival time can be shown.")
    if mode not in MODES:
        raise MapsError("invalid", "Unknown travel mode.")
    for lat, lon in (origin, destination):
        numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon))
        if not (numeric and is_valid_coordinate(lat, lon)):
            raise MapsError("invalid", "That is not a valid place.")
    traffic = mode in ("drive", "two_wheeler")           # Google supports traffic-aware routing only for motor vehicles
    body = {"origin": _waypoint(*origin), "destination": _waypoint(*destination), "travelMode": MODES[mode],
            "languageCode": "en-IN", "units": "METRIC", "computeAlternativeRoutes": False}
    if traffic:
        body["routingPreference"] = "TRAFFIC_AWARE"
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": env["GOOGLE_MAPS_SERVER_API_KEY"].strip(), "X-Goog-FieldMask": FIELD_MASK}
    status, data = (transport or maps_http.request)("POST", ENDPOINT, headers=headers, json=body, timeout=8.0)
    maps_http.raise_for_status(status)
    return parse_response(data, mode, traffic, now)
