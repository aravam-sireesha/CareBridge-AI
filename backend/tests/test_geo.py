"""Location maths and privacy rules. Pure Python, no database. Run with:  python -m pytest tests/test_geo.py -q"""
import math
import os
from types import SimpleNamespace as NS

from app.services import geo

LONDON, PARIS = (51.5074, -0.1278), (48.8566, 2.3522)
DELHI, MUMBAI = (28.6139, 77.2090), (19.0760, 72.8777)


def _need(i, lat=None, lon=None, **kw):
    return NS(id=i, latitude=lat, longitude=lon, title=kw.get("title"), category=kw.get("category", "Books"), urgency="high", quantity=5)


def _person(i, lat=None, lon=None, radius=None, name=None):
    return NS(id=i, name=name or f"P{i}", latitude=lat, longitude=lon, service_radius_km=radius)


# ------------------------------------------------------------------ validation
def test_valid_and_invalid_coordinates():
    assert geo.is_valid_coordinate(14.4673, 78.8242)
    assert geo.is_valid_coordinate("14.4673", "78.8242")          # numeric strings are accepted
    assert geo.is_valid_coordinate(-90, 180) and geo.is_valid_coordinate(90, -180)
    for bad in [(None, 1), (1, None), ("x", 1), (91, 0.5), (-91, 0.5), (1, 181), (1, -181),
                (float("nan"), 1), (1, float("inf")), (True, 1), (0, 0), (0.0, 0.0)]:
        assert not geo.is_valid_coordinate(*bad), bad


def test_origin_of_the_grid_is_treated_as_missing_but_the_equator_is_not():
    assert not geo.is_valid_coordinate(0, 0)
    assert geo.is_valid_coordinate(0, 10) and geo.is_valid_coordinate(10, 0)


# ------------------------------------------------------------------ distance
def test_haversine_matches_known_city_distances():
    assert abs(geo.haversine_km(*LONDON, *PARIS) - 343.5) < 3.5       # about 343.5 km
    assert abs(geo.haversine_km(*DELHI, *MUMBAI) - 1148) < 12        # about 1148 km


def test_haversine_zero_symmetric_and_antipodal_does_not_crash():
    assert geo.haversine_km(10, 20, 10, 20) == 0
    assert math.isclose(geo.haversine_km(*LONDON, *PARIS), geo.haversine_km(*PARIS, *LONDON))
    assert 20000 < geo.haversine_km(0, 10, 0, -170) < 20100            # half the Earth's circumference


def test_coarse_distance_rounds_up_and_never_says_zero():
    assert geo.coarse_distance(0.0) == (1, "within 1 km")
    assert geo.coarse_distance(0.2) == (1, "within 1 km")
    assert geo.coarse_distance(1.0) == (1, "within 1 km")
    assert geo.coarse_distance(1.01) == (2, "within 2 km")
    assert geo.coarse_distance(4.2) == (5, "within 5 km")


# ------------------------------------------------------------------ radius
def test_default_radius_is_configurable_and_clamped():
    old = os.environ.get("GEO_DEFAULT_RADIUS_KM")
    try:
        os.environ.pop("GEO_DEFAULT_RADIUS_KM", None)
        assert geo.default_radius_km() == 25.0
        os.environ["GEO_DEFAULT_RADIUS_KM"] = "40"
        assert geo.default_radius_km() == 40.0
        os.environ["GEO_DEFAULT_RADIUS_KM"] = "99999"
        assert geo.default_radius_km() == geo.MAX_RADIUS_KM
        os.environ["GEO_DEFAULT_RADIUS_KM"] = "-3"
        assert geo.default_radius_km() == 1.0
        os.environ["GEO_DEFAULT_RADIUS_KM"] = "banana"
        assert geo.default_radius_km() == 25.0
    finally:
        if old is None:
            os.environ.pop("GEO_DEFAULT_RADIUS_KM", None)
        else:
            os.environ["GEO_DEFAULT_RADIUS_KM"] = old


def test_clamp_radius():
    assert geo.clamp_radius(10) == 10
    assert geo.clamp_radius(10_000) == geo.MAX_RADIUS_KM
    for bad in (None, 0, -5, "x", float("nan")):
        assert geo.clamp_radius(bad) == geo.default_radius_km()


# ------------------------------------------------------------------ need position
def test_need_position_falls_back_to_the_organization_and_says_which():
    org = NS(latitude=17.385, longitude=78.4867)
    assert geo.need_point(_need(1, 17.4, 78.5), org).source == "need"
    assert geo.need_point(_need(1), org).source == "organization"
    assert geo.need_point(_need(1), NS(latitude=None, longitude=None)) is None
    assert geo.need_point(_need(1, 0, 0), None) is None               # (0, 0) is "no data"


# ------------------------------------------------------------------ nearby needs (donor / volunteer view)
ORIGIN = geo.Point(17.385, 78.4867, "profile")


def test_nearby_needs_are_filtered_by_radius_and_sorted_nearest_first():
    near = _need(1, 17.39, 78.49)      # ~0.7 km
    mid = _need(2, 17.45, 78.55)       # ~10 km
    far = _need(3, 18.9, 79.9)         # ~220 km
    org = NS(name="Hope Home", latitude=None, longitude=None)
    out = geo.rank_nearby_needs([(far, org), (mid, org), (near, org)], ORIGIN, radius_km=25)
    assert [n["need_id"] for n in out] == [1, 2]
    assert out[0]["distance_label"] == "within 1 km" and out[1]["distance_km"] >= 9


def test_nearby_needs_skip_unplaceable_ones_and_use_organization_fallback():
    org_located = NS(name="A", latitude=17.39, longitude=78.49)
    org_unlocated = NS(name="B", latitude=None, longitude=None)
    out = geo.rank_nearby_needs([(_need(1), org_located), (_need(2), org_unlocated)], ORIGIN, 25)
    assert [n["need_id"] for n in out] == [1] and out[0]["distance_basis"] == "organization"


def test_nearby_needs_never_return_coordinates_or_addresses():
    need = _need(1, 17.39, 78.49)
    need.location = "12 Private Lane"
    out = geo.rank_nearby_needs([(need, NS(name="A", latitude=17.39, longitude=78.49, address="x"))], ORIGIN, 25)
    flat = repr(out).lower()
    assert "latitude" not in flat and "longitude" not in flat and "private lane" not in flat and "17.39" not in flat


def test_nearby_needs_respect_the_limit():
    org = NS(name="A", latitude=None, longitude=None)
    rows = [(_need(i, 17.385 + i * 0.001, 78.4867), org) for i in range(1, 10)]
    assert len(geo.rank_nearby_needs(rows, ORIGIN, 25, limit=3)) == 3
    assert geo.rank_nearby_needs(rows, ORIGIN, 25, limit=0) == []


# ------------------------------------------------------------------ nearby people (organization / admin view)
def test_nearby_people_counts_the_unlocated_and_flags_service_radius():
    people = [_person(1, 17.39, 78.49, radius=5), _person(2, 17.45, 78.55, radius=2), _person(3), _person(4, 18.9, 79.9)]
    out, unlocated = geo.rank_nearby_people(ORIGIN, people, "volunteer", radius_km=25)
    assert [p["id"] for p in out] == [1, 2] and unlocated == 1
    assert out[0]["within_service_radius"] is True and out[1]["within_service_radius"] is False


def test_volunteer_without_a_service_radius_is_not_flagged_either_way():
    out, _ = geo.rank_nearby_people(ORIGIN, [_person(1, 17.39, 78.49)], "volunteer", 25)
    assert out[0]["within_service_radius"] is None


def test_donors_have_no_service_radius_fields():
    out, _ = geo.rank_nearby_people(ORIGIN, [_person(1, 17.39, 78.49)], "donor", 25)
    assert "within_service_radius" not in out[0]


def test_two_people_at_different_close_distances_look_identical_so_probing_cannot_pinpoint_them():
    """Trilateration guard: anything inside 1 km reports the same value."""
    out, _ = geo.rank_nearby_people(ORIGIN, [_person(1, 17.3868, 78.4867), _person(2, 17.3935, 78.4867)], "donor", 25)
    assert {p["distance_km"] for p in out} == {1}


# ------------------------------------------------------------------ matching integration
def _cand(score=0.8):
    return {"donor_id": None, "volunteer_id": 7, "score": score, "category_score": 1.0, "reasons": ["Skill match"]}


def test_no_position_on_either_side_changes_nothing():
    c = _cand()
    before = dict(c, reasons=list(c["reasons"]))
    assert geo.apply_to_candidate(c, None, _person(1, 17.39, 78.49), "volunteer") is True
    assert geo.apply_to_candidate(c, ORIGIN, _person(2), "volunteer") is True
    assert c == before


def test_volunteer_outside_their_own_service_radius_is_excluded():
    assert geo.apply_to_candidate(_cand(), ORIGIN, _person(1, 18.9, 79.9, radius=10), "volunteer") is False


def test_volunteer_without_a_service_radius_is_never_excluded_for_distance():
    c = _cand()
    assert geo.apply_to_candidate(c, ORIGIN, _person(1, 18.9, 79.9), "volunteer") is True
    assert c["distance_km"] > 100 and any(r.startswith("Location:") for r in c["reasons"])


def test_score_is_never_modified_by_location():
    c = _cand(0.8123)
    geo.apply_to_candidate(c, ORIGIN, _person(1, 17.39, 78.49, radius=50), "volunteer")
    assert c["score"] == 0.8123


def test_donor_far_away_is_kept_with_a_reason_not_excluded():
    c = {"donor_id": 3, "volunteer_id": None, "score": 0.5, "category_score": 1.0, "reasons": []}
    assert geo.apply_to_candidate(c, ORIGIN, _person(3, 18.9, 79.9), "donor") is True
    assert "straight-line distance" in c["reasons"][-1]
