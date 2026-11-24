"""Live tracking rules: pure Python. Run with:  python -m pytest tests/test_tracking.py -q"""
from datetime import datetime, timedelta

from app.services import delivery_flow as f
from app.services import tracking as t

NOW = datetime(2026, 10, 26, 12, 0, 0)


def raises(code, fn, *a):
    try:
        fn(*a)
    except t.TrackingError as e:
        assert e.code == code, (e.code, e.message)
        return e
    raise AssertionError("expected TrackingError " + code)


def test_valid_fixes_pass_and_invalid_ones_do_not():
    assert t.validate_fix(17.385, 78.4867, 12) == (17.385, 78.4867, 12.0)
    assert t.validate_fix("17.385", "78.4867") == (17.385, 78.4867, None)
    for bad in [(None, 1), (91, 0), (0, 0), ("x", 1), (float("nan"), 1), (True, 1)]:
        raises("invalid_input", t.validate_fix, *bad)


def test_accuracy_must_be_a_sane_number_of_metres():
    for bad in ("x", -1, float("inf"), float("nan")):
        raises("invalid_input", t.validate_fix, 17.4, 78.4, bad)
    e = raises("invalid_input", t.validate_fix, 17.4, 78.4, 20000)
    assert "imprecise" in e.message
    assert t.validate_fix(17.4, 78.4, 0)[2] == 0.0


def test_only_the_assigned_volunteer_can_start_and_only_while_holding_the_task():
    for status in t.HOLDING_STATUSES:
        t.can_start(status, {"assigned_volunteer"})
    for who in ({"org_owner"}, {"donor_owner"}, {"admin"}, set()):
        raises("forbidden", t.can_start, f.ACCEPTED, who)
    for status in (f.OFFERED, f.COMMITTED, f.DELIVERED, f.RECEIPT_CONFIRMED, f.CANCELLED, f.EXCEPTION, f.PROPOSED):
        raises("invalid_state", t.can_start, status, {"assigned_volunteer"})


def test_others_can_watch_only_during_the_delivery_leg():
    for who in ({"org_owner"}, {"donor_owner"}, {"admin"}):
        assert t.can_view(f.PICKED_UP, who) and t.can_view(f.IN_TRANSIT, who)
        for status in (f.ACCEPTED, f.PICKUP_SCHEDULED, f.DELIVERED, f.RECEIPT_CONFIRMED, f.CANCELLED, f.EXCEPTION, f.OFFERED, f.COMMITTED):
            assert not t.can_view(status, who), (who, status)


def test_the_volunteer_sees_their_own_position_while_holding_the_task_and_strangers_never_do():
    for status in t.HOLDING_STATUSES:
        assert t.can_view(status, {"assigned_volunteer"})
    assert not t.can_view(f.DELIVERED, {"assigned_volunteer"})
    for status in f.STATUSES:
        assert not t.can_view(status, set())


def test_updates_faster_than_the_minimum_interval_are_refused_with_a_wait_time():
    assert t.seconds_to_wait(None, NOW) == 0
    assert t.seconds_to_wait(NOW, NOW) == 5
    assert t.seconds_to_wait(NOW - timedelta(seconds=3, milliseconds=200), NOW) == 2
    assert t.seconds_to_wait(NOW - timedelta(seconds=5), NOW) == 0
    assert t.seconds_to_wait(NOW - timedelta(minutes=5), NOW) == 0


def test_a_missing_position_is_reported_as_none_never_invented():
    assert t.present(None, NOW, {"org_owner"}) == {"has_position": False}
    assert t.present({"latitude": None, "longitude": None}, NOW, {"admin"}) == {"has_position": False}


def test_freshness_and_staleness_are_computed_from_the_server_clock():
    fresh = {"latitude": 17.38512, "longitude": 78.48671, "accuracy_m": 9.0, "recorded_at": NOW - timedelta(seconds=30)}
    assert t.present(fresh, NOW, {"admin"})["stale"] is False and t.present(fresh, NOW, {"admin"})["age_seconds"] == 30
    old = dict(fresh, recorded_at=NOW - timedelta(seconds=121))
    assert t.present(old, NOW, {"admin"})["stale"] is True
    edge = dict(fresh, recorded_at=NOW - timedelta(seconds=120))
    assert t.present(edge, NOW, {"admin"})["stale"] is False
    future = dict(fresh, recorded_at=NOW + timedelta(seconds=30))     # a skewed clock must not produce a negative age
    assert t.present(future, NOW, {"admin"})["age_seconds"] == 0


def test_other_people_see_a_rounded_position_and_the_volunteer_sees_their_own_exactly():
    fix = {"latitude": 17.385129, "longitude": 78.486718, "accuracy_m": 8.0, "recorded_at": NOW}
    seen = t.present(fix, NOW, {"org_owner"})
    assert (seen["latitude"], seen["longitude"]) == (17.3851, 78.4867)
    own = t.present(fix, NOW, {"assigned_volunteer"})
    assert (own["latitude"], own["longitude"]) == (17.385129, 78.486718)


def test_the_position_is_kept_only_while_the_volunteer_holds_the_task():
    for status in t.HOLDING_STATUSES:
        assert t.keeps_position(status)
    for status in (f.DELIVERED, f.RECEIPT_CONFIRMED, f.CANCELLED, f.EXCEPTION, f.COMMITTED, f.OFFERED, f.REJECTED):
        assert not t.keeps_position(status), status
