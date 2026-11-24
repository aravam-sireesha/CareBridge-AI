"""RAG assistant 2.0: live database facts, organization health and need/donor selection."""
import hashlib
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
from app.routers import assistant as assistant_router
from app.services import embeddings, live_assistant, org_health, rag

PASSWORD = "StrongPass1234"


def fake_embed(text):
    vec = [0.0] * 64
    for w in text.lower().split():
        vec[int(hashlib.md5(w.strip(".,:;!?").encode()).hexdigest(), 16) % 64] += 1.0
    return vec


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for mod, name in ((embeddings, "embed_text"), (rag, "embed_text"), (assistant_router, "embed_text")):
        monkeypatch.setattr(mod, name, fake_embed)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    now = datetime.utcnow()
    good = models.Organization(name="Hope Home", contact="a", verified=True)
    weak = models.Organization(name="Little Stars", contact="b", verified=False)
    db.add_all([good, weak])
    db.flush()
    d_edu = models.Donor(name="Edu Donor", contact="e", preferences="education")
    d_food = models.Donor(name="Food Donor", contact="f", preferences="food")
    db.add_all([d_edu, d_food])
    db.flush()
    n1 = models.Need(org_id=good.id, category="School supplies", quantity=60, urgency="critical", status="open", created_at=now - timedelta(days=40))
    n2 = models.Need(org_id=good.id, category="Meals", quantity=10, urgency="medium", status="open", created_at=now - timedelta(days=2))
    n3 = models.Need(org_id=weak.id, category="Clothes", quantity=5, urgency="high", status="open", created_at=now - timedelta(days=45))
    done = models.Need(org_id=good.id, category="Books", quantity=5, urgency="low", status="fulfilled")
    db.add_all([n1, n2, n3, done])
    db.flush()
    db.add(models.Donation(donor_id=d_food.id, need_id=n2.id, amount=1000, timestamp=now - timedelta(days=3)))
    db.add(models.Child(org_id=good.id, age=10))
    db.add(models.Child(org_id=good.id, age=12))
    users = {
        "admin": models.User(email="a@x.org", hashed_password=hash_password(PASSWORD), role="admin"),
        "org": models.User(email="o@x.org", hashed_password=hash_password(PASSWORD), role="organization", organization_id=good.id),
        "donor": models.User(email="d@x.org", hashed_password=hash_password(PASSWORD), role="donor", donor_id=d_edu.id),
        "vol": models.User(email="v@x.org", hashed_password=hash_password(PASSWORD), role="volunteer"),
    }
    db.add_all(users.values())
    db.add(models.KnowledgeBase(title="Volunteer policy", content="Volunteers need a background check before contact with children.",
                                source="Policy", embedding=fake_embed("Volunteer policy. Volunteers need a background check before contact with children."),
                                embedding_model="fake"))
    db.commit()

    def override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        def h(key):
            email = users[key].email
            token = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
            return {"Authorization": f"Bearer {token}"}
        yield client, db, h, {"good": good, "weak": weak, "n1": n1}
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def test_intent_classification():
    assert "health" in live_assistant.classify("How can my organization improve and develop?")
    assert "selection" in live_assistant.classify("Which donors should we ask for the urgent needs?")
    assert "health" in live_assistant.classify("Compare all organizations")
    assert live_assistant.classify("What is the volunteer background check policy?") == []
    # plain policy wording that merely contains "need", "match" or "donor" stays on the knowledge base
    assert live_assistant.classify("Do volunteers need a background check before matching?") == []
    assert live_assistant.classify("Do donors receive a receipt?") == []


def test_org_health_scores_reflect_database_state(world):
    _, db, _, o = world
    good = org_health.organization_health(db, o["good"])
    weak = org_health.organization_health(db, o["weak"])
    assert 0 <= weak["score"] < good["score"] <= 100
    titles = " ".join(r["title"] for r in weak["recommendations"])
    assert "verification" in titles.lower() and weak["recommendations"][0]["priority"] == "high"
    assert any("older than" in r["title"] for r in good["recommendations"])  # the 40-day-old critical need
    assert any("career profile" in r["title"] for r in good["recommendations"])  # 2 children, 0 profiles
    assert good["metrics"]["open_needs"] == 2 and good["metrics"]["amount_30d"] == 1000


def test_admin_asks_about_donors_and_gets_live_ranked_selection(world):
    client, _, h, _ = world
    res = client.post("/assistant/ask", headers=h("admin"), json={"question": "Which donors should we select for the most urgent needs?"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["answer_mode"] == "live_analysis" and body["answer"].startswith("Live data as of")
    sel = body["analysis"]["selection"]
    assert sel[0]["category"] == "School supplies"  # critical + old beats the rest
    assert sel[0]["donors"][0]["label"] == "Edu Donor"  # admins see donor names
    assert body["live_sources"] and body["live_sources"][0]["title"].endswith("(live)")


def test_organization_scope_and_donor_privacy(world):
    client, _, h, o = world
    body = client.post("/assistant/ask", headers=h("org"), json={"question": "How can our organization improve its health?"}).json()
    health = body["analysis"]["health"]
    assert [x["organization_id"] for x in health] == [o["good"].id]  # only its own organization
    sel = client.get("/assistant/insights", headers=h("org")).json()["selection"]
    assert all(s["organization_id"] == o["good"].id for s in sel)
    labels = [d["label"] for s in sel for d in s["donors"]]
    assert labels and all(l.startswith("Donor #") for l in labels)  # donors outside the org stay anonymous


def test_admin_sees_every_organization_lowest_first(world):
    client, _, h, _ = world
    health = client.get("/assistant/insights", headers=h("admin")).json()["health"]
    assert [x["name"] for x in health] == ["Little Stars", "Hope Home"]


def test_donor_gets_needs_for_their_interests_from_verified_orgs_only(world):
    client, _, h, _ = world
    data = client.get("/assistant/insights", headers=h("donor")).json()
    assert [s["category"] for s in data["selection"]] == ["School supplies"]  # education fit; unverified org's need excluded
    assert data["health"] == []


def test_volunteer_has_no_live_insights_and_policy_questions_still_use_the_knowledge_base(world):
    client, _, h, _ = world
    assert client.get("/assistant/insights", headers=h("vol")).status_code == 403
    body = client.post("/assistant/ask", headers=h("admin"), json={"question": "What is the volunteer background check policy?"}).json()
    assert body["analysis"] is None and body["matches"] and body["matches"][0]["title"] == "Volunteer policy"


def test_data_changes_show_up_immediately(world):
    client, db, h, o = world
    before = client.get("/assistant/insights", headers=h("admin")).json()["snapshot"]["open_needs"]
    db.add(models.Need(org_id=o["good"].id, category="Medicine", quantity=3, urgency="high", status="open"))
    db.commit()
    assert client.get("/assistant/insights", headers=h("admin")).json()["snapshot"]["open_needs"] == before + 1


# ---------------------------------------------------------------- RAG development: entities, records, donors, follow-ups
def ask(client, headers, q):
    res = client.post("/assistant/ask", headers=headers, json={"question": q})
    assert res.status_code == 200, res.text
    return res.json()


def test_admin_can_name_an_organization_and_gets_only_that_organization(world):
    client, _, h, o = world
    body = ask(client, h("admin"), "How is Little Stars doing?")
    assert body["focus"] == ["Little Stars"]
    assert [x["name"] for x in body["analysis"]["health"]] == ["Little Stars"]
    assert all(s["organization"] == "Little Stars" for s in body["analysis"]["selection"])
    assert "Focused on: Little Stars" in body["answer"]


def test_organization_users_cannot_pull_other_organizations_by_name(world):
    client, _, h, o = world
    body = ask(client, h("org"), "How is Little Stars doing compared to us? How can we improve?")
    assert body["focus"] == []  # entity zoom is administrator-only
    assert [x["organization_id"] for x in body["analysis"]["health"]] == [o["good"].id]
    assert "Little Stars" not in str(body["analysis"])


def test_naming_a_need_category_zooms_in_on_it(world):
    client, _, h, _ = world
    body = ask(client, h("admin"), "Who could help with Meals?")
    assert body["focus"] == ["Meals"]
    assert [s["category"] for s in body["analysis"]["selection"]] == ["Meals"]


def test_naming_a_donor_returns_a_live_profile_with_best_needs(world):
    client, _, h, _ = world
    body = ask(client, h("admin"), "Tell me about Food Donor")
    prof = body["analysis"]["donor_profiles"][0]
    assert prof["label"] == "Food Donor" and prof["gifts"] == 1 and prof["total_given"] == 1000
    assert prof["status"] == "active" and prof["best_needs"][0]["category"] == "Meals"
    assert "Food Donor is active" in body["answer"]


def test_donor_analytics_lapsed_gaps_and_privacy(world):
    client, db, h, o = world
    old = models.Donor(name="Old Friend", contact="o", preferences="education")
    db.add(old)
    db.flush()
    need = db.query(models.Need).filter_by(category="Meals").one()
    db.add(models.Donation(donor_id=old.id, need_id=need.id, amount=300, timestamp=datetime.utcnow() - timedelta(days=200)))
    db.commit()
    body = ask(client, h("admin"), "Which donors have stopped giving? Show donor analysis")
    di = body["analysis"]["donor_insights"]
    assert di["lapsed_count"] == 1 and di["lapsed"][0]["label"] == "Old Friend"
    assert di["never_given"] >= 1 and di["top_donors"][0]["label"] == "Food Donor"
    assert any(g["category"] == "Clothes" for g in di["interest_gaps"])  # nobody supports clothes
    assert "Lapsed donors worth contacting" in body["answer"]
    # an organization only analyses donors linked to it, never other people's donors
    org_body = ask(client, h("org"), "Show donor analysis and which donors have stopped giving")
    names = str(org_body["analysis"]["donor_insights"])
    assert "Old Friend" not in names


def test_live_records_are_retrieved_for_plain_questions(world):
    client, _, h, _ = world
    body = ask(client, h("admin"), "school supplies quantity at Hope Home")
    assert body["records"] and body["records"][0]["kind"] in ("need", "organization")
    assert any("School supplies" in r["title"] for r in body["records"])
    assert all(r["live"] for r in body["records"])


def test_policy_questions_do_not_pull_in_live_records_or_analysis(world):
    client, _, h, _ = world
    body = ask(client, h("admin"), "Who can see a child's record?")
    assert body["analysis"] is None and body["records"] == [] and body["follow_ups"] == []


def test_short_follow_up_inherits_the_previous_question(world):
    client, _, h, _ = world
    headers = h("admin")
    first = ask(client, headers, "Which needs are most urgent right now?")
    assert first["analysis"]["selection"] and first["follow_ups"]
    follow = ask(client, headers, "and for Little Stars?")
    assert follow["follow_up_of"] == "Which needs are most urgent right now?"
    assert follow["focus"] == ["Little Stars"]
    assert ask(client, headers, "Who can see a child's record?")["follow_up_of"] is None  # no follow-up cue


def test_volunteers_get_no_live_records(world):
    client, _, h, _ = world
    body = ask(client, h("vol"), "Which needs are most urgent right now? Tell me about Hope Home")
    assert body["analysis"] is None and body["records"] == []
