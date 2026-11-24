"""Administration module: sign-up/sign-in, need management and ML donor suggestions."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.services import donor_ml
from admin_factory import make_admin

PASSWORD = "StrongPass1234"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
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


def signup(client, email="boss@carebridge.org"):
    return make_admin(client, email, PASSWORD, "Asha Rao")


def admin_headers(client, email="boss@carebridge.org"):
    assert signup(client, email).status_code == 201
    res = client.post("/admin/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def seed(db):
    org = models.Organization(name="Hope Home", contact="x", verified=True)
    db.add(org)
    db.flush()
    needs = {
        "crit": models.Need(org_id=org.id, category="School supplies", quantity=80, urgency="critical", status="open",
                            created_at=datetime.utcnow() - timedelta(days=20)),
        "low": models.Need(org_id=org.id, category="Clothes", quantity=5, urgency="low", status="open"),
        "done": models.Need(org_id=org.id, category="Books", quantity=5, urgency="high", status="fulfilled"),
    }
    db.add_all(needs.values())
    donors = {
        "edu": models.Donor(name="Edu Donor", contact="e@x", preferences="education"),
        "food": models.Donor(name="Food Donor", contact="f@x", preferences="food, nutrition"),
        "none": models.Donor(name="Quiet Donor", contact="q@x", preferences="astronomy"),
    }
    db.add_all(donors.values())
    db.commit()
    return org, needs, donors


# ---------------------------------------------------------------- sign up / sign in
def test_first_admin_setup_with_one_time_token(api, monkeypatch):
    client, db = api
    token = "t" * 32
    body = {"setup_token": token, "email": "boss@carebridge.org", "password": "Sturdy-Pass-2026!x", "confirm_password": "Sturdy-Pass-2026!x",
            "full_name": "Asha Rao", "designation": "Program Director"}
    # no token configured: setup does not exist
    assert client.get("/admin/setup-status").json() == {"setup_open": False}
    assert client.post("/admin/setup", json=body).status_code == 404
    monkeypatch.setenv("ADMIN_SETUP_TOKEN", token)
    assert client.get("/admin/setup-status").json() == {"setup_open": True}
    assert client.post("/admin/setup", json={**body, "setup_token": "w" * 32}).status_code == 403
    assert client.post("/admin/setup", json={**body, "confirm_password": "different"}).status_code == 422
    assert client.post("/admin/setup", json={**body, "password": "alllowercaseletters", "confirm_password": "alllowercaseletters"}).status_code == 422
    res = client.post("/admin/setup", json=body)
    assert res.status_code == 201, res.text
    user = db.query(models.User).filter_by(email="boss@carebridge.org").one()
    assert user.role == "admin" and user.hashed_password != body["password"] and token not in user.hashed_password
    assert db.query(models.Administrator).filter_by(user_id=user.id).one().full_name == "Asha Rao"
    actions = [a.action for a in db.query(models.AuditLog).all()]
    assert "admin.setup_failed" in actions and "admin.setup_completed" in actions
    assert token not in str([a.detail for a in db.query(models.AuditLog).all()])
    # single use: closed for good, even with the right token
    assert client.get("/admin/setup-status").json() == {"setup_open": False}
    assert client.post("/admin/setup", json={**body, "email": "second@carebridge.org"}).status_code == 404
    assert db.query(models.User).filter_by(role="admin").count() == 1
    assert client.post("/admin/login", json={"email": "boss@carebridge.org", "password": body["password"]}).status_code == 200


def test_short_setup_token_keeps_setup_closed(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv("ADMIN_SETUP_TOKEN", "short")
    assert client.get("/admin/setup-status").json() == {"setup_open": False}


def test_public_register_cannot_create_an_admin(api):
    client, db = api
    res = client.post("/auth/register", json={"email": "sneaky@x.org", "password": PASSWORD, "role": "admin", "organization_name": "X"})
    assert res.status_code in (201, 403, 422)
    user = db.query(models.User).filter_by(email="sneaky@x.org").first()
    assert user is None or user.role != "admin"
    assert client.post("/admin/register", json={"email": "a@x.org", "password": PASSWORD, "full_name": "A"}).status_code in (404, 405)


def test_only_a_signed_in_admin_can_add_administrators(api):
    client, db = api
    headers = admin_headers(client)
    body = {"email": "second@carebridge.org", "password": "Another-Pass-2026!", "full_name": "Second"}
    assert client.post("/admin/administrators", json=body).status_code == 401
    assert client.post("/admin/administrators", json={**body, "password": "weakweakweak"}, headers=headers).status_code == 422
    assert client.post("/admin/administrators", json=body, headers=headers).status_code == 201
    assert client.post("/admin/administrators", json=body, headers=headers).status_code == 409
    assert db.query(models.AuditLog).filter_by(action="admin.created").count() == 1


def test_logout_revokes_only_that_session(api):
    client, _ = api
    signup(client)
    login = lambda: {"Authorization": "Bearer " + client.post("/admin/login", json={"email": "boss@carebridge.org", "password": PASSWORD}).json()["access_token"]}
    first, second = login(), login()
    assert client.get("/admin/overview", headers=first).status_code == 200
    assert client.post("/admin/logout", headers=first).status_code == 200
    assert client.get("/admin/overview", headers=first).status_code == 401   # signed-out token is dead
    assert client.get("/admin/overview", headers=second).status_code == 200  # other session untouched
    assert client.post("/admin/logout").status_code == 401


def test_login_rules(api):
    client, db = api
    signup(client)
    ok = client.post("/admin/login", json={"email": "BOSS@carebridge.org", "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["admin"]["full_name"] == "Asha Rao"
    assert ok.json()["admin"]["last_login_at"] is not None
    assert client.post("/admin/login", json={"email": "boss@carebridge.org", "password": "bad-password-1"}).status_code == 401
    db.add(models.User(email="org@x.org", hashed_password=hash_password(PASSWORD), role="organization"))
    db.commit()
    assert client.post("/admin/login", json={"email": "org@x.org", "password": PASSWORD}).status_code == 403
    # the normal login shows the administrator's real name
    assert client.post("/auth/login", json={"email": "boss@carebridge.org", "password": PASSWORD}).json()["user"]["display_name"] == "Asha Rao"


def test_admin_routes_are_admin_only_and_script_created_admins_get_a_profile(api):
    client, db = api
    assert client.get("/admin/overview").status_code == 401
    db.add(models.User(email="org@x.org", hashed_password=hash_password(PASSWORD), role="organization"))
    db.add(models.User(email="script@x.org", hashed_password=hash_password(PASSWORD), role="admin"))
    db.commit()
    org_token = client.post("/auth/login", json={"email": "org@x.org", "password": PASSWORD}).json()["access_token"]
    assert client.get("/admin/overview", headers={"Authorization": f"Bearer {org_token}"}).status_code == 403
    res = client.post("/admin/login", json={"email": "script@x.org", "password": PASSWORD})
    assert res.status_code == 200
    assert db.query(models.Administrator).count() == 1  # created lazily


def test_deactivated_admin_is_locked_out(api):
    client, db = api
    headers = admin_headers(client)
    db.query(models.Administrator).update({"is_active": False})
    db.commit()
    assert client.get("/admin/overview", headers=headers).status_code == 403


# ---------------------------------------------------------------- needs + ML
def test_needs_are_ranked_by_ml_priority(api):
    client, db = api
    headers = admin_headers(client)
    seed(db)
    needs = client.get("/admin/needs", headers=headers).json()
    assert [n["category"] for n in needs][:2] == ["School supplies", "Clothes"]  # critical + old before low
    assert needs[0]["priority_level"] in ("critical", "high") and needs[0]["priority_score"] > needs[1]["priority_score"]
    assert needs[-1]["status"] == "fulfilled"  # closed needs sink to the bottom
    assert client.get("/admin/needs?urgency=low", headers=headers).json()[0]["category"] == "Clothes"


def test_donor_suggestions_match_need_and_explain_why(api):
    client, db = api
    headers = admin_headers(client)
    _, needs, donors = seed(db)
    res = client.post(f"/admin/needs/{needs['crit'].id}/suggest-donors", headers=headers)
    assert res.status_code == 200, res.text
    sug = res.json()["suggestions"]
    assert sug[0]["donor_name"] == "Edu Donor" and sug[0]["rank_in_need"] == 1
    assert all(s["donor_name"] != "Quiet Donor" for s in sug)  # nothing links an astronomy donor to school supplies
    assert any("category" in r.lower() or "supports" in r.lower() for r in sug[0]["reasons"])
    assert sug[0]["priority_score"] > 0 and sug[0]["model_version"].startswith("donor-ml-1.0.0")
    assert db.query(models.DonorSuggestion).count() == len(sug)
    # closed needs are refused
    assert client.post(f"/admin/needs/{needs['done'].id}/suggest-donors", headers=headers).status_code == 409
    assert client.post("/admin/needs/9999/suggest-donors", headers=headers).status_code == 404


def test_review_is_saved_and_not_overwritten_or_resurfaced(api):
    client, db = api
    headers = admin_headers(client)
    _, needs, _ = seed(db)
    first = client.post(f"/admin/needs/{needs['crit'].id}/suggest-donors", headers=headers).json()["suggestions"]
    sid = first[0]["id"]
    assert client.post(f"/admin/suggestions/{sid}/review", headers=headers, json={"decision": "approved"}).status_code == 200
    again = client.post(f"/admin/needs/{needs['crit'].id}/suggest-donors", headers=headers).json()["suggestions"]
    assert [s for s in again if s["id"] == sid][0]["status"] == "approved"
    assert db.query(models.DonorSuggestion).count() == len(first)  # no duplicates

    # a rejected donor never comes back for the same need
    rejected = db.query(models.DonorSuggestion).filter_by(id=sid).one()
    rejected.status = "rejected"
    db.commit()
    after = client.post(f"/admin/needs/{needs['crit'].id}/suggest-donors", headers=headers).json()["suggestions"]
    assert all(s["donor_id"] != rejected.donor_id for s in after)
    assert client.post(f"/admin/suggestions/{sid}/review", headers=headers, json={"decision": "maybe"}).status_code == 422


def test_generate_all_and_overview(api):
    client, db = api
    headers = admin_headers(client)
    seed(db)
    res = client.post("/admin/suggestions/generate", headers=headers).json()
    assert res["needs_scanned"] == 2 and res["suggestions"] >= 1
    overview = client.get("/admin/overview", headers=headers).json()
    assert overview["totals"]["open_needs"] == 2 and overview["totals"]["suggestions_waiting"] >= 1
    assert overview["model"]["mode"] == "blend"
    queue = client.get("/admin/suggestions?status=suggested", headers=headers).json()
    assert queue == sorted(queue, key=lambda s: s["priority_score"], reverse=True)
    orgs = client.get("/admin/organizations", headers=headers).json()
    assert orgs[0]["needs"] == 3 and orgs[0]["open_needs"] == 2


def test_model_learns_from_administrator_decisions(api):
    client, db = api
    headers = admin_headers(client)
    _, needs, donors = seed(db)
    assert donor_ml.model_info(db)["mode"] == "blend"
    for i in range(24):
        good = i % 2 == 0
        db.add(models.DonorSuggestion(
            need_id=needs["crit"].id, donor_id=donors["edu"].id if good else donors["food"].id,
            fit_score=0.5, urgency_score=0.5, priority_score=0.5, reasons=[], model_version="x",
            status="approved" if good else "rejected",
            features={"text_sim": 0.8 if good else 0.1, "group_match": 1.0 if good else 0.0,
                      "history": 0.6 if good else 0.0, "recency": 0.5 if good else 0.1}))
    # unique (need, donor) pair: keep only distinct rows by using different need ids
    db.rollback()
    for i in range(24):
        good = i % 2 == 0
        n = models.Need(org_id=1, category=f"cat{i}", quantity=1, urgency="low", status="open")
        db.add(n)
        db.flush()
        db.add(models.DonorSuggestion(
            need_id=n.id, donor_id=donors["edu"].id if good else donors["food"].id,
            fit_score=0.5, urgency_score=0.5, priority_score=0.5, reasons=[], model_version="x",
            status="approved" if good else "rejected",
            features={"text_sim": 0.8 if good else 0.1, "group_match": 1.0 if good else 0.0,
                      "history": 0.6 if good else 0.0, "recency": 0.5 if good else 0.1}))
    db.commit()
    info = client.get("/admin/model", headers=headers).json()
    assert info["mode"] == "learned" and info["coefficients"]["group_match"] > 0
    res = client.post(f"/admin/needs/{needs['crit'].id}/suggest-donors", headers=headers).json()
    assert res["model_version"].endswith("learned")


def test_urgency_scoring_orders_levels():
    now = datetime.utcnow()
    mk = lambda u, days=0, q=10: models.Need(urgency=u, quantity=q, created_at=now - timedelta(days=days))
    scores = [donor_ml.score_need(mk(u), now)["score"] for u in ("low", "medium", "high", "critical")]
    assert scores == sorted(scores)
    assert donor_ml.score_need(mk("low", 40), now)["score"] > donor_ml.score_need(mk("low", 0), now)["score"]


# ---------------------------------------------------------------- team, donors, needs management
def test_admin_team_create_and_deactivate(api):
    client, db = api
    headers = admin_headers(client)
    assert client.get("/admin/administrators", headers=headers).json()[0]["is_you"] is True
    res = client.post("/admin/administrators", headers=headers, json={
        "email": "second@carebridge.org", "password": PASSWORD, "full_name": "Ravi K"})
    assert res.status_code == 201, res.text
    again = client.post("/admin/administrators", headers=headers, json={
        "email": "second@carebridge.org", "password": PASSWORD, "full_name": "Ravi K"})
    assert again.status_code == 409
    team = client.get("/admin/administrators", headers=headers).json()
    assert [t["email"] for t in team] == ["boss@carebridge.org", "second@carebridge.org"]
    me, other = team
    assert client.patch(f"/admin/administrators/{me['id']}", headers=headers, json={"is_active": False}).status_code == 409
    assert client.patch(f"/admin/administrators/{other['id']}", headers=headers, json={"is_active": False}).status_code == 200
    # the deactivated administrator can no longer sign in
    assert client.post("/admin/login", json={"email": "second@carebridge.org", "password": PASSWORD}).status_code == 403


def test_admin_sees_and_manages_donors_of_all_organizations(api):
    client, db = api
    headers = admin_headers(client)
    org, needs, donors = seed(db)
    other = models.Organization(name="Other Org", contact="o", verified=True)
    db.add(other)
    db.flush()
    donors["edu"].organization_id = org.id
    donors["food"].organization_id = other.id
    db.add(models.Donation(donor_id=donors["edu"].id, need_id=needs["crit"].id, amount=500))
    db.commit()

    rows = client.get("/admin/donors", headers=headers).json()
    assert {r["name"] for r in rows} == {"Edu Donor", "Food Donor", "Quiet Donor"}  # every organization's donors
    edu = [r for r in rows if r["name"] == "Edu Donor"][0]
    assert edu["organization_name"] == "Hope Home" and edu["gifts"] == 1 and edu["total_given"] == 500
    assert [r["name"] for r in client.get(f"/admin/donors?organization_id={other.id}", headers=headers).json()] == ["Food Donor"]

    detail = client.get(f"/admin/donors/{donors['edu'].id}", headers=headers).json()
    assert detail["donations"][0]["need_category"] == "School supplies"
    assert detail["recommended_needs"] and detail["recommended_needs"][0]["category"] == "School supplies"

    created = client.post("/admin/donors", headers=headers, json={"name": "New Donor", "preferences": "medicine", "organization_id": other.id})
    assert created.status_code == 201 and created.json()["organization_name"] == "Other Org"
    assert client.post("/admin/donors", headers=headers, json={"name": "X", "organization_id": 999}).status_code == 404
    patched = client.patch(f"/admin/donors/{created.json()['id']}", headers=headers, json={"preferences": "health care", "clear_organization": True})
    assert patched.json()["preferences"] == "health care" and patched.json()["organization_id"] is None

    assert client.delete(f"/admin/donors/{created.json()['id']}", headers=headers).status_code == 200
    assert client.delete(f"/admin/donors/{donors['edu'].id}", headers=headers).status_code == 409  # has a donation
    assert client.get("/admin/donors/9999", headers=headers).status_code == 404


def test_admin_can_edit_and_delete_needs(api):
    client, db = api
    headers = admin_headers(client)
    _, needs, donors = seed(db)
    res = client.patch(f"/needs/{needs['low'].id}", headers=headers, json={"category": "Winter clothes", "urgency": "high", "quantity": 40})
    assert res.status_code == 200, res.text
    assert client.get("/admin/needs?urgency=high", headers=headers).json()[0]["category"] in ("Winter clothes", "School supplies")
    client.post(f"/admin/needs/{needs['low'].id}/suggest-donors", headers=headers)
    assert client.delete(f"/admin/needs/{needs['low'].id}", headers=headers).status_code == 200
    assert db.query(models.DonorSuggestion).filter_by(need_id=needs["low"].id).count() == 0
    db.add(models.Donation(donor_id=donors["edu"].id, need_id=needs["crit"].id, amount=5))
    db.commit()
    assert client.delete(f"/admin/needs/{needs['crit'].id}", headers=headers).status_code == 409
    assert client.delete("/admin/needs/9999", headers=headers).status_code == 404
