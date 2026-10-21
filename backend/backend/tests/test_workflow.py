"""Admin workflow console: five-stage board, review queue, scans, resources, allocations and the audit trail."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from admin_factory import make_admin
from app import models
from app.auth import hash_password
from app.database import Base, get_db
from app.main import app

PASSWORD = "StrongPass1234!"


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k")
    monkeypatch.setenv("ADMIN_SIGNUP_CODE", "invite-123")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    now = datetime.utcnow()
    hope = models.Organization(name="Hope Home", contact="a", verified=True)
    new = models.Organization(name="New Org", contact="b", verified=False)
    db.add_all([hope, new])
    db.flush()
    books = models.Need(org_id=hope.id, category="Books", quantity=40, urgency="critical", status="open", created_at=now - timedelta(days=12))
    food = models.Need(org_id=hope.id, category="Food", quantity=10, urgency="medium", status="open")
    db.add_all([books, food])
    donor = models.Donor(name="Edu Donor", contact="e", preferences="education")
    vol = models.Volunteer(name="Tutor", contact="t", skills="teaching", availability="weekends")
    db.add_all([donor, vol, models.Child(org_id=hope.id, age=9)])
    db.flush()
    don = models.Donation(donor_id=donor.id, need_id=books.id, amount=500)
    db.add(don)
    db.flush()
    flag = models.DonationFlag(donation_id=don.id, anomaly_score=0.91, reasons=["Unusually large amount"], model_version="t")
    alert = models.NeedAlert(need_id=books.id, score=0.8, reasons=["Demand rising"], model_version="t")
    match = models.Match(need_id=books.id, donor_id=donor.id, volunteer_id=vol.id, score=0.7, reasons=["Skills match"], status="suggested")
    db.add_all([flag, alert, match])
    db.add(models.User(email="org@x.org", hashed_password=hash_password(PASSWORD), role="organization", organization_id=hope.id))
    db.commit()

    def override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        make_admin(client, "boss@x.org", PASSWORD)
        token = client.post("/admin/login", json={"email": "boss@x.org", "password": PASSWORD}).json()["access_token"]
        yield client, db, {"Authorization": f"Bearer {token}"}, {"hope": hope, "new": new, "books": books, "food": food, "donor": donor, "flag": flag, "alert": alert, "match": match}
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def add_resource(client, h, **kw):
    body = {"name": "Textbook set", "category": "books", "quantity_total": 30, "unit": "sets", **kw}
    res = client.post("/resources/", headers=h, json=body)
    assert res.status_code == 201, res.text
    return res.json()


def test_workflow_board_follows_the_five_stages_with_live_numbers(world):
    client, db, h, o = world
    add_resource(client, h)
    data = client.get("/admin/workflow", headers=h).json()
    assert [s["key"] for s in data["stages"]] == ["input", "processing", "decision", "action", "outcomes"]
    by = {i["key"]: i for s in data["stages"] for i in s["items"]}
    assert by["organizations"]["count"] == 2 and "1 verified" in by["organizations"]["detail"]
    assert by["children"]["count"] == 1 and by["donors"]["count"] == 1 and by["resources"]["count"] == 1
    assert by["fraud"]["count"] == 1 and by["predict"]["count"] == 1 and by["matching"]["count"] == 1
    assert by["review"]["count"] == data["pending"]["total"] == 4 + 0  # org, fraud, alert, match
    assert data["pending"]["by_type"] == {"organization": 1, "fraud_flag": 1, "need_alert": 1, "match": 1}


def test_review_queue_lists_every_decision_and_each_one_is_audited(world):
    client, db, h, o = world
    q = client.get("/admin/review-queue", headers=h).json()
    assert [i["type"] for i in q["items"]] == ["fraud_flag", "need_alert", "organization", "match"]  # most serious first
    assert q["items"][0]["decisions"] == ["confirmed_fraud", "false_positive"]
    assert client.get("/admin/review-queue?type=match", headers=h).json()["total"] == 4  # total ignores the filter
    assert [i["type"] for i in client.get("/admin/review-queue?type=match", headers=h).json()["items"]] == ["match"]

    d = lambda t, i, dec: client.post(f"/admin/review-queue/{t}/{i}", headers=h, json={"decision": dec})  # noqa: E731
    assert d("fraud_flag", o["flag"].id, "approved").status_code == 422  # wrong vocabulary for this type
    assert d("nothing", 1, "x").status_code == 404 and d("match", 999, "confirmed").status_code == 404
    assert d("fraud_flag", o["flag"].id, "confirmed_fraud").status_code == 200
    assert d("need_alert", o["alert"].id, "action_taken").status_code == 200
    assert d("organization", o["new"].id, "verify").status_code == 200
    assert d("match", o["match"].id, "confirmed").status_code == 200
    db.expire_all()
    assert o["flag"].review_decision == "confirmed_fraud" and o["new"].verified and o["match"].status == "confirmed"
    assert client.get("/admin/review-queue", headers=h).json()["total"] == 0
    trail = client.get("/admin/audit", headers=h).json()
    assert {"fraud.reviewed", "need_alert.reviewed", "organization.verified", "match.reviewed"} <= {r["action"] for r in trail["items"]}
    assert all(r["actor_email"] == "boss@x.org" for r in trail["items"] if r["action"].endswith(".reviewed"))


def test_queue_and_workflow_are_admin_only(world):
    client, db, h, o = world
    tok = client.post("/auth/login", json={"email": "org@x.org", "password": PASSWORD}).json()["access_token"]
    oh = {"Authorization": f"Bearer {tok}"}
    for path in ("/admin/workflow", "/admin/review-queue", "/admin/audit", "/admin/allocations"):
        assert client.get(path, headers=oh).status_code == 403
        assert client.get(path).status_code == 401


def test_run_scans_does_everything_in_one_click(world):
    client, db, h, o = world
    add_resource(client, h)
    s = client.post("/admin/workflow/run-scans", headers=h)
    assert s.status_code == 200, s.text
    body = s.json()
    assert body["donor_suggestions"] >= 1 and body["resource_proposals"] >= 1 and "new_fraud_flags" in body
    assert db.query(models.ResourceAllocation).filter_by(status="proposed").count() >= 1
    assert "ai.scans_run" in {a.action for a in db.query(models.AuditLog).all()}


def test_resource_allocation_lifecycle_updates_stock_and_fulfils_the_need(world):
    client, db, h, o = world
    res = add_resource(client, h, quantity_total=40)
    sug = client.post(f"/admin/needs/{o['books'].id}/suggest-resources", headers=h).json()
    assert sug["allocations"][0]["resource_name"] == "Textbook set" and sug["allocations"][0]["quantity"] == 40
    alloc = sug["allocations"][0]
    assert client.post(f"/admin/needs/{o['food'].id}/suggest-resources", headers=h).json()["allocations"] == []  # nothing fits food

    rv = lambda dec: client.post(f"/admin/allocations/{alloc['id']}/review", headers=h, json={"decision": dec})  # noqa: E731
    assert rv("delivered").status_code == 409  # must be approved first
    assert rv("approved").status_code == 200
    stock = lambda: [r for r in client.get("/resources/", headers=h).json() if r["id"] == res["id"]][0]  # noqa: E731
    assert stock()["quantity_available"] == 0 and stock()["allocated"] == 40
    assert rv("approved").status_code == 409  # already approved
    assert rv("cancelled").status_code == 200 and stock()["quantity_available"] == 40  # stock returns
    # propose again, approve and deliver: the need is fulfilled
    alloc2 = client.post(f"/admin/needs/{o['books'].id}/suggest-resources", headers=h).json()["allocations"][0]
    assert client.post(f"/admin/allocations/{alloc2['id']}/review", headers=h, json={"decision": "approved"}).status_code == 200
    assert client.post(f"/admin/allocations/{alloc2['id']}/review", headers=h, json={"decision": "delivered"}).status_code == 200
    db.expire_all()
    assert o["books"].status == "fulfilled"
    acts = {a.action for a in db.query(models.AuditLog).all()}
    assert {"resource.created", "allocation.approved", "allocation.cancelled", "allocation.delivered", "need.fulfilled"} <= acts
    assert client.post(f"/admin/needs/{o['books'].id}/suggest-resources", headers=h).status_code == 409  # closed need


def test_manual_allocation_and_queue_decision_for_allocations(world):
    client, db, h, o = world
    res = add_resource(client, h, quantity_total=10)
    bad = client.post("/admin/allocations", headers=h, json={"resource_id": res["id"], "need_id": o["books"].id, "quantity": 99})
    assert bad.status_code == 422
    made = client.post("/admin/allocations", headers=h, json={"resource_id": res["id"], "need_id": o["books"].id, "quantity": 5})
    assert made.status_code == 201 and made.json()["status"] == "proposed"
    q = client.get("/admin/review-queue?type=allocation", headers=h).json()["items"]
    assert q[0]["decisions"] == ["approved", "rejected"]
    assert client.post(f"/admin/review-queue/allocation/{q[0]['id']}", headers=h, json={"decision": "approved"}).status_code == 200


def test_organizations_manage_only_their_own_resources(world):
    client, db, h, o = world
    tok = client.post("/auth/login", json={"email": "org@x.org", "password": PASSWORD}).json()["access_token"]
    oh = {"Authorization": f"Bearer {tok}"}
    mine = client.post("/resources/", headers=oh, json={"name": "Meals", "category": "food", "quantity_total": 5, "organization_id": o["new"].id}).json()
    assert mine["organization_id"] == o["hope"].id  # the body cannot choose another organization
    other = add_resource(client, h, organization_id=o["new"].id)
    assert [r["id"] for r in client.get("/resources/", headers=oh).json()] == [mine["id"]]
    assert client.patch(f"/resources/{other['id']}", headers=oh, json={"name": "x"}).status_code == 404
    assert client.delete(f"/resources/{other['id']}", headers=oh).status_code == 404
    assert len(client.get("/resources/", headers=h).json()) == 2  # the administrator sees all
    donor_user = models.User(email="d@x.org", hashed_password=hash_password(PASSWORD), role="donor")
    db.add(donor_user)
    db.commit()
    dt = client.post("/auth/login", json={"email": "d@x.org", "password": PASSWORD}).json()["access_token"]
    assert client.get("/resources/", headers={"Authorization": f"Bearer {dt}"}).status_code == 403
    # cannot shrink below what is already allocated; cannot delete allocated stock
    alloc = client.post("/admin/allocations", headers=h, json={"resource_id": other["id"], "need_id": o["books"].id, "quantity": 20}).json()
    client.post(f"/admin/allocations/{alloc['id']}/review", headers=h, json={"decision": "approved"})
    assert client.patch(f"/resources/{other['id']}", headers=h, json={"quantity_total": 10}).status_code == 409
    assert client.delete(f"/resources/{other['id']}", headers=h).status_code == 409


def test_audit_trail_filters_and_is_append_only(world):
    client, db, h, o = world
    client.post("/auth/login", json={"email": "org@x.org", "password": "wrong-password-1"})
    all_ = client.get("/admin/audit", headers=h).json()
    assert all_["total"] >= 3 and "auth.login_failed" in all_["actions"]
    failed = client.get("/admin/audit?action=auth.login_failed", headers=h).json()
    assert failed["items"] and all(r["action"] == "auth.login_failed" for r in failed["items"])
    assert all(r["ip"] for r in all_["items"])
    assert client.get("/admin/audit?search=boss@x.org", headers=h).json()["total"] >= 1
    page = client.get("/admin/audit?limit=1&offset=1", headers=h).json()
    assert len(page["items"]) == 1
    # there is deliberately no way to change or remove an entry
    assert client.delete("/admin/audit/1", headers=h).status_code in (404, 405)
    assert client.patch("/admin/audit/1", headers=h, json={}).status_code in (404, 405)
