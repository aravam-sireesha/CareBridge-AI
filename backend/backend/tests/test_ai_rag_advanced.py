"""Phase 2: hybrid retrieval, metadata filtering, reranking, GraphRAG, decomposition, CRAG, adaptive routing, cited answers."""
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models as m
from app.ai.rag import adaptive, answer as ans, crag, decompose as dec, filters, graph, pipeline
from app.database import Base
from app.knowledge.default_kb import ENTRIES, with_keywords
from app.services import rag_hybrid

ROOT = Path(__file__).resolve().parents[1]


def kb():
    return [m.KnowledgeBase(id=i + 1, title=t, source=s, content=with_keywords(t, c)) for i, (t, s, c) in enumerate(ENTRIES)]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    for e in kb():
        s.add(m.KnowledgeBase(title=e.title, source=e.source, content=e.content))
    org = m.Organization(name="Hope Home", contact="a", verified=True)
    s.add(org)
    s.flush()
    s.add(m.Need(org_id=org.id, category="Books", quantity=40, urgency="critical", status="open"))
    s.add(m.Donor(name="Edu Donor", contact="e", preferences="education"))
    s.add(m.Organization(name="Other Org", contact="b", verified=True, ))
    s.commit()
    yield s
    s.close()
    engine.dispose()


# ----------------------------------------------------------------------------- metadata filtering
def test_metadata_filters_scope_by_topic_organization_and_source():
    entries = kb() + [m.KnowledgeBase(id=900, title="Private", source="Org policy", content="Only for org 7", organization_id=7)]
    sec = filters.apply(entries, filters.MetadataFilter(topics={"security"}))
    assert sec and all(filters.entry_topic(e) == "security" for e in sec)
    assert all(e.organization_id is None for e in filters.apply(entries, filters.MetadataFilter(only_global=True)))
    assert any(e.id == 900 for e in filters.apply(entries, filters.MetadataFilter(organization_id=7)))
    assert not any(e.id == 900 for e in filters.apply(entries, filters.MetadataFilter(organization_id=8)))
    assert filters.infer("How many wrong passwords lock me out?").topics >= {"security"}
    assert filters.infer("How do donors register?") is None
    assert filters.infer("password and consent for photos") is None  # two topics: no hard filter


# ----------------------------------------------------------------------------- reranking and extra rankers
def test_a_cross_encoder_can_reorder_candidates_and_a_failing_one_is_ignored():
    rows = kb()
    q = "Is a donor allowed to open a student's profile?"
    base = rag_hybrid.search(rows, q, None, 3)
    target = base[-1]["title"]

    def ce(query, passages):  # a stand-in cross-encoder that strongly prefers one entry
        return [8.0 if target in p else -8.0 for p in passages]

    boosted = rag_hybrid.search(rows, q, None, 3, cross_encoder=ce, ce_weight=0.9)
    assert boosted[0]["title"] == target and boosted[0]["signals"]["cross_encoder"] > 0.9
    broken = rag_hybrid.search(rows, q, None, 3, cross_encoder=lambda *_: 1 / 0)
    assert [r["title"] for r in broken] == [r["title"] for r in base]


# ----------------------------------------------------------------------------- GraphRAG
def test_graph_ranker_reaches_entries_through_related_concepts():
    rows = kb()
    kg = graph.KnowledgeGraph(rows)
    ranks = kg.rank("authenticator")  # the ontology links 'authenticator' to 'recovery', so recovery-code entries are reached too
    top = [rows[i - 1].title for i, _ in sorted(ranks.items(), key=lambda kv: -kv[1])[:3]]
    assert "Recovery codes and lost phone for two-step verification" in top and max(ranks.values()) == 1.0
    assert kg.rank("zzzz qqqq") == {}
    q = "lost authenticator"
    entry = [r for r in rows if r.title.startswith("Recovery codes")][0]
    assert kg.concepts_linking(entry.id, q)
    # the graph is cached per knowledge-base content
    assert graph.knowledge_graph(rows) is graph.knowledge_graph(rows)


def test_live_graph_walks_from_an_organization_to_matching_donors(db):
    out = graph.related_entities(db, {"role": "admin", "id": 1}, "Which donors could help Hope Home?")
    assert out and out[0]["type"] in ("need", "donor") and any(o["type"] == "donor" and o["label"] == "Edu Donor" for o in out)
    assert graph.related_entities(db, {"role": "admin", "id": 1}, "what is two-step verification") == []


# ----------------------------------------------------------------------------- decomposition and routing
def test_query_decomposition():
    parts = [p["text"] for p in dec.decompose("How do I add a need and what happens when it is fulfilled?")]
    assert len(parts) == 2 and parts[0].startswith("How do I add a need") and parts[1].startswith("what happens")
    cmp_ = dec.decompose("Compare donors and volunteers")
    assert [p["text"] for p in cmp_] == ["What is donors?", "What is volunteers?"]
    ref = dec.decompose("How do I reset my password? And for administrators?")
    assert ref[1]["depends_on"] == 0 and "about:" in ref[1]["text"]
    assert len(dec.decompose("a? b? c? d? e? f?")) <= 4 and dec.decompose("   ") == []
    # an LLM decomposition is accepted only if it is valid
    assert [p["text"] for p in dec.decompose("anything", llm=lambda q: ["First part?", "Second part?"])] == ["First part?", "Second part?"]
    assert dec.decompose("How do I add a need?", llm=lambda q: "not a list")[0]["text"] == "How do I add a need?"
    assert dec.decompose("How do I add a need?", llm=lambda q: 1 / 0)[0]["text"] == "How do I add a need?"


ROUTE_CASES = [
    ("Hello there", "chitchat"), ("thanks!", "chitchat"),
    ("How do I reset my password?", "knowledge"), ("What does verification mean?", "knowledge"),
    ("Which needs are most urgent right now?", "live_data"), ("Compare all organizations", "live_data"),
    ("Forecast the demand for books next month", "prediction"), ("What is the risk of a shortage?", "prediction"),
    ("Allocate the books fairly across the homes", "optimization"), ("Optimize the assignment of volunteers", "optimization"),
    ("Calculate the average donation per need", "calculation"), ("What is the total of 12 + 30?", "calculation"),
    ("Show suspicious donations", "anomaly"), ("Are there any outliers in the needs?", "anomaly"),
]


@pytest.mark.parametrize("q,route", ROUTE_CASES)
def test_adaptive_routing(q, route):
    assert adaptive.classify(q)["route"] == route


def test_mixed_questions_are_marked_multi():
    r = adaptive.classify("Forecast book demand and then allocate the stock fairly")
    assert r["complexity"] == "multi" and set(r["routes"]) >= {"prediction", "optimization"}


# ----------------------------------------------------------------------------- corrective RAG
def test_crag_grades_and_corrects_a_weak_first_retrieval():
    rows = kb()
    calls = []

    def retrieve(q, f, ids=None):
        calls.append((q, f))
        pool = rows if f is None else filters.apply(rows, f)
        return rag_hybrid.search([e for e in pool if ids is None or e.id in ids], q, None, 5)

    # a metadata filter that hides the right entry is dropped, the retrieval re-run, and the grade improves
    wrong = filters.MetadataFilter(topics={"safeguarding"})
    out = crag.corrective_retrieve(retrieve, "How many wrong passwords before the account is locked?", wrong)
    steps = [a["step"] for a in out["actions"]]
    assert steps[0] == "retrieve" and "drop_filter" in steps and out["results"][0]["title"] == "Account lockout after wrong passwords"
    assert out["grade"] in ("correct", "ambiguous")
    off = crag.corrective_retrieve(lambda q, f, ids=None: rag_hybrid.search([e for e in rows if ids is None or e.id in ids], q, None, 5), "What is the capital of France?")
    assert off["grade"] == "incorrect" and crag.grade([]) == "incorrect"
    # a rewrite may only add words; off-topic questions must still be refused after correction (the earlier bug)
    for q in ("Who invented the telephone?", "How do I bake a chocolate cake?"):
        res = crag.corrective_retrieve(lambda qq, f, ids=None: rag_hybrid.search([e for e in rows if ids is None or e.id in ids], qq, None, 5), q)["results"]
        assert not res[0]["answerable"]
    assert crag.rewrite("password", rag_hybrid.search(rows, "password", None, 3)).startswith("password")


# ----------------------------------------------------------------------------- cited answers and self-checks
EVIDENCE = [{"n": 1, "title": "Lockout", "source": "s", "confidence": 0.8, "text": "After 5 wrong passwords the account is locked for 15 minutes. A correct sign-in resets the counter."},
            {"n": 2, "title": "2FA", "source": "s", "confidence": 0.6, "text": "Administrators can turn on two-step verification in Settings. Each recovery code works only one time."}]


def test_extractive_answers_quote_the_evidence_and_cite_it():
    a = ans.extractive_answer("How long is an account locked after wrong passwords?", EVIDENCE)
    assert "15 minutes" in a["text"] and "[1]" in a["text"]
    chk = ans.verify(a["text"], EVIDENCE)
    assert chk["ok"] and chk["invalid_citations"] == [] and all(s["support"] >= 0.6 for s in chk["sentences"])


def test_verification_catches_unsupported_sentences_bad_citations_and_invented_numbers():
    fabricated = "The account is locked for 90 minutes [1]. Administrators must change passwords every 3 days [7]."
    chk = ans.verify(fabricated, EVIDENCE)
    assert not chk["ok"] and chk["invalid_citations"] == [7] and len(chk["unsupported"]) == 2
    nums = ans.numbers_grounded(fabricated, [e["text"] for e in EVIDENCE])
    assert not nums["ok"] and "90" in nums["ungrounded"][0]
    assert ans.numbers_grounded("It is locked for 15 minutes [1].", [e["text"] for e in EVIDENCE])["ok"]
    assert ans.numbers_grounded("The optimizer assigns 42 units.", [], allowed=[42.0])["ok"]  # a tool result is trusted


def test_list_markers_in_multi_part_answers_are_not_treated_as_unsupported_numbers():
    text = "1) After 5 wrong passwords the account is locked for 15 minutes [1]. 2) Each recovery code works only one time [2]."
    chk = ans.verify(text, EVIDENCE)
    assert chk["ok"] and chk["unsupported"] == []
    assert ans.numbers_grounded(text, [e["text"] for e in EVIDENCE])["ok"]


def test_llm_answers_are_verified_and_unsupported_ones_fall_back():
    good = ans.llm_answer("How long is the lock?", EVIDENCE, lambda p: "The account is locked for 15 minutes [1].")
    assert good["mode"] == "llm_verified" and "15 minutes" in good["text"]
    mixed = ans.llm_answer("How long?", EVIDENCE, lambda p: "The account is locked for 15 minutes [1]. Bananas are blue [2].")
    assert mixed["mode"] == "llm_verified" and mixed["dropped"] == ["Bananas are blue."]
    assert ans.llm_answer("q", EVIDENCE, lambda p: "Locked for an hour [9].")["mode"] == "extractive_fallback"
    assert ans.llm_answer("q", EVIDENCE, lambda p: "INSUFFICIENT EVIDENCE")["mode"] == "extractive_fallback"
    assert ans.llm_answer("q", EVIDENCE, lambda p: 1 / 0)["reason"] == "language model unavailable"
    assert "ONLY the numbered passages" in ans.build_prompt("q", EVIDENCE)


# ----------------------------------------------------------------------------- the whole pipeline
def test_pipeline_answers_with_citations_routing_and_validation(db):
    out = pipeline.answer_question(db, "How many wrong passwords before an account is locked?", {"role": "admin", "id": 1}, cross_encoder=None)
    assert out["answerable"] and out["route"] == "knowledge" and out["mode"] == "extractive"
    assert "15 minutes" in out["answer"] and out["citations"] and out["citations"][0]["title"] == "Account lockout after wrong passwords"
    assert out["validation"]["ok"] and out["validation"]["numbers"]["ok"] and out["graph"] is True
    assert out["subquestions"][0]["grade"] in ("correct", "ambiguous") and out["evidence"][0]["via"] is not None


def test_pipeline_decomposes_multi_part_questions_and_cites_each_part(db):
    out = pipeline.answer_question(db, "How do I turn on two-step verification and what are recovery codes?", {"role": "admin", "id": 1}, cross_encoder=None)
    assert len(out["subquestions"]) == 2 and "1)" in out["answer"] and "2)" in out["answer"]
    titles = {e["title"] for e in out["evidence"]}
    assert "How to set up two-step verification" in titles and "Recovery codes and lost phone for two-step verification" in titles


def test_pipeline_abstains_greets_and_uses_live_data(db):
    off = pipeline.answer_question(db, "What is the capital of France?", {"role": "admin", "id": 1}, cross_encoder=None)
    assert not off["answerable"] and off["mode"] == "abstained" and off["evidence"] == []
    hi = pipeline.answer_question(db, "Hello", cross_encoder=None)
    assert hi["mode"] == "no_retrieval" and hi["evidence"] == []
    live = pipeline.answer_question(db, "Which needs are most urgent right now?", {"role": "admin", "id": 1}, cross_encoder=None)
    assert live["route"] == "live_data" and any(e["kind"] == "live" for e in live["evidence"]) and "Live data as of" in live["answer"]


def test_pipeline_respects_roles_and_private_knowledge(db):
    org_id = db.query(m.Organization).first().id
    db.add(m.KnowledgeBase(title="Fire drill", source="Our policy", content="The fire drill assembly point is the east playground.", organization_id=org_id))
    db.commit()
    q = "Where is the fire drill assembly point?"
    mine = pipeline.answer_question(db, q, {"role": "organization", "id": 5, "organization_id": org_id}, cross_encoder=None)
    other = pipeline.answer_question(db, q, {"role": "donor", "id": 6}, cross_encoder=None)
    assert any(e["title"] == "Fire drill" for e in mine["evidence"]) and not any(e["title"] == "Fire drill" for e in other["evidence"])


def test_pipeline_uses_a_language_model_only_through_verification(db):
    out = pipeline.answer_question(db, "How long is an account locked?", {"role": "admin", "id": 1}, cross_encoder=None,
                                   llm=lambda prompt: "The account is locked for 15 minutes [1]. It also deletes your files [1].")
    assert out["mode"] == "llm_verified" and "deletes" not in out["answer"]


def test_corrective_and_graph_stages_do_not_hurt_retrieval_accuracy():
    """On the fresh question set the full pipeline must be at least as good as plain hybrid retrieval."""
    data = json.loads((ROOT / "app" / "knowledge" / "eval_fresh.json").read_text())
    rows = kb()
    kg = graph.KnowledgeGraph(rows)
    plain = full = 0
    for it in data["in_scope"]:
        a = [r["title"] for r in rag_hybrid.search(rows, it["q"], None, 3)]
        out = crag.corrective_retrieve(lambda q, f, ids=None: rag_hybrid.search([e for e in rows if ids is None or e.id in ids], q, None, 5, extra_rankers=[(0.8, kg.rank(q))]), it["q"])
        b = [r["title"] for r in out["results"][:3]]
        plain += it["expected"] in a
        full += it["expected"] in b
    assert full >= plain - 1, (plain, full)


def test_without_networkx_everything_still_works_just_without_the_graph(db, monkeypatch):
    monkeypatch.setattr(graph, "nx", None)
    assert graph.knowledge_graph(kb()) is None and graph.related_entities(db, {"role": "admin", "id": 1}, "Hope Home") == []
    out = pipeline.answer_question(db, "How many wrong passwords before an account is locked?", {"role": "admin", "id": 1}, cross_encoder=None)
    assert out["answerable"] and out["graph"] is False and "15 minutes" in out["answer"]
