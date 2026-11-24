"""Ranking, fit bands and 'why nothing matched'. Pure Python. Run with:  python -m pytest tests/test_matching_center.py -q"""
import sys
import types
from types import SimpleNamespace as NS

try:                                    # run without SQLAlchemy installed by stubbing only the import boundary
    import sqlalchemy.orm  # noqa: F401
except ImportError:
    orm = types.ModuleType("sqlalchemy.orm"); orm.Session = object
    sys.modules.setdefault("sqlalchemy", types.ModuleType("sqlalchemy")); sys.modules["sqlalchemy.orm"] = orm
    models = types.ModuleType("app.models")
    for name in ("Donor", "Volunteer", "Need", "Organization"):
        setattr(models, name, type(name, (), {}))
    sys.modules["app.models"] = models

from app.services import matching_rules as mr
from app.services import geo

NEED = NS(id=1, org_id=1, category="food", urgency="high", quantity=100, latitude=None, longitude=None)
ORIGIN = geo.Point(17.385, 78.4867, "organization")


def donor(i, prefs, lat=None, lon=None):
    return NS(id=i, name=f"D{i}", preferences=prefs, latitude=lat, longitude=lon, service_radius_km=None)


def vol(i, skills, lat=None, lon=None, r=None):
    return NS(id=i, name=f"V{i}", skills=skills, availability="weekends", latitude=lat, longitude=lon, service_radius_km=r)


def test_fit_bands_are_thresholds_on_a_transparent_score_not_probabilities():
    assert [mr.fit_band(x) for x in (1.0, 0.70, 0.699, 0.45, 0.449, 0.0)] == ["strong", "strong", "good", "good", "partial", "partial"]


def test_ranking_is_deterministic_for_identical_inputs():
    donors = [donor(1, "food"), donor(2, "groceries"), donor(3, "food")]
    first = mr.rank_candidates(NEED, donors, [vol(1, "food")], ORIGIN)
    again = mr.rank_candidates(NEED, list(donors), [vol(1, "food")], ORIGIN)
    assert first == again


def test_people_with_no_category_overlap_are_excluded_and_counted():
    r = mr.rank_candidates(NEED, [donor(1, "books"), donor(2, "food")], [vol(1, "carpentry")], None)
    assert [c["donor_id"] for c in r["candidates"] if c["donor_id"]] == [2]
    assert r["stats"]["donors_category_miss"] == 1 and r["stats"]["volunteers_category_miss"] == 1 and r["candidates"][0]["reasons"]


def test_volunteers_outside_their_travel_range_are_excluded_and_counted_separately():
    r = mr.rank_candidates(NEED, [], [vol(1, "food", 17.39, 78.49, r=10), vol(2, "food", 18.9, 79.9, r=10)], ORIGIN)
    assert [c["volunteer_id"] for c in r["candidates"]] == [1] and r["stats"]["volunteers_out_of_range"] == 1 and r["stats"]["volunteers_category_miss"] == 0


def test_empty_pools_produce_empty_results_not_errors():
    r = mr.rank_candidates(NEED, [], [], ORIGIN)
    assert r["candidates"] == [] and r["stats"]["donors_considered"] == 0


def test_explanations_name_the_real_cause_and_a_next_step():
    r = mr.rank_candidates(NEED, [], [], ORIGIN)
    reasons = mr.explain_unmatched(NEED, r["stats"])
    assert {x["kind"] for x in reasons} == {"donor", "volunteer"} and all(x["suggestion"] for x in reasons)
    r = mr.rank_candidates(NEED, [donor(1, "books"), donor(2, "toys")], [], ORIGIN)
    text = " ".join(x["reason"] for x in mr.explain_unmatched(NEED, r["stats"]))
    assert "None of your 2 donor(s)" in text and "'food'" in text


def test_a_fully_covered_need_says_so_instead_of_blaming_the_people():
    r = mr.rank_candidates(NEED, [donor(1, "books")], [], ORIGIN)
    out = mr.explain_unmatched(NEED, r["stats"], remaining_quantity=0)
    assert len(out) == 1 and "already cover" in out[0]["reason"]


def test_out_of_range_and_missing_location_are_explained():
    r = mr.rank_candidates(NEED, [], [vol(2, "food", 18.9, 79.9, r=10)], ORIGIN)
    text = " ".join(x["reason"] for x in mr.explain_unmatched(NEED, r["stats"], has_location=False))
    assert "outside the travel range" in text and "no saved location" in text


def test_no_explanation_is_invented_when_matches_exist():
    r = mr.rank_candidates(NEED, [donor(1, "food")], [vol(1, "food")], ORIGIN)
    assert mr.explain_unmatched(NEED, r["stats"]) == []


# ------------------------------------------------------------------ availability and capacity in the ranking
from datetime import datetime

MON_10_UTC = datetime(2026, 10, 26, 10, 0)        # 15:30 Monday in Asia/Kolkata
OFFICE = [{"weekday": 0, "start": "09:00", "end": "17:00"}]


def vol2(i, slots=None, cap=None, tz="Asia/Kolkata"):
    v = vol(i, "food")
    v.availability_slots, v.availability_timezone, v.carry_capacity_kg = slots, tz, cap
    return v


def test_without_a_context_availability_and_capacity_change_nothing_at_all():
    vols = [vol2(1, OFFICE, 10.0), vol2(2, [{"weekday": 6, "start": "01:00", "end": "02:00"}], 1.0), vol2(3)]
    assert [c["volunteer_id"] for c in mr.rank_candidates(NEED, [], vols, ORIGIN)["candidates"]] == [1, 2, 3]
    r = mr.rank_candidates(NEED, [], vols, ORIGIN)
    assert r["stats"]["volunteers_unavailable"] == 0 and r["stats"]["volunteers_over_capacity"] == 0


def test_declared_hours_that_do_not_cover_the_pickup_exclude_the_volunteer_and_it_is_counted():
    vols = [vol2(1, OFFICE), vol2(2, [{"weekday": 6, "start": "09:00", "end": "17:00"}])]
    r = mr.rank_candidates(NEED, [], vols, ORIGIN, {"when": MON_10_UTC, "weight_kg": None})
    assert [c["volunteer_id"] for c in r["candidates"]] == [1] and r["stats"]["volunteers_unavailable"] == 1
    assert any("covers the pickup time" in x for x in r["candidates"][0]["reasons"])


def test_a_declared_capacity_below_the_load_excludes_and_is_counted_separately():
    vols = [vol2(1, None, 60.0), vol2(2, None, 20.0)]
    r = mr.rank_candidates(NEED, [], vols, ORIGIN, {"when": None, "weight_kg": 40.0})
    assert [c["volunteer_id"] for c in r["candidates"]] == [1] and r["stats"]["volunteers_over_capacity"] == 1 and r["stats"]["volunteers_unavailable"] == 0


def test_missing_information_never_excludes_and_is_reported_honestly():
    r = mr.rank_candidates(NEED, [], [vol2(1)], ORIGIN, {"when": MON_10_UTC, "weight_kg": 40.0})
    c = r["candidates"][0]
    assert any("Availability not stated" in x for x in c["reasons"]) and any("capacity not stated" in x.lower() for x in c["reasons"])


def test_explanations_name_availability_and_capacity_causes_with_a_next_step():
    vols = [vol2(1, [{"weekday": 6, "start": "09:00", "end": "17:00"}]), vol2(2, None, 5.0)]
    r = mr.rank_candidates(NEED, [], vols, ORIGIN, {"when": MON_10_UTC, "weight_kg": 40.0})
    text = " ".join(x["reason"] + " " + x["suggestion"] for x in mr.explain_unmatched(NEED, r["stats"]))
    assert "declared hours that do not cover" in text and "cannot carry a load that heavy" in text and "Split the delivery" in text
