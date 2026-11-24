"""Location endpoints: opt-in sharing, privacy, scoping and matching. Run with:  python -m pytest tests/test_locations.py -q"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.auth import hash_password
from app.database import Base, get_db
from app.main import app

PASSWORD = "StrongPass1234"
HYD = (17.385, 78.4867)        # Hyderabad
NEAR = (17.39, 78.49)          # < 1 km from HYD
FAR = (18.9, 79.9)             # ~220 km from HYD


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()

    org_a = models.Organization(name="Hope Home", verified=True, verification_status="verified", latitude=HYD[0], longitude=HYD[1])
    org_b = models.Organization(name="Other Home", verified=True, verification_status="verified", latitude=FAR[0], longitude=FAR[1])
    org_c = models.Organization(name="Unverified Home", verified=False, verification_status="pending", latitude=NEAR[0], longitude=NEAR[1])
    db.add_all([org_a, org_b, org_c])
    db.flush()
    donor = models.Donor(name="Dana Donor", organization_id=org_a.id, preferences="food")
    donor_other = models.Donor(name="Other Org Donor", organization_id=org_b.id, preferences="food")
    donor_unowned = models.Donor(name="Self Registered", organization_id=None, preferences="food")
    vol = models.Volunteer(name="Vik Volunteer", organization_id=org_a.id, skills="food", availability="weekends")
    db.add_all([donor, donor_other, donor_unowned, vol])
    db.flush()
    needs = {
        "open_a": models.Need(org_id=org_a.id, category="food", quantity=5, urgency="high", status="open", title="Meals"),
        "closed_a": models.Need(org_id=org_a.id, category="books", quantity=5, urgency="low", status="closed"),
        "open_b": models.Need(org_id=org_b.id, category="food", quantity=5, urgency="low", status="open"),
        "open_c": models.Need(org_id=org_c.id, category="food", quantity=5, urgency="low", status="open"),
    }
    db.add_all(needs.values())
    db.flush()
    db.add_all([
        models.User(email="admin@x.org", hashed_password=hash_password(PASSWORD), role="admin"),
        models.User(email="org@x.org", hashed_password=hash_password(PASSWORD), role="organization", organization_id=org_a.id),
        models.User(email="orgb@x.org", hashed_password=hash_password(PASSWORD), role="organization", organization_id=org_b.id),
        models.User(email="donor@x.org", hashed_password=hash_password(PASSWORD), role="donor", donor_id=donor.id),
        models.User(email="vol@x.org", hashed_password=hash_password(PASSWORD), role="volunteer", volunteer_id=vol.id),
    ])
    db.commit()
    ids = {"org_a": org_a.id, "org_b": org_b.id, "donor": donor.id, "vol": vol.id, **{k: v.id for k, v in needs.items()}}

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        def h(email):
            return {"Authorization": "Bearer " + client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]}
        yield client, db, h, ids
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def _put(client, headers, pos, **extra):
    return client.put("/locations/me", headers=headers, json={"latitude": pos[0], "longitude": pos[1], **extra})


# ------------------------------------------------------------------ authentication and roles
def test_requires_sign_in(env):
    client, *_ = env
    assert client.get("/locations/me").status_code == 401
    assert client.get("/locations/nearby-needs").status_code == 401


def test_administrators_have_no_location_profile(env):
    client, _, h, _ = env
    assert client.get("/locations/me", headers=h("admin@x.org")).status_code == 403
    assert _put(client, h("admin@x.org"), HYD).status_code == 403


# ------------------------------------------------------------------ own location: set, read, clear
def test_a_donor_can_share_read_and_remove_their_location(env):
    client, db, h, ids = env
    hd = h("donor@x.org")
    assert client.get("/locations/me", headers=hd).json()["has_location"] is False
    res = _put(client, hd, NEAR, label="Banjara Hills")
    assert res.status_code == 200
    body = res.json()
    assert body["has_location"] and (body["latitude"], body["longitude"]) == NEAR and body["label"] == "Banjara Hills"
    assert db.get(models.Donor, ids["donor"]).location == "Banjara Hills"
    cleared = client.delete("/locations/me", headers=hd).json()
    assert cleared["has_location"] is False and cleared["latitude"] is None
    assert cleared["label"] == "Banjara Hills"                         # the text stays unless asked to go
    assert client.delete("/locations/me?clear_label=true", headers=hd).json()["label"] is None


def test_a_volunteer_can_set_a_service_radius_and_a_donor_cannot(env):
    client, _, h, _ = env
    assert _put(client, h("vol@x.org"), NEAR, service_radius_km=15).json()["service_radius_km"] == 15
    assert _put(client, h("donor@x.org"), NEAR, service_radius_km=15).status_code == 422
    assert client.delete("/locations/me", headers=h("vol@x.org")).json()["service_radius_km"] is None


def test_an_organization_updates_its_own_position(env):
    client, db, h, ids = env
    assert _put(client, h("org@x.org"), NEAR, label="12 Main Road").status_code == 200
    org = db.get(models.Organization, ids["org_a"])
    assert (org.latitude, org.longitude, org.address) == (NEAR[0], NEAR[1], "12 Main Road")


@pytest.mark.parametrize("lat,lon", [(91, 10), (-91, 10), (10, 181), (10, -181), (0, 0)])
def test_invalid_positions_are_rejected(env, lat, lon):
    client, _, h, _ = env
    assert _put(client, h("donor@x.org"), (lat, lon)).status_code == 422


def test_a_non_numeric_position_is_rejected(env):
    client, _, h, _ = env
    assert client.put("/locations/me", headers=h("donor@x.org"), json={"latitude": "north", "longitude": 1}).status_code == 422
    assert client.put("/locations/me", headers=h("donor@x.org"), json={"latitude": 1}).status_code == 422


def test_radius_must_be_positive_and_bounded(env):
    client, _, h, _ = env
    for bad in (0, -1, 501):
        assert _put(client, h("vol@x.org"), NEAR, service_radius_km=bad).status_code == 422


# ------------------------------------------------------------------ privacy
def test_coordinates_never_appear_in_other_users_views(env):
    client, _, h, ids = env
    _put(client, h("donor@x.org"), (17.391234, 78.481234))
    _put(client, h("vol@x.org"), (17.395678, 78.485678), service_radius_km=20)
    for url in ("/donors/", "/volunteers/", "/admin/donors", "/admin/volunteers"):
        who = "admin@x.org" if url.startswith("/admin") else "org@x.org"
        res = client.get(url, headers=h(who))
        assert res.status_code == 200, url
        text = res.text
        assert "17.391234" not in text and "78.481234" not in text and "17.395678" not in text, url
    helpers = client.get(f"/locations/needs/{ids['open_a']}/nearby", headers=h("org@x.org")).text
    # the need's own place (the organization's published location) may be returned; no donor or volunteer position may be
    for leaked in ("17.3912", "78.4812", "17.3956", "78.4856", "17.39,", "17.40"):
        assert leaked not in helpers
    assert "latitude" not in helpers and "position" not in helpers


def test_the_audit_trail_records_that_a_location_changed_but_not_where(env):
    client, db, h, _ = env
    _put(client, h("donor@x.org"), (17.391234, 78.481234))
    client.delete("/locations/me", headers=h("donor@x.org"))
    rows = db.query(models.AuditLog).filter(models.AuditLog.action.like("location.%")).all()
    assert {r.action for r in rows} == {"location.updated", "location.cleared"}
    assert "17.39" not in repr([r.detail for r in rows])


# ------------------------------------------------------------------ nearby needs (donor / volunteer)
def test_nearby_needs_asks_for_a_location_first(env):
    client, _, h, _ = env
    body = client.get("/locations/nearby-needs", headers=h("donor@x.org")).json()
    assert body["located"] is False and body["needs"] == []


def test_nearby_needs_lists_only_open_needs_of_verified_organizations_inside_the_radius(env):
    client, _, h, ids = env
    _put(client, h("donor@x.org"), NEAR)
    body = client.get("/locations/nearby-needs", headers=h("donor@x.org")).json()
    assert body["located"] and [n["need_id"] for n in body["needs"]] == [ids["open_a"]]   # not closed, not far, not unverified
    n = body["needs"][0]
    assert n["distance_label"] == "within 1 km" and n["organization_name"] == "Hope Home"
    assert "latitude" not in n and "longitude" not in n and "location" not in n


def test_a_wider_radius_includes_further_needs_but_the_radius_is_capped(env):
    client, _, h, ids = env
    _put(client, h("donor@x.org"), NEAR)
    wide = client.get("/locations/nearby-needs?radius_km=300", headers=h("donor@x.org")).json()
    assert {n["need_id"] for n in wide["needs"]} == {ids["open_a"], ids["open_b"]}
    assert client.get("/locations/nearby-needs?radius_km=9999", headers=h("donor@x.org")).status_code == 422


def test_a_volunteers_service_radius_is_the_default_search_radius(env):
    client, _, h, ids = env
    _put(client, h("vol@x.org"), NEAR, service_radius_km=500)
    body = client.get("/locations/nearby-needs", headers=h("vol@x.org")).json()
    assert body["radius_km"] == 500 and {n["need_id"] for n in body["needs"]} == {ids["open_a"], ids["open_b"]}


def test_organizations_and_admins_cannot_use_the_donor_search(env):
    client, _, h, _ = env
    assert client.get("/locations/nearby-needs", headers=h("org@x.org")).status_code == 403
    assert client.get("/locations/nearby-needs", headers=h("admin@x.org")).status_code == 403


# ------------------------------------------------------------------ helpers near a need (organization / admin)
def test_an_organization_sees_only_its_own_people_near_its_own_need(env):
    client, _, h, ids = env
    _put(client, h("donor@x.org"), NEAR)
    _put(client, h("vol@x.org"), NEAR, service_radius_km=5)
    body = client.get(f"/locations/needs/{ids['open_a']}/nearby", headers=h("org@x.org")).json()
    assert body["located"] and body["distance_basis"] == "organization"
    assert [d["name"] for d in body["donors"]] == ["Dana Donor"]
    assert [v["name"] for v in body["volunteers"]] == ["Vik Volunteer"] and body["volunteers"][0]["within_service_radius"] is True
    names = repr(body)
    assert "Other Org Donor" not in names and "Self Registered" not in names


def test_people_who_have_not_shared_a_location_are_counted_not_guessed(env):
    client, _, h, ids = env
    body = client.get(f"/locations/needs/{ids['open_a']}/nearby", headers=h("org@x.org")).json()
    assert body["donors"] == [] and body["donors_without_location"] == 1 and body["volunteers_without_location"] == 1


def test_another_organizations_need_looks_like_it_does_not_exist(env):
    client, _, h, ids = env
    assert client.get(f"/locations/needs/{ids['open_b']}/nearby", headers=h("org@x.org")).status_code == 404
    assert client.get("/locations/needs/99999/nearby", headers=h("org@x.org")).status_code == 404


def test_donors_and_volunteers_cannot_search_for_helpers(env):
    client, _, h, ids = env
    assert client.get(f"/locations/needs/{ids['open_a']}/nearby", headers=h("donor@x.org")).status_code == 403
    assert client.get(f"/locations/needs/{ids['open_a']}/nearby", headers=h("vol@x.org")).status_code == 403


def test_an_administrator_sees_everyone_including_unowned_records(env):
    client, _, h, ids = env
    for email in ("donor@x.org",):
        _put(client, h(email), NEAR)
    body = client.get(f"/locations/needs/{ids['open_a']}/nearby", headers=h("admin@x.org")).json()
    assert body["donors_without_location"] == 2        # the other organization's donor and the self-registered one


def test_a_need_with_no_position_says_so(env):
    client, db, h, ids = env
    org = db.get(models.Organization, ids["org_a"])
    org.latitude = org.longitude = None
    db.commit()
    body = client.get(f"/locations/needs/{ids['open_a']}/nearby", headers=h("org@x.org")).json()
    assert body["located"] is False and "location" in body["message"].lower()


# ------------------------------------------------------------------ matching integration
def test_matching_adds_distance_and_drops_volunteers_outside_their_radius(env):
    client, db, h, ids = env
    _put(client, h("vol@x.org"), FAR, service_radius_km=10)       # lives ~220 km away, travels 10 km
    _put(client, h("donor@x.org"), NEAR)
    body = client.post(f"/matching/suggest/{ids['open_a']}", headers=h("admin@x.org")).json()
    kinds = {(s["donor_id"], s["volunteer_id"]) for s in body["suggestions"]}
    assert (ids["donor"], None) in kinds
    assert (None, ids["vol"]) not in kinds
    donor_row = next(s for s in body["suggestions"] if s["donor_id"] == ids["donor"])
    assert any(r.startswith("Location:") for r in donor_row["reasons"])
    assert body["model_version"] == "matching-rules-1.5.0"


def test_matching_is_unchanged_when_nobody_shared_a_location(env):
    client, _, h, ids = env
    body = client.post(f"/matching/suggest/{ids['open_a']}", headers=h("admin@x.org")).json()
    assert body["suggestions"] and not any(r.startswith("Location:") for s in body["suggestions"] for r in s["reasons"])


# ------------------------------------------------------------------ matching center (organization view)
def test_matching_center_ranks_the_organizations_own_people_with_reasons_and_bands(env):
    client, db, h, ids = env
    _put(client, h("donor@x.org"), NEAR)
    body = client.get(f"/matching/center/{ids['open_a']}", headers=h("org@x.org")).json()
    assert [d["name"] for d in body["donors"]] == ["Dana Donor"] and body["donors"][0]["fit"] in ("strong", "good", "partial")
    assert body["donors"][0]["source"] == "your organization" and body["donors"][0]["reasons"]
    assert "not approvals" in body["note"] and body["model_version"] == "matching-rules-1.5.0"
    assert "Other Org Donor" not in repr(body) and "Self Registered" not in repr(body)
    assert "latitude" not in repr(body) and "17.39" not in repr(body)


def test_matching_center_includes_people_an_administrator_recommended_for_this_need(env):
    client, db, h, ids = env
    client.post(f"/matching/suggest/{ids['open_a']}", headers=h("admin@x.org"))
    body = client.get(f"/matching/center/{ids['open_a']}", headers=h("org@x.org")).json()
    assert any(d["source"] == "recommended by an administrator" for d in body["donors"])


def test_matching_center_explains_an_empty_result_and_is_scoped(env):
    client, db, h, ids = env
    body = client.get(f"/matching/center/{ids['open_b']}", headers=h("org@x.org"))
    assert body.status_code == 404                                                    # someone else's need
    for who in ("donor@x.org", "vol@x.org"):
        assert client.get(f"/matching/center/{ids['open_a']}", headers=h(who)).status_code == 403
    db.query(models.Donor).filter_by(name="Dana Donor").one().preferences = "books"
    db.query(models.Volunteer).filter_by(name="Vik Volunteer").one().skills = "carpentry"; db.commit()
    empty = client.get(f"/matching/center/{ids['open_a']}", headers=h("org@x.org")).json()
    assert empty["donors"] == [] and empty["volunteers"] == [] and {u["kind"] for u in empty["unmatched"]} >= {"donor", "volunteer"}
    assert all(u["suggestion"] for u in empty["unmatched"])


# ------------------------------------------------------------------ availability and capacity (API)
def test_a_volunteer_saves_a_validated_schedule_and_capacity_and_it_is_labelled_unverified(env):
    client, db, h, ids = env
    body = {"slots": [{"weekday": 5, "start": "09:00", "end": "13:00"}], "timezone": "Asia/Kolkata", "transport_mode": "car", "carry_capacity_kg": 80}
    res = client.put("/availability/me", headers=h("vol@x.org"), json=body)
    assert res.status_code == 200 and res.json()["has_schedule"] and res.json()["carry_capacity_kg"] == 80 and "not verified" in res.json()["capacity_note"]
    assert client.get("/availability/me", headers=h("vol@x.org")).json()["slots"] == body["slots"]
    for bad in ({"slots": [{"weekday": 9, "start": "09:00", "end": "10:00"}]}, {"slots": [{"weekday": 1, "start": "10:00", "end": "09:00"}]},
                {"timezone": "Mars/Base"}, {"transport_mode": "rocket"}, {"carry_capacity_kg": -3}, {"carry_capacity_kg": "heavy"}):
        assert client.put("/availability/me", headers=h("vol@x.org"), json=bad).status_code == 422, bad


def test_only_volunteers_have_an_availability_profile(env):
    client, db, h, ids = env
    for who in ("org@x.org", "donor@x.org", "admin@x.org"):
        assert client.get("/availability/me", headers=h(who)).status_code == 403
    assert client.get("/availability/me").status_code == 401


def test_old_free_text_is_only_suggested_never_saved(env):
    client, db, h, ids = env
    db.query(models.Volunteer).filter_by(name="Vik Volunteer").one().availability = "weekends"; db.commit()
    sug = client.get("/availability/suggest", headers=h("vol@x.org")).json()
    assert [s["weekday"] for s in sug["slots"]] == [5, 6] and "Nothing is saved until you confirm" in sug["note"]
    assert client.get("/availability/me", headers=h("vol@x.org")).json()["has_schedule"] is False          # still not saved


def test_the_audit_trail_records_that_availability_changed_but_not_the_schedule(env):
    client, db, h, ids = env
    client.put("/availability/me", headers=h("vol@x.org"), json={"slots": [{"weekday": 5, "start": "09:00", "end": "13:00"}], "carry_capacity_kg": 80})
    row = db.query(models.AuditLog).filter_by(action="availability.updated").one()
    assert row.detail == {"slots": 1, "capacity_declared": True}


def test_the_matching_center_filters_by_pickup_time_and_load_and_says_why(env):
    client, db, h, ids = env
    v = db.query(models.Volunteer).filter_by(name="Vik Volunteer").one()
    v.availability_slots, v.availability_timezone, v.carry_capacity_kg = [{"weekday": 0, "start": "09:00", "end": "17:00"}], "Asia/Kolkata", 30.0; db.commit()
    url = f"/matching/center/{ids['open_a']}"
    assert [x["name"] for x in client.get(url, headers=h("org@x.org")).json()["volunteers"]] == ["Vik Volunteer"]                         # no context: unchanged
    ok = client.get(url + "?when=2026-10-26T10:00:00Z&weight_kg=20", headers=h("org@x.org")).json()
    assert [x["name"] for x in ok["volunteers"]] == ["Vik Volunteer"] and any("covers the pickup time" in r for r in ok["volunteers"][0]["reasons"])
    late = client.get(url + "?when=2026-10-26T12:30:00Z", headers=h("org@x.org")).json()
    assert late["volunteers"] == [] and any("declared hours" in u["reason"] for u in late["unmatched"])
    heavy = client.get(url + "?weight_kg=45", headers=h("org@x.org")).json()
    assert heavy["volunteers"] == [] and any("cannot carry a load that heavy" in u["reason"] for u in heavy["unmatched"])
    assert client.get(url + "?when=yesterday", headers=h("org@x.org")).status_code == 422
    assert client.get(url + "?weight_kg=-1", headers=h("org@x.org")).status_code == 422


# ------------------------------------------------------------------ map views
def _decimals(v):
    return len(repr(v).split(".")[1]) if "." in repr(v) else 0


def test_nearby_needs_returns_snapped_pins_and_only_the_callers_own_origin(env):
    client, _, h, ids = env
    _put(client, h("donor@x.org"), (17.391234, 78.481234))
    body = client.get("/locations/nearby-needs", headers=h("donor@x.org")).json()
    assert body["origin"] == {"lat": 17.391234, "lon": 78.481234}          # their own saved position, nobody else's
    pin = body["needs"][0]["position"]
    assert _decimals(pin["lat"]) <= 2 and _decimals(pin["lon"]) <= 2        # snapped to ~1 km
    assert abs(pin["lat"] - HYD[0]) < 0.01 and abs(pin["lon"] - HYD[1]) < 0.01
    assert "latitude" not in body["needs"][0] and "address" not in repr(body["needs"][0])


def test_helpers_near_need_never_pins_individual_people(env):
    client, _, h, ids = env
    _put(client, h("donor@x.org"), (17.391234, 78.481234))
    body = client.get(f"/locations/needs/{ids['open_a']}/nearby", headers=h("org@x.org")).json()
    assert body["donors"] and "position" not in body["donors"][0]
    assert abs(body["origin"]["lat"] - HYD[0]) < 0.001                      # the need's place, for the search ring


def test_admin_map_is_for_administrators_only(env):
    client, _, h, _ = env
    assert client.get("/admin/map").status_code == 401
    for who in ("donor@x.org", "vol@x.org", "org@x.org"):
        assert client.get("/admin/map", headers=h(who)).status_code == 403, who
    assert client.get("/admin/map", headers=h("admin@x.org")).status_code == 200


def test_admin_map_places_records_and_snaps_people(env):
    client, _, h, ids = env
    _put(client, h("donor@x.org"), (17.391234, 78.481234))
    _put(client, h("vol@x.org"), (17.395678, 78.485678), service_radius_km=20)
    res = client.get("/admin/map", headers=h("admin@x.org"))
    body = res.json()
    assert {o["name"] for o in body["organizations"]} == {"Hope Home", "Other Home", "Unverified Home"}
    assert {n["id"] for n in body["needs"]} == {ids["open_a"], ids["open_b"], ids["open_c"]}   # closed need left out
    assert len(body["donors"]) == 1 and len(body["volunteers"]) == 1                          # only people who shared a position
    assert body["unplaced"]["donors"] == 2 and body["unplaced"]["volunteers"] == 0
    for person in body["donors"] + body["volunteers"]:
        assert _decimals(person["position"]["lat"]) <= 2 and _decimals(person["position"]["lon"]) <= 2
    for leaked in ("17.391234", "78.481234", "17.395678", "78.485678"):
        assert leaked not in res.text


def test_admin_map_flags_needs_with_no_volunteer_in_range(env):
    client, _, h, ids = env
    first = client.get("/admin/map", headers=h("admin@x.org")).json()
    assert ids["open_a"] in {g["need_id"] for g in first["gaps"]}              # nobody has shared a position yet
    _put(client, h("vol@x.org"), NEAR, service_radius_km=5)
    second = client.get("/admin/map?radius_km=10", headers=h("admin@x.org")).json()
    assert ids["open_a"] not in {g["need_id"] for g in second["gaps"]}
    assert next(n for n in second["needs"] if n["id"] == ids["open_a"])["volunteers_in_range"] == 1
    assert ids["open_b"] in {g["need_id"] for g in second["gaps"]}              # ~220 km away
    assert client.get("/admin/map?radius_km=9999", headers=h("admin@x.org")).status_code == 422
