"""Availability and carrying capacity: pure Python. Run with:  python -m pytest tests/test_availability.py -q"""
from datetime import datetime, timedelta

from app.services import availability as av

# 2026-10-26 is a Monday. India (Asia/Kolkata) is UTC+5:30, so 10:00 UTC is 15:30 local.
MON_10_UTC = datetime(2026, 10, 26, 10, 0)
SLOTS = [{"weekday": 0, "start": "09:00", "end": "17:00"}, {"weekday": 5, "start": "10:00", "end": "14:00"}]


def err(fn, *a):
    try:
        fn(*a)
    except av.AvailabilityError as e:
        return str(e)
    raise AssertionError("expected AvailabilityError")


def test_valid_schedules_are_normalised_and_sorted():
    out = av.validate_slots([{"weekday": 5, "start": "9:30", "end": "13:00"}, {"weekday": 0, "start": "09:00", "end": "17:00"}])
    assert out == [{"weekday": 0, "start": "09:00", "end": "17:00"}, {"weekday": 5, "start": "09:30", "end": "13:00"}]
    assert av.validate_slots(None) == [] and av.validate_slots([]) == []


def test_invalid_slots_get_specific_messages():
    assert "choose a weekday" in err(av.validate_slots, [{"weekday": 7, "start": "09:00", "end": "10:00"}])
    assert "choose a weekday" in err(av.validate_slots, [{"weekday": True, "start": "09:00", "end": "10:00"}])
    assert "24-hour" in err(av.validate_slots, [{"weekday": 1, "start": "25:00", "end": "26:00"}])
    assert "24-hour" in err(av.validate_slots, [{"weekday": 1, "start": "9", "end": "10:00"}])
    assert "end must be after the start" in err(av.validate_slots, [{"weekday": 1, "start": "18:00", "end": "09:00"}])
    assert "two slots" in err(av.validate_slots, [{"weekday": 1, "start": "22:00", "end": "02:00"}])          # overnight is explained, not silently guessed
    assert "at least 15 minutes" in err(av.validate_slots, [{"weekday": 1, "start": "09:00", "end": "09:10"}])
    assert "list of time slots" in err(av.validate_slots, "weekends")
    assert "Slot 1 is not valid" in err(av.validate_slots, ["x"])
    assert "28" in err(av.validate_slots, [{"weekday": i % 7, "start": f"{i % 7:02d}:00", "end": f"{i % 7:02d}:30"} for i in range(29)])


def test_overlapping_slots_on_one_day_are_refused_but_adjacent_ones_are_fine():
    assert "overlap" in err(av.validate_slots, [{"weekday": 2, "start": "09:00", "end": "12:00"}, {"weekday": 2, "start": "11:00", "end": "14:00"}])
    assert len(av.validate_slots([{"weekday": 2, "start": "09:00", "end": "12:00"}, {"weekday": 2, "start": "12:00", "end": "14:00"}])) == 2
    assert len(av.validate_slots([{"weekday": 2, "start": "09:00", "end": "12:00"}, {"weekday": 3, "start": "09:00", "end": "12:00"}])) == 2


def test_profile_fields():
    assert av.validate_profile("Asia/Kolkata", "Car", "120") == ("Asia/Kolkata", "car", 120.0)
    assert av.validate_profile(None, None, None) == (None, None, None) and av.validate_profile("", "", "") == (None, None, None)
    assert "not recognised" in err(av.validate_profile, "Mars/Olympus", None, None)
    assert "Choose how you travel" in err(av.validate_profile, None, "teleport", None)
    for bad in ("heavy", 0, -5, 99999, True, float("nan")):
        assert "Capacity" in err(av.validate_profile, None, None, bad), bad


def test_availability_is_judged_in_the_volunteers_own_timezone():
    assert av.is_available(SLOTS, "Asia/Kolkata", MON_10_UTC) is True                      # 15:30 Monday in India
    assert av.is_available(SLOTS, "Asia/Kolkata", datetime(2026, 10, 26, 12, 0)) is False  # 17:30 local: after the slot
    assert av.is_available(SLOTS, "Asia/Kolkata", datetime(2026, 10, 26, 3, 30)) is True   # 09:00 local, the slot's first minute
    assert av.is_available(SLOTS, "Asia/Kolkata", datetime(2026, 10, 26, 11, 30)) is False  # 17:00 local, the end is exclusive
    assert av.is_available(SLOTS, "America/New_York", MON_10_UTC) is False                 # 06:00 in New York: same instant, different answer


def test_the_date_changes_with_the_timezone():
    sunday_night_utc = datetime(2026, 10, 25, 20, 0)                                       # Sunday 20:00 UTC = Monday 01:30 in India
    mon_early = [{"weekday": 0, "start": "00:00", "end": "06:00"}]
    assert av.is_available(mon_early, "Asia/Kolkata", sunday_night_utc) is True
    assert av.is_available(mon_early, "UTC", sunday_night_utc) is False


def test_no_schedule_or_an_unreadable_timezone_means_unknown_never_free():
    assert av.is_available([], "Asia/Kolkata", MON_10_UTC) is None and av.is_available(None, None, MON_10_UTC) is None
    assert av.is_available(SLOTS, "Not/AZone", MON_10_UTC) is None


def test_capacity_status():
    assert av.capacity_status(20, 50) == "ok" and av.capacity_status(50, 50) == "ok" and av.capacity_status(51, 50) == "exceeds"
    assert av.capacity_status(None, 50) == "unknown" and av.capacity_status(20, None) == "unknown" and av.capacity_status(0, 50) == "unknown"


def test_conflicting_pickups_within_two_hours_are_found():
    base = datetime(2026, 10, 26, 10, 0)
    assert av.has_conflict([base + timedelta(minutes=90)], base) == base + timedelta(minutes=90)
    assert av.has_conflict([base - timedelta(minutes=119)], base) is not None
    assert av.has_conflict([base + timedelta(minutes=120)], base) is None                  # exactly the window apart is allowed
    assert av.has_conflict([None, base + timedelta(days=1)], base) is None and av.has_conflict([], base) is None


def test_assessment_excludes_only_on_declared_facts():
    inside = av.assess(SLOTS, "Asia/Kolkata", 60.0, MON_10_UTC, 40.0)
    assert not inside["exclude"] and inside["available"] is True and inside["capacity"] == "ok" and len(inside["reasons"]) == 2
    outside = av.assess(SLOTS, "Asia/Kolkata", 60.0, datetime(2026, 10, 26, 12, 0), 40.0)
    assert outside["exclude"] and outside["available"] is False
    heavy = av.assess(SLOTS, "Asia/Kolkata", 30.0, MON_10_UTC, 40.0)
    assert heavy["exclude"] and heavy["capacity"] == "exceeds" and "above the 30 kg" in heavy["reasons"][-1]
    unknown = av.assess(None, None, None, MON_10_UTC, 40.0)
    assert not unknown["exclude"] and unknown["available"] is None and unknown["capacity"] == "unknown" and all("not stated" in r for r in unknown["reasons"])
    assert av.assess(SLOTS, "Asia/Kolkata", None) == {"available": None, "capacity": "unknown", "exclude": False, "reasons": []}   # nothing asked, nothing said


def test_capacity_reasons_say_it_is_self_declared():
    assert "self-declared, not verified" in av.assess(None, None, 60.0, None, 40.0)["reasons"][0]


def test_free_text_is_only_ever_suggested_and_says_so():
    s = av.suggest_from_text("weekends")
    assert [x["weekday"] for x in s["slots"]] == [5, 6] and s["slots"][0]["start"] == "09:00" and "Nothing is saved until you confirm" in s["note"] and "no time of day" in s["note"]
    e = av.suggest_from_text("weekday evenings")
    assert [x["weekday"] for x in e["slots"]] == [0, 1, 2, 3, 4] and e["slots"][0] == {"weekday": 0, "start": "17:00", "end": "21:00"} and "no time of day" not in e["note"]
    assert [x["weekday"] for x in av.suggest_from_text("Sat mornings and Wed")["slots"]] == [2, 5]
    assert len(av.suggest_from_text("full time")["slots"]) == 7 and len(av.suggest_from_text("anytime, flexible")["slots"]) == 7
    for nothing in ("", None, "sometimes", "unavailable", "none", "weekends unavailable"):
        assert av.suggest_from_text(nothing)["slots"] == [], nothing


def test_every_suggestion_passes_the_same_validation_a_person_would_face():
    for text in ("weekends", "weekday evenings", "Sat mornings and Wed", "full time", "afternoons on Monday"):
        assert av.validate_slots(av.suggest_from_text(text)["slots"]), text
