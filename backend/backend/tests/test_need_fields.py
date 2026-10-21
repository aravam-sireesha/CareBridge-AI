"""The richer need fields (used by the ML models and routing) and the fulfilment timestamp the prediction model learns from."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models as m
from app.ai.ml import dataset
from app.auth import hash_password
from app.database import Base, get_db
from app.main import app

PASSWORD = "StrongPass1234!"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    org = m.Organization(name="Hope", contact="c", verified=True)
    db.add(org)
    db.flush()
    db.add(m.User(email="org@x.org", hashed_password=hash_password(PASSWORD), role="organization", organization_id=org.id))
    db.commit()

    def override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        token = client.post("/auth/login", json={"email": "org@x.org", "password": PASSWORD}).json()["access_token"]
        yield client, db, {"Authorization": f"Bearer {token}"}, org
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def test_new_fields_round_trip_and_are_validated(api):
    client, db, h, org = api
    body = {"category": "Books", "quantity": 40, "urgency": "high", "title": "Class 8 books", "description": "Maths and science", "required_by": "2026-12-01T00:00:00",
            "location": "Kadapa", "beneficiaries": 25, "latitude": 14.47, "longitude": 78.82}
    res = client.post("/needs/", headers=h, json=body)
    assert res.status_code in (200, 201), res.text
    out = res.json()
    assert out["title"] == "Class 8 books" and out["beneficiaries"] == 25 and out["latitude"] == 14.47 and out["fulfilled_at"] is None
    assert client.post("/needs/", headers=h, json={**body, "latitude": 123}).status_code == 422
    assert client.post("/needs/", headers=h, json={**body, "beneficiaries": -1}).status_code == 422
    plain = client.post("/needs/", headers=h, json={"category": "Food", "quantity": 5, "urgency": "low"})
    assert plain.status_code in (200, 201) and plain.json()["title"] is None  # the old request shape still works


def test_fulfilling_a_need_stamps_the_time_and_reopening_clears_it(api):
    client, db, h, org = api
    need_id = client.post("/needs/", headers=h, json={"category": "Books", "quantity": 10, "urgency": "high"}).json()["id"]
    done = client.patch(f"/needs/{need_id}", headers=h, json={"status": "fulfilled"})
    assert done.status_code == 200 and done.json()["fulfilled_at"] is not None
    first = done.json()["fulfilled_at"]
    again = client.patch(f"/needs/{need_id}", headers=h, json={"quantity": 11})
    assert again.json()["fulfilled_at"] == first                           # editing something else does not move the outcome time
    assert client.patch(f"/needs/{need_id}", headers=h, json={"status": "open"}).json()["fulfilled_at"] is None


def test_the_prediction_dataset_uses_the_recorded_fulfilment_time(api):
    client, db, h, org = api
    now = datetime(2026, 6, 30)
    quick = m.Need(org_id=org.id, category="Books", quantity=5, urgency="high", status="fulfilled", created_at=now - timedelta(days=40), fulfilled_at=now - timedelta(days=36))
    slow = m.Need(org_id=org.id, category="Books", quantity=5, urgency="high", status="fulfilled", created_at=now - timedelta(days=60), fulfilled_at=now - timedelta(days=20))
    db.add_all([quick, slow])
    db.commit()
    frame = dataset.training_frame(db, now)
    by_days = {round(r.days_to_fulfil): r.label for r in frame.itertuples()}
    assert by_days == {4: 1, 40: 0}
