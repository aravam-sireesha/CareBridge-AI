"""Live delivery tracking rules. Pure Python: no database, no web framework (tested in tests/test_tracking.py).

Principles:
* Opt-in per delivery. A volunteer starts sharing for ONE delivery, by pressing a button, and can stop at any time.
* Only the volunteer assigned to the delivery can report a position, and only while they hold the task.
* Only the LATEST position is kept, and it is deleted as soon as the delivery leaves the active stages. A movement trail exists
  ONLY if the volunteer ticked a separate consent when starting; it is kept for LOCATION_RETENTION_DAYS and read by admins only.
* The organization, donor and administrators see it only during the delivery leg (picked up / in transit), rounded to about 11 m.
* Nothing is simulated: with no fix the answer is "no position yet", and an old fix is flagged stale rather than shown as live.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from . import delivery_flow as flow
from .geo import haversine_km, is_valid_coordinate

MIN_INTERVAL_SECONDS = 5          # a phone may call far more often than anyone needs; ignore the excess
STALE_AFTER_SECONDS = 120         # older than this is shown as "last known", not "live"
MAX_ACCURACY_M = 5000.0           # a fix this vague (cell tower or IP guess) is not useful for tracking a delivery
HOLDING_STATUSES = {flow.ACCEPTED, flow.PICKUP_SCHEDULED, flow.PICKED_UP, flow.IN_TRANSIT}   # the volunteer holds the task
VIEWER_STATUSES = {flow.PICKED_UP, flow.IN_TRANSIT}                                           # others may watch only now
VIEWER_DECIMALS = 4               # about 11 metres


class TrackingError(Exception):
    """code: forbidden (403) | invalid_state (409) | invalid_input (422) | too_soon (429)."""

    def __init__(self, code: str, message: str, retry_after: int = 0):
        super().__init__(message)
        self.code, self.message, self.retry_after = code, message, retry_after


def validate_fix(lat: object, lon: object, accuracy: object = None) -> tuple[float, float, Optional[float]]:
    if not is_valid_coordinate(lat, lon):
        raise TrackingError("invalid_input", "That is not a valid position.")
    acc = None
    if accuracy is not None:
        try:
            acc = float(accuracy)
        except (TypeError, ValueError):
            raise TrackingError("invalid_input", "The accuracy must be a number of metres.") from None
        if not math.isfinite(acc) or acc < 0:
            raise TrackingError("invalid_input", "The accuracy must be a number of metres.")
        if acc > MAX_ACCURACY_M:
            raise TrackingError("invalid_input", "The position is too imprecise to use for tracking. Move to where the device gets a better signal.")
    return float(lat), float(lon), acc


def can_start(status: str, rel: Iterable[str]) -> None:
    if "assigned_volunteer" not in set(rel):
        raise TrackingError("forbidden", "Only the volunteer assigned to this delivery can share a live location for it.")
    if status not in HOLDING_STATUSES:
        raise TrackingError("invalid_state", "Live location can only be shared while you are carrying out this delivery.")


def can_view(status: str, rel: Iterable[str]) -> bool:
    rel = set(rel)
    if "assigned_volunteer" in rel:
        return status in HOLDING_STATUSES
    if rel & {"org_owner", "donor_owner", "admin"}:
        return status in VIEWER_STATUSES
    return False


def seconds_to_wait(last_recorded_at: Optional[datetime], now: datetime) -> int:
    if last_recorded_at is None:
        return 0
    return max(0, math.ceil(MIN_INTERVAL_SECONDS - (now - last_recorded_at).total_seconds()))


def age_seconds(recorded_at: Optional[datetime], now: datetime) -> Optional[int]:
    return None if recorded_at is None else max(0, int((now - recorded_at).total_seconds()))


def present(fix: Optional[dict], now: datetime, rel: Iterable[str]) -> dict:
    """What a viewer receives. `fix` = {latitude, longitude, accuracy_m, recorded_at} or None. Others get rounded coordinates."""
    if not fix or fix.get("latitude") is None or fix.get("longitude") is None:
        return {"has_position": False}
    own = "assigned_volunteer" in set(rel)
    lat, lon = (fix["latitude"], fix["longitude"]) if own else (round(fix["latitude"], VIEWER_DECIMALS), round(fix["longitude"], VIEWER_DECIMALS))
    age = age_seconds(fix.get("recorded_at"), now)
    return {"has_position": True, "latitude": lat, "longitude": lon, "accuracy_m": fix.get("accuracy_m"),
            "recorded_at": fix["recorded_at"].isoformat() if fix.get("recorded_at") else None, "age_seconds": age,
            "stale": age is None or age > STALE_AFTER_SECONDS}


def keeps_position(new_status: str) -> bool:
    """The stored position is deleted as soon as a delivery moves to a status where tracking is not allowed."""
    return new_status in HOLDING_STATUSES


# --------------------------------------------------------------------------- Phase 2: richer fixes, sessions, trail
CONSENT_VERSION = "2026-11"          # bump when the wording the volunteer agrees to changes; stored with every session
MAX_REPORTED_SPEED_MPS = 120.0       # ~430 km/h: above this a device is lying or broken
MAX_PLAUSIBLE_SPEED_MPS = 70.0       # ~250 km/h implied between two fixes: a teleport, flagged (not silently trusted)
MAX_FIX_AGE_SECONDS = 120            # a fix the device took longer ago than this is a cached position, not "now"
MAX_FUTURE_SECONDS = 60              # a device clock this far ahead is wrong or forged
DEFAULT_SESSION_HOURS = 12


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.getenv(name, "") or default)
    except ValueError:
        return default
    return max(lo, min(hi, value))


def stale_after_seconds() -> int:
    return _env_int("TRACKING_STALE_SECONDS", STALE_AFTER_SECONDS, 30, 3600)


def retention_days() -> int:
    return _env_int("LOCATION_RETENTION_DAYS", 30, 1, 365)


def history_enabled() -> bool:
    return os.getenv("TRACKING_HISTORY_ENABLED", "true").strip().lower() != "false"


def retention_cutoff(now: datetime, days: Optional[int] = None) -> datetime:
    """Trail points recorded before this moment are deleted."""
    return now - timedelta(days=retention_days() if days is None else days)


def session_expiry(now: datetime, hours: Optional[int] = None) -> datetime:
    return now + timedelta(hours=hours if hours is not None else _env_int("TRACKING_SESSION_MAX_HOURS", DEFAULT_SESSION_HOURS, 1, 48))


def session_expired(expires_at: Optional[datetime], now: datetime) -> bool:
    return expires_at is not None and now >= expires_at


def is_stale(recorded_at: Optional[datetime], now: datetime, seconds: Optional[int] = None) -> bool:
    age = age_seconds(recorded_at, now)
    return age is None or age > (seconds if seconds is not None else stale_after_seconds())


def validate_motion(heading: object = None, speed: object = None) -> tuple[Optional[float], Optional[float]]:
    """Heading in degrees [0, 360], speed in metres/second [0, MAX_REPORTED_SPEED_MPS]. None means 'not reported'."""
    def num(value, label):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise TrackingError("invalid_input", f"The {label} must be a number.")
        return float(value)
    h, v = num(heading, "heading"), num(speed, "speed")
    if h is not None and not 0 <= h <= 360:
        raise TrackingError("invalid_input", "The heading must be between 0 and 360 degrees.")
    if v is not None and not 0 <= v <= MAX_REPORTED_SPEED_MPS:
        raise TrackingError("invalid_input", "That speed is not plausible for a delivery.")
    return h, v


def client_time(timestamp_ms: object, now: datetime) -> Optional[datetime]:
    """Device timestamp (epoch milliseconds, as the browser reports it) -> naive UTC. Cached or future fixes are refused;
    None means the device did not send one (older clients), which is accepted: the SERVER clock decides freshness anyway."""
    if timestamp_ms is None:
        return None
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, (int, float)) or not math.isfinite(timestamp_ms) or timestamp_ms <= 0:
        raise TrackingError("invalid_input", "The position time is not valid.")
    try:
        taken = datetime.fromtimestamp(timestamp_ms / 1000.0, timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        raise TrackingError("invalid_input", "The position time is not valid.") from None
    if (now - taken).total_seconds() > MAX_FIX_AGE_SECONDS:
        raise TrackingError("invalid_input", "That position is out of date (the device sent an old reading). Wait for a fresh GPS fix.")
    if (taken - now).total_seconds() > MAX_FUTURE_SECONDS:
        raise TrackingError("invalid_input", "The device clock looks wrong: the position is dated in the future.")
    return taken


def is_new_sequence(last_seq: int, seq: Optional[int]) -> bool:
    """False for a re-sent or out-of-order point (seq <= the last accepted). No seq at all = an older client: accepted."""
    return seq is None or seq > last_seq


def implied_speed_mps(prev: Optional[dict], lat: float, lon: float, now: datetime) -> Optional[float]:
    """Speed needed to get from the previous stored fix to this one. None when there is nothing to compare with."""
    if not prev or prev.get("latitude") is None or prev.get("recorded_at") is None:
        return None
    seconds = (now - prev["recorded_at"]).total_seconds()
    if seconds <= 0:
        return None
    return haversine_km(prev["latitude"], prev["longitude"], lat, lon) * 1000.0 / seconds


def is_implausible_jump(prev: Optional[dict], lat: float, lon: float, now: datetime) -> bool:
    speed = implied_speed_mps(prev, lat, lon, now)
    return speed is not None and speed > MAX_PLAUSIBLE_SPEED_MPS
