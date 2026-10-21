import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.auth import create_access_token
from app.database import Base, get_db
from app.main import app
from app.services import embeddings, rag


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestSession()
    db.add_all([
        models.User(id=1, email="admin@example.test", hashed_password="unused", role="admin"),
        models.User(id=2, email="org@example.test", hashed_password="unused", role="organization"),
    ])
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        test_client.admin_headers = {
            "Authorization": f"Bearer {create_access_token({'sub': 'admin@example.test', 'user_id': 1, 'role': 'admin'})}"
        }
        test_client.org_headers = {
            "Authorization": f"Bearer {create_access_token({'sub': 'org@example.test', 'user_id': 2, 'role': 'organization'})}"
        }
        yield test_client, db

    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


PROFILE = {
    "Age": 21,
    "Gender": "Female",
    "Field_of_Study": "Science",
    "Year_of_Study": 3,
    "University_Location": "Region A",
    "GPA": 3.5,
    "Relevant_Coursework": 1,
    "Prior_Employment": 0,
    "Employment_Type": "Internship",
    "Entrepreneurial_Experience": 0,
    "Startup_Participation": 0,
    "Career_Interests": "Tech",
    "Entrepreneurial_Aspirations": "High",
}


def test_public_registration_cannot_assign_admin(client):
    test_client, _ = client
    response = test_client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "safe-test-password", "role": "admin"},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "organization"


@pytest.mark.parametrize("role", ["organization", "donor", "volunteer"])
def test_registration_persists_role_profile(client, role):
    test_client, db = client
    profile = {"role": role}
    if role == "organization":
        profile["organization_name"] = "North Star Care"
    else:
        profile["name"] = f"New {role}"
        profile["location"] = "Austin"
    response = test_client.post(
        "/auth/register",
        json={"email": f"{role}@example.com", "password": "safe-test-password", **profile},
    )
    assert response.status_code == 201
    user = db.query(models.User).filter_by(email=f"{role}@example.com").one()
    assert user.role == role
    login = test_client.post(
        "/auth/login",
        json={"email": user.email, "password": "safe-test-password"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == role
    assert login.json()["user"]["id"] == user.id
    if role == "organization":
        assert db.get(models.Organization, user.organization_id).name == "North Star Care"
    elif role == "donor":
        assert db.get(models.Donor, user.donor_id).name == "New donor"
    else:
        assert db.get(models.Volunteer, user.volunteer_id).name == "New volunteer"


def test_password_reset_is_single_use_and_revokes_existing_sessions(client, monkeypatch):
    test_client, db = client
    from app import auth as auth_service
    from app.routers import auth as auth_router

    monkeypatch.setenv("SMTP_HOST", "mail.example.test")
    monkeypatch.setenv("SMTP_FROM", "carebridge@example.test")
    user = models.User(
        email="reset@example.com",
        hashed_password=auth_service.hash_password("initial-safe-password"),
        role="organization",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    old_token = create_access_token({
        "sub": user.email,
        "user_id": user.id,
        "role": user.role,
        "token_version": user.token_version,
    })
    delivered = {}
    monkeypatch.setattr(auth_router, "_send_reset_email", lambda email, token: delivered.update(email=email, token=token))

    response = test_client.post("/auth/password-reset/request", json={"email": user.email})
    assert response.status_code == 200
    assert response.json()["message"].startswith("If an account exists")
    assert delivered["email"] == user.email

    response = test_client.post(
        "/auth/password-reset/complete",
        json={"token": delivered["token"], "new_password": "replacement-safe-password"},
    )
    assert response.status_code == 200
    assert user.token_version == 1
    assert auth_service.verify_password("replacement-safe-password", user.hashed_password)
    response = test_client.get("/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert response.status_code == 401
    response = test_client.post(
        "/auth/password-reset/complete",
        json={"token": delivered["token"], "new_password": "another-safe-password"},
    )
    assert response.status_code == 400


def test_recommendation_requires_admin_and_persists_profile(client):
    test_client, db = client
    response = test_client.post("/career/recommend/1")
    assert response.status_code == 401

    response = test_client.post("/career/recommend/1", headers=test_client.org_headers)
    assert response.status_code == 403

    response = test_client.post("/career/recommend/1", headers=test_client.admin_headers)
    assert response.status_code == 404

    child = models.Child(age=21, interests="Tech", skills="Science", academic_performance="3.5")
    db.add(child)
    db.commit()
    response = test_client.post(
        f"/career/profiles/{child.id}", json=PROFILE, headers=test_client.admin_headers
    )
    assert response.status_code == 201

    response = test_client.post(f"/career/recommend/{child.id}", headers=test_client.admin_headers)
    assert response.status_code == 201
    body = response.json()
    assert len(body["candidates"]) == 3
    assert body["candidates"][0] == "Tech"
    assert "scores" not in body
    assert body["model_version"] == "career-hybrid-1.1.0"
    record = db.query(models.CareerRecommendation).one()
    assert len(record.candidates) == 3
    assert record.created_by == 1
    assert record.model_version == "career-hybrid-1.1.0"
    assert db.query(models.ChildProfile).one().profile_data["Career_Interests"] == "Tech"


def test_feedback_requires_admin_and_is_stored(client):
    test_client, db = client
    recommendation = models.CareerRecommendation(
        recommended_path="Tech",
        candidates=["Tech", "Design", "Business"],
        model_version="career-hybrid-1.1.0",
        created_by=1,
    )
    db.add(recommendation)
    db.commit()

    payload = {"decision": "accepted", "chosen_career": "Tech", "comment": "Approved"}
    response = test_client.post(
        f"/career/{recommendation.id}/feedback", json=payload, headers=test_client.org_headers
    )
    assert response.status_code == 403

    response = test_client.post(
        f"/career/{recommendation.id}/feedback", json=payload, headers=test_client.admin_headers
    )
    assert response.status_code == 201
    feedback = db.query(models.RecommendationFeedback).one()
    assert feedback.decision == "accepted"
    assert feedback.admin_id == 1
    assert feedback.chosen_career == "Tech"
    assert feedback.comment == "Approved"

    response = test_client.post(
        f"/career/{recommendation.id}/feedback", json=payload, headers=test_client.admin_headers
    )
    assert response.status_code == 409
    assert db.query(models.RecommendationFeedback).count() == 1


def test_feedback_requires_chosen_career_for_accept_or_modify(client):
    test_client, _ = client
    response = test_client.post(
        "/career/1/feedback", json={"decision": "modified"}, headers=test_client.admin_headers
    )
    assert response.status_code == 422


def test_fraud_score_requires_admin_and_valid_feature_set(client):
    test_client, _ = client
    response = test_client.post("/fraud/score", json={"features": {}}, headers=test_client.org_headers)
    assert response.status_code == 403

    response = test_client.post("/fraud/score", json={"features": {}}, headers=test_client.admin_headers)
    assert response.status_code == 422

    fraud_features = {"Time": 0.0, **{f"V{index}": 0.0 for index in range(1, 29)}, "Amount": 1.0}
    response = test_client.post(
        "/fraud/score", json={"features": fraud_features}, headers=test_client.admin_headers
    )
    assert response.status_code == 200
    assert 0 <= response.json()["fraud_probability"] <= 1
    assert response.json()["model_version"] == "fraud-hgb-1.0.0"


def test_donation_rules_flag_large_first_donation_and_persist_review(client):
    test_client, db = client
    donor = models.Donor(name="Large donor")
    db.add(donor)
    db.commit()
    donation = models.Donation(donor_id=donor.id, amount=60000)
    db.add(donation)
    db.commit()

    response = test_client.post(
        f"/fraud/score/{donation.id}", headers=test_client.admin_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["flagged"] is True
    assert body["score"] == 0.4
    assert "First donation" in body["reasons"][0]
    flag = db.get(models.DonationFlag, body["flag_id"])
    assert flag.model_version == "fraud-rules-1.0.0"

    response = test_client.post(
        f"/fraud/flags/{flag.id}/review?decision=confirmed_fraud",
        headers=test_client.admin_headers,
    )

    assert response.status_code == 200
    db.refresh(flag)
    assert flag.reviewed_by == 1
    assert flag.review_decision == "confirmed_fraud"
    assert flag.reviewed_at is not None


def test_donation_rules_leave_normal_donation_unflagged_and_require_admin(client):
    test_client, db = client
    donor = models.Donor(name="Regular donor")
    db.add(donor)
    db.commit()
    donation = models.Donation(donor_id=donor.id, amount=25)
    db.add(donation)
    db.commit()

    response = test_client.post(f"/fraud/score/{donation.id}")
    assert response.status_code == 401

    response = test_client.post(
        f"/fraud/score/{donation.id}", headers=test_client.admin_headers
    )
    assert response.status_code == 200
    assert response.json() == {"flagged": False}


def test_donation_flag_review_rejects_invalid_decision(client):
    test_client, db = client
    donor = models.Donor(name="Flagged donor")
    db.add(donor)
    db.commit()
    donation = models.Donation(donor_id=donor.id, amount=60000)
    db.add(donation)
    db.commit()
    flag = models.DonationFlag(
        donation_id=donation.id,
        anomaly_score=0.4,
        reasons=["test"],
        model_version="fraud-rules-1.0.0",
    )
    db.add(flag)
    db.commit()

    response = test_client.post(
        f"/fraud/flags/{flag.id}/review?decision=invalid",
        headers=test_client.admin_headers,
    )

    assert response.status_code == 422


def test_donation_rules_flag_amount_spike_and_rapid_donations(client):
    test_client, db = client
    donor = models.Donor(name="Frequent donor")
    db.add(donor)
    db.commit()
    donations = [
        models.Donation(donor_id=donor.id, amount=10),
        models.Donation(donor_id=donor.id, amount=10),
        models.Donation(donor_id=donor.id, amount=10),
        models.Donation(donor_id=donor.id, amount=100),
    ]
    db.add_all(donations)
    db.commit()

    response = test_client.post(
        f"/fraud/score/{donations[-1].id}", headers=test_client.admin_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["flagged"] is True
    assert body["score"] == 0.9
    assert any("5x+ this donor's average" in reason for reason in body["reasons"])
    assert any("donations from this donor within 1 hour" in reason for reason in body["reasons"])


def test_donation_create_and_list_persist_database_records(client):
    test_client, db = client
    organization = models.Organization(name="Safe Harbor", verified=True)
    db.add(organization)
    db.flush()
    donor = models.Donor(name="Community Donor", organization_id=organization.id)
    need = models.Need(org_id=organization.id, category="Books", quantity=8, urgency="medium")
    db.add_all([donor, need])
    db.commit()

    response = test_client.post(
        "/donations/",
        json={"donor_id": donor.id, "need_id": need.id, "amount": 125.5, "resource_description": "Reading kits"},
        headers=test_client.admin_headers,
    )
    assert response.status_code == 201
    donation_id = response.json()["id"]
    assert db.get(models.Donation, donation_id).resource_description == "Reading kits"

    response = test_client.get("/donations/", headers=test_client.admin_headers)
    assert response.status_code == 200
    assert response.json()[0]["id"] == donation_id


def test_matching_suggestions_rank_overlap_and_review_match(client):
    test_client, db = client
    need = models.Need(category="school supplies", urgency="high")
    matching_donor = models.Donor(name="Education donor", preferences="education")
    other_donor = models.Donor(name="Clothing donor", preferences="Clothing")
    volunteer = models.Volunteer(
        name="Mentor volunteer", skills="mentoring", availability="Weekdays"
    )
    db.add_all([need, matching_donor, other_donor, volunteer])
    db.commit()

    response = test_client.post(f"/matching/suggest/{need.id}")
    assert response.status_code == 401

    response = test_client.post(
        f"/matching/suggest/{need.id}", headers=test_client.admin_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model_version"] == "matching-rules-1.2.0"
    suggestions = body["suggestions"]
    assert len(suggestions) == 2
    donor_suggestion = next(item for item in suggestions if item["donor_id"] == matching_donor.id)
    volunteer_suggestion = next(item for item in suggestions if item["volunteer_id"] == volunteer.id)
    assert donor_suggestion["score"] == 0.61
    assert volunteer_suggestion["score"] == 0.67
    assert any("Category-group match" in reason and "(0.4)" in reason for reason in donor_suggestion["reasons"])
    assert any("Category-group skill match" in reason and "(0.4)" in reason for reason in volunteer_suggestion["reasons"])

    match = db.get(models.Match, donor_suggestion["match_id"])
    assert match.status == "suggested"
    response = test_client.post(
        f"/matching/{match.id}/review",
        json={"status": "confirmed"},
        headers=test_client.admin_headers,
    )
    assert response.status_code == 200
    db.refresh(match)
    assert match.status == "confirmed"


def test_matching_suggest_requires_existing_need_and_review_valid_status(client):
    test_client, db = client
    response = test_client.post("/matching/suggest/999", headers=test_client.admin_headers)
    assert response.status_code == 404

    need = models.Need(category="books", urgency="medium")
    db.add(need)
    db.commit()
    donor = models.Donor(name="Book donor", preferences="books")
    db.add(donor)
    db.commit()
    response = test_client.post(
        f"/matching/suggest/{need.id}", headers=test_client.admin_headers
    )
    match_id = response.json()["suggestions"][0]["match_id"]
    response = test_client.post(
        f"/matching/{match_id}/review",
        json={"status": "pending_review"},
        headers=test_client.admin_headers,
    )
    assert response.status_code == 422


def test_matching_suggest_reuses_pending_suggestions(client):
    test_client, db = client
    need = models.Need(category="education", urgency="high")
    donor = models.Donor(name="Education donor", preferences="education")
    db.add_all([need, donor])
    db.commit()

    first_response = test_client.post(
        f"/matching/suggest/{need.id}", headers=test_client.admin_headers
    )
    need.urgency = "low"
    db.commit()
    second_response = test_client.post(
        f"/matching/suggest/{need.id}", headers=test_client.admin_headers
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    first_match_id = first_response.json()["suggestions"][0]["match_id"]
    second_match_id = second_response.json()["suggestions"][0]["match_id"]
    assert second_match_id == first_match_id
    assert second_response.json()["suggestions"][0]["score"] == 0.755
    assert db.query(models.Match).filter(models.Match.need_id == need.id).count() == 1
    match = db.get(models.Match, first_match_id)
    assert match.score == 0.755

    response = test_client.post(
        f"/matching/{first_match_id}/review",
        json={"status": "confirmed"},
        headers=test_client.admin_headers,
    )
    assert response.status_code == 200
    response = test_client.post(
        f"/matching/suggest/{need.id}", headers=test_client.admin_headers
    )
    assert response.status_code == 200
    new_match_id = response.json()["suggestions"][0]["match_id"]
    assert new_match_id != first_match_id
    assert db.query(models.Match).filter(models.Match.need_id == need.id).count() == 2


@pytest.mark.parametrize("status", ["open", "pending"])
def test_need_alert_scan_persists_refreshes_and_reviews_alerts(client, status):
    test_client, db = client
    need = models.Need(
        category="school supplies",
        urgency="high",
        status=status,
        quantity=55,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3),
    )
    db.add(need)
    db.commit()

    response = test_client.post("/needs/scan")
    assert response.status_code == 401

    response = test_client.post("/needs/scan", headers=test_client.admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["alerts"]) == 1
    first_alert = body["alerts"][0]
    assert first_alert["score"] == 1.0
    assert any("high urgency" in reason for reason in first_alert["reasons"])
    assert any("exceeds 2-day limit" in reason for reason in first_alert["reasons"])
    assert any("Large quantity" in reason for reason in first_alert["reasons"])

    need.quantity = 60
    db.commit()
    response = test_client.post("/needs/scan", headers=test_client.admin_headers)
    assert response.status_code == 200
    second_alert = response.json()["alerts"][0]
    assert second_alert["alert_id"] == first_alert["alert_id"]
    assert "Large quantity requested: 60" in second_alert["reasons"]
    assert db.query(models.NeedAlert).filter(models.NeedAlert.need_id == need.id).count() == 1

    response = test_client.post(
        f"/needs/alerts/{first_alert['alert_id']}/review",
        json={"decision": "action_taken"},
        headers=test_client.admin_headers,
    )
    assert response.status_code == 200
    alert = db.get(models.NeedAlert, first_alert["alert_id"])
    assert alert.reviewed_by == 1
    assert alert.review_decision == "action_taken"
    assert alert.reviewed_at is not None


def test_embed_missing_knowledge_entries_persists_vectors(client, monkeypatch):
    _, db = client
    db.add_all(
        [
            models.KnowledgeBase(title="Donation process", content="Review donor details."),
            models.KnowledgeBase(title="Career guidance", content="Use student interests."),
        ]
    )
    db.commit()
    monkeypatch.setattr(embeddings, "embed_text", lambda text: [float(len(text)), 1.0])

    embedded_count = embeddings.embed_missing_entries(db)

    assert embedded_count == 2
    rows = db.query(models.KnowledgeBase).order_by(models.KnowledgeBase.id).all()
    assert all(row.embedding is not None for row in rows)
    assert all(row.embedding_model == embeddings.MODEL_NAME for row in rows)
    assert embeddings.embed_missing_entries(db) == 0


def test_retrieve_ranks_knowledge_entries_by_cosine_similarity(client, monkeypatch):
    _, db = client
    db.add_all(
        [
            models.KnowledgeBase(
                title="Unrelated", content="Other subject", embedding=[0.0, 1.0], source="a"
            ),
            models.KnowledgeBase(
                title="Donation review", content="Check donation flags", embedding=[1.0, 0.0], source="b"
            ),
            models.KnowledgeBase(title="No vector", content="Not embedded yet"),
        ]
    )
    db.commit()
    monkeypatch.setattr(rag, "embed_text", lambda text: [1.0, 0.0])

    results = rag.retrieve(db, "How do I review a donation?", top_k=1)

    assert len(results) == 1
    assert results[0]["title"] == "Donation review"
    # the dense (cosine) signal is still exact; "score" is now the calibrated hybrid confidence
    assert results[0]["signals"]["dense"] == 1.0
    assert 0.5 < results[0]["score"] <= 1.0 and results[0]["answerable"] is True
    assert rag.retrieve(db, "unused", top_k=0) == []


def test_retrieve_scopes_private_knowledge_to_organization(client, monkeypatch):
    _, db = client
    first_org = models.Organization(name="First Org")
    second_org = models.Organization(name="Second Org")
    db.add_all([first_org, second_org])
    db.flush()
    db.add_all([
        models.KnowledgeBase(title="Shared policy", content="Shared guidance", embedding=[1.0, 0.0]),
        models.KnowledgeBase(title="First private", content="First guidance", organization_id=first_org.id, embedding=[1.0, 0.0]),
        models.KnowledgeBase(title="Second private", content="Second guidance", organization_id=second_org.id, embedding=[1.0, 0.0]),
    ])
    db.commit()
    monkeypatch.setattr(rag, "embed_text", lambda text: [1.0, 0.0])

    results = rag.retrieve(db, "guidance", organization_id=first_org.id)

    assert {item["title"] for item in results} == {"Shared policy", "First private"}
    global_results = rag.retrieve(db, "guidance", global_only=True)
    assert [item["title"] for item in global_results] == ["Shared policy"]


def test_ask_requires_auth(client):
    test_client, _ = client

    response = test_client.post("/assistant/ask", json={"question": "test"})

    assert response.status_code == 401


def test_ask_empty_question_rejected(client):
    test_client, _ = client

    response = test_client.post(
        "/assistant/ask",
        json={"question": "  "},
        headers=test_client.admin_headers,
    )

    assert response.status_code == 422


def test_ask_returns_relevant_match(client, monkeypatch):
    test_client, db = client
    db.add(
        models.KnowledgeBase(
            title="Volunteer Background Check Policy",
            content="Volunteers are background checked before placement.",
            embedding=[1.0, 0.0],
            source="test",
        )
    )
    db.commit()
    monkeypatch.setattr(rag, "embed_text", lambda text: [1.0, 0.0])
    monkeypatch.setattr(rag, "generate_grounded_answer", lambda question, matches: ("Grounded answer [SOURCE 1].", "grounded_generation"))

    response = test_client.post(
        "/assistant/ask",
        json={"question": "background check for volunteers"},
        headers=test_client.admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["matches"][0]["title"] == "Volunteer Background Check Policy"
    assert response.json()["matches"][0]["score"] > 0.5
    assert response.json()["answer"] == "Grounded answer [SOURCE 1]."
    saved = db.query(models.AssistantMessage).one()
    assert saved.question == "background check for volunteers"
    assert saved.sources[0]["title"] == "Volunteer Background Check Policy"