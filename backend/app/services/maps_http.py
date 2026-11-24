"""One tiny seam for outbound HTTP to Google Maps Platform, so adapters can be unit-tested without a network or a key.

`post/get(...)` return (status_code, parsed_json_or_None). They never raise for HTTP errors, and they NEVER log URLs or headers
(a Geocoding request carries the API key in its query string). Only the status code and the exception class are logged.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

Transport = Callable[..., tuple[int, Any]]


class MapsError(Exception):
    """code: not_configured | unavailable | rejected | no_route | invalid"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _request(method: str, url: str, headers: Optional[dict] = None, json: Any = None, params: Optional[dict] = None, timeout: float = 8.0) -> tuple[int, Any]:
    import httpx                                   # lazy: the module stays importable (and testable) without the library

    try:
        with httpx.Client(timeout=timeout) as client:
            res = client.request(method, url, headers=headers, json=json, params=params)
    except httpx.HTTPError as exc:
        logger.warning("Maps request failed (%s)", type(exc).__name__)
        raise MapsError("unavailable", "The map service is not reachable right now. Please try again shortly.") from None
    try:
        data = res.json()
    except ValueError:
        data = None
    if res.status_code >= 400:
        logger.warning("Maps request returned HTTP %s", res.status_code)
    return res.status_code, data


def request(method: str, url: str, **kwargs) -> tuple[int, Any]:
    return _request(method, url, **kwargs)


def raise_for_status(status: int) -> None:
    if status == 429 or status >= 500:
        raise MapsError("unavailable", "The map service is busy. Please try again shortly.")
    if status in (400, 404):
        raise MapsError("no_route", "No result was found for that request.")
    if status >= 400:                              # 401/403: key missing, restricted to other IPs, or API not enabled: an operator problem
        raise MapsError("rejected", "The map service refused the request. An administrator needs to check the Google Maps configuration.")
