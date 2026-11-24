"""Corrective RAG (CRAG): grade what was retrieved and correct it before answering.

    correct    the best passage is confident            -> use it
    ambiguous  weak or contested match                  -> drop the metadata filter, rewrite the query (synonyms +
                                                           pseudo-relevance feedback terms) and retrieve again
    incorrect  still nothing reliable after correction  -> say so, and hand over to live data or abstain
"""
from __future__ import annotations

from collections import Counter

from ...services import rag_hybrid
from ...services.rag_hybrid import tokens


def grade(results: list[dict]) -> str:
    if not results:
        return "incorrect"
    top = results[0]["confidence"]
    t = rag_hybrid.threshold()
    if top >= t + 0.12:
        return "correct"
    return "ambiguous" if top >= t - 0.08 else "incorrect"


def rewrite(query: str, results: list[dict], max_new: int = 4) -> str:
    """Pseudo-relevance feedback: add the most characteristic words of the best passages that the query lacks."""
    have = set(tokens(query))
    counts: Counter = Counter()
    for r in results[:3]:
        for t in set(tokens(r["title"] + " " + r["content"])):
            if t not in have and len(t) > 3:
                counts[t] += 1
    extra = [t for t, c in counts.most_common(max_new * 3) if c >= 2][:max_new]
    synonyms = [s for t in have for s in rag_hybrid.SYNONYMS.get(t, [])][:4]
    return " ".join([query, *extra, *synonyms]).strip()


def corrective_retrieve(retrieve, query: str, metadata_filter=None, max_rounds: int = 2) -> dict:
    """`retrieve(query, metadata_filter, ids=None)` -> list[dict] from rag_hybrid. Returns results, the grade and the actions taken.

    A rewritten query is used only to FIND candidates. They are then re-scored against the original question, so rewriting can
    never make an unrelated answer look confident (an earlier version did, and off-topic refusals fell from 15/15 to 11/15)."""
    actions = []
    results = retrieve(query, metadata_filter)
    g = grade(results)
    actions.append({"step": "retrieve", "filter": metadata_filter.describe() if metadata_filter else None, "top_confidence": results[0]["confidence"] if results else 0.0, "grade": g})
    rounds = 0
    best = results
    while g != "correct" and rounds < max_rounds:
        rounds += 1
        if metadata_filter is not None and rounds == 1:
            metadata_filter = None
            cand = retrieve(query, None)
            actions.append({"step": "drop_filter", "top_confidence": cand[0]["confidence"] if cand else 0.0})
        else:
            q2 = rewrite(query, best)
            if q2 == query:
                break
            found = retrieve(q2, None)
            cand = retrieve(query, None, {r["id"] for r in found}) if found else []
            actions.append({"step": "rewrite", "query": q2, "top_confidence": cand[0]["confidence"] if cand else 0.0})
        if cand and (not best or cand[0]["confidence"] > best[0]["confidence"]):
            best = cand
        g = grade(best)
    return {"results": best, "grade": g, "actions": actions}
