"""Integration tests for: deactivation, role-change audit, verification workflow, notifications, user admin, bulk upload,
reports, public data, children summary. Same harness style as test_administration.py (in-memory SQLite)."""
import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from admin_factory import make_admin
from app import models
from app.database import Base, get_db
from app.main import app

PASSWORD = "StrongPass1234"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("ADMIN_SIGNUP_CODE", "invite-123")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()

    def override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        yield client, db
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def hdr(res):
    assert res.status_code in (200, 201), res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def admin(client, email="boss@carebridge.org"):
    assert make_admin(client, email, PASSWORD).status_code == 201
    return hdr(client.post("/admin/login", json={"email": email, "password": PASSWORD}))


def signup(client, role, email, **extra):
    body = {"email": email, "password": PASSWORD, "role": role, **extra}
    assert client.post("/auth/register", json=body).status_code == 201
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return hdr(res), res.json()["user"]


def test_deactivated_account_is_locked_out_immediately(api):
    client, db = api
    a = admin(client)
    donor_h, donor = signup(client, "donor", "d@x.org", name="Dee")
    assert client.get("/auth/me", headers=donor_h).status_code == 200
    assert client.patch(f"/admin/users/{donor['id']}/status", json={"is_active": False, "reason": "test"}, headers=a).status_code == 200
    assert client.get("/auth/me", headers=donor_h).status_code == 401                       # the old token stops working
    assert client.post("/auth/login", json={"email": "d@x.org", "password": PASSWORD}).status_code == 403
    assert client.post("/auth/login", json={"email": "d@x.org", "password": "wrong-password-1"}).status_code == 401   # no hint without the password
    assert client.patch(f"/admin/users/{donor['id']}/status", json={"is_active": True}, headers=a).status_code == 200
    assert client.post("/auth/login", json={"email": "d@x.org", "password": PASSWORD}).status_code == 200
    actions = [r.action for r in db.query(models.AuditLog).all()]
    assert "user.deactivated" in actions and "user.reactivated" in actions


def test_user_admin_guards(api):
    client, db = api
    a = admin(client)
    me = db.query(models.User).filter_by(email="boss@carebridge.org").one()
    assert client.patch(f"/admin/users/{me.id}/status", json={"is_active": False}, headers=a).status_code == 409   # not yourself / not an admin
    org_h, _ = signup(client, "organization", "o@x.org", organization_name="Hope")
    assert client.get("/admin/users/", headers=org_h).status_code == 403
    listing = client.get("/admin/users/?q=hope&role=organization", headers=a).json()
    assert listing["total"] == 1 and "hashed_password" not in listing["items"][0] and "token_version" not in listing["items"][0]
    assert client.get("/admin/users/?role=root", headers=a).status_code == 422


def test_role_change_is_audited_and_signs_the_person_out(api):
    client, db = api
    a = admin(client)
    donor_h, donor = signup(client, "donor", "d@x.org", name="Dee")
    assert client.patch(f"/auth/users/{donor['id']}/role", json={"role": "volunteer"}, headers=a).status_code == 200
    assert client.get("/auth/me", headers=donor_h).status_code == 401
    row = db.query(models.AuditLog).filter_by(action="user.role_changed").one()
    assert row.detail["from"] == "donor" and row.detail["to"] == "volunteer"
    assert client.patch(f"/auth/users/{donor['id']}/role", json={"role": "admin"}, headers=donor_h).status_code in (401, 403)


def test_verification_workflow_keeps_flag_status_audit_and_notification_in_step(api):
    client, db = api
    a = admin(client)
    org_h, org_user = signup(client, "organization", "o@x.org", organization_name="Hope Home")
    org_id = org_user["organization_id"]
    assert client.post(f"/admin/verifications/{org_id}/decision", json={"decision": "approve"}, headers=org_h).status_code == 403
    assert client.post(f"/admin/verifications/{org_id}/decision", json={"decision": "reject"}, headers=a).status_code == 422       # reason required
    stale = client.post(f"/admin/verifications/{org_id}/decision", json={"decision": "approve", "expected_status": "verified"}, headers=a)
    assert stale.status_code == 409
    ok = client.post(f"/admin/verifications/{org_id}/decision", json={"decision": "approve", "expected_status": "pending"}, headers=a)
    assert ok.status_code == 200 and ok.json()["status"] == "verified" and ok.json()["verified"] is True
    org = db.get(models.Organization, org_id)
    assert org.verified is True and org.verification_status == "verified" and org.verified_at is not None
    revoked = client.post(f"/admin/verifications/{org_id}/decision", json={"decision": "reject", "note": "Documents expired"}, headers=a)
    assert revoked.json()["verified"] is False and revoked.json()["note"] == "Documents expired"
    detail = client.get(f"/admin/verifications/{org_id}", headers=a).json()
    assert [h["action"] for h in detail["history"]][:2] == ["organization.verification.reject", "organization.verification.approve"]
    assert detail["history"][0]["by"] == "boss@carebridge.org"
    notes = client.get("/notifications/", headers=org_h).json()
    assert notes["total"] == 2 and notes["unread"] == 2
    assert client.get("/admin/verifications/?status=rejected", headers=a).json()["total"] == 1


def test_old_verified_toggle_no_longer_drifts(api):
    client, db = api
    a = admin(client)
    _, org_user = signup(client, "organization", "o@x.org", organization_name="Hope")
    oid = org_user["organization_id"]
    assert client.patch(f"/organizations/{oid}/verification", json={"verified": True}, headers=a).status_code == 200
    assert db.get(models.Organization, oid).verification_status == "verified"


def test_notifications_are_private_and_markable(api):
    client, db = api
    a = admin(client)
    h1, u1 = signup(client, "donor", "d1@x.org", name="One")
    h2, u2 = signup(client, "donor", "d2@x.org", name="Two")
    n = models.Notification(user_id=u1["id"], kind="donation", title="Hello", link="/donations")
    db.add(n)
    db.commit()
    assert client.get("/notifications/unread-count", headers=h1).json() == {"unread": 1}
    assert client.get("/notifications/", headers=h2).json()["total"] == 0
    assert client.post(f"/notifications/{n.id}/read", headers=h2).status_code == 404         # someone else's: indistinguishable from missing
    assert client.get("/notifications/", headers=a).json()["total"] == 0                     # even admins only see their own
    assert client.post(f"/notifications/{n.id}/read", headers=h1).json()["unread"] == 0
    assert client.put("/notifications/preferences", json={"donation": False}, headers=h1).json()["preferences"]["donation"] is False
    assert client.put("/notifications/preferences", json={"security": False}, headers=h1).status_code == 422
    assert client.get("/notifications/unread-count").status_code == 401


def test_bulk_upload_isolation_preview_and_import(api):
    client, db = api
    h1, u1 = signup(client, "organization", "o1@x.org", organization_name="One")
    h2, u2 = signup(client, "organization", "o2@x.org", organization_name="Two")
    don_h, _ = signup(client, "donor", "d@x.org", name="Dee")
    text = ("title,category,quantity,urgency,organization_id\nBlankets,Clothing,10,high,\nBad,,x,high,\n"
            f"Sneaky,Food,3,low,{u2['organization_id']}\nBlankets,Clothing,10,high,\n")
    assert client.post("/needs/bulk/validate", json={"csv": text}, headers=don_h).status_code == 403
    preview = client.post("/needs/bulk/validate", json={"csv": text}, headers=h1).json()
    assert preview["saved"] is False and db.query(models.Need).count() == 0
    assert [r["status"] for r in preview["rows"]] == ["ready", "rejected", "rejected", "skipped"]
    strict = client.post("/needs/bulk/import", json={"csv": text, "strict": True}, headers=h1)
    assert strict.status_code == 409 and db.query(models.Need).count() == 0
    done = client.post("/needs/bulk/import", json={"csv": text}, headers=h1).json()
    assert done["counts"] == {"ready": 0, "created": 1, "rejected": 2, "skipped": 1}
    need = db.query(models.Need).one()
    assert need.org_id == u1["organization_id"]                                              # never the other organization
    assert done["warnings"]                                                                  # org is unverified: hidden from donors
    again = client.post("/needs/bulk/import", json={"csv": "title,category,quantity\nBlankets,Clothing,10\n"}, headers=h1).json()
    assert again["counts"]["skipped"] == 1 and db.query(models.Need).count() == 1            # duplicates of existing needs are skipped
    assert client.post("/needs/bulk/validate", json={"csv": "category;quantity\nFood;3"}, headers=h1).status_code == 422


def test_reports_scope_and_csv_safety(api):
    client, db = api
    a = admin(client)
    h1, u1 = signup(client, "organization", "o1@x.org", organization_name="=cmd|' /C calc'!A0")
    h2, u2 = signup(client, "organization", "o2@x.org", organization_name="Two")
    db.add_all([models.Need(org_id=u1["organization_id"], category="Food", quantity=1, status="open"),
                models.Need(org_id=u2["organization_id"], category="Books", quantity=1, status="open")])
    db.commit()
    mine = client.get("/reports/need_fulfillment?organization_id=" + str(u2["organization_id"]), headers=h1)   # tries to read org 2
    assert mine.status_code == 200
    rows = list(csv.reader(io.StringIO(mine.text.lstrip("\ufeff"), newline="")))
    assert any("Food" in r for r in rows) and not any("Books" in r for r in rows)
    assert all(not c.startswith(("=", "+", "-", "@")) for r in rows for c in r)
    assert client.get("/reports/org_verification", headers=h1).status_code == 403
    assert client.get("/reports/fund_utilization", headers=a).status_code == 404
    assert "attachment" in client.get("/reports/org_verification", headers=a).headers["content-disposition"]
    assert db.query(models.AuditLog).filter_by(action="report.exported").count() >= 2
    assert client.get("/reports/need_fulfillment?date_from=2026-02-01&date_to=2026-01-01", headers=a).status_code == 422


def test_public_endpoints_expose_only_verified_aggregates(api):
    client, db = api
    ok = models.Organization(name="Verified Home", verified=True, verification_status="verified", website="javascript:alert(1)", description="About us")
    bad = models.Organization(name="Pending Home", verified=False)
    db.add_all([ok, bad]); db.flush()
    db.add_all([models.Need(org_id=ok.id, category="Food", quantity=5, urgency="critical", status="open", description="child name here"),
                models.Need(org_id=bad.id, category="Hidden", quantity=5, urgency="critical", status="open")])
    db.commit()
    stats = client.get("/public/stats").json()
    assert stats["verified_organizations"] == 1 and stats["open_needs"] == 1
    needs = client.get("/public/needs").json()
    assert [n["category"] for n in needs] == ["Food"] and "description" not in needs[0]
    orgs = client.get("/public/organizations").json()
    assert orgs[0]["website"] is None and "contact" not in orgs[0]                         # unsafe link dropped, no contact details


def test_children_summary_hides_details(api):
    client, db = api
    h, u = signup(client, "organization", "o@x.org", organization_name="Hope")
    db.add(models.Child(org_id=u["organization_id"], age=9, interests="drawing", academic_performance="B+"))
    db.commit()
    assert client.get("/children/?view=summary", headers=h).json() == [{"id": 1, "org_id": u["organization_id"], "age_group": "6-11"}]
    assert client.get("/children/", headers=h).json()[0]["interests"] == "drawing"          # default view unchanged


def test_public_admin_signup_endpoints_no_longer_exist(api):
    client, _ = api
    body = {"email": "x@x.org", "password": PASSWORD, "full_name": "X", "invite_code": "invite-123"}
    assert client.post("/admin/register", json=body).status_code in (404, 405)
    assert client.get("/admin/register-status").status_code in (404, 405)
