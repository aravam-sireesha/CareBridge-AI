"""/maps/* through the real API with a FAKE route provider (no Google calls). Needs FastAPI + SQLAlchemy like the other API tests."""
from datetime import timedelta

import pytest

from app import models
from app.routers import maps as maps_router
from app.services.maps_http import MapsError
from app.services.routing import RouteResult
from test_deliveries_api import _put_fix, _to_transit, env, journey_to  # noqa: F401  (env is a fixture)

VOL, ORG, DONOR, ADMIN = "vol@x.org", "org@x.org", "donor@x.org", "admin@x.org"
OUTSIDERS = ("org2@x.org", "donor2@x.org", "vol2@x.org")
RESULT = RouteResult(11250, 1260, 900, "_p~iF~ps|U", True, "drive", "2026-11-05T10:21:00Z")


@pytest.fixture
def fake_route(monkeypatch):
    calls = []

    def fake(origin, dest, env_, mode="drive", **kw):
        calls.append({"origin": origin, "dest": dest, "mode": mode})
        return RESULT
    monkeypatch.setattr(maps_router.routing, "compute_route", fake)
    return calls


def _share(client, h, tid, **fix):
    client.post(f"/deliveries/{tid}/tracking/start", headers=h(VOL))
    return _put_fix(client, h, VOL, tid, **fix)


def _route(client, h, who, tid, **params):
    return client.get("/maps/route", params={"delivery_id": tid, **params}, headers=h(who))


def test_route_requires_a_signed_in_user(env):
    client, db, h, ids = env
    assert client.get("/maps/route", params={"delivery_id": 1}).status_code == 401
    assert client.get("/maps/autocomplete", params={"q": "banjara"}).status_code == 401


def test_outsiders_cannot_route_someone_elses_delivery(env, fake_route):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids); _share(client, h, tid, lat=17.385129, lon=78.486718)
    for who in OUTSIDERS:
        assert _route(client, h, who, tid).status_code == 404, who
    assert fake_route == []                                                  # the provider was never called for them


def test_a_viewer_is_routed_from_the_ROUNDED_position_and_never_sees_the_origin(env, fake_route):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids); _share(client, h, tid, lat=17.385129, lon=78.486718)
    r = _route(client, h, ORG, tid)
    assert r.status_code == 200 and r.json()["duration_s"] == 1260 and r.json()["leg"] == "delivery"
    assert fake_route[0]["origin"] == (17.3851, 78.4867)                     # ~11 m, same as the live view: not the exact fix
    body = r.text
    assert "17.385129" not in body and "78.486718" not in body and "origin" not in r.json()


def test_a_viewer_gets_no_eta_unless_the_volunteer_is_sharing_and_fresh(env, fake_route):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    assert _route(client, h, ORG, tid).status_code == 409                    # not sharing yet
    _share(client, h, tid)
    row = db.query(models.DeliveryLocation).one(); row.recorded_at = row.recorded_at - timedelta(minutes=10); db.commit()
    assert _route(client, h, ORG, tid).status_code == 409                    # sharing, but the position is out of date
    client.post(f"/deliveries/{tid}/tracking/pause", headers=h(VOL))
    assert _route(client, h, ORG, tid).status_code == 409                    # paused: position erased
    assert fake_route == []


def test_no_route_before_the_stage_where_the_viewer_may_see_the_position(env, fake_route):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "accept")
    client.post(f"/deliveries/{tid}/tracking/start", headers=h(VOL)); _put_fix(client, h, VOL, tid)
    assert _route(client, h, ORG, tid).status_code in (404, 409)
    assert fake_route == []


def test_the_volunteer_routes_from_their_own_exact_position(env, fake_route):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    r = _route(client, h, VOL, tid, lat=17.385129, lon=78.486718, mode="two_wheeler")
    assert r.status_code == 200
    assert fake_route[0]["origin"] == (17.385129, 78.486718) and fake_route[0]["mode"] == "two_wheeler"


def test_the_volunteer_without_any_position_is_told_what_to_do(env, fake_route):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    r = _route(client, h, VOL, tid)
    assert r.status_code == 422 and "location" in r.json()["detail"].lower()


def test_a_destination_the_delivery_view_hides_is_not_routable(env, fake_route):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "offer")                                # offered, not yet accepted: no addresses for the volunteer
    r = _route(client, h, VOL, tid, lat=17.4, lon=78.4)
    assert r.status_code in (404, 409) and fake_route == []


def test_without_provider_configuration_there_is_no_straight_line_fallback(env, monkeypatch):
    client, db, h, ids = env
    for name in ("GOOGLE_ROUTES_ENABLED", "GOOGLE_MAPS_SERVER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    tid = _to_transit(client, h, ids)
    r = _route(client, h, VOL, tid, lat=17.385, lon=78.486)
    assert r.status_code == 503 and "distance_m" not in r.json() and "road" in r.json()["detail"].lower()


def test_provider_errors_become_clean_http_errors(env, monkeypatch):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    for code, status in (("rejected", 502), ("unavailable", 503), ("no_route", 404)):
        def boom(*a, _c=code, **k):
            raise MapsError(_c, "provider said no")
        monkeypatch.setattr(maps_router.routing, "compute_route", boom)
        r = _route(client, h, VOL, tid, lat=17.385, lon=78.486)
        assert r.status_code == status and r.json()["detail"] == "provider said no"


@pytest.mark.parametrize("params", [{"mode": "teleport"}, {"leg": "home"}, {"lat": 99, "lon": 1}, {"delivery_id": 0}])
def test_bad_parameters_are_refused_before_any_work(env, fake_route, params):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    assert client.get("/maps/route", params={"delivery_id": tid, **params}, headers=h(VOL)).status_code == 422
    assert fake_route == []


def test_route_calls_are_rate_limited_per_account(env, fake_route):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    codes = [_route(client, h, VOL, tid, lat=17.385, lon=78.486).status_code for _ in range(32)]
    assert codes[:30] == [200] * 30 and codes[30] == 429 and codes[31] == 429


def test_search_endpoints_report_not_configured_instead_of_failing_mysteriously(env, monkeypatch):
    client, db, h, ids = env
    for name in ("GOOGLE_GEOCODING_ENABLED", "GOOGLE_MAPS_SERVER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert client.get("/maps/config", headers=h(ORG)).json() == {"geocoding": False, "routes": False}
    assert client.get("/maps/autocomplete", params={"q": "banjara"}, headers=h(ORG)).status_code == 503
    assert client.get("/maps/geocode", params={"address": "12 Hope Road"}, headers=h(ORG)).status_code == 503


def test_search_returns_provider_results_and_validates_input(env, monkeypatch):
    client, db, h, ids = env
    monkeypatch.setattr(maps_router.geocoding, "autocomplete", lambda q, e, session_token=None, bias=None: [{"place_id": "ChIJabcdefghijk", "text": q, "main_text": q, "secondary_text": ""}])
    r = client.get("/maps/autocomplete", params={"q": "banjara", "lat": 17.4, "lon": 78.4}, headers=h(ORG))
    assert r.status_code == 200 and r.json()["suggestions"][0]["place_id"] == "ChIJabcdefghijk"
    assert client.get("/maps/autocomplete", params={"q": "x" * 201}, headers=h(ORG)).status_code == 422
    assert client.get("/maps/place/short", headers=h(ORG)).status_code in (422, 503)
