"""Address search and geocoding through Google Places (New) and the Geocoding API.

* autocomplete(): type-ahead suggestions (Places API (New) "autocomplete"), restricted to India by default.
* place_location(): turn a chosen suggestion into coordinates (Places API (New) "place details", location + address only).
* geocode_address(): Geocoding API fallback for a typed address.
Configuration (environment only): GOOGLE_MAPS_SERVER_API_KEY and GOOGLE_GEOCODING_ENABLED=true. The key must be restricted by server IP
and to the Places and Geocoding APIs.

The results are for the signed-in person to place THEIR OWN organization/home area or to search the map; nothing here stores them.
LIVE USE IS UNTESTED here (no credentials); tests use a fake transport.
"""
from __future__ import annotations

import re
from typing import Mapping, Optional

from . import maps_http
from .geo import is_valid_coordinate
from .maps_http import MapsError

AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_PLACE_ID = re.compile(r"^[A-Za-z0-9_\-]{10,300}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")


def enabled(env: Mapping[str, str]) -> bool:
    return str(env.get("GOOGLE_GEOCODING_ENABLED", "")).strip().lower() == "true" and bool((env.get("GOOGLE_MAPS_SERVER_API_KEY") or "").strip())


def clean_query(value: object, lo: int = 2, hi: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if not (lo <= len(text) <= hi) or any(ord(c) < 32 for c in text):
        raise MapsError("invalid", f"Type between {lo} and {hi} characters to search.")
    return text


def _require(env: Mapping[str, str]) -> str:
    if not enabled(env):
        raise MapsError("not_configured", "Address search is not set up on this server. You can type the coordinates instead.")
    return env["GOOGLE_MAPS_SERVER_API_KEY"].strip()


def parse_suggestions(data: object, limit: int = 6) -> list[dict]:
    out = []
    for item in (data.get("suggestions") if isinstance(data, dict) else None) or []:
        p = item.get("placePrediction") if isinstance(item, dict) else None
        if not isinstance(p, dict) or not _PLACE_ID.match(str(p.get("placeId") or "")):
            continue
        fmt = p.get("structuredFormat") or {}
        out.append({"place_id": p["placeId"], "text": str((p.get("text") or {}).get("text") or "")[:200],
                    "main_text": str((fmt.get("mainText") or {}).get("text") or "")[:120],
                    "secondary_text": str((fmt.get("secondaryText") or {}).get("text") or "")[:160]})
        if len(out) >= limit:
            break
    return out


def autocomplete(query: str, env: Mapping[str, str], session_token: Optional[str] = None, bias: Optional[tuple[float, float]] = None,
                 transport=None, region: str = "in") -> list[dict]:
    key = _require(env)
    body: dict = {"input": clean_query(query), "includedRegionCodes": [region]}
    if session_token:
        if not _TOKEN.match(session_token):
            raise MapsError("invalid", "Invalid search session.")
        body["sessionToken"] = session_token                      # groups keystrokes + the final pick into one billed session
    if bias and is_valid_coordinate(*bias):
        body["locationBias"] = {"circle": {"center": {"latitude": bias[0], "longitude": bias[1]}, "radius": 50000.0}}
    status, data = (transport or maps_http.request)("POST", AUTOCOMPLETE_URL, headers={"Content-Type": "application/json", "X-Goog-Api-Key": key}, json=body, timeout=6.0)
    maps_http.raise_for_status(status)
    return parse_suggestions(data)


def parse_place(data: object) -> dict:
    loc = (data.get("location") if isinstance(data, dict) else None) or {}
    lat, lon = loc.get("latitude"), loc.get("longitude")
    numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon))
    if not (numeric and is_valid_coordinate(lat, lon)):
        raise MapsError("no_route", "That place has no usable location.")
    return {"latitude": float(lat), "longitude": float(lon), "address": str(data.get("formattedAddress") or "")[:300],
            "name": str((data.get("displayName") or {}).get("text") or "")[:160]}


def place_location(place_id: str, env: Mapping[str, str], session_token: Optional[str] = None, transport=None) -> dict:
    key = _require(env)
    if not _PLACE_ID.match(place_id or ""):
        raise MapsError("invalid", "Invalid place.")
    params = {"sessionToken": session_token} if session_token and _TOKEN.match(session_token) else None
    status, data = (transport or maps_http.request)("GET", DETAILS_URL.format(place_id=place_id), headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": "location,formattedAddress,displayName"}, params=params, timeout=6.0)
    maps_http.raise_for_status(status)
    return parse_place(data)


def geocode_address(address: str, env: Mapping[str, str], transport=None, region: str = "in") -> dict:
    key = _require(env)
    status, data = (transport or maps_http.request)("GET", GEOCODE_URL, params={"address": clean_query(address, 3, 200), "region": region, "key": key}, timeout=6.0)
    maps_http.raise_for_status(status)
    results = data.get("results") if isinstance(data, dict) else None
    if not results or data.get("status") != "OK":
        if isinstance(data, dict) and data.get("status") in ("OVER_QUERY_LIMIT", "REQUEST_DENIED"):
            raise MapsError("rejected" if data["status"] == "REQUEST_DENIED" else "unavailable", "The map service could not process that search.")
        raise MapsError("no_route", "No place was found for that address.")
    first = results[0]
    return parse_place({"location": {"latitude": ((first.get("geometry") or {}).get("location") or {}).get("lat"),
                                     "longitude": ((first.get("geometry") or {}).get("location") or {}).get("lng")},
                        "formattedAddress": first.get("formatted_address"), "displayName": {"text": ""}})
