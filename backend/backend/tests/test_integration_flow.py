"""End-to-end API flow: register -> login -> read/write every table through the API."""
import hashlib

import pytest
from fastapi.testclient import TestClient
from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.routers import assistant as assistant_router
from app.services import embeddings, rag

PASSWORD = "StrongPass1234"


def fake_embed(text: str) -> list[float]:
    vec = [0.0] * 64
    for word in text.lower().split():
        word = word.strip(".,:;!?")
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1.0
    return vec


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(embeddings, "embed_text", fake_embed)
    monkeypatch.setattr(rag, "embed_text", fake_embed)
    monkeypatch.setattr(assistant_router, "embed_text", fake_embed)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    db.add(models.User(email="admin@carebridge-demo.org", hashed_password=hash_password(PASSWORD), role="admin"))
    db.commit()

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


def login(client, email, password=PASSWORD):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, response.json()


def register_org(client, email="hope@carebridge-demo.org"):
    response = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "role": "organization", "organization_name": "Hope Home", "contact": "99999"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_registered_account_can_log_in_and_read_its_own_rows(api):
    client, db = api
    created = register_org(client)
    assert created["display_name"] == "Hope Home"

    headers, body = login(client, "hope@carebridge-demo.org")
    assert body["user"]["role"] == "organization"
    assert body["user"]["display_name"] == "Hope Home"
    me = client.get("/auth/me", headers=headers).json()
    assert me["organization_id"] == created["organization_id"]
    # the rows really are in the tables
    assert db.query(models.User).filter_by(email="hope@carebridge-demo.org").count() == 1
    assert db.query(models.Organization).filter_by(name="Hope Home").count() == 1


def test_login_is_case_insensitive_and_wrong_password_is_401(api):
    client, _ = api
    register_org(client)
    ok = client.post("/auth/login", json={"email": "HOPE@carebridge-demo.org", "password": PASSWORD})
    assert ok.status_code == 200
    bad = client.post("/auth/login", json={"email": "hope@carebridge-demo.org", "password": "wrong-password!!"})
    assert bad.status_code == 401


def test_corrupt_stored_hash_is_401_not_500(api):
    client, db = api
    db.add(models.User(email="legacy@carebridge-demo.org", hashed_password="not-a-real-hash", role="organization"))
    db.commit()
    response = client.post("/auth/login", json={"email": "legacy@carebridge-demo.org", "password": PASSWORD})
    assert response.status_code == 401


def test_accounts_created_by_the_old_passlib_code_still_log_in(api):
    client, db = api
    old_hash = CryptContext(schemes=["bcrypt"]).hash(PASSWORD)
    db.add(models.User(email="old@carebridge-demo.org", hashed_password=old_hash, role="organization"))
    db.commit()
    assert client.post("/auth/login", json={"email": "old@carebridge-demo.org", "password": PASSWORD}).status_code == 200


def test_null_columns_do_not_break_listings(api):
    """Rows inserted by hand in pgAdmin often leave nullable columns empty."""
    client, db = api
    org = register_org(client)
    headers, _ = login(client, "hope@carebridge-demo.org")
    db.add(models.Need(org_id=org["organization_id"]))  # category/quantity/urgency/status all NULL
    db.query(models.Organization).update({"verified": None})
    db.commit()
    assert client.get("/needs/", headers=headers).status_code == 200
    assert client.get("/organizations/", headers=headers).status_code == 200


def test_organization_workflow_children_needs_dashboard_alerts(api):
    client, db = api
    org = register_org(client)
    headers, _ = login(client, "hope@carebridge-demo.org")

    child = client.post("/children/", headers=headers, json={"age": 11, "interests": "Science"})
    assert child.status_code == 201, child.text
    cid = child.json()["id"]
    assert client.get(f"/children/{cid}", headers=headers).json()["interests"] == "Science"
    assert len(client.get("/children/", headers=headers).json()) == 1

    need = client.post("/needs/", headers=headers, json={"category": "School supplies", "quantity": 20, "urgency": "high"})
    assert need.status_code == 201, need.text
    assert need.json()["status"] == "open"
    assert need.json()["organization_name"] == "Hope Home"

    summary = client.get("/dashboard/summary", headers=headers).json()
    assert summary["totals"]["children"] == 1
    assert summary["totals"]["open_needs"] == 1
    assert summary["needs_by_urgency"] == {"high": 1}
    assert len(summary["donations_by_month"]) == 6

    # regression: organization accounts used to get a 500 here (missing Need import)
    assert client.get("/needs/alerts", headers=headers).status_code == 200
    assert client.get("/matching/", headers=headers).status_code == 200
    # admin-only actions stay admin-only
    assert client.post("/needs/scan", headers=headers).status_code == 403
    assert org["organization_id"] is not None


def test_children_of_other_organizations_are_hidden(api):
    client, _ = api
    register_org(client, "a@carebridge-demo.org")
    register_org(client, "b@carebridge-demo.org")
    a, _ = login(client, "a@carebridge-demo.org")
    b, _ = login(client, "b@carebridge-demo.org")
    cid = client.post("/children/", headers=a, json={"age": 8}).json()["id"]
    assert client.get(f"/children/{cid}", headers=b).status_code == 404
    assert client.get("/children/", headers=b).json() == []


def test_admin_ai_review_queues_read_from_database(api):
    client, db = api
    org = register_org(client)
    org_headers, _ = login(client, "hope@carebridge-demo.org")
    admin, _ = login(client, "admin@carebridge-demo.org")
    need = client.post("/needs/", headers=org_headers, json={"category": "School supplies", "quantity": 20, "urgency": "high"}).json()
    donor = models.Donor(name="Asha", preferences="education", organization_id=org["organization_id"])
    db.add(donor)
    db.commit()
    for amount in (100, 110, 90, 105, 95, 9000):
        db.add(models.Donation(donor_id=donor.id, need_id=need["id"], amount=amount))
    db.commit()

    scan = client.post("/fraud/scan", headers=admin).json()
    assert scan["scanned"] == 6 and scan["new_flags"] >= 1
    flags = client.get("/fraud/flags", headers=admin).json()
    big = next(f for f in flags if f["amount"] == 9000)
    assert big["status"] == "suggested" and big["reasons"]
    review = client.post(f"/fraud/flags/{big['flag_id']}/review?decision=false_positive", headers=admin)
    assert review.status_code == 200
    after = next(f for f in client.get("/fraud/flags", headers=admin).json() if f["flag_id"] == big["flag_id"])
    assert after["status"] == "false_positive"

    alerts = client.post("/needs/scan", headers=admin).json()["alerts"]
    assert alerts
    listed = client.get("/needs/alerts", headers=admin).json()
    assert listed[0]["need_category"] == "School supplies"

    suggested = client.post(f"/matching/suggest/{need['id']}", headers=admin).json()["suggestions"]
    assert suggested
    matches = client.get("/matching/", headers=admin).json()
    assert matches[0]["need_category"] == "School supplies"


def test_rag_assistant_reads_and_writes_the_knowledge_tables(api):
    client, db = api
    admin, _ = login(client, "admin@carebridge-demo.org")
    db.add_all([
        models.KnowledgeBase(title="Volunteer Background Check", content="Volunteers must complete a background check before matching.", source="Policy"),
        models.KnowledgeBase(title="Donation Receipts", content="Donors receive a receipt within seven working days.", source="FAQ"),
    ])
    db.commit()
    status = client.get("/assistant/status", headers=admin).json()
    assert status["knowledge_entries"] == 2 and status["embedded_entries"] == 0

    assert client.post("/assistant/reindex", headers=admin).json() == {"embedded": 2}
    assert client.get("/assistant/status", headers=admin).json()["embedded_entries"] == 2

    answer = client.post("/assistant/ask", headers=admin, json={"question": "Do volunteers need a background check before matching?"}).json()
    assert answer["matches"][0]["title"] == "Volunteer Background Check"
    assert answer["answer_mode"] == "retrieval_only"
    history = client.get("/assistant/history", headers=admin).json()
    assert history and history[0]["question"].startswith("Do volunteers")
    assert db.query(models.AssistantMessage).count() == 1


def test_health_db_reports_connection_and_counts(api, monkeypatch):
    from app import database, diagnostics

    client, db = api
    bind = db.get_bind()
    monkeypatch.setattr(diagnostics, "engine", bind)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=bind))
    body = client.get("/health/db").json()
    assert body["database"]["connected"] is True
    assert body["secret_key_configured"] is True
    assert body["schema"]["ok"] is True
    assert body["row_counts"]["users"] == 1


def test_admin_can_issue_reset_code_and_user_sets_new_password(api):
    client, _ = api
    created = register_org(client)
    admin, _ = login(client, "admin@carebridge-demo.org")
    issued = client.post(f"/auth/users/{created['id']}/reset-code", headers=admin)
    assert issued.status_code == 200, issued.text
    token = issued.json()["token"]
    # organizations cannot issue codes
    org_headers, _ = login(client, "hope@carebridge-demo.org")
    assert client.post(f"/auth/users/{created['id']}/reset-code", headers=org_headers).status_code == 403

    done = client.post("/auth/password-reset/complete", json={"token": token, "new_password": "BrandNewPass9876"})
    assert done.status_code == 200, done.text
    assert client.post("/auth/login", json={"email": "hope@carebridge-demo.org", "password": PASSWORD}).status_code == 401
    assert client.post("/auth/login", json={"email": "hope@carebridge-demo.org", "password": "BrandNewPass9876"}).status_code == 200
    # a code can only be used once
    again = client.post("/auth/password-reset/complete", json={"token": token, "new_password": "AnotherPass123456"})
    assert again.status_code == 400


def test_donations_list_shows_donor_and_need_names(api):
    client, db = api
    org = register_org(client)
    headers, _ = login(client, "hope@carebridge-demo.org")
    need = client.post("/needs/", headers=headers, json={"category": "Books", "quantity": 5, "urgency": "low"}).json()
    donor = client.post("/donors/", headers=headers, json={"name": "Asha Foundation", "preferences": "books"}).json()
    created = client.post("/donations/", headers=headers, json={"donor_id": donor["id"], "need_id": need["id"], "amount": 500})
    assert created.status_code == 201, created.text
    row = client.get("/donations/", headers=headers).json()[0]
    assert row["donor_name"] == "Asha Foundation" and row["need_name"] == "Books"
    assert org["organization_id"] is not None


def test_unexpected_errors_return_json_with_a_hint(api):
    client, _ = api

    @app.get("/__boom")
    def boom():  # pragma: no cover - exercised through the client
        raise RuntimeError("boom")

    response = TestClient(app, raise_server_exceptions=False).get("/__boom")
    assert response.status_code == 500
    assert "check_schema.py" in response.json()["detail"]
