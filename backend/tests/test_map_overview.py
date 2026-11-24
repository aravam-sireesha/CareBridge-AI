"""Pure rules behind the administrator map (no database, no web framework). Run with:  python -m pytest tests/test_map_overview.py -q"""
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

from app.services import geo, map_overview as mo

NOW = datetime(2026, 11, 4, 12, 0, 0)
HYD = (17.385, 78.4867)


def org(i, lat=HYD[0], lon=HYD[1], verified=True):
    return NS(id=i, name=f"Org {i}", verified=verified, verification_status="verified" if verified else "pending", address=None, latitude=lat, longitude=lon)


def need(i, org_id=1, urgency="medium", status="open", lat=None, lon=None):
    return NS(id=i, org_id=org_id, title=f"Need {i}", category="food", urgency=urgency, status=status, quantity=3, latitude=lat, longitude=lon)


def person(i, lat=None, lon=None, radius=None):
    return NS(id=i, name=f"P{i}", organization_id=None, latitude=lat, longitude=lon, service_radius_km=radius)


def test_approx_position_snaps_to_the_requested_grid():
    assert geo.approx_position(17.391234, 78.481234) == {"lat": 17.39, "lon": 78.48}
    assert geo.approx_position(17.391234, 78.481234, 4) == {"lat": 17.3912, "lon": 78.4812}


def test_records_without_a_position_are_counted_not_placed():
    out = mo.build_overview([org(1), org(2, None, None)], [need(1, 2)], [person(1)], [person(2)], [], None, NOW)
    assert [o["id"] for o in out["organizations"]] == [1]
    assert out["needs"] == [] and out["unplaced"] == {"organizations": 1, "needs": 1, "donors": 1, "volunteers": 1}


def test_closed_needs_are_left_out_and_a_need_uses_its_organizations_place():
    out = mo.build_overview([org(1)], [need(1), need(2, status="closed"), need(3, status="pending")], [], [], [], None, NOW)
    assert {n["id"] for n in out["needs"]} == {1, 3}
    assert out["needs"][0]["located_via"] == "organization"


def test_people_are_snapped_and_organizations_are_not():
    out = mo.build_overview([org(1, 17.385123, 78.486789)], [], [person(1, 17.391234, 78.481234)], [person(2, 17.395678, 78.485678, 20)], [], None, NOW)
    assert out["organizations"][0]["position"] == {"lat": 17.3851, "lon": 78.4868}
    assert out["donors"][0]["position"] == {"lat": 17.39, "lon": 78.48}
    assert out["volunteers"][0]["position"] == {"lat": 17.4, "lon": 78.49} and out["volunteers"][0]["service_radius_km"] == 20


def test_a_volunteer_outside_their_own_travel_range_does_not_close_the_gap():
    far_enough = person(1, 17.45, 78.55, radius=2)           # ~10 km away but only willing to go 2 km
    willing = person(2, 17.45, 78.55, radius=30)
    assert mo.build_overview([org(1)], [need(1)], [], [far_enough], [], 50, NOW)["gaps"][0]["need_id"] == 1
    assert mo.build_overview([org(1)], [need(1)], [], [willing], [], 50, NOW)["gaps"] == []


def test_the_search_radius_decides_who_counts_and_gaps_sort_by_urgency():
    vol = person(1, 17.45, 78.55)                             # ~10 km
    wide = mo.build_overview([org(1)], [need(1)], [], [vol], [], 25, NOW)
    narrow = mo.build_overview([org(1)], [need(1, urgency="low"), need(2, urgency="high"), need(3, urgency="critical")], [], [vol], [], 5, NOW)
    assert wide["gaps"] == [] and wide["needs"][0]["volunteers_in_range"] == 1
    assert [g["need_id"] for g in narrow["gaps"]] == [3, 2, 1]
    assert narrow["gaps"][0]["nearest_volunteer_km"] >= 9


def test_live_deliveries_follow_the_tracking_rules():
    fresh = {"task_id": 1, "status": "in_transit", "latitude": 17.385123, "longitude": 78.486789, "accuracy_m": 8, "recorded_at": NOW - timedelta(seconds=10)}
    old = {**fresh, "task_id": 2, "recorded_at": NOW - timedelta(minutes=10)}
    not_allowed = {**fresh, "task_id": 3, "status": "accepted"}           # the volunteer has not collected it yet
    no_fix = {**fresh, "task_id": 4, "latitude": None, "longitude": None}
    out = mo.build_overview([], [], [], [], [fresh, old, not_allowed, no_fix], None, NOW)["live_deliveries"]
    assert [d["task_id"] for d in out] == [1, 2]
    assert out[0]["position"] == {"lat": 17.3851, "lon": 78.4868} and out[0]["stale"] is False and out[1]["stale"] is True
