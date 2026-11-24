"""Phase 2 GPS rules: invalid coordinates, stale/future/cached fixes, duplicate sequences, spoofed jumps, expiry and retention."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import tracking as t

NOW = datetime(2026, 11, 5, 10, 0, 0)


def ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


# ---------------------------------------------------------------- invalid coordinates (existing rule, asserted again at the edges)
@pytest.mark.parametrize("lat,lon", [(91, 0), (-91, 0), (0, 181), (0, -181), (float("nan"), 0), (0, float("inf")), ("x", 1), (None, None), (True, 1)])
def test_invalid_coordinates_are_rejected(lat, lon):
    with pytest.raises(t.TrackingError):
        t.validate_fix(lat, lon)


@pytest.mark.parametrize("acc", [-1, float("nan"), "abc", 5001])
def test_invalid_accuracy_is_rejected(acc):
    with pytest.raises(t.TrackingError):
        t.validate_fix(17.4, 78.4, acc)


# ---------------------------------------------------------------- heading / speed
def test_valid_motion_passes_through_and_none_means_not_reported():
    assert t.validate_motion(90, 4.5) == (90.0, 4.5)
    assert t.validate_motion(None, None) == (None, None)
    assert t.validate_motion(0, 0) == (0.0, 0.0) and t.validate_motion(360, 120) == (360.0, 120.0)


@pytest.mark.parametrize("heading,speed", [(-1, None), (361, None), (None, -0.1), (None, 121), ("90", None), (None, True), (float("nan"), None), (None, float("inf"))])
def test_invalid_motion_is_rejected(heading, speed):
    with pytest.raises(t.TrackingError):
        t.validate_motion(heading, speed)


# ---------------------------------------------------------------- device timestamp
def test_fresh_device_time_is_accepted_and_converted_to_naive_utc():
    taken = NOW - timedelta(seconds=5)
    assert t.client_time(ms(taken), NOW) == taken


def test_missing_device_time_is_allowed_for_older_clients():
    assert t.client_time(None, NOW) is None


def test_cached_old_fix_is_refused():
    with pytest.raises(t.TrackingError, match="out of date"):
        t.client_time(ms(NOW - timedelta(seconds=t.MAX_FIX_AGE_SECONDS + 5)), NOW)


def test_future_dated_fix_is_refused():
    with pytest.raises(t.TrackingError, match="clock"):
        t.client_time(ms(NOW + timedelta(seconds=t.MAX_FUTURE_SECONDS + 5)), NOW)


def test_small_clock_skew_is_tolerated():
    assert t.client_time(ms(NOW + timedelta(seconds=10)), NOW) is not None


@pytest.mark.parametrize("bad", [0, -5, True, "1700000000000", float("nan"), 1e30])
def test_nonsense_device_time_is_refused(bad):
    with pytest.raises(t.TrackingError):
        t.client_time(bad, NOW)


# ---------------------------------------------------------------- duplicate protection
def test_sequence_numbers_must_increase():
    assert t.is_new_sequence(-1, 0) and t.is_new_sequence(4, 5)
    assert not t.is_new_sequence(5, 5)                    # the same point re-sent after a network retry
    assert not t.is_new_sequence(5, 3)                    # an old point arriving late
    assert t.is_new_sequence(5, None)                     # older client without seq


# ---------------------------------------------------------------- spoofed / glitched jumps
PREV = {"latitude": 17.3850, "longitude": 78.4867, "recorded_at": NOW - timedelta(seconds=10)}


def test_walking_pace_is_plausible():
    assert not t.is_implausible_jump(PREV, 17.38505, 78.48675, NOW)


def test_road_speed_is_plausible():
    # ~0.2 km in 10 s = ~20 m/s (72 km/h)
    assert not t.is_implausible_jump(PREV, 17.3868, 78.4867, NOW)


def test_teleporting_across_the_city_is_flagged():
    # Hyderabad -> Secunderabad-ish ~ 8 km in 10 s
    assert t.is_implausible_jump(PREV, 17.4400, 78.4983, NOW)


def test_no_previous_fix_means_nothing_to_flag():
    assert not t.is_implausible_jump(None, 10.0, 10.0, NOW)
    assert not t.is_implausible_jump({"latitude": None, "recorded_at": None}, 10.0, 10.0, NOW)


def test_zero_or_negative_elapsed_time_cannot_cause_a_division_error():
    same_instant = {"latitude": 17.0, "longitude": 78.0, "recorded_at": NOW}
    assert t.implied_speed_mps(same_instant, 17.1, 78.1, NOW) is None


# ---------------------------------------------------------------- stale detection
def test_stale_is_decided_by_server_time_and_configurable(monkeypatch):
    assert not t.is_stale(NOW - timedelta(seconds=30), NOW)
    assert t.is_stale(NOW - timedelta(seconds=300), NOW)
    assert t.is_stale(None, NOW)
    monkeypatch.setenv("TRACKING_STALE_SECONDS", "600")
    assert not t.is_stale(NOW - timedelta(seconds=300), NOW)
    monkeypatch.setenv("TRACKING_STALE_SECONDS", "banana")
    assert t.stale_after_seconds() == t.STALE_AFTER_SECONDS     # a bad setting falls back, never crashes


# ---------------------------------------------------------------- sessions, retention
def test_session_expires_after_the_configured_duration(monkeypatch):
    exp = t.session_expiry(NOW)
    assert exp == NOW + timedelta(hours=12)
    assert not t.session_expired(exp, NOW + timedelta(hours=11)) and t.session_expired(exp, exp)
    assert not t.session_expired(None, NOW)
    monkeypatch.setenv("TRACKING_SESSION_MAX_HOURS", "2")
    assert t.session_expiry(NOW) == NOW + timedelta(hours=2)


def test_retention_defaults_are_bounded(monkeypatch):
    assert t.retention_days() == 30
    monkeypatch.setenv("LOCATION_RETENTION_DAYS", "0")
    assert t.retention_days() == 1                          # can never be configured to "keep forever" or "0"
    monkeypatch.setenv("LOCATION_RETENTION_DAYS", "100000")
    assert t.retention_days() == 365
    monkeypatch.setenv("LOCATION_RETENTION_DAYS", "7")
    assert t.retention_cutoff(NOW) == NOW - timedelta(days=7)


def test_history_can_be_switched_off_entirely(monkeypatch):
    assert t.history_enabled() is True
    monkeypatch.setenv("TRACKING_HISTORY_ENABLED", "false")
    assert t.history_enabled() is False
