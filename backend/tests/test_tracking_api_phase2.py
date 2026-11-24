"""Live tracking through the real API: sessions and consent, validation, duplicate protection, pause/resume, the opt-in trail
and its admin-only audited access, and what gets broadcast (and to whom). Needs FastAPI + SQLAlchemy, like the other API tests.
Run with:  python -m pytest tests/test_tracking_api_phase2.py -q"""
import time
from datetime import timedelta

import pytest

from app import models
from app.services import events as live
from test_deliveries_api import _put_fix, _to_transit, do, env, journey_to  # noqa: F401  (env is a fixture)

VOL, ORG, DONOR, ADMIN = "vol@x.org", "org@x.org", "donor@x.org", "admin@x.org"
OUTSIDERS = ("org2@x.org", "donor2@x.org", "vol2@x.org")


def _start(client, h, tid, **body):
    return client.post(f"/deliveries/{tid}/tracking/start", headers=h(VOL), json=body or None)


def _age(db, seconds=10):
    """Move the stored fix into the past so the next one is not 'too soon'."""
    row = db.query(models.DeliveryLocation).one()
    row.recorded_at = row.recorded_at - timedelta(seconds=seconds)
    db.commit()


def _now_ms(offset_s=0):
    return int((time.time() + offset_s) * 1000)


def _events(kind):
    return [e for e in live._ring if e.type == kind]


# ------------------------------------------------------------------ sessions and consent
def test_start_creates_a_consent_record_and_returns_the_session(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "accept")
    r = _start(client, h, tid)
    assert r.status_code == 200 and r.json()["tracking_session_id"] and r.json()["retain_history"] is False
    s = db.query(models.TrackingSession).one()
    assert (s.status, s.purpose, s.retain_history) == ("active", "delivery_tracking", False)
    assert s.consent_version and s.consented_at and s.expires_at > s.consented_at


def test_a_restart_replaces_the_previous_session(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "accept")
    _start(client, h, tid); _start(client, h, tid)
    statuses = sorted(s.status for s in db.query(models.TrackingSession).all())
    assert statuses == ["active", "stopped"]


def test_a_fix_for_another_session_or_delivery_is_refused(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "accept")
    _start(client, h, tid)
    assert _put_fix(client, h, VOL, tid, tracking_session_id="00000000-0000-0000-0000-000000000000").status_code == 409
    assert _put_fix(client, h, VOL, tid, delivery_id=tid + 99).status_code == 422
    sid = db.query(models.TrackingSession).one().public_id
    assert _put_fix(client, h, VOL, tid, tracking_session_id=sid, delivery_id=tid).status_code == 200


def test_an_expired_session_stops_sharing_and_erases_the_position(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "accept")
    _start(client, h, tid); _put_fix(client, h, VOL, tid)
    s = db.query(models.TrackingSession).one(); s.expires_at = s.consented_at - timedelta(hours=1); db.commit()
    _age(db)
    assert _put_fix(client, h, VOL, tid).status_code == 409
    db.expire_all()
    assert db.query(models.TrackingSession).one().status == "expired"
    assert db.query(models.DeliveryLocation).one().latitude is None


def test_finishing_the_delivery_closes_the_session(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    _start(client, h, tid)
    assert do(client, h, VOL, tid, "deliver", note="Handed to the warden").status_code == 200
    db.expire_all()
    assert db.query(models.TrackingSession).one().status == "stopped"


# ------------------------------------------------------------------ validation
@pytest.mark.parametrize("extra", [{"heading": 400}, {"heading": -1}, {"speed": -3}, {"speed": 500}, {"timestamp": 1000},
                                   {"timestamp": _now_ms(-3600)}, {"timestamp": _now_ms(3600)}])
def test_bad_motion_or_device_time_is_rejected(env, extra):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "accept")
    _start(client, h, tid)
    assert _put_fix(client, h, VOL, tid, **extra).status_code == 422
    assert db.query(models.DeliveryLocation).one().latitude is None          # nothing was stored


def test_a_fresh_full_payload_is_accepted(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "accept")
    _start(client, h, tid)
    r = _put_fix(client, h, VOL, tid, accuracy_m=8, heading=90, speed=4.2, timestamp=_now_ms(-2), seq=0)
    assert r.status_code == 200 and r.json()["seq"] == 0


# ------------------------------------------------------------------ duplicate protection
def test_a_resent_fix_is_acknowledged_but_not_stored_or_broadcast_twice(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    _start(client, h, tid, retain_history=True)
    assert _put_fix(client, h, VOL, tid, seq=0).json().get("duplicate") is None
    again = _put_fix(client, h, VOL, tid, seq=0)                               # network retry: same seq, no 429 either
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert db.query(models.LocationHistory).count() == 1
    assert len(_events("delivery.location")) == 1


# ------------------------------------------------------------------ the opt-in trail
def test_no_trail_is_kept_unless_the_volunteer_opted_in(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    _start(client, h, tid)                                                     # no retain_history
    _put_fix(client, h, VOL, tid, seq=0)
    assert db.query(models.LocationHistory).count() == 0


def test_a_trail_is_kept_when_the_volunteer_opts_in(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    assert _start(client, h, tid, retain_history=True).json()["retain_history"] is True
    _put_fix(client, h, VOL, tid, seq=0)
    assert db.query(models.LocationHistory).count() == 1


def test_switching_history_off_means_no_trail_even_if_the_volunteer_asks_for_one(env, monkeypatch):
    client, db, h, ids = env
    monkeypatch.setenv("TRACKING_HISTORY_ENABLED", "false")
    tid = _to_transit(client, h, ids)
    assert _start(client, h, tid, retain_history=True).json()["retain_history"] is False
    _put_fix(client, h, VOL, tid, seq=0)
    assert db.query(models.LocationHistory).count() == 0


def test_only_admins_can_read_the_trail_and_every_read_is_audited(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    _start(client, h, tid, retain_history=True); _put_fix(client, h, VOL, tid, seq=0)
    for who in (ORG, DONOR, VOL, *OUTSIDERS):
        assert client.get(f"/deliveries/{tid}/history", headers=h(who)).status_code == 403, who
    r = client.get(f"/deliveries/{tid}/history", headers=h(ADMIN))
    assert r.status_code == 200 and len(r.json()["points"]) == 1 and r.json()["retention_days"] == 30
    assert db.query(models.AuditLog).filter_by(action="delivery.history_viewed").count() == 1
    client.get(f"/deliveries/{tid}/history", headers=h(ADMIN))
    assert db.query(models.AuditLog).filter_by(action="delivery.history_viewed").count() == 2


# ------------------------------------------------------------------ pause / resume / stop
def test_pausing_hides_the_position_and_refuses_fixes_until_resumed(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    _start(client, h, tid); _put_fix(client, h, VOL, tid)
    assert client.get(f"/deliveries/{tid}/location", headers=h(ORG)).json()["has_position"] is True
    assert client.post(f"/deliveries/{tid}/tracking/pause", headers=h(VOL)).json() == {"sharing": True, "paused": True}
    assert client.get(f"/deliveries/{tid}/location", headers=h(ORG)).json()["has_position"] is False
    _age(db)
    assert _put_fix(client, h, VOL, tid).status_code == 409
    assert client.post(f"/deliveries/{tid}/tracking/resume", headers=h(VOL)).json()["paused"] is False
    assert _put_fix(client, h, VOL, tid).status_code == 200


def test_only_the_assigned_volunteer_can_pause_resume_or_stop(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    _start(client, h, tid)
    for action in ("pause", "resume", "stop"):
        for who in (ORG, DONOR, ADMIN):
            assert client.post(f"/deliveries/{tid}/tracking/{action}", headers=h(who)).status_code == 403, (action, who)
        for who in OUTSIDERS:
            assert client.post(f"/deliveries/{tid}/tracking/{action}", headers=h(who)).status_code == 404, (action, who)


def test_stop_ends_the_session_and_erases_the_position(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    _start(client, h, tid); _put_fix(client, h, VOL, tid)
    assert client.post(f"/deliveries/{tid}/tracking/stop", headers=h(VOL)).json() == {"sharing": False}
    db.expire_all()
    assert db.query(models.TrackingSession).one().status == "stopped"
    assert db.query(models.DeliveryLocation).one().latitude is None


# ------------------------------------------------------------------ spoofed jumps
def test_a_teleporting_fix_is_flagged_alerted_and_never_broadcast(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    _start(client, h, tid, retain_history=True)
    _put_fix(client, h, VOL, tid, lat=17.3850, lon=78.4867, seq=0)
    _age(db, 5)
    before = len(_events("delivery.location"))
    r = _put_fix(client, h, VOL, tid, lat=28.6139, lon=77.2090, seq=1)          # Hyderabad -> Delhi in seconds
    assert r.status_code == 200
    assert [p.flagged for p in db.query(models.LocationHistory).order_by(models.LocationHistory.seq)] == [False, True]
    assert len(_events("delivery.location")) == before                          # the implausible point was not shown to anyone
    alerts = _events("risk.alert")
    assert len(alerts) == 1 and alerts[0].payload["kind"] == "location_jump" and alerts[0].audience.roles == frozenset({"admin"})
    assert db.query(models.AuditLog).filter_by(action="delivery.location_jump").count() == 1


# ------------------------------------------------------------------ what is broadcast, and to whom
def test_location_events_are_rounded_minimal_and_never_reach_outsiders_or_the_volunteer(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    _start(client, h, tid)
    _put_fix(client, h, VOL, tid, lat=17.385129, lon=78.486718, accuracy_m=7, heading=10, speed=3)
    (event,) = _events("delivery.location")
    assert event.payload["latitude"] == 17.3851 and event.payload["longitude"] == 78.4867          # ~11 m, like the HTTP view
    assert set(event.payload) <= live.SCHEMAS["delivery.location"]                                   # no heading/speed/volunteer id
    principal = lambda role, **ids_: {"id": 0, "role": role, "organization_id": None, "donor_id": None, "volunteer_id": None, **ids_}  # noqa: E731
    org_id, donor_id = db.query(models.DeliveryTask).one().org_id, db.query(models.DeliveryTask).one().donor_id
    assert event.audience.allows(principal("organization", organization_id=org_id))
    assert event.audience.allows(principal("donor", donor_id=donor_id))
    assert event.audience.allows(principal("admin"))
    assert not event.audience.allows(principal("volunteer", volunteer_id=ids["vol"]))               # the volunteer knows where they are
    assert not event.audience.allows(principal("organization", organization_id=org_id + 1))
    assert not event.audience.allows(principal("donor", donor_id=donor_id + 1))


def test_no_location_event_is_sent_before_the_delivery_leg(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "schedule_pickup")                         # accepted, not yet picked up
    _start(client, h, tid); _put_fix(client, h, VOL, tid)
    assert _events("delivery.location") == []                                  # same rule as GET /location for viewers


def test_status_changes_are_broadcast_to_the_people_involved_only(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "pick_up")
    statuses = _events("delivery.status")
    assert statuses and statuses[-1].payload["status"] == "picked_up"
    aud = statuses[-1].audience
    task = db.query(models.DeliveryTask).one()
    assert aud.org_ids == frozenset({task.org_id}) and aud.donor_ids == frozenset({task.donor_id}) and ids["vol"] in aud.volunteer_ids
    assert None not in aud.volunteer_ids


def test_a_refused_action_publishes_nothing(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "accept")
    before = len(live._ring)
    r = do(client, h, ORG, tid, "deliver", note="not the volunteer's job")       # the organization may not mark a delivery delivered
    assert r.status_code in (403, 409)
    assert len(live._ring) == before                                              # nothing was announced for an action that did not happen
    assert all(e.payload.get("status") != "delivered" for e in _events("delivery.status"))


def test_notifications_reach_only_the_recipient(env):
    client, db, h, ids = env
    journey_to(client, h, ids, "offer")
    notes = _events("notification")
    assert notes
    for e in notes:
        assert len(e.audience.user_ids) == 1 and not e.audience.roles and not e.audience.org_ids
        assert set(e.payload) <= live.SCHEMAS["notification"]


# ------------------------------------------------------------------ the stream endpoint (authentication only: a stream never ends in a test)
def test_the_event_stream_requires_a_valid_bearer_token(env):
    client, db, h, ids = env
    assert client.get("/events/stream").status_code == 401
    assert client.get("/events/stream", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert client.get("/events/stream", params={"access_token": "x"}).status_code == 401      # URL tokens are not accepted


def test_event_status_is_admin_only(env):
    client, db, h, ids = env
    assert client.get("/events/status", headers=h(ORG)).status_code == 403
    assert client.get("/events/status", headers=h(ADMIN)).json()["redis"] == "not_configured"
