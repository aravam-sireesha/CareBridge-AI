"""Google Routes / Places / Geocoding adapters against a FAKE transport (no network, no key). Live behaviour is NOT covered here."""
from datetime import datetime, timezone

import pytest

from app.services import geocoding, maps_http, routing
from app.services.maps_http import MapsError

ENV = {"GOOGLE_MAPS_SERVER_API_KEY": "SERVER-KEY", "GOOGLE_ROUTES_ENABLED": "true", "GOOGLE_GEOCODING_ENABLED": "true"}
NOW = datetime(2026, 11, 5, 10, 0, 0, tzinfo=timezone.utc)
A, B = (17.4065, 78.4772), (17.4435, 78.3772)


class Fake:
    def __init__(self, status=200, data=None):
        self.status, self.data, self.calls = status, data, []

    def __call__(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.status, self.data


GOOD = {"routes": [{"duration": "1260s", "staticDuration": "900s", "distanceMeters": 11250, "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"}}]}


# ---------------------------------------------------------------- routing
def test_routing_is_off_unless_enabled_and_keyed():
    assert not routing.enabled({}) and not routing.enabled({"GOOGLE_ROUTES_ENABLED": "true"})
    assert not routing.enabled({"GOOGLE_MAPS_SERVER_API_KEY": "k"}) and routing.enabled(ENV)
    with pytest.raises(MapsError) as e:
        routing.compute_route(A, B, {}, transport=Fake(200, GOOD))
    assert e.value.code == "not_configured"                 # never a silent straight-line fallback


def test_a_good_response_becomes_a_road_route_with_traffic_eta():
    r = routing.compute_route(A, B, ENV, transport=Fake(200, GOOD), now=NOW)
    assert (r.distance_m, r.duration_s, r.static_duration_s) == (11250, 1260, 900)
    assert r.traffic_aware is True and r.arrival_at == "2026-11-05T10:21:00Z" and r.provider == "google_routes"
    assert r.polyline.startswith("_p~iF")


def test_request_shape_key_in_header_only_and_field_mask():
    fake = Fake(200, GOOD)
    routing.compute_route(A, B, ENV, transport=fake, now=NOW)
    method, url, kw = fake.calls[0]
    assert method == "POST" and url == routing.ENDPOINT and "SERVER-KEY" not in url
    assert kw["headers"]["X-Goog-Api-Key"] == "SERVER-KEY" and kw["headers"]["X-Goog-FieldMask"] == routing.FIELD_MASK
    assert kw["json"]["travelMode"] == "DRIVE" and kw["json"]["routingPreference"] == "TRAFFIC_AWARE"
    assert kw["json"]["origin"]["location"]["latLng"] == {"latitude": A[0], "longitude": A[1]}


def test_walking_is_not_asked_for_traffic_awareness():
    fake = Fake(200, GOOD)
    r = routing.compute_route(A, B, ENV, mode="walk", transport=fake, now=NOW)
    assert "routingPreference" not in fake.calls[0][2]["json"] and r.traffic_aware is False and fake.calls[0][2]["json"]["travelMode"] == "WALK"


def test_two_wheeler_mode_is_supported():
    fake = Fake(200, GOOD)
    routing.compute_route(A, B, ENV, mode="two_wheeler", transport=fake, now=NOW)
    assert fake.calls[0][2]["json"]["travelMode"] == "TWO_WHEELER"


@pytest.mark.parametrize("bad", [(91, 0), (0, 0), ("x", 1), (None, None), (True, 1), (float("nan"), 1)])
def test_invalid_places_never_reach_google(bad):
    fake = Fake(200, GOOD)
    with pytest.raises(MapsError) as e:
        routing.compute_route(bad, B, ENV, transport=fake)
    assert e.value.code == "invalid" and not fake.calls


def test_unknown_mode_is_rejected():
    with pytest.raises(MapsError) as e:
        routing.compute_route(A, B, ENV, mode="teleport", transport=Fake(200, GOOD))
    assert e.value.code == "invalid"


@pytest.mark.parametrize("status,code", [(429, "unavailable"), (503, "unavailable"), (403, "rejected"), (401, "rejected"), (404, "no_route"), (400, "no_route")])
def test_http_failures_are_classified_without_leaking_provider_text(status, code):
    with pytest.raises(MapsError) as e:
        routing.compute_route(A, B, ENV, transport=Fake(status, {"error": {"message": "key SERVER-KEY is restricted"}}))
    assert e.value.code == code and "SERVER-KEY" not in e.value.message


@pytest.mark.parametrize("payload", [{}, {"routes": []}, {"routes": [None]}, None, "text",
                                     {"routes": [{"duration": "5s", "distanceMeters": 10}]},                                   # no polyline
                                     {"routes": [{"duration": "soon", "distanceMeters": 10, "polyline": {"encodedPolyline": "x"}}]},
                                     {"routes": [{"duration": "5s", "distanceMeters": -4, "polyline": {"encodedPolyline": "x"}}]},
                                     {"routes": [{"duration": "5s", "distanceMeters": True, "polyline": {"encodedPolyline": "x"}}]}])
def test_malformed_or_empty_responses_are_errors_not_zeros(payload):
    with pytest.raises(MapsError):
        routing.parse_response(payload, "drive", True)


@pytest.mark.parametrize("raw,expected", [("1260s", 1260), ("1260.4s", 1260), ("0s", 0), ("12m", None), ("", None), (None, None), ("-5s", None)])
def test_duration_parsing(raw, expected):
    assert routing.parse_duration(raw) == expected


def test_missing_static_duration_falls_back_to_the_traffic_duration():
    data = {"routes": [{"duration": "300s", "distanceMeters": 1000, "polyline": {"encodedPolyline": "abc"}}]}
    assert routing.parse_response(data, "drive", True, NOW).static_duration_s == 300


# ---------------------------------------------------------------- autocomplete / place / geocode
SUGGEST = {"suggestions": [
    {"placePrediction": {"placeId": "ChIJabcdefghijk", "text": {"text": "Banjara Hills, Hyderabad"}, "structuredFormat": {"mainText": {"text": "Banjara Hills"}, "secondaryText": {"text": "Hyderabad, Telangana"}}}},
    {"queryPrediction": {"text": {"text": "not a place"}}},
    {"placePrediction": {"placeId": "bad id with spaces", "text": {"text": "x"}}},
]}


def test_autocomplete_returns_only_valid_place_predictions():
    out = geocoding.autocomplete("banjara", ENV, session_token="tok12345678", transport=Fake(200, SUGGEST))
    assert out == [{"place_id": "ChIJabcdefghijk", "text": "Banjara Hills, Hyderabad", "main_text": "Banjara Hills", "secondary_text": "Hyderabad, Telangana"}]


def test_autocomplete_request_is_india_restricted_biased_and_session_grouped():
    fake = Fake(200, SUGGEST)
    geocoding.autocomplete("banjara", ENV, session_token="tok12345678", bias=(17.4, 78.4), transport=fake)
    _, url, kw = fake.calls[0]
    assert url == geocoding.AUTOCOMPLETE_URL and kw["json"]["includedRegionCodes"] == ["in"] and kw["json"]["sessionToken"] == "tok12345678"
    assert kw["json"]["locationBias"]["circle"]["center"] == {"latitude": 17.4, "longitude": 78.4}
    assert kw["headers"]["X-Goog-Api-Key"] == "SERVER-KEY"


@pytest.mark.parametrize("q", ["", "a", "x" * 121, "bad\x00query", "   "])
def test_bad_search_text_never_reaches_google(q):
    fake = Fake(200, SUGGEST)
    with pytest.raises(MapsError) as e:
        geocoding.autocomplete(q, ENV, transport=fake)
    assert e.value.code == "invalid" and not fake.calls


def test_bad_session_token_is_refused():
    with pytest.raises(MapsError):
        geocoding.autocomplete("banjara", ENV, session_token="bad token!", transport=Fake(200, SUGGEST))


def test_geocoding_disabled_is_a_clear_error():
    with pytest.raises(MapsError) as e:
        geocoding.autocomplete("banjara", {}, transport=Fake(200, SUGGEST))
    assert e.value.code == "not_configured"


def test_place_details_ask_only_for_location_address_and_name():
    fake = Fake(200, {"location": {"latitude": 17.41, "longitude": 78.43}, "formattedAddress": "Banjara Hills, Hyderabad", "displayName": {"text": "Banjara Hills"}})
    out = geocoding.place_location("ChIJabcdefghijk", ENV, transport=fake)
    assert out == {"latitude": 17.41, "longitude": 78.43, "address": "Banjara Hills, Hyderabad", "name": "Banjara Hills"}
    assert fake.calls[0][2]["headers"]["X-Goog-FieldMask"] == "location,formattedAddress,displayName"


@pytest.mark.parametrize("pid", ["", "short", "has space in it", "../../etc/passwd", "x" * 301])
def test_a_forged_place_id_never_reaches_google(pid):
    fake = Fake(200, {})
    with pytest.raises(MapsError):
        geocoding.place_location(pid, ENV, transport=fake)
    assert not fake.calls


@pytest.mark.parametrize("loc", [{}, {"latitude": 0, "longitude": 0}, {"latitude": 99, "longitude": 1}, {"latitude": "a", "longitude": 1}])
def test_a_place_without_a_usable_location_is_an_error(loc):
    with pytest.raises(MapsError):
        geocoding.parse_place({"location": loc})


def test_geocode_address_parses_the_first_result_and_keeps_the_key_out_of_errors():
    ok = {"status": "OK", "results": [{"formatted_address": "12 Hope Rd, Hyderabad", "geometry": {"location": {"lat": 17.39, "lng": 78.48}}}]}
    out = geocoding.geocode_address("12 Hope Road Hyderabad", ENV, transport=Fake(200, ok))
    assert (out["latitude"], out["longitude"], out["address"]) == (17.39, 78.48, "12 Hope Rd, Hyderabad")
    for payload in ({"status": "ZERO_RESULTS", "results": []}, {"status": "REQUEST_DENIED", "results": []}, None):
        with pytest.raises(MapsError) as e:
            geocoding.geocode_address("12 Hope Road Hyderabad", ENV, transport=Fake(200, payload))
        assert "SERVER-KEY" not in e.value.message


def test_raise_for_status_boundaries():
    maps_http.raise_for_status(200); maps_http.raise_for_status(204)
    for status, code in ((500, "unavailable"), (429, "unavailable"), (403, "rejected"), (404, "no_route")):
        with pytest.raises(MapsError) as e:
            maps_http.raise_for_status(status)
        assert e.value.code == code
