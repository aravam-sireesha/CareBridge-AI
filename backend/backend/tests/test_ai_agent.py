"""Phase 5: agentic AI - tool selection, structured and validated outputs, human approval for consequential decisions."""
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from admin_factory import make_admin
from app import models as m
from app.ai.agent import orchestrator, planner, tools
from app.auth import hash_password
from app.database import Base, get_db
from app.knowledge.default_kb import ENTRIES, with_keywords
from app.main import app

PASSWORD = "StrongPass1234!"


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_KEY", "k")
    monkeypatch.setenv("ADMIN_SIGNUP_CODE", "invite-123")
    monkeypatch.setenv("RAG_CROSS_ENCODER", "off")
    from app.ai.ml import need_model
    monkeypatch.setattr(need_model, "MODEL_DIR", tmp_path)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    for t, s, c in ENTRIES:
        db.add(m.KnowledgeBase(title=t, source=s, content=with_keywords(t, c)))
    now = datetime.utcnow()
    hope = m.Organization(name="Hope Home", contact="a", verified=True)
    stars = m.Organization(name="Little Stars", contact="b", verified=True)
    db.add_all([hope, stars])
    db.flush()
    needs = []
    for i in range(8):
        needs.append(m.Need(org_id=hope.id if i % 2 == 0 else stars.id, category="Books", quantity=20 + i, urgency=["critical", "high", "medium", "low"][i % 4], status="open",
                            created_at=now - timedelta(days=30 * (i // 2) + 4)))
    needs.append(m.Need(org_id=hope.id, category="Meals", quantity=15, urgency="medium", status="open", created_at=now - timedelta(days=3)))
    db.add_all(needs)
    donors = [m.Donor(name="Edu Donor", contact="e", preferences="education"), m.Donor(name="Food Donor", contact="f", preferences="food")]
    db.add_all(donors + [m.Resource(organization_id=hope.id, name="Textbook set", category="books", quantity_total=40, quantity_available=40, unit="sets"),
                         m.Resource(organization_id=stars.id, name="Meal packs", category="food", quantity_total=10, quantity_available=10, unit="packs")])
    db.flush()
    db.add(m.Donation(donor_id=donors[0].id, need_id=needs[0].id, amount=1500))
    db.add(m.User(email="org@x.org", hashed_password=hash_password(PASSWORD), role="organization", organization_id=hope.id))
    db.commit()

    def override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        make_admin(client, "boss@x.org", PASSWORD)
        heads = {"admin": {"Authorization": "Bearer " + client.post("/admin/login", json={"email": "boss@x.org", "password": PASSWORD}).json()["access_token"]},
                 "org": {"Authorization": "Bearer " + client.post("/auth/login", json={"email": "org@x.org", "password": PASSWORD}).json()["access_token"]}}
        yield client, db, heads, {"needs": needs, "hope": hope}
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


ADMIN = {"role": "admin", "id": 1, "email": "boss@x.org"}


# ----------------------------------------------------------------------------- tools
def test_every_tool_has_typed_input_and_output_and_a_clear_boundary():
    assert {"retrieve_knowledge", "query_live_data", "forecast_demand", "predict_fulfilment", "simulate_shortfall", "detect_anomalies", "calculate",
            "optimize_allocation", "optimize_matching", "plan_route", "check_data_quality", "similar_needs"} == set(tools.REGISTRY)
    kinds = {t.kind for t in tools.REGISTRY.values()}
    assert kinds == {"knowledge", "ml", "python", "optimization"}
    for t in tools.REGISTRY.values():
        spec = t.spec()
        assert spec["input_schema"]["type"] == "object" and t.output.model_json_schema()
    assert {t.name for t in tools.REGISTRY.values() if t.requires_approval} == {"optimize_allocation", "optimize_matching"}
    assert {t.name for t in tools.REGISTRY.values() if not t.admin_only} == {"retrieve_knowledge", "query_live_data"}


def test_python_calculates_safely_and_exactly():
    assert tools.safe_eval("12 * 30 + 5") == 365 and tools.safe_eval("(2 + 3) ** 2 / 5") == 5.0 and tools.safe_eval("-4 + +6") == 2
    for bad in ("__import__('os').system('x')", "open('f')", "a + 1", "2 ** 1000", "[1,2]", "1 if 1 else 2", "lambda: 1"):
        with pytest.raises((ValueError, SyntaxError, TypeError)):
            tools.safe_eval(bad)
    with pytest.raises(ZeroDivisionError):
        tools.safe_eval("1/0")
    assert planner.extract_expression("What is 1,200 * 3 + 5 ?") == "1200*3+5" or planner.extract_expression("What is 1,200 * 3 + 5 ?").replace(" ", "") == "1200*3+5"


# ----------------------------------------------------------------------------- planning and routing
def test_the_planner_picks_the_right_tools_for_each_kind_of_question(world):
    _, db, _, w = world
    plan = lambda q: [s["tool"] for s in planner.make_plan(db, ADMIN, q)[0]]  # noqa: E731
    assert plan("How many wrong passwords lock an account?") == ["retrieve_knowledge"]
    assert plan("Forecast books demand next month") == ["forecast_demand", "simulate_shortfall"]
    assert plan(f"Will need {w['needs'][0].id} be fulfilled in time?") == ["predict_fulfilment", "similar_needs"]
    assert plan("Allocate the books fairly") == ["optimize_allocation"]
    assert plan("Match donors to the open needs") == ["optimize_matching"]
    assert plan("Plan the delivery route for the trucks") == ["plan_route"]
    assert plan("Calculate the average donation") == ["calculate"] and plan("What is 12 * 30 + 5?") == ["calculate"]
    assert plan("Show suspicious donations") == ["detect_anomalies"] and plan("Is the data consistent? Check data quality") [-1] == "check_data_quality"
    multi = plan("Forecast book demand and then allocate the stock fairly")
    assert "forecast_demand" in multi and "optimize_allocation" in multi


def test_an_llm_plan_is_validated_and_bad_plans_fall_back_to_the_rules(world):
    _, db, _, _ = world
    good = lambda p: json.dumps([{"tool": "calculate", "args": {"expression": "2+2"}, "why": "x"}, {"tool": "delete_everything", "args": {}}, {"tool": "optimize_allocation", "args": {"fairness": "bogus"}}])  # noqa: E731
    steps, by = planner.make_plan(db, ADMIN, "anything about 4", llm=good)
    assert by == "llm" and [s["tool"] for s in steps] == ["calculate"]               # unknown tool and invalid argument were dropped
    for broken in (lambda p: "not json", lambda p: 1 / 0, lambda p: "[]"):
        steps, by = planner.make_plan(db, ADMIN, "How do I reset my password?", llm=broken)
        assert by == "rules" and steps[0]["tool"] == "retrieve_knowledge"


# ----------------------------------------------------------------------------- the whole agent
def test_the_agent_answers_from_knowledge_with_citations_and_passes_every_check(world):
    _, db, _, _ = world
    r = orchestrator.run_agent(db, "How many wrong passwords lock an account?", ADMIN)
    assert [s["tool"] for s in r["steps"]] == ["retrieve_knowledge"] and r["steps"][0]["agent"] == "retriever"
    assert "15 minutes" in r["answer"] and r["citations"][0]["title"] == "Account lockout after wrong passwords"
    assert r["validation"] == {**r["validation"], "schema_ok": True, "rag_ok": True, "constraints_ok": True, "numbers_ok": True} and r["requires_approval"] is False
    assert [t["agent"] for t in r["trace"]] == ["router", "planner", "tools", "verifier"]


def test_ml_and_python_tools_run_and_every_number_in_the_answer_comes_from_a_tool(world):
    _, db, _, w = world
    f = orchestrator.run_agent(db, "Forecast books demand next month", ADMIN)
    assert [s["status"] for s in f["steps"]] == ["ok", "ok"] and {s["agent"] for s in f["steps"]} == {"analyst"} and f["validation"]["numbers_ok"]
    assert "books" in f["answer"].lower() and "chance of a shortfall" in f["answer"]
    p = orchestrator.run_agent(db, f"Will need {w['needs'][0].id} be fulfilled in time?", ADMIN)
    out = p["steps"][0]["output"]
    assert 0 <= out["probability"] <= 1 and f"{round(100 * out['probability'])}%" in p["answer"] and p["validation"]["numbers_ok"]
    c = orchestrator.run_agent(db, "What is 12 * 30 + 5?", ADMIN)
    assert c["steps"][0]["output"]["value"] == 365 and "365" in c["answer"]
    d = orchestrator.run_agent(db, "What is the total donations given?", ADMIN)
    assert d["steps"][0]["output"]["value"] == 1500.0 and "1500" in d["answer"]


def test_a_failing_tool_is_isolated_and_reported(world):
    _, db, _, _ = world
    r = orchestrator.run_agent(db, "Will need 99999 be fulfilled in time?", ADMIN)
    assert r["steps"][0]["status"] == "error" and "not found" in r["steps"][0]["error"].lower() and "could not run" in r["answer"]
    bad = orchestrator.run_agent(db, "What is 1 / 0 ?", ADMIN)
    assert bad["steps"][0]["status"] == "error" and bad["validation"]["numbers_ok"] is True


def test_non_admins_only_get_the_knowledge_tools(world):
    _, db, _, _ = world
    org = {"role": "organization", "id": 5, "organization_id": 1, "email": "org@x.org"}
    r = orchestrator.run_agent(db, "Allocate the books fairly", org, create_proposals=True)
    assert r["steps"][0]["status"] == "denied" and r["proposals"] == [] and any("administrators only" in w for w in r["validation"]["warnings"])
    assert db.query(m.ResourceAllocation).count() == 0
    ok = orchestrator.run_agent(db, "How do I reset my password?", org)
    assert ok["steps"][0]["status"] == "ok"


# ----------------------------------------------------------------------------- human approval for consequential decisions
def test_optimizers_only_propose_and_a_person_must_approve(world):
    _, db, _, _ = world
    dry = orchestrator.run_agent(db, "Allocate the books fairly across the needs", ADMIN)
    out = dry["steps"][0]["output"]
    assert dry["requires_approval"] is True and out["proposals_created"] == [] and out["violations"] == [] and db.query(m.ResourceAllocation).count() == 0
    per_supply = {}
    for a in out["allocations"]:
        per_supply[a["supply_id"]] = per_supply.get(a["supply_id"], 0) + a["units"]
    stock = {r.id: r.quantity_available for r in db.query(m.Resource).all()}
    assert all(u <= stock[r] for r, u in per_supply.items()) and "needs human approval" in dry["answer"]
    live = orchestrator.run_agent(db, "Allocate the books fairly across the needs", ADMIN, create_proposals=True)
    rows = db.query(m.ResourceAllocation).all()
    assert rows and all(r.status == "proposed" for r in rows) and live["proposals"] and all(p["status"] == "proposed" for p in live["proposals"])
    assert db.query(m.Resource).filter_by(name="Textbook set").one().quantity_available == 40       # stock untouched until a person approves
    acts = {a.action for a in db.query(m.AuditLog).all()}
    assert {"agent.run", "agent.proposals_created"} <= acts
    match = orchestrator.run_agent(db, "Match donors to the open needs", ADMIN, create_proposals=True)
    assert match["requires_approval"] and all(s.status == "suggested" for s in db.query(m.DonorSuggestion).filter_by(model_version="milp-matching-1.0").all())
    assert "capacity" in match["answer"]


def test_the_language_model_may_only_use_numbers_from_the_tool_results(world):
    _, db, _, _ = world
    honest = orchestrator.run_agent(db, "What is 12 * 30 + 5?", ADMIN, llm=lambda p: "The result is 365.")
    assert honest["mode"] == "llm_verified" and honest["answer"] == "The result is 365."
    liar = orchestrator.run_agent(db, "What is 12 * 30 + 5?", ADMIN, llm=lambda p: "The result is 99999.")
    assert liar["mode"] == "template" and "365" in liar["answer"] and any("not in the tool results" in w for w in liar["validation"]["warnings"])
    crash = orchestrator.run_agent(db, "What is 12 * 30 + 5?", ADMIN, llm=lambda p: 1 / 0)
    assert crash["mode"] == "template" and any("unavailable" in w for w in crash["validation"]["warnings"])
    seen = []
    orchestrator.run_agent(db, "What is 12 * 30 + 5?", ADMIN, llm=lambda p: seen.append(p) or "365")
    assert "ONLY numbers that appear in the results" in seen[0] and "needs human approval" in seen[0]


def test_greetings_use_no_tools_and_runs_are_deterministic(world):
    _, db, _, _ = world
    hi = orchestrator.run_agent(db, "Hello", ADMIN)
    assert hi["steps"] == [] and hi["mode"] == "no_tools"
    a = orchestrator.run_agent(db, "Allocate the books fairly across the needs", ADMIN)
    b = orchestrator.run_agent(db, "Allocate the books fairly across the needs", ADMIN)
    assert a["steps"][0]["output"]["allocations"] == b["steps"][0]["output"]["allocations"] and a["answer"] == b["answer"]


def test_routing_needs_coordinates_and_says_so(world):
    _, db, _, _ = world
    r = orchestrator.run_agent(db, "Plan the delivery route", ADMIN)
    assert r["steps"][0]["status"] == "error" and "coordinates" in r["steps"][0]["error"]
    stops = [{"id": 1, "lat": 17.4, "lon": 78.5, "demand": 5}, {"id": 2, "lat": 17.5, "lon": 78.4, "demand": 5}]
    out = tools.REGISTRY["plan_route"].run(db, ADMIN, tools.RouteIn(depot_lat=17.38, depot_lon=78.48, stops=stops, vehicles=1, capacity=20))
    assert tools.RouteOut.model_validate(out).vehicles_needed == 1


# ----------------------------------------------------------------------------- the API
def test_agent_endpoints_and_role_gating(world):
    client, db, h, w = world
    assert client.post("/agent/run", json={"question": "hi there"}).status_code == 401
    assert {t["name"] for t in client.get("/agent/tools", headers=h["org"]).json()} == {"retrieve_knowledge", "query_live_data"}
    assert len(client.get("/agent/tools", headers=h["admin"]).json()) == 12
    r = client.post("/agent/run", headers=h["admin"], json={"question": "Forecast books demand next month"}).json()
    assert r["steps"][0]["tool"] == "forecast_demand" and r["validation"]["numbers_ok"]
    denied = client.post("/agent/run", headers=h["org"], json={"question": "Forecast books demand next month"}).json()
    assert denied["steps"][0]["status"] == "denied"
    adv = client.post("/assistant/answer", headers=h["org"], json={"question": "How many wrong passwords lock an account?"}).json()
    assert adv["answerable"] and adv["citations"] and adv["route"] == "knowledge"
    for path in ("/admin/ai/data-quality", "/admin/ai/models", "/admin/ai/forecast", "/admin/ai/anomalies", "/admin/ai/segments", "/admin/ai/report"):
        assert client.get(path, headers=h["org"]).status_code == 403 and client.get(path, headers=h["admin"]).status_code == 200


def test_ai_lab_endpoints_work_end_to_end(world):
    client, db, h, w = world
    dq = client.get("/admin/ai/data-quality", headers=h["admin"]).json()
    assert dq["tables"]["needs"] == 9 and "ok" in dq
    models_ = client.get("/admin/ai/models", headers=h["admin"]).json()
    assert models_["trained"] is False and "fulfilled within 14 days" in models_["problem"]
    train = client.post("/admin/ai/models/train", headers=h["admin"]).json()
    assert train["trained"] is False and "at least" in train["reason"].lower()
    pred = client.get(f"/admin/ai/predict/{w['needs'][0].id}", headers=h["admin"]).json()
    assert 0 <= pred["probability"] <= 1 and client.get("/admin/ai/predict/9999", headers=h["admin"]).status_code == 404
    fc = client.get("/admin/ai/forecast", headers=h["admin"]).json()
    assert fc and fc[0]["category"] == "books" and "method" in fc[0]
    opt = client.post("/admin/ai/optimize/allocation", headers=h["admin"], json={"fairness": "maxmin", "create_proposals": True}).json()
    assert opt["requires_approval"] and opt["violations"] == [] and opt["proposals_created"]
    assert client.post("/admin/ai/optimize/allocation", headers=h["admin"], json={"fairness": "invalid"}).status_code == 422
    # break the inventory, see it detected, repair it
    res = db.query(m.Resource).filter_by(name="Meal packs").one()
    res.quantity_available = 3
    db.commit()
    bad = client.get("/admin/ai/data-quality", headers=h["admin"]).json()
    assert "resource_stock" in {i["code"] for i in bad["issues"]}
    fixed = client.post("/admin/ai/data-quality/repair", headers=h["admin"], json={"fixes": ["resource_stock"]}).json()
    assert fixed["changed"] == {"resource_stock": 1} and "resource_stock" not in {i["code"] for i in fixed["report"]["issues"]}
    assert client.post("/admin/ai/data-quality/repair", headers=h["admin"], json={"fixes": ["drop_tables"]}).status_code == 422
