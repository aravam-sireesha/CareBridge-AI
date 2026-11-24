"""Measure retrieval accuracy of the knowledge base on the labelled questions.

    python scripts/eval_rag.py                # lexical rankers only (no model download needed)
    python scripts/eval_rag.py --dense        # also use sentence-transformers vectors (all-MiniLM-L6-v2)
    python scripts/eval_rag.py --show-misses

Reports recall@1, recall@3, MRR, and how many out-of-scope questions are correctly refused (confidence below
the threshold). Re-run after editing the knowledge base or the retrieval code."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge.default_kb import ENTRIES, with_keywords  # noqa: E402
from app.models import KnowledgeBase  # noqa: E402
from app.services import rag_hybrid  # noqa: E402


def build(dense: bool):
    rows = [KnowledgeBase(id=i + 1, title=t, source=s, content=with_keywords(t, c), embedding=None) for i, (t, s, c) in enumerate(ENTRIES)]
    embed = None
    if dense:
        from app.services.embeddings import embed_text
        embed = embed_text
        for r in rows:
            r.embedding = embed(f"{r.title}. {r.content}")
    return rows, embed


def evaluate(dense: bool = False, show_misses: bool = False, dataset: str = "eval_questions.json") -> dict:
    data = json.loads((Path(__file__).resolve().parents[1] / "app" / "knowledge" / dataset).read_text())
    rows, embed = build(dense)
    r1 = r3 = 0
    rr = 0.0
    misses = []
    calib = {"high": [0, 0], "medium": [0, 0], "abstained": [0, 0]}   # label -> [correct, total]
    for item in data["in_scope"]:
        vec = embed(item["q"]) if embed else None
        res = rag_hybrid.search(rows, item["q"], vec, top_k=3)
        titles = [r["title"] for r in res]
        bucket = res[0]["label"] if res and res[0]["answerable"] else "abstained"
        calib[bucket if bucket in calib else "medium"][1] += 1
        if titles[:1] == [item["expected"]]:
            r1 += 1
            calib[bucket if bucket in calib else "medium"][0] += 1
        if item["expected"] in titles:
            r3 += 1
            rr += 1.0 / (titles.index(item["expected"]) + 1)
        else:
            misses.append((item["q"], item["expected"], titles[:1]))
    refused = 0
    leaks = []
    for q in data["out_of_scope"]:
        res = rag_hybrid.search(rows, q, embed(q) if embed else None, top_k=1)
        if not res or not res[0]["answerable"]:
            refused += 1
        else:
            leaks.append((q, res[0]["title"], res[0]["confidence"]))
    n, m = len(data["in_scope"]), len(data["out_of_scope"])
    out = {"calibration": {k: {"correct": v[0], "total": v[1], "accuracy": round(v[0] / v[1], 3) if v[1] else None} for k, v in calib.items()}, "questions": n, "recall_at_1": round(r1 / n, 3), "recall_at_3": round(r3 / n, 3), "mrr": round(rr / n, 3),
           "out_of_scope": m, "correctly_refused": refused, "refusal_rate": round(refused / m, 3), "threshold": rag_hybrid.CONFIDENCE_THRESHOLD,
           "dense": dense}
    if show_misses:
        out["misses"] = misses
        out["leaks"] = leaks
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dense", action="store_true")
    ap.add_argument("--show-misses", action="store_true")
    ap.add_argument("--heldout", action="store_true", help="the first held-out set (written before tuning, but see README caveat)")
    ap.add_argument("--fresh", action="store_true", help="the fresh set written after tuning and run once")
    a = ap.parse_args()
    print(json.dumps(evaluate(a.dense, a.show_misses, "eval_fresh.json" if a.fresh else "eval_heldout.json" if a.heldout else "eval_questions.json"), indent=2, default=str))
