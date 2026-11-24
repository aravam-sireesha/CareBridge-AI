"""RAG v3: hybrid retrieval, hidden phrasings, calibrated confidence, abstention, default knowledge base, gaps."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from admin_factory import make_admin
from app import models
from app.auth import hash_password
from app.database import Base, get_db
from app.knowledge.default_kb import ALSO, ENTRIES, with_keywords
from app.main import app
from app.services import rag_hybrid

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "StrongPass1234!"


def kb_rows():
    return [models.KnowledgeBase(id=i + 1, title=t, source=s, content=with_keywords(t, c)) for i, (t, s, c) in enumerate(ENTRIES)]


def run(dataset):
    data = json.loads((ROOT / "app" / "knowledge" / dataset).read_text())
    rows = kb_rows()
    top3 = top1 = 0
    for it in data["in_scope"]:
        titles = [r["title"] for r in rag_hybrid.search(rows, it["q"], None, 3)]
        top1 += titles[:1] == [it["expected"]]
        top3 += it["expected"] in titles
    refused = sum(1 for q in data["out_of_scope"] if not (r := rag_hybrid.search(rows, q, None, 1)) or not r[0]["answerable"])
    n, m = len(data["in_scope"]), len(data["out_of_scope"])
    return top1 / n, top3 / n, refused / m


# ---------------------------------------------------------------- building blocks
def test_default_knowledge_base_is_consistent():
    assert len(ENTRIES) >= 50 and all(len(c.split()) >= 25 for _, _, c in ENTRIES)
    assert set(ALSO) == {t for t, _, _ in ENTRIES}
    for name in ("eval_questions.json", "eval_heldout.json", "eval_fresh.json"):
        d = json.loads((ROOT / "app" / "knowledge" / name).read_text())
        titles = {t for t, _, _ in ENTRIES}
        assert all(i["expected"] in titles for i in d["in_scope"]) and d["out_of_scope"]


def test_text_processing():
    assert rag_hybrid.stem("donations") == rag_hybrid.stem("donation") and rag_hybrid.stem("running") == "run"
    assert "the" not in rag_hybrid.tokens("What is the password?") and rag_hybrid.tokens("2FA") == ["2fa"]
    w = rag_hybrid.expand(rag_hybrid.tokens("kid scam"))
    assert w["kid"] == 1.0 and w["child"] == 0.5 and w["fraud"] == 0.5  # synonyms count half
    shown, hidden = rag_hybrid.split_hidden(with_keywords("What is CareBridge AI", "Body text here."))
    assert shown == "Body text here." and "what does this website do" in hidden


def test_long_entries_are_split_into_overlapping_passages():
    sentences = [f"Sentence number {i} talks about topic{i} in some detail." for i in range(60)]
    parts = rag_hybrid.chunk(" ".join(sentences))
    assert len(parts) > 3 and all(len(p.split()) <= 140 for p in parts)
    last_sentence_of_first = parts[0].rsplit(". ", 1)[-1].rstrip(".")
    assert last_sentence_of_first in parts[1]  # one sentence of overlap keeps context across the cut
    assert rag_hybrid.chunk("short entry") == ["short entry"] and rag_hybrid.chunk("") == []


def test_the_relevant_paragraph_of_a_long_entry_is_returned():
    filler = " ".join(f"Filler sentence {i} about unrelated gardening and weather." for i in range(40))
    long_entry = models.KnowledgeBase(id=1, title="Handbook", source="s", content=filler + " The fire drill assembly point is the east playground behind the library. " + filler)
    other = models.KnowledgeBase(id=2, title="Other", source="s", content="Completely different words about finances and budgets.")
    best = rag_hybrid.search([long_entry, other], "Where is the fire drill assembly point?", None, 1)[0]
    assert best["id"] == 1 and "east playground" in best["content"] and len(best["content"].split()) < len(best["full_content"].split()) / 2


def test_hidden_phrasings_are_used_for_matching_but_never_shown():
    rows = kb_rows()
    hit = rag_hybrid.search(rows, "I want to enable 2fa", None, 1)[0]
    assert hit["title"] == "How to set up two-step verification"
    assert "[Also asked" not in hit["content"] and "[Also asked" not in hit["full_content"]


def test_confidence_is_calibrated_and_off_topic_questions_are_refused():
    rows = kb_rows()
    good = rag_hybrid.search(rows, "How many wrong passwords before the account is locked?", None, 3)
    assert good[0]["title"] == "Account lockout after wrong passwords" and good[0]["answerable"] and good[0]["label"] in ("medium", "high")
    assert 0 <= good[0]["confidence"] <= 1 and set(good[0]["signals"]) >= {"coverage", "phrase", "title", "bm25", "char", "dense"}
    for q in ("What is the capital of France?", "How do I bake bread?"):
        assert not rag_hybrid.search(rows, q, None, 1)[0]["answerable"]
    assert rag_hybrid.search([], "anything", None, 3) == [] and rag_hybrid.search(rows, "the of and", None, 3) == []


def test_threshold_can_be_tuned_with_an_environment_variable(monkeypatch):
    rows = kb_rows()
    q = "What is the capital of France?"
    assert not rag_hybrid.search(rows, q, None, 1)[0]["answerable"]
    monkeypatch.setenv("RAG_CONFIDENCE_THRESHOLD", "0.01")
    assert rag_hybrid.search(rows, q, None, 1)[0]["answerable"]
    monkeypatch.setenv("RAG_CONFIDENCE_THRESHOLD", "not-a-number")
    assert rag_hybrid.threshold() == rag_hybrid.CONFIDENCE_THRESHOLD


def test_retrieval_accuracy_does_not_regress():
    """Lexical rankers only (no model download). Measured when written: dev 0.87/0.95, held-out 0.89/0.96, fresh 0.50/0.59
    (recall@1 / recall@3). The fresh set is the honest one: paraphrases that share few words with the entries, where the
    dense vectors are expected to help. Off-topic questions must always be refused."""
    d1, d3, dr = run("eval_questions.json")
    h1, h3, hr = run("eval_heldout.json")
    f1, f3, fr = run("eval_fresh.json")
    assert d3 >= 0.9 and h3 >= 0.9 and f3 >= 0.5 and d1 >= 0.8 and f1 >= 0.4
    assert dr == 1.0 and hr == 1.0 and fr == 1.0


# ---------------------------------------------------------------- through the API
@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k")
    monkeypatch.setenv("ADMIN_SIGNUP_CODE", "invite-123")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    org = models.Organization(name="Hope Home", contact="a", verified=True)
    db.add(org)
    db.flush()
    db.add(models.User(email="org@x.org", hashed_password=hash_password(PASSWORD), role="organization", organization_id=org.id))
    db.add(models.User(email="vol@x.org", hashed_password=hash_password(PASSWORD), role="volunteer"))
    db.commit()

    def override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        make_admin(client, "boss@x.org", PASSWORD)
        heads = {}
        for k, e in (("admin", "boss@x.org"), ("org", "org@x.org"), ("vol", "vol@x.org")):
            path = "/admin/login" if k == "admin" else "/auth/login"
            heads[k] = {"Authorization": f"Bearer {client.post(path, json={'email': e, 'password': PASSWORD}).json()['access_token']}"}
        yield client, db, heads
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def test_seeding_the_default_knowledge_base_is_idempotent_and_admin_only(api):
    client, db, h = api
    assert client.post("/assistant/knowledge/seed-defaults", headers=h["org"]).status_code == 403
    first = client.post("/assistant/knowledge/seed-defaults", headers=h["admin"]).json()
    assert first["added"] == len(ENTRIES) and first["updated"] == 0 and first["total"] == len(ENTRIES)
    assert first["dense_available"] is False and first["dense_error"]  # no sentence-transformers in this environment: still works
    second = client.post("/assistant/knowledge/seed-defaults", headers=h["admin"]).json()
    assert second["added"] == 0 and second["updated"] == 0
    entry = db.query(models.KnowledgeBase).filter_by(title="What is CareBridge AI").one()
    entry.content = "old text"
    db.commit()
    assert client.post("/assistant/knowledge/seed-defaults", headers=h["admin"]).json()["updated"] == 1
    status = client.get("/assistant/status", headers=h["admin"]).json()
    assert status["guide_entries_loaded"] == len(ENTRIES) and status["dense_vectors"] is False
    listed = client.get("/assistant/knowledge", headers=h["admin"]).json()
    assert len(listed) == len(ENTRIES) and not any("[Also asked" in e["content"] for e in listed)
    assert "knowledge.defaults_loaded" in {a.action for a in db.query(models.AuditLog).all()}


def test_assistant_answers_from_the_seeded_guide_with_confidence(api):
    client, _, h = api
    client.post("/assistant/knowledge/seed-defaults", headers=h["admin"])
    body = client.post("/assistant/ask", headers=h["org"], json={"question": "How do I recover my access if I lose my authenticator phone?"}).json()
    assert body["matches"][0]["title"] == "Recovery codes and lost phone for two-step verification"
    assert body["confidence"]["answerable"] is True and body["confidence"]["label"] in ("medium", "high") and body["answer_mode"] == "retrieval_only"
    assert "[Also asked" not in body["answer"] and all("[Also asked" not in m["content"] for m in body["matches"])


def test_assistant_abstains_instead_of_guessing_and_the_gap_is_reported(api):
    client, db, h = api
    client.post("/assistant/knowledge/seed-defaults", headers=h["admin"])
    q = "What is the capital of France?"
    for _ in range(2):
        body = client.post("/assistant/ask", headers=h["org"], json={"question": q}).json()
    assert body["answer_mode"] == "low_confidence" and "will not guess" in body["answer"]
    assert body["confidence"]["answerable"] is False and body["matches"]  # closest passages are still shown
    client.post("/assistant/ask", headers=h["org"], json={"question": "How do I turn on 2FA?"})
    gaps = client.get("/assistant/gaps", headers=h["admin"]).json()
    assert [g["question"] for g in gaps] == [q] and gaps[0]["times"] == 2 and gaps[0]["best_confidence"] < 0.33
    assert client.get("/assistant/gaps", headers=h["org"]).status_code == 403


def test_organization_knowledge_works_without_the_embedding_model(api):
    client, db, h = api
    res = client.post("/assistant/knowledge", headers=h["org"], json={"title": "Fire drill", "content": "The fire drill assembly point is the east playground.", "source": "Our policy"})
    assert res.status_code == 201 and res.json()["embedding_model"] is None
    body = client.post("/assistant/ask", headers=h["org"], json={"question": "Where is the fire drill assembly point?"}).json()
    assert body["matches"][0]["title"] == "Fire drill" and body["confidence"]["answerable"]
    # another organization's volunteers do not see this private entry
    other = client.post("/assistant/ask", headers=h["vol"], json={"question": "Where is the fire drill assembly point?"}).json()
    assert all(m["title"] != "Fire drill" for m in other["matches"])
