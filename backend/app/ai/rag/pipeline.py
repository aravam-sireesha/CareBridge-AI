"""Phase 2 pipeline: adaptive routing -> query decomposition -> metadata-filtered hybrid retrieval (BM25 + n-gram + dense,
fused with RRF, plus a GraphRAG ranker) -> cross-encoder reranking -> corrective retrieval (CRAG) -> cited, self-checked answer."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ...models import KnowledgeBase
from ...services import live_assistant, live_retrieval, rag_hybrid
from . import adaptive, answer as ans, crag, decompose as dec, filters, graph, rerank

logger = logging.getLogger(__name__)
ABSTAIN = ("I could not find a reliable answer in the approved knowledge base, so I will not guess. "
           "Try rephrasing with specific words from the topic, or ask an administrator to add guidance on it.")
GREETING = "Hello! I can explain how CareBridge AI works, show live needs and donors, and suggest next steps. Ask me anything about the platform."


def scope_entries(db: Session, viewer: dict) -> list[KnowledgeBase]:
    q = db.query(KnowledgeBase)
    if viewer.get("role") == "admin":
        return q.all()
    org = viewer.get("organization_id")
    if viewer.get("role") == "organization" and org:
        return q.filter((KnowledgeBase.organization_id.is_(None)) | (KnowledgeBase.organization_id == org)).all()
    return q.filter(KnowledgeBase.organization_id.is_(None)).all()


def _safe_embed(embed):
    def f(text: str):
        if embed is None:
            return None
        try:
            return embed(text)
        except Exception:
            return None
    return f


def live_evidence(db: Session, viewer: dict, question: str) -> list[dict]:
    """Rows from the live database as evidence (role scoped). Numbers here are computed in Python, so they are trusted."""
    if viewer.get("role") == "volunteer":
        return []
    intents = live_assistant.classify(question)
    entities = live_retrieval.detect_entities(db, viewer, question)
    items: list[dict] = []
    if intents or live_retrieval.has_entities(entities):
        analysis = live_assistant.build_analysis(db, viewer, intents or ["health", "selection"], focus=entities)
        if live_assistant.has_content(analysis):
            items.append({"kind": "live", "title": "Live analysis", "source": "database (computed now)", "text": live_assistant.compose_answer(analysis, intents or ["health", "selection"]), "confidence": 1.0})
    for r in live_retrieval.retrieve_records(db, viewer, question, k=3, min_score=0.3):
        items.append({"kind": "live", "title": r["title"], "source": r["source"], "text": r["content"], "confidence": r["score"]})
    related = graph.related_entities(db, viewer, question, top_n=5) if live_retrieval.has_entities(entities) else []
    if related:
        items.append({"kind": "live", "title": "Related entities (graph)", "source": "database graph (personalised PageRank)",
                      "text": "Related by the graph: " + "; ".join(f"{r['type']} {r['label']}" for r in related) + ".", "confidence": 0.6})
    return items


def answer_question(db: Session, question: str, viewer: dict | None = None, *, llm=None, embed=None, cross_encoder="auto", use_graph: bool = True,
                    decompose_llm=None, top_k: int = 3, with_live: bool = True) -> dict:
    viewer = viewer or {"role": "admin", "id": 0}
    question = (question or "").strip()
    live_intents = live_assistant.classify(question) if viewer.get("role") != "volunteer" else []
    route = adaptive.classify(question, live_intents, live_retrieval.has_entities(live_retrieval.detect_entities(db, viewer, question)) if question else False)
    base = {"question": question, "route": route["route"], "routes": route["routes"], "complexity": route["complexity"], "route_scores": route["scores"]}
    if route["route"] == "chitchat":
        return {**base, "answer": GREETING, "answerable": True, "confidence": 1.0, "evidence": [], "citations": [], "subquestions": [], "mode": "no_retrieval",
                "validation": {"ok": True, "unsupported": [], "invalid_citations": [], "numbers": {"ok": True, "ungrounded": []}}}

    entries = scope_entries(db, viewer)
    kg = graph.knowledge_graph(entries) if use_graph and entries else None
    vec = _safe_embed(embed)
    ce = rerank.get_cross_encoder() if cross_encoder == "auto" else cross_encoder
    org, only_global = viewer.get("organization_id"), viewer.get("role") not in ("admin", "organization")
    subs = dec.decompose(question, decompose_llm)

    evidence: list[dict] = []
    sub_report = []
    seen: set[tuple] = set()
    for sub in subs:
        mf = filters.infer(sub["text"], org, only_global)

        def retrieve(q: str, f, ids=None, _entries=entries):
            pool = filters.apply(_entries, f)
            if ids is not None:
                pool = [e for e in pool if e.id in ids]
            extra = [(0.8, kg.rank(q))] if kg is not None else None
            return rag_hybrid.search(pool, q, vec(q), top_k + 2, extra_rankers=extra, cross_encoder=ce)

        out = crag.corrective_retrieve(retrieve, sub["text"], mf)
        sub_report.append({"text": sub["text"], "grade": out["grade"], "actions": out["actions"],
                           "top_confidence": out["results"][0]["confidence"] if out["results"] else 0.0})
        if out["grade"] == "incorrect":
            continue
        for r in out["results"][:top_k]:
            key = (r["id"], r["content"])
            if key in seen or r["confidence"] < rag_hybrid.threshold():
                continue
            seen.add(key)
            via = kg.concepts_linking(r["id"], sub["text"]) if kg is not None else []
            evidence.append({"kind": "knowledge", "title": r["title"], "source": r["source"], "text": r["content"], "confidence": r["confidence"],
                             "entry_id": r["id"], "sub_question": sub["text"], "via": via, "signals": r["signals"]})
    live = live_evidence(db, viewer, question) if with_live and route["route"] in ("live_data", "anomaly") or (with_live and "live_data" in route["routes"]) else []
    evidence.extend(live)
    for i, ev in enumerate(evidence, start=1):
        ev["n"] = i

    if not evidence:
        return {**base, "answer": ABSTAIN, "answerable": False, "confidence": max([s["top_confidence"] for s in sub_report] or [0.0]), "evidence": [], "citations": [],
                "subquestions": sub_report, "mode": "abstained", "validation": {"ok": True, "unsupported": [], "invalid_citations": [], "numbers": {"ok": True, "ungrounded": []}}}

    if llm is not None:
        composed = ans.llm_answer(question, evidence, llm)
    else:
        composed = ans.extractive_answer(question, evidence)
        composed["mode"] = "extractive"
    if len(subs) > 1 and composed["mode"] == "extractive":
        # one short block per sub-question keeps multi-part answers readable
        parts = []
        for i, sub in enumerate(subs, start=1):
            sub_ev = [e for e in evidence if e.get("sub_question") == sub["text"]] or evidence
            piece = ans.extractive_answer(sub["text"], sub_ev, max_sentences=2)
            if piece["text"]:
                parts.append(f"{i}) {piece['text']}")
        if parts:
            composed["text"] = "\n".join(parts)
    # live evidence is computed in Python from the database, so its sentences are quoted directly (and cited)
    live_lines = []
    for ev in evidence:
        if ev["kind"] == "live" and ev["title"] in ("Live analysis", "Related entities (graph)"):
            live_lines.append(" ".join(ans.cite_sentence(s, ev["n"]) for s in ans.split_sentences(ev["text"])))
    if live_lines and composed["mode"] != "llm_verified":
        composed["text"] = (" ".join(live_lines) + " " + composed["text"]).strip()
    check = ans.verify(composed["text"], evidence)
    nums = ans.numbers_grounded(composed["text"], [e["text"] for e in evidence])
    conf = round(sum(e["confidence"] for e in evidence[:3]) / min(3, len(evidence)), 3)
    if not check["ok"]:
        conf = round(conf * 0.7, 3)
    cited = sorted({int(c) for c in ans.CITE.findall(composed["text"])})
    return {**base, "answer": composed["text"], "answerable": True, "confidence": conf, "mode": composed["mode"], "evidence": evidence,
            "citations": [{"n": e["n"], "title": e["title"], "source": e["source"], "kind": e["kind"]} for e in evidence if e["n"] in cited],
            "subquestions": sub_report, "validation": {"ok": check["ok"], "unsupported": check["unsupported"], "invalid_citations": check["invalid_citations"], "numbers": nums},
            "reranker": "cross-encoder" if ce else "feature reranker", "graph": bool(kg)}
