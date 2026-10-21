"""High-accuracy hybrid retrieval for the knowledge base.

Pipeline (every stage is deterministic and explainable; nothing here calls an external service):

  1. Chunk      long entries are split into overlapping passages, so the *relevant paragraph* is retrieved,
                not a whole page.
  2. Expand     the question is normalised (stop-words, light stemming) and expanded with domain synonyms
                ("kid" -> child, "scam" -> fraud, "2fa" -> two-step verification ...).
  3. Retrieve   three independent rankers over the passages:
                  BM25 (word match, title boosted) | character n-gram TF-IDF (typo tolerant) | dense embeddings
                  (sentence-transformers vectors already stored per entry; used when available).
  4. Fuse       reciprocal-rank fusion of the rankers.
  5. Rerank     the best passages are re-scored on query-term coverage (idf weighted), exact phrase overlap,
                title overlap, term proximity, plus the fused and dense signals.
  6. Calibrate  the reranker score becomes a 0-1 confidence. Below CONFIDENCE_THRESHOLD the system abstains
                ("not found in the knowledge base") instead of guessing. The threshold is tuned on the labelled
                evaluation set in app/knowledge/eval_questions.json (scripts/eval_rag.py).
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter

from sklearn.feature_extraction.text import TfidfVectorizer
from sqlalchemy.orm import Session

from ..models import KnowledgeBase

CONFIDENCE_THRESHOLD = 0.33   # default; chosen so that every off-topic question in the evaluation sets is refused
HIGH_CONFIDENCE = 0.6
RRF_K = 60
CHUNK_WORDS = 90

STOP = set("""a an and are as at be been being but by can could did do does doing for from had has have how i if in into is it its
me my of on or our should so than that the their them then there these they this those to us was we were what when where which
while who whom why will with would you your about also any all not no yes just more most some such very per get got""".split())

# domain synonyms: stem of query word -> extra words that mean the same thing in this knowledge base
SYNONYMS = {
    "kid": ["child"], "minor": ["child"], "youngster": ["child"], "student": ["child"],
    "donat": ["donation", "donor"], "contribut": ["donation"], "gift": ["donation"], "sponsor": ["donor"], "charity": ["donation"],
    "fake": ["fraud", "suspicious"], "scam": ["fraud"], "cheat": ["fraud"], "fraudulent": ["fraud"], "suspect": ["suspicious", "fraud"],
    "login": ["sign", "in"], "signin": ["sign", "in"], "logon": ["sign", "in"], "locked": ["lockout"], "lock": ["lockout"],
    "2fa": ["two", "step", "verification", "authenticator"], "mfa": ["two", "step", "verification", "authenticator"],
    "otp": ["authenticator", "code"], "totp": ["authenticator", "code"], "authenticator": ["two", "step", "verification"],
    "ngo": ["organization"], "orphanage": ["organization"], "shelter": ["organization"], "charity-home": ["organization"],
    "administrator": ["admin"], "moderator": ["admin"],
    "recommend": ["suggest", "suggestion"], "suggest": ["recommend", "suggestion"], "match": ["suggest", "fit"],
    "forgot": ["reset", "password"], "forgotten": ["reset", "password"], "pwd": ["password"], "passcode": ["password"],
    "hungry": ["food", "meals"], "meal": ["food"], "nutrition": ["food"], "school": ["education"], "study": ["education"],
    "medic": ["medical", "healthcare"], "health": ["medical", "healthcare"], "doctor": ["medical"], "cloth": ["clothing"],
    "money": ["funds", "donation"], "cash": ["funds", "donation"], "fund": ["donation"],
    "delete": ["remove"], "erase": ["remove"], "privacy": ["confidential", "data", "protection"], "confidential": ["privacy"],
    "bias": ["fair", "fairness"], "unfair": ["fairness", "bias"], "explain": ["reason", "why"], "accuracy": ["confidence", "reliable"],
    "wrong": ["incorrect", "mistake"], "photo": ["image", "media", "consent"], "picture": ["photo", "media", "consent"],
    "report": ["concern", "safeguarding"], "abuse": ["safeguarding", "concern"], "safe": ["safeguarding"],
    "beginner": ["glossary", "simple"], "meaning": ["glossary", "definition"], "mean": ["glossary", "definition"],
    "audit": ["trail", "log"], "history": ["trail", "log"], "log": ["audit", "trail"],
    "dark": ["theme", "appearance"], "theme": ["appearance", "dark"],
}


def stem(word: str) -> str:
    w = word.lower()
    if len(w) <= 3 or w.isdigit():
        return w
    for suf, rep in (("ization", "ize"), ("ational", "ate"), ("ations", "ate"), ("ation", "ate"), ("ingly", ""), ("ings", ""), ("ing", ""),
                     ("edly", ""), ("ies", "y"), ("ied", "y"), ("ness", ""), ("ments", "ment"), ("ers", "er"), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) + len(rep) >= 3:
            w = w[: -len(suf)] + rep
            break
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeioulsz":
        w = w[:-1]
    return w


def tokens(text: str) -> list[str]:
    return [stem(t) for t in re.findall(r"[a-z0-9][a-z0-9\-']*", (text or "").lower().replace("two-step", "two step"))
            if t not in STOP and len(t) > 1]


def expand(query_tokens: list[str]) -> dict[str, float]:
    """Query term weights: original words 1.0, synonyms 0.5."""
    weights: dict[str, float] = {}
    for t in query_tokens:
        weights[t] = 1.0
    for t in query_tokens:
        for syn in SYNONYMS.get(t, []):
            s = stem(syn)
            weights.setdefault(s, 0.5)
    return weights


def chunk(content: str, words: int = CHUNK_WORDS) -> list[str]:
    content = (content or "").strip()
    if len(content.split()) <= words * 1.2:
        return [content] if content else []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", content) if s.strip()]
    chunks, cur, count = [], [], 0
    for s in sentences:
        n = len(s.split())
        if cur and count + n > words:
            chunks.append(" ".join(cur))
            cur, count = cur[-1:], len(cur[-1].split())  # one sentence of overlap keeps context across the cut
        cur.append(s)
        count += n
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def _rank(scores: list[float]) -> list[int]:
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    ranks = [0] * len(scores)
    for r, i in enumerate(order, start=1):
        ranks[i] = r
    return ranks


def _cos(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    den = math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
    return num / den if den else 0.0


ALSO_MARK = "\n\n[Also asked: "


def split_hidden(content: str) -> tuple[str, str]:
    """An entry may end with "[Also asked: ...]": everyday phrasings that help retrieval but are not shown."""
    if ALSO_MARK in (content or ""):
        shown, hidden = content.split(ALSO_MARK, 1)
        return shown.strip(), hidden.rstrip("] \n")
    return (content or "").strip(), ""


class Passage:
    __slots__ = ("entry", "text", "title", "toks", "tf", "length")

    def __init__(self, entry: KnowledgeBase, text: str, hidden: str = ""):
        self.entry, self.text, self.title = entry, text, entry.title or ""
        title_toks = tokens(self.title)
        self.toks = tokens(text)
        self.tf = Counter(self.toks + title_toks * 2 + tokens(hidden))   # title words count triple; hidden phrasings once
        self.length = sum(self.tf.values())


def _bm25(passages: list[Passage], weights: dict[str, float], k1: float = 1.5, b: float = 0.75) -> tuple[list[float], dict[str, float]]:
    n = len(passages)
    avg = sum(p.length for p in passages) / max(1, n)
    df = Counter()
    for p in passages:
        df.update(p.tf.keys())
    idf = {t: math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5)) for t in weights}
    scores = []
    for p in passages:
        s = 0.0
        for t, w in weights.items():
            f = p.tf.get(t, 0)
            if f:
                s += w * idf[t] * (f * (k1 + 1)) / (f + k1 * (1 - b + b * p.length / max(avg, 1)))
        scores.append(s)
    return scores, idf


def _proximity(p: Passage, terms: set[str]) -> float:
    pos = [i for i, t in enumerate(p.toks) if t in terms]
    if len(pos) < 2:
        return 0.0
    distinct = len({p.toks[i] for i in pos})
    if distinct < 2:
        return 0.0
    best = len(p.toks)
    seen: dict[str, int] = {}
    left = 0
    for right, i in enumerate(pos):
        seen[p.toks[i]] = seen.get(p.toks[i], 0) + 1
        while len(seen) == distinct:
            best = min(best, i - pos[left] + 1)
            t = p.toks[pos[left]]
            seen[t] -= 1
            if not seen[t]:
                del seen[t]
            left += 1
    return min(1.0, distinct / max(best, distinct))


def threshold() -> float:
    """Abstention threshold. Override with RAG_CONFIDENCE_THRESHOLD after running scripts/eval_rag.py --dense."""
    try:
        return float(os.getenv("RAG_CONFIDENCE_THRESHOLD", CONFIDENCE_THRESHOLD))
    except ValueError:
        return CONFIDENCE_THRESHOLD


def _label(conf: float) -> str:
    return "high" if conf >= HIGH_CONFIDENCE else "medium" if conf >= threshold() else "low"


def search(entries: list[KnowledgeBase], query: str, query_vector: list[float] | None = None, top_k: int = 3,
           extra_rankers: list[tuple[float, dict[int, float]]] | None = None, cross_encoder=None, ce_weight: float = 0.5) -> list[dict]:
    """Rank `entries` for `query`. Returns the best passage of the best `top_k` entries, each with a calibrated confidence."""
    q_toks = tokens(query)
    if not entries or not q_toks:
        return []
    passages = []
    for e in entries:
        shown, hidden = split_hidden(e.content)
        for c in chunk(shown):
            passages.append(Passage(e, c, hidden))
    if not passages:
        return []
    weights = expand(q_toks)

    bm25, idf = _bm25(passages, weights)
    try:
        docs = [f"{p.title}. {p.text} {split_hidden(p.entry.content)[1]}" for p in passages]
        mat = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True).fit_transform(docs + [query])
        char = [float(x) for x in (mat[:-1] @ mat[-1].T).toarray().ravel()]
    except ValueError:
        char = [0.0] * len(passages)
    dense = [max(0.0, _cos(query_vector, p.entry.embedding)) if query_vector and p.entry.embedding else 0.0 for p in passages]
    has_dense = any(d > 0 for d in dense)

    lists = [(1.0, _rank(bm25)), (0.7, _rank(char))] + ([(1.0, _rank(dense))] if has_dense else [])
    for weight, by_entry in extra_rankers or []:   # e.g. the knowledge-graph ranker: a score per entry id
        lists.append((weight, _rank([by_entry.get(p.entry.id, 0.0) for p in passages])))
    fused = [sum(w / (RRF_K + r[i]) for w, r in lists) for i in range(len(passages))]
    top = sorted(range(len(passages)), key=lambda i: -fused[i])[:15]
    fmax = max(fused[i] for i in top) or 1.0
    bm_ideal = sum(w * idf[t] * 2.5 for t, w in weights.items() if w >= 1.0) or 1.0   # score of a perfect passage

    base_terms = {t for t in q_toks}
    total_idf = sum(idf.get(t, 0.0) for t in base_terms) or 1.0
    bigrams = {(a, b) for a, b in zip(q_toks, q_toks[1:])}
    results = []
    for i in top:
        p = passages[i]
        have = set(p.tf)
        coverage = sum(idf.get(t, 0.0) for t in base_terms if t in have) / total_idf
        syn_hit = sum(w * idf.get(t, 0.0) for t, w in weights.items() if w < 1.0 and t in have) / total_idf
        coverage = min(1.0, coverage + 0.5 * syn_hit * (1 - coverage))
        pairs = set(zip(p.toks, p.toks[1:]))
        phrase = (len(bigrams & pairs) / len(bigrams)) if bigrams else 0.0
        title_toks = set(tokens(p.title))
        title = (len(base_terms & title_toks) / len(base_terms)) if base_terms else 0.0
        prox = _proximity(p, base_terms | {t for t, w in weights.items() if w < 1.0})
        bm = min(1.0, bm25[i] / bm_ideal)
        char_s = min(1.0, char[i] * 2.5)
        dense_s = min(1.0, max(0.0, (dense[i] - 0.2) / 0.5))
        # every term below is an ABSOLUTE measure (not "relative to the best passage"), so an off-topic question
        # cannot look confident just because something has to rank first
        if has_dense:
            score = 0.32 * coverage + 0.09 * phrase + 0.10 * title + 0.04 * prox + 0.12 * bm + 0.05 * char_s + 0.28 * dense_s
        else:
            score = 0.46 * coverage + 0.12 * phrase + 0.12 * title + 0.05 * prox + 0.15 * bm + 0.10 * char_s
        results.append((score, i, {"coverage": round(coverage, 3), "phrase": round(phrase, 3), "title": round(title, 3), "bm25": round(bm, 3),
                                   "char": round(char[i], 3), "dense": round(dense[i], 3)}))
    if cross_encoder is not None and results:
        # a cross-encoder reads the question and the passage together, which a bi-encoder or keyword score cannot
        try:
            raw = cross_encoder(query, [f"{passages[i].title}. {passages[i].text}" for _, i, _ in results])
            norm = [1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, float(x))))) for x in raw]
            results = [((1 - ce_weight) * sc + ce_weight * n, i, {**sig, "cross_encoder": round(n, 3)}) for (sc, i, sig), n in zip(results, norm)]
        except Exception:  # a failing reranker must never break retrieval
            pass
    results.sort(key=lambda r: -r[0])
    out, seen = [], set()
    for score, i, signals in results:
        e = passages[i].entry
        if e.id in seen:
            continue
        seen.add(e.id)
        conf = round(max(0.0, min(1.0, score)), 3)
        out.append({"id": e.id, "title": e.title, "content": passages[i].text, "full_content": split_hidden(e.content)[0], "source": e.source, "score": conf,
                    "confidence": conf, "label": _label(conf), "answerable": conf >= threshold(), "signals": signals})
        if len(out) >= top_k:
            break
    return out


def retrieve(db: Session, query: str, top_k: int = 3, organization_id: int | None = None, global_only: bool = False,
             embed=None) -> list[dict]:
    if top_k <= 0:
        return []
    q = db.query(KnowledgeBase)
    if global_only:
        q = q.filter(KnowledgeBase.organization_id.is_(None))
    elif organization_id is not None:
        q = q.filter((KnowledgeBase.organization_id.is_(None)) | (KnowledgeBase.organization_id == organization_id))
    vector = None
    if embed is not None:
        try:
            vector = embed(query)
        except Exception:  # embedding model unavailable: the lexical rankers still work
            vector = None
    return search(q.all(), query, vector, top_k)
