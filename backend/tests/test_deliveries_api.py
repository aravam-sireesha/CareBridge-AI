"""Delivery workflow through the API, with four real accounts. Run with:  python -m pytest tests/test_deliveries_api.py -q"""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.auth import hash_password
from app.database import Base, get_db
from app.main import app

PW = "StrongPass1234"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 40)
    monkeypatch.delenv("DELIVERY_APPROVAL_REQUIRED", raising=False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    org = models.Organization(name="Hope Home", verified=True, address="12 Hope Road")
    org2 = models.Organization(name="Other Home", verified=True)
    db.add_all([org, org2]); db.flush()
    donor = models.Donor(name="Dana", organization_id=org.id, location="Banjara Hills")
    donor2 = models.Donor(name="Stranger Donor", organization_id=org2.id)
    vol = models.Volunteer(name="Vik", organization_id=org.id)
    vol2 = models.Volunteer(name="Other Vol", organization_id=org2.id)
    db.add_all([donor, donor2, vol, vol2]); db.flush()
    need = models.Need(org_id=org.id, category="food", quantity=100, urgency="high", status="open", title="Meals")
    need2 = models.Need(org_id=org2.id, category="food", quantity=10, status="open")
    db.add_all([need, need2]); db.flush()
    users = [("admin@x.org", "admin", {}), ("org@x.org", "organization", {"organization_id": org.id}), ("org2@x.org", "organization", {"organization_id": org2.id}),
             ("donor@x.org", "donor", {"donor_id": donor.id}), ("donor2@x.org", "donor", {"donor_id": donor2.id}),
             ("vol@x.org", "volunteer", {"volunteer_id": vol.id}), ("vol2@x.org", "volunteer", {"volunteer_id": vol2.id})]
    for email, role, links in users:
        db.add(models.User(email=email, hashed_password=hash_password(PW), role=role, **links))
    db.commit()
    ids = dict(org=org.id, donor=donor.id, vol=vol.id, vol2=vol2.id, need=need.id, need2=need2.id)

    def override():
        yield db
    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        cache = {}

        def h(email):
            if email not in cache:
                cache[email] = {"Authorization": "Bearer " + client.post("/auth/login", json={"email": email, "password": PW}).json()["access_token"]}
            return cache[email]
        yield client, db, h, ids
    app.dependency_overrides.clear(); db.close(); engine.dispose()


def propose(client, h, ids, qty=40):
    r = client.post("/deliveries/", headers=h("org@x.org"), json={"need_id": ids["need"], "donor_id": ids["donor"], "quantity": qty, "item_description": "Rice"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def do(client, h, who, tid, action, **body):
    return client.post(f"/deliveries/{tid}/actions/{action}", headers=h(who), json=body)


def journey_to(client, h, ids, stop):
    """Walk a delivery through the real API up to (and including) the named action."""
    tid = propose(client, h, ids)
    steps = [("org@x.org", "submit", {}), ("admin@x.org", "approve", {}), ("donor@x.org", "commit", {}), ("org@x.org", "offer", {"volunteer_id": ids["vol"]}),
             ("vol@x.org", "accept", {}), ("vol@x.org", "schedule_pickup", {"pickup_at": (datetime.utcnow() + timedelta(days=1)).isoformat()}),
             ("vol@x.org", "pick_up", {}), ("vol@x.org", "start_transit", {}), ("vol@x.org", "deliver", {"note": "Handed to the warden"}),
             ("org@x.org", "confirm_receipt", {"received_quantity": 40})]
    for who, action, body in steps:
        r = do(client, h, who, tid, action, **body)
        assert r.status_code == 200, (action, r.text)
        if action == stop:
            break
    return tid


def test_full_journey_records_every_actor_and_ends_confirmed(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "confirm_receipt")
    final = client.get(f"/deliveries/{tid}", headers=h("org@x.org")).json()
    assert final["status"] == "receipt_confirmed" and final["received_quantity"] == 40
    assert [e["to"] for e in final["events"]] == ["proposed", "awaiting_approval", "approved", "committed", "offered", "accepted", "pickup_scheduled", "picked_up", "in_transit", "delivered", "receipt_confirmed"]
    assert [e["actor_role"] for e in final["events"]][:4] == ["organization", "organization", "admin", "donor"]
    assert all(final["milestones"][k] for k in ("submitted_at", "decided_at", "committed_at", "accepted_at", "picked_up_at", "in_transit_at", "delivered_at", "confirmed_at"))


def test_a_recommendation_alone_never_assigns_a_volunteer(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "offer")
    task = db.get(models.DeliveryTask, tid)
    assert task.status == "offered" and task.accepted_at is None
    assert do(client, h, "vol@x.org", tid, "pick_up").status_code == 409            # cannot act before accepting
    assert do(client, h, "org@x.org", tid, "accept").status_code == 403


def test_unapproved_work_cannot_proceed(env):
    client, db, h, ids = env
    tid = propose(client, h, ids); do(client, h, "org@x.org", tid, "submit")
    assert do(client, h, "donor@x.org", tid, "commit").status_code == 409
    assert do(client, h, "org@x.org", tid, "approve").status_code == 403
    assert do(client, h, "admin@x.org", tid, "reject").status_code == 422           # a reason is required
    assert do(client, h, "admin@x.org", tid, "reject", reason="Quantity looks too high").json()["status"] == "rejected"


def test_approval_can_be_switched_off_by_policy(env, monkeypatch):
    client, db, h, ids = env
    monkeypatch.setenv("DELIVERY_APPROVAL_REQUIRED", "false")
    tid = propose(client, h, ids)
    assert do(client, h, "org@x.org", tid, "submit").json()["status"] == "approved"


def test_quantity_can_never_exceed_what_the_need_requires(env):
    client, db, h, ids = env
    propose(client, h, ids, 60)
    r = client.post("/deliveries/", headers=h("org@x.org"), json={"need_id": ids["need"], "donor_id": ids["donor"], "quantity": 41})
    assert r.status_code == 422 and "40" in r.json()["detail"]
    assert client.post("/deliveries/", headers=h("org@x.org"), json={"need_id": ids["need"], "donor_id": ids["donor"], "quantity": 40}).status_code == 201
    for bad in (0, -5, "ten", 2.5):
        assert client.post("/deliveries/", headers=h("org@x.org"), json={"need_id": ids["need"], "donor_id": ids["donor"], "quantity": bad}).status_code == 422


def test_a_cancelled_delivery_frees_its_quantity(env):
    client, db, h, ids = env
    tid = propose(client, h, ids, 100)
    assert client.post("/deliveries/", headers=h("org@x.org"), json={"need_id": ids["need"], "donor_id": ids["donor"], "quantity": 1}).status_code == 422
    assert do(client, h, "org@x.org", tid, "cancel", reason="Donor unavailable").status_code == 200
    assert client.post("/deliveries/", headers=h("org@x.org"), json={"need_id": ids["need"], "donor_id": ids["donor"], "quantity": 100}).status_code == 201


def test_receipt_confirmation_counts_once_and_closes_the_need_only_when_fully_received(env):
    client, db, h, ids = env
    journey_to(client, h, ids, "confirm_receipt")
    assert db.get(models.Need, ids["need"]).status == "open"                        # 40 of 100 received
    impact = client.get("/deliveries/impact", headers=h("org@x.org")).json()
    assert impact["quantities"]["confirmed"] == 40 and impact["counts"]["confirmed"] == 1
    t2 = propose(client, h, ids, 60)
    for who, action, body in [("org@x.org", "submit", {}), ("admin@x.org", "approve", {}), ("donor@x.org", "commit", {}), ("org@x.org", "offer", {"volunteer_id": ids["vol"]}), ("vol@x.org", "accept", {}),
                              ("vol@x.org", "schedule_pickup", {"pickup_at": (datetime.utcnow() + timedelta(days=1)).isoformat()}), ("vol@x.org", "pick_up", {}), ("vol@x.org", "start_transit", {}),
                              ("vol@x.org", "deliver", {"note": "Delivered to reception"}), ("org@x.org", "confirm_receipt", {"received_quantity": 60})]:
        assert do(client, h, who, t2, action, **body).status_code == 200
    need = db.get(models.Need, ids["need"])
    assert need.status == "fulfilled" and need.fulfilled_at is not None
    assert client.get("/deliveries/impact", headers=h("admin@x.org")).json()["quantities"]["confirmed"] == 100   # 40 + 60, not 140


def test_a_receipt_with_a_different_quantity_needs_a_note_and_the_confirmed_total_uses_what_arrived(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "deliver")
    assert do(client, h, "org@x.org", tid, "confirm_receipt", received_quantity=30).status_code == 422
    res = do(client, h, "org@x.org", tid, "confirm_receipt", received_quantity=30, note="Ten bags were torn").json()
    assert res["quantity_mismatch"] is True
    assert client.get("/deliveries/impact", headers=h("admin@x.org")).json()["quantities"]["confirmed"] == 30


def test_volunteer_sees_no_addresses_until_they_accept_and_none_after_the_job(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "offer")
    offered = client.get(f"/deliveries/{tid}", headers=h("vol@x.org")).json()
    assert offered["pickup_area"] is None and offered["delivery_area"] is None and offered["donor"] is None
    do(client, h, "vol@x.org", tid, "accept")
    accepted = client.get(f"/deliveries/{tid}", headers=h("vol@x.org")).json()
    assert accepted["pickup_area"] == "Banjara Hills" and accepted["delivery_area"] == "12 Hope Road" and accepted["donor"]["name"] == "Dana"
    for who, action, body in [("vol@x.org", "schedule_pickup", {"pickup_at": (datetime.utcnow() + timedelta(days=1)).isoformat()}), ("vol@x.org", "pick_up", {}), ("vol@x.org", "start_transit", {}),
                              ("vol@x.org", "deliver", {"note": "Handed over"}), ("org@x.org", "confirm_receipt", {"received_quantity": 40})]:
        do(client, h, who, tid, action, **body)
    done = client.get(f"/deliveries/{tid}", headers=h("vol@x.org")).json()
    assert done["pickup_area"] is None and done["delivery_area"] is None


def test_strangers_cannot_see_or_touch_a_delivery_and_cannot_tell_it_exists(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "accept")
    for who in ("org2@x.org", "donor2@x.org", "vol2@x.org"):
        assert client.get(f"/deliveries/{tid}", headers=h(who)).status_code == 404
        assert do(client, h, who, tid, "cancel", reason="spiteful").status_code == 404
        assert client.get("/deliveries/", headers=h(who)).json() == []
    assert client.get(f"/deliveries/{99999}", headers=h("org@x.org")).status_code == 404


def test_donors_and_volunteers_cannot_propose_and_organizations_only_use_their_own_needs_and_people(env):
    client, db, h, ids = env
    body = {"need_id": ids["need"], "donor_id": ids["donor"], "quantity": 5}
    for who in ("donor@x.org", "vol@x.org"):
        assert client.post("/deliveries/", headers=h(who), json=body).status_code == 403
    assert client.post("/deliveries/", headers=h("org2@x.org"), json=body).status_code == 404                       # someone else's need
    other_donor = {**body, "donor_id": db.query(models.Donor).filter_by(name="Stranger Donor").one().id}
    assert client.post("/deliveries/", headers=h("org@x.org"), json=other_donor).status_code == 422               # not linked to this org


def test_a_recommended_donor_from_a_match_can_be_used(env):
    client, db, h, ids = env
    outsider = models.Donor(name="Recommended", organization_id=None); db.add(outsider); db.flush()
    db.add(models.Match(need_id=ids["need"], donor_id=outsider.id, score=0.9, reasons=["category"])); db.commit()
    assert client.post("/deliveries/", headers=h("org@x.org"), json={"need_id": ids["need"], "donor_id": outsider.id, "quantity": 5}).status_code == 201
    names = [d["name"] for d in client.get(f"/deliveries/candidates/{ids['need']}", headers=h("org@x.org")).json()["donors"]]
    assert "Recommended" in names and "Stranger Donor" not in names


def test_an_unverified_organization_cannot_arrange_deliveries(env):
    client, db, h, ids = env
    db.get(models.Organization, ids["org"]).verified = False; db.commit()
    r = client.post("/deliveries/", headers=h("org@x.org"), json={"need_id": ids["need"], "donor_id": ids["donor"], "quantity": 5})
    assert r.status_code == 409


def test_problems_go_to_administrators_who_resolve_them(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "pick_up")
    assert do(client, h, "vol@x.org", tid, "raise_exception").status_code == 422                                    # reason required
    assert do(client, h, "vol@x.org", tid, "raise_exception", reason="Boxes were damaged").json()["status"] == "exception"
    assert db.query(models.Notification).filter(models.Notification.user_id == db.query(models.User).filter_by(email="admin@x.org").one().id).count() >= 1
    assert do(client, h, "org@x.org", tid, "resolve_exception", resolution="cancel").status_code == 403
    assert do(client, h, "admin@x.org", tid, "resolve_exception", resolution="reoffer").status_code == 409         # already collected
    assert do(client, h, "admin@x.org", tid, "resolve_exception", resolution="resume", note="Replaced the boxes").json()["status"] == "picked_up"


def test_a_volunteer_stepping_back_returns_the_task_for_reassignment(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "accept")
    res = do(client, h, "vol@x.org", tid, "withdraw", reason="Family emergency").json()
    assert res["status"] == "committed" and res["volunteer"] is None
    assert db.get(models.DeliveryTask, tid).volunteer_id is None
    assert do(client, h, "org@x.org", tid, "offer", volunteer_id=ids["vol"]).json()["status"] == "offered"


def test_the_ui_is_only_offered_actions_the_server_accepts(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "offer")
    for who in ("org@x.org", "donor@x.org", "vol@x.org", "admin@x.org"):
        for a in client.get(f"/deliveries/{tid}", headers=h(who)).json()["allowed_actions"]:
            probe = {"reason": "A good reason", "note": "A good note", "volunteer_id": ids["vol"], "received_quantity": 40, "resolution": "cancel", "pickup_at": (datetime.utcnow() + timedelta(days=1)).isoformat()}
            assert do(client, h, who, tid, a["action"], **probe).status_code in (200,), (who, a["action"])
            break    # one probe per person: the state changes after each


def test_impact_is_scoped_to_the_caller(env):
    client, db, h, ids = env
    journey_to(client, h, ids, "confirm_receipt")
    assert client.get("/deliveries/impact", headers=h("org@x.org")).json()["quantities"]["confirmed"] == 40
    assert client.get("/deliveries/impact", headers=h("org2@x.org")).json()["quantities"]["confirmed"] == 0
    assert client.get("/deliveries/impact", headers=h("vol2@x.org")).json()["counts"]["total"] == 0


# ------------------------------------------------------------------ live tracking and navigation points
from datetime import timedelta as _td


def _put_fix(client, h, who, tid, lat=17.385129, lon=78.486718, **extra):
    return client.put(f"/deliveries/{tid}/location", headers=h(who), json={"latitude": lat, "longitude": lon, **extra})


def _to_transit(client, h, ids):
    tid = journey_to(client, h, ids, "start_transit")
    return tid


def test_nothing_is_stored_until_the_volunteer_opts_in(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "accept")
    assert db.query(models.DeliveryLocation).count() == 0
    assert _put_fix(client, h, "vol@x.org", tid).status_code == 409                         # must start sharing first
    assert client.post(f"/deliveries/{tid}/tracking/start", headers=h("vol@x.org")).status_code == 200
    assert _put_fix(client, h, "vol@x.org", tid).status_code == 200


def test_only_the_assigned_volunteer_can_start_or_report(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "accept")
    for who in ("org@x.org", "donor@x.org", "admin@x.org"):
        assert client.post(f"/deliveries/{tid}/tracking/start", headers=h(who)).status_code == 403
    for who in ("org2@x.org", "donor2@x.org", "vol2@x.org"):
        assert client.post(f"/deliveries/{tid}/tracking/start", headers=h(who)).status_code == 404       # strangers do not learn it exists
        assert _put_fix(client, h, who, tid).status_code == 404


def test_cannot_share_before_accepting(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "offer")
    assert client.post(f"/deliveries/{tid}/tracking/start", headers=h("vol@x.org")).status_code == 409


def test_positions_are_validated_and_rate_limited(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "accept")
    client.post(f"/deliveries/{tid}/tracking/start", headers=h("vol@x.org"))
    for bad in ({"latitude": 91, "longitude": 10}, {"latitude": 0, "longitude": 0}, {"latitude": "x", "longitude": 1}, {"latitude": 17.3, "longitude": 78.4, "accuracy_m": 99999}):
        assert client.put(f"/deliveries/{tid}/location", headers=h("vol@x.org"), json=bad).status_code == 422
    assert _put_fix(client, h, "vol@x.org", tid).status_code == 200
    again = _put_fix(client, h, "vol@x.org", tid)
    assert again.status_code == 429 and int(again.headers["Retry-After"]) >= 1


def test_organization_and_donor_see_the_position_only_during_the_delivery_leg_and_rounded(env):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "schedule_pickup")
    client.post(f"/deliveries/{tid}/tracking/start", headers=h("vol@x.org")); _put_fix(client, h, "vol@x.org", tid)
    for who in ("org@x.org", "donor@x.org", "admin@x.org"):
        assert client.get(f"/deliveries/{tid}/location", headers=h(who)).json() == {"sharing": False, "has_position": False}      # not yet picked up
    own = client.get(f"/deliveries/{tid}/location", headers=h("vol@x.org")).json()
    assert own["has_position"] and own["latitude"] == 17.385129                                                                   # the volunteer sees their own exact fix
    do(client, h, "vol@x.org", tid, "pick_up")
    seen = client.get(f"/deliveries/{tid}/location", headers=h("org@x.org")).json()
    assert seen["has_position"] and (seen["latitude"], seen["longitude"]) == (17.3851, 78.4867) and seen["stale"] is False


def test_a_missing_or_old_position_is_never_shown_as_live(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    client.post(f"/deliveries/{tid}/tracking/start", headers=h("vol@x.org"))
    assert client.get(f"/deliveries/{tid}/location", headers=h("org@x.org")).json()["has_position"] is False       # sharing, but no fix yet
    _put_fix(client, h, "vol@x.org", tid)
    row = db.query(models.DeliveryLocation).one(); row.recorded_at = row.recorded_at - _td(minutes=10); db.commit()
    old = client.get(f"/deliveries/{tid}/location", headers=h("org@x.org")).json()
    assert old["stale"] is True and old["age_seconds"] >= 600


def test_strangers_and_other_roles_never_see_a_position(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    client.post(f"/deliveries/{tid}/tracking/start", headers=h("vol@x.org")); _put_fix(client, h, "vol@x.org", tid)
    for who in ("org2@x.org", "donor2@x.org", "vol2@x.org"):
        assert client.get(f"/deliveries/{tid}/location", headers=h(who)).status_code == 404


def test_stopping_erases_the_position_immediately(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    client.post(f"/deliveries/{tid}/tracking/start", headers=h("vol@x.org")); _put_fix(client, h, "vol@x.org", tid)
    assert client.post(f"/deliveries/{tid}/tracking/stop", headers=h("org@x.org")).status_code == 403
    assert client.post(f"/deliveries/{tid}/tracking/stop", headers=h("vol@x.org")).json() == {"sharing": False}
    row = db.query(models.DeliveryLocation).one()
    assert row.latitude is None and row.longitude is None and row.stopped_at is not None
    assert client.get(f"/deliveries/{tid}/location", headers=h("org@x.org")).json()["has_position"] is False
    assert _put_fix(client, h, "vol@x.org", tid).status_code == 409


def test_the_position_is_deleted_when_the_delivery_ends_or_the_volunteer_steps_back(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    client.post(f"/deliveries/{tid}/tracking/start", headers=h("vol@x.org")); _put_fix(client, h, "vol@x.org", tid)
    do(client, h, "vol@x.org", tid, "deliver", note="Handed to the warden")
    assert db.query(models.DeliveryLocation).count() == 0
    tid2 = journey_to(client, h, ids, "accept")
    client.post(f"/deliveries/{tid2}/tracking/start", headers=h("vol@x.org"))
    do(client, h, "vol@x.org", tid2, "withdraw", reason="Family emergency")
    assert db.query(models.DeliveryLocation).filter_by(task_id=tid2).count() == 0


def test_navigation_points_follow_the_same_stage_rules_as_addresses(env):
    client, db, h, ids = env
    db.get(models.Donor, ids["donor"]).latitude, db.get(models.Donor, ids["donor"]).longitude = 17.40, 78.45
    db.get(models.Organization, ids["org"]).latitude, db.get(models.Organization, ids["org"]).longitude = 17.385, 78.4867; db.commit()
    tid = journey_to(client, h, ids, "offer")
    offered = client.get(f"/deliveries/{tid}", headers=h("vol@x.org")).json()
    assert offered["points"] == {"pickup": None, "delivery": None}                       # nothing before they accept
    do(client, h, "vol@x.org", tid, "accept")
    accepted = client.get(f"/deliveries/{tid}", headers=h("vol@x.org")).json()
    assert accepted["points"]["pickup"]["latitude"] == 17.40 and accepted["points"]["delivery"]["latitude"] == 17.385
    org_view = client.get(f"/deliveries/{tid}", headers=h("org@x.org")).json()
    assert org_view["points"]["pickup"] is None and org_view["points"]["delivery"] is not None      # the organization never gets the donor's coordinates
    assert accepted["tracking"] == {"can_share": True, "sharing": False, "can_watch": False}


def test_the_audit_trail_records_start_and_stop_but_never_a_position(env):
    client, db, h, ids = env
    tid = _to_transit(client, h, ids)
    client.post(f"/deliveries/{tid}/tracking/start", headers=h("vol@x.org")); _put_fix(client, h, "vol@x.org", tid, lat=17.385129, lon=78.486718)
    client.post(f"/deliveries/{tid}/tracking/stop", headers=h("vol@x.org"))
    rows = db.query(models.AuditLog).filter(models.AuditLog.action.like("delivery.tracking_%")).all()
    assert {r.action for r in rows} == {"delivery.tracking_started", "delivery.tracking_stopped"}
    assert "17.385" not in repr([r.detail for r in rows])


# ------------------------------------------------------------------ capacity and conflicts in the delivery flow
def _propose_weight(client, h, ids, kg, qty=10):
    r = client.post("/deliveries/", headers=h("org@x.org"), json={"need_id": ids["need"], "donor_id": ids["donor"], "quantity": qty, "estimated_weight_kg": kg})
    assert r.status_code == 201, r.text
    return r.json()["id"], r.json()


def _to_committed(client, h, tid):
    for who, action in (("org@x.org", "submit"), ("admin@x.org", "approve"), ("donor@x.org", "commit")):
        assert do(client, h, who, tid, action).status_code == 200


def test_the_weight_is_validated_and_shown(env):
    client, db, h, ids = env
    for bad in (0, -2, 99999, "heavy"):
        assert client.post("/deliveries/", headers=h("org@x.org"), json={"need_id": ids["need"], "donor_id": ids["donor"], "quantity": 5, "estimated_weight_kg": bad}).status_code == 422
    tid, body = _propose_weight(client, h, ids, 25.5)
    assert body["estimated_weight_kg"] == 25.5


def test_offering_a_heavy_delivery_to_a_volunteer_with_a_smaller_declared_capacity_is_refused(env):
    client, db, h, ids = env
    db.query(models.Volunteer).filter_by(name="Vik").one().carry_capacity_kg = 20.0; db.commit()
    tid, _ = _propose_weight(client, h, ids, 45.0); _to_committed(client, h, tid)
    res = do(client, h, "org@x.org", tid, "offer", volunteer_id=ids["vol"])
    assert res.status_code == 422 and "20 kg" in res.json()["detail"] and "self-declared" in res.json()["detail"]
    db.query(models.Volunteer).filter_by(name="Vik").one().carry_capacity_kg = 60.0; db.commit()
    assert do(client, h, "org@x.org", tid, "offer", volunteer_id=ids["vol"]).status_code == 200


def test_unknown_capacity_or_weight_never_blocks_an_offer(env):
    client, db, h, ids = env
    tid, _ = _propose_weight(client, h, ids, 45.0); _to_committed(client, h, tid)
    assert do(client, h, "org@x.org", tid, "offer", volunteer_id=ids["vol"]).status_code == 200          # volunteer declared nothing


def test_a_volunteer_cannot_hold_two_pickups_at_nearly_the_same_time(env):
    client, db, h, ids = env
    base = datetime.utcnow() + timedelta(days=2)
    first = journey_to(client, h, ids, "accept")
    assert do(client, h, "vol@x.org", first, "schedule_pickup", pickup_at=base.isoformat()).status_code == 200
    second = journey_to(client, h, ids, "accept")
    clash = do(client, h, "vol@x.org", second, "schedule_pickup", pickup_at=(base + timedelta(minutes=60)).isoformat())
    assert clash.status_code == 409 and "already has another pickup" in clash.json()["detail"]
    assert do(client, h, "vol@x.org", second, "schedule_pickup", pickup_at=(base + timedelta(hours=3)).isoformat()).status_code == 200


def test_a_donor_cannot_book_outside_the_hours_the_volunteer_declared_but_the_volunteer_can(env):
    client, db, h, ids = env
    when = datetime.utcnow() + timedelta(days=3)
    v = db.query(models.Volunteer).filter_by(name="Vik").one()
    v.availability_timezone = "UTC"; v.availability_slots = [{"weekday": (when.weekday() + 1) % 7, "start": "09:00", "end": "17:00"}]; db.commit()   # a different day
    tid = journey_to(client, h, ids, "accept")
    res = do(client, h, "donor@x.org", tid, "schedule_pickup", pickup_at=when.isoformat())
    assert res.status_code == 422 and "outside the hours" in res.json()["detail"]
    assert do(client, h, "vol@x.org", tid, "schedule_pickup", pickup_at=when.isoformat()).status_code == 200
