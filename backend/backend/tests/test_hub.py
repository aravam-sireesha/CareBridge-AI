"""Administrator as the centre: suggestions across organizations, needs, donors and volunteers; forecast; volunteers."""
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
from app.services import forecast, volunteer_ml

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
    stars = models.Organization(name="Little Stars", contact="b", verified=True)
    fresh = models.Organization(name="Fresh Start", contact="c", verified=False)
    db.add_all([hope, stars, fresh])
    db.flush()
    n = {
        "books": models.Need(org_id=hope.id, category="Books", quantity=40, urgency="critical", status="open", created_at=now - timedelta(days=10)),
        "food": models.Need(org_id=hope.id, category="Meals", quantity=10, urgency="medium", status="open", created_at=now - timedelta(days=2)),
        "medicine": models.Need(org_id=stars.id, category="Medicine", quantity=5, urgency="high", status="open", created_at=now - timedelta(days=5)),
        "tutoring": models.Need(org_id=fresh.id, category="Tutoring", quantity=3, urgency="high", status="open", created_at=now - timedelta(days=3)),
    }
    db.add_all(n.values())
    d = {"edu": models.Donor(name="Edu Donor", contact="e", preferences="education"),
         "food": models.Donor(name="Food Donor", contact="f", preferences="food"),
         "health": models.Donor(name="Health Donor", contact="h", preferences="medicine, healthcare")}
    v = {"tutor": models.Volunteer(name="Tutor", contact="t", skills="teaching, tutoring", availability="weekends", organization_id=hope.id),
         "cook": models.Volunteer(name="Cook", contact="c", skills="cooking, meals", availability="evenings"),
         "nurse": models.Volunteer(name="Nurse", contact="n", skills="healthcare", availability="unavailable")}
    db.add_all(list(d.values()) + list(v.values()))
    db.add_all([models.Resource(organization_id=stars.id, name="Textbook set", category="books", kind="material", quantity_total=30, quantity_available=30, unit="sets"),
                models.Resource(organization_id=hope.id, name="Meal packs", category="food", kind="material", quantity_total=20, quantity_available=20, unit="packs")])
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
        yield client, db, {"Authorization": f"Bearer {token}"}, {"orgs": {"hope": hope, "stars": stars, "fresh": fresh}, "needs": n, "donors": d, "vols": v}
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def rec(client, h, entity, id_, **kw):
    r = client.get(f"/admin/recommend?entity={entity}&id={id_}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_need_gets_donors_volunteers_resources_and_partner_organizations(world):
    client, db, h, o = world
    out = rec(client, h, "need", o["needs"]["books"].id)
    s = out["sections"]
    assert out["entity"]["kind"] == "need" and "critical" in out["entity"]["sublabel"]
    assert s["donors"][0]["label"] == "Edu Donor" and s["donors"][0]["reasons"]
    assert s["volunteers"][0]["label"] == "Tutor"
    assert any("Already part of this organization" in r for r in s["volunteers"][0]["reasons"])
    assert s["resources"][0]["label"] == "Textbook set" and s["resources"][0]["extra"]["quantity"] == 30
    # a partner organization holds the matching resource; the need's own organization is not a "partner"
    assert [x["label"] for x in s["organizations"]] == ["Little Stars"]
    assert all(0 <= x["score"] <= 1 for sec in s.values() for x in sec)


def test_a_donor_gets_needs_and_organizations_and_unverified_orgs_are_flagged(world):
    client, db, h, o = world
    out = rec(client, h, "donor", o["donors"]["edu"].id)
    assert out["sections"]["needs"][0]["label"].startswith("Books")
    orgs = out["sections"]["organizations"]
    assert orgs[0]["label"] == "Hope Home" and orgs[0]["extra"]["verified"] is True
    fresh = [x for x in orgs if x["label"] == "Fresh Start"]  # tutoring is in the education group, so it is a candidate too
    assert fresh and any("Not verified" in r for r in fresh[0]["reasons"]) and fresh[0]["score"] < orgs[0]["score"]


def test_a_volunteer_gets_needs_and_organizations(world):
    client, db, h, o = world
    out = rec(client, h, "volunteer", o["vols"]["tutor"].id)
    labels = [x["label"] for x in out["sections"]["needs"]]
    assert labels[0].startswith(("Books", "Tutoring")) and not any(l.startswith("Medicine") for l in labels)
    assert out["sections"]["organizations"][0]["extra"]["need_ids"]


def test_an_organization_gets_ranked_needs_best_donors_volunteers_resources_and_health(world):
    client, db, h, o = world
    out = rec(client, h, "organization", o["orgs"]["hope"].id)
    assert out["entity"]["label"] == "Hope Home" and "health" in out["entity"]["sublabel"]
    needs = out["sections"]["needs"]
    assert [x["label"] for x in needs] == ["Books", "Meals"]  # critical and older first
    assert needs[0]["score"] > needs[1]["score"]
    assert {x["label"] for x in out["sections"]["donors"]} >= {"Edu Donor", "Food Donor"}
    assert [x for x in out["sections"]["donors"] if x["label"] == "Edu Donor"][0]["sublabel"] == "best for 'Books'"
    assert "Tutor" in [x["label"] for x in out["sections"]["volunteers"]]
    assert {x["label"] for x in out["sections"]["resources"]} == {"Textbook set", "Meal packs"}
    assert 0 <= out["health"]["score"] <= 100 and out["health"]["recommendations"]
    assert isinstance(out["forecast"], list)


def test_hub_validation_and_access(world):
    client, db, h, o = world
    assert client.get("/admin/recommend?entity=planet&id=1", headers=h).status_code == 422
    for e in ("need", "donor", "volunteer", "organization"):
        assert client.get(f"/admin/recommend?entity={e}&id=9999", headers=h).status_code == 404
    tok = client.post("/auth/login", json={"email": "org@x.org", "password": PASSWORD}).json()["access_token"]
    oh = {"Authorization": f"Bearer {tok}"}
    for path in ("/admin/recommend?entity=need&id=1", "/admin/entities", "/admin/forecast", "/admin/volunteers", "/admin/models"):
        assert client.get(path, headers=oh).status_code == 403
        assert client.get(path).status_code == 401
    ents = client.get("/admin/entities", headers=h).json()
    assert set(ents) == {"organization", "need", "donor", "volunteer"}
    assert len(ents["organization"]) == 3 and len(ents["need"]) == 4 and ents["need"][0]["label"].startswith("Books")  # most urgent first


# ---------------------------------------------------------------- volunteer model
def test_availability_parsing():
    s = volunteer_ml.availability_score
    assert s("unavailable") == 0 and s("") == 0 and s(None) == 0
    assert s("full time") == 1.0 and s("flexible") == 1.0 and s("weekends") == 0.7 and s("2 hours a month") == 0.4 and s("sometimes") == 0.6


def test_unavailable_volunteers_rank_lower_and_say_so(world):
    client, db, h, o = world
    need = o["needs"]["medicine"]
    cands = volunteer_ml.suggest_volunteers(db, need, 5)
    assert cands and cands[0]["volunteer_id"] == o["vols"]["nurse"].id  # only one with the skill
    assert any("Availability is not stated" in r for r in cands[0]["reasons"])
    f = cands[0]["features"]
    assert f["availability"] == 0 and f["group_match"] >= 0.4


def test_volunteer_suggestions_flow_through_the_review_queue_and_are_audited(world):
    client, db, h, o = world
    res = client.post(f"/admin/needs/{o['needs']['books'].id}/suggest-volunteers", headers=h)
    assert res.status_code == 200, res.text
    sug = res.json()["suggestions"]
    assert sug[0]["volunteer_name"] == "Tutor" and sug[0]["rank_in_need"] == 1
    q = client.get("/admin/review-queue?type=volunteer_suggestion", headers=h).json()
    assert q["items"][0]["decisions"] == ["approved", "contacted", "rejected"]
    done = client.post(f"/admin/review-queue/volunteer_suggestion/{q['items'][0]['id']}", headers=h, json={"decision": "approved"})
    assert done.status_code == 200
    assert client.get("/admin/volunteer-suggestions?status=approved", headers=h).json()[0]["volunteer_name"] == "Tutor"
    assert "volunteer_suggestion.reviewed" in {a.action for a in db.query(models.AuditLog).all()}
    # regenerating never overwrites a decision, and a rejected volunteer is not offered again
    again = client.post(f"/admin/needs/{o['needs']['books'].id}/suggest-volunteers", headers=h).json()["suggestions"]
    assert [s for s in again if s["volunteer_name"] == "Tutor"][0]["status"] == "approved"
    row = db.query(models.VolunteerSuggestion).filter_by(status="approved").one()
    row.status = "rejected"
    db.commit()
    after = client.post(f"/admin/needs/{o['needs']['books'].id}/suggest-volunteers", headers=h).json()["suggestions"]
    assert all(s["volunteer_name"] != "Tutor" for s in after)
    assert client.post("/admin/needs/9999/suggest-volunteers", headers=h).status_code == 404


def test_volunteer_model_learns_from_decisions_and_run_scans_includes_volunteers(world):
    client, db, h, o = world
    assert client.get("/admin/models", headers=h).json()["volunteer"]["mode"] == "blend"
    for i in range(24):
        good = i % 2 == 0
        need = models.Need(org_id=o["orgs"]["hope"].id, category=f"cat{i}", quantity=1, urgency="low", status="open")
        db.add(need)
        db.flush()
        db.add(models.VolunteerSuggestion(need_id=need.id, volunteer_id=o["vols"]["tutor"].id if good else o["vols"]["cook"].id, fit_score=.5, urgency_score=.5,
                                          priority_score=.5, reasons=[], model_version="x", status="approved" if good else "rejected",
                                          features={"text_sim": .8 if good else .1, "group_match": 1.0 if good else 0.0, "availability": .7, "history": .5 if good else 0, "familiarity": 1.0 if good else 0}))
    db.commit()
    info = client.get("/admin/models", headers=h).json()["volunteer"]
    assert info["mode"] == "learned" and info["coefficients"]["group_match"] > 0
    scans = client.post("/admin/workflow/run-scans", headers=h).json()
    assert scans["volunteer_suggestions"] >= 1


# ---------------------------------------------------------------- forecast
def test_forecast_detects_a_rising_category_and_flags_supply_gaps(world):
    client, db, h, o = world
    now = datetime.utcnow()
    hope = o["orgs"]["hope"]
    for months_ago, count in ((4, 1), (3, 2), (2, 3), (1, 4), (0, 5)):  # steadily rising demand for clothes, newest period last
        for _ in range(count):
            db.add(models.Need(org_id=hope.id, category="Clothes", quantity=4, urgency="medium", status="open", created_at=now - timedelta(days=30 * months_ago + 10)))
    db.commit()
    items = forecast.forecast_categories(db, now)
    c = [i for i in items if i["category"] == "clothes"][0]
    assert c["trend"] == "rising" and c["forecast_needs"] > 5 and c["periods"] == 5 and c["method"].startswith("damped")
    assert c["matching_donors"] == 0 and c["stock_units"] == 0 and c["risk"] == "high" and c["supply_gap_units"] > 0
    assert any("No donor" in n for n in c["notes"])
    assert items[0]["risk"] == "high"  # most worrying first
    api = client.get("/admin/forecast", headers=h).json()
    assert api["summary"]["high_risk"] >= 1 and api["items"][0]["category"]
    short = [i for i in items if i["category"] == "books"][0]  # a single recent need: not enough history
    assert short["method"].startswith("recent average") and short["confidence"] <= 0.2


def test_constant_demand_is_steady_and_forecast_matches_it():
    n, rmse, trend = forecast._fit_holt([4, 4, 4, 4, 4])
    assert round(n) == 4 and rmse == 0 and trend == 0
    up, _, t = forecast._fit_holt([1, 2, 3, 4, 5, 6])
    assert up > 6 and t > 0


# ---------------------------------------------------------------- volunteers of every organization
def test_admin_sees_and_manages_volunteers_of_all_organizations(world):
    client, db, h, o = world
    rows = client.get("/admin/volunteers", headers=h).json()
    assert {r["name"] for r in rows} == {"Tutor", "Cook", "Nurse"}
    assert [r["name"] for r in client.get(f"/admin/volunteers?organization_id={o['orgs']['hope'].id}", headers=h).json()] == ["Tutor"]
    created = client.post("/admin/volunteers", headers=h, json={"name": "New Vol", "skills": "music", "availability": "weekends", "organization_id": o["orgs"]["stars"].id})
    assert created.status_code == 201 and created.json()["organization_name"] == "Little Stars"
    assert client.post("/admin/volunteers", headers=h, json={"name": "X", "organization_id": 999}).status_code == 404
    vid = created.json()["id"]
    patched = client.patch(f"/admin/volunteers/{vid}", headers=h, json={"skills": "music, art", "clear_organization": True})
    assert patched.json()["skills"] == "music, art" and patched.json()["organization_id"] is None
    detail = client.get(f"/admin/volunteers/{o['vols']['tutor'].id}", headers=h).json()
    assert detail["recommended_needs"] and detail["recommended_needs"][0]["category"] in ("Tutoring", "Books")
    db.add(models.Match(need_id=o["needs"]["books"].id, volunteer_id=o["vols"]["tutor"].id, score=.8, status="confirmed", reasons=[]))
    db.commit()
    assert client.get(f"/admin/volunteers/{o['vols']['tutor'].id}", headers=h).json()["matches_history"][0]["status"] == "confirmed"
    assert client.delete(f"/admin/volunteers/{o['vols']['tutor'].id}", headers=h).status_code == 409  # has a match
    assert client.delete(f"/admin/volunteers/{vid}", headers=h).status_code == 200
    assert client.get("/admin/volunteers/9999", headers=h).status_code == 404
    acts = {a.action for a in db.query(models.AuditLog).all()}
    assert {"volunteer.created", "volunteer.updated", "volunteer.deleted"} <= acts
