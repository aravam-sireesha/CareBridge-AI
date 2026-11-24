"""The need-form assistant returns validated suggestions only and never saves anything. Run with:  python -m pytest tests/test_need_assist.py -q"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.routers import need_assist as router_mod
from app.services import llm

PASSWORD = "StrongPass1234"
TEXT = "We urgently need 40 winter blankets for the children by Friday because nights are cold."


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k")
    for n in ("LLM_API_KEY", "OPENAI_API_KEY", "LLM_BASE_URL", "OPENAI_BASE_URL"):
        monkeypatch.delenv(n, raising=False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    org = models.Organization(name="Hope", contact="c", verified=True)
    db.add(org)
    db.flush()
    db.add_all([models.User(email="o@x.org", hashed_password=hash_password(PASSWORD), role="organization", organization_id=org.id),
                models.User(email="d@x.org", hashed_password=hash_password(PASSWORD), role="donor")])
    db.commit()
    router_mod._hits.clear()

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


def test_rules_suggest_when_no_model_is_connected_and_say_so(env):
    client, db, h = env
    res = client.post("/need-assist", headers=h("o@x.org"), json={"text": TEXT}).json()
    assert res["source"] == "rules" and "keyword rules" in res["notice"]
    assert res["suggestions"]["urgency"] == "high" and res["suggestions"]["category"] == "Clothing"
    assert db.query(models.Need).count() == 0                                   # nothing is saved


def test_model_output_is_validated_and_used(env, monkeypatch):
    client, _, h = env
    monkeypatch.setattr(llm, "config", lambda: llm.LLMConfig("k", "http://x", "m", "m", 5))
    monkeypatch.setattr(llm, "stream_chat", lambda *a, **k: iter(['{"category":"Clothing","urgency":"extreme","title":"Winter blankets","description":"40 blankets needed.","missing":[]}']))
    res = client.post("/need-assist", headers=h("o@x.org"), json={"text": TEXT}).json()
    assert res["source"] == "model" and res["suggestions"]["title"] == "Winter blankets"
    assert res["suggestions"]["urgency"] == "high"                              # the model's invalid "extreme" was discarded; the rule value is kept


def test_model_failure_falls_back_to_rules_with_a_reason(env, monkeypatch):
    client, _, h = env
    monkeypatch.setattr(llm, "config", lambda: llm.LLMConfig("k", "http://x", "m", "m", 5))

    def boom(*a, **k):
        raise llm.LLMError("The language model service is rate limiting requests right now.")
        yield  # pragma: no cover

    monkeypatch.setattr(llm, "stream_chat", boom)
    res = client.post("/need-assist", headers=h("o@x.org"), json={"text": TEXT}).json()
    assert res["source"] == "rules" and "rate limiting" in res["notice"]


def test_only_admins_and_organizations_and_input_is_bounded(env):
    client, _, h = env
    assert client.post("/need-assist", headers=h("d@x.org"), json={"text": TEXT}).status_code == 403
    assert client.post("/need-assist", json={"text": TEXT}).status_code == 401
    assert client.post("/need-assist", headers=h("o@x.org"), json={"text": "short"}).status_code == 422
    assert client.post("/need-assist", headers=h("o@x.org"), json={"text": "x" * 2001}).status_code == 422


def test_rate_limit(env, monkeypatch):
    client, _, h = env
    monkeypatch.setattr(router_mod, "LIMIT", 2)
    codes = [client.post("/need-assist", headers=h("o@x.org"), json={"text": TEXT}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
