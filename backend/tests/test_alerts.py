"""Admin alerts are calculated from stored records only. Run with:  python -m pytest tests/test_alerts.py -q"""
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
from app.services import alerts

PASSWORD = "StrongPass1234"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    db.add_all([models.User(email="a@x.org", hashed_password=hash_password(PASSWORD), role="admin"), models.User(email="o@x.org", hashed_password=hash_password(PASSWORD), role="organization")])
    db.commit()

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        def h(email):
            return {"Authorization": "Bearer " + client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]}
        yield client, db, h
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def test_no_records_means_no_alerts_and_the_untracked_items_are_stated(env):
    client, _, h = env
    body = client.get("/admin/alerts", headers=h("a@x.org")).json()
    assert body["alerts"] == [] and {n["key"] for n in body["not_tracked"]} == {"overdue_deliveries", "failed_workflows"}


def test_alerts_count_real_records_and_link_to_them(env):
    client, db, h = env
    now = datetime.utcnow()
    org = models.Organization(name="Pending Home", contact="c", verified=False, verification_status="pending", verification_submitted_at=now - timedelta(days=6))
    db.add(org)
    db.flush()
    stale = models.Need(org_id=org.id, category="Meals", quantity=5, urgency="critical", status="open", created_at=now - timedelta(days=20))
    fresh = models.Need(org_id=org.id, category="Books", quantity=5, urgency="low", status="open", created_at=now - timedelta(days=3))
    donor = models.Donor(name="D")
    db.add_all([stale, fresh, donor])
    db.flush()
    old = models.Donation(donor_id=donor.id, need_id=stale.id, amount=10, status="pending", timestamp=now - timedelta(days=30))
    done = models.Donation(donor_id=donor.id, need_id=stale.id, amount=10, status="delivered", timestamp=now - timedelta(days=30))
    db.add_all([old, done])
    db.flush()
    db.add_all([models.DonationFlag(donation_id=old.id, anomaly_score=0.9, reasons=["large"], model_version="t", flagged_at=now - timedelta(days=2)),
                models.DonationFlag(donation_id=done.id, anomaly_score=0.8, reasons=["x"], model_version="t", review_decision="false_positive")])
    db.commit()
    by_key = {a["key"]: a for a in client.get("/admin/alerts", headers=h("a@x.org")).json()["alerts"]}
    assert by_key["stale_needs"]["count"] == 1 and by_key["stale_needs"]["severity"] == "high" and by_key["stale_needs"]["items"][0]["link"] == f"/needs?open={stale.id}"
    assert by_key["verification"]["count"] == 1 and by_key["anomalies"]["count"] == 1      # the reviewed flag is not counted
    assert by_key["undelivered"]["count"] == 1 and by_key["undelivered"]["items"][0]["link"] == f"/donations?open={old.id}"   # the delivered donation is not counted


def test_only_administrators_can_read_alerts(env):
    client, _, h = env
    assert client.get("/admin/alerts", headers=h("o@x.org")).status_code == 403
    assert client.get("/admin/alerts").status_code == 401


def test_threshold_is_applied_to_the_age_of_the_record(env):
    _, db, _ = env
    now = datetime.utcnow()
    org = models.Organization(name="Hope", contact="c", verified=True)
    db.add(org)
    db.flush()
    db.add(models.Need(org_id=org.id, category="Meals", quantity=1, urgency="low", status="open", created_at=now - timedelta(days=alerts.STALE_DAYS - 1)))
    db.commit()
    assert alerts.build_alerts(db, now)["alerts"] == []


# ----------------------------------------------------------------------------- forecast dashboard data
def test_forecast_dashboard_returns_real_history_and_never_invents_a_band(env):
    client, db, h = env
    now = datetime.utcnow()
    org = models.Organization(name="Hope", contact="c", verified=True)
    db.add(org)
    db.flush()
    for months_ago in range(0, 3):           # three periods of history: too short for a backtest band
        db.add(models.Need(org_id=org.id, category="Food", quantity=10, urgency="low", status="open", created_at=now - timedelta(days=30 * months_ago + 1)))
    db.commit()
    body = client.get("/admin/forecast-dashboard", headers=h("a@x.org")).json()
    food = next(c for c in body["categories"] if c["category"] == "food")
    assert [p["value"] for p in food["history"]] == [1.0, 1.0, 1.0] and food["forecast"]["band"] is None and food["confident"] is False
    assert "not a probability" in body["risk_method"] and body["limitations"] and body["horizon"] == "next 30 days"
    assert food["shortfall"] is None or food["shortfall"]["risk"] in ("low", "medium", "high")


def test_forecast_dashboard_is_admin_only(env):
    client, _, h = env
    assert client.get("/admin/forecast-dashboard", headers=h("o@x.org")).status_code == 403
