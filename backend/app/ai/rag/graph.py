"""GraphRAG (lightweight, no LLM needed).

Two graphs, both ranked with personalised PageRank seeded from the question:

* Knowledge graph  - nodes are knowledge-base entries and the concepts they talk about; concepts are linked by a small
  domain ontology (donor-donation-need ...). A question that names one concept reaches entries about *related* concepts
  (multi-hop), which keyword and vector search cannot do.
* Live graph       - organizations, needs, categories, donors, volunteers and resources from the database, so a question
  such as "who could help Hope Home?" is answered by walking organization -> needs -> category -> donors/volunteers.

Entity and relation extraction is rule-based. A production GraphRAG would add LLM extraction and community summaries."""
from __future__ import annotations

from collections import Counter, defaultdict

try:  # optional: without it retrieval simply runs without the graph ranker
    import networkx as nx
except Exception:  # pragma: no cover
    nx = None

from ...services import donor_ml
from ...services.matching_rules import _normalize, _tag_match_score
from ...services.rag_hybrid import expand, split_hidden, stem, tokens

ONTOLOGY = [
    ("donor", "donation"), ("donation", "need"), ("need", "organization"), ("volunteer", "skill"), ("volunteer", "need"),
    ("resource", "allocation"), ("allocation", "need"), ("admin", "verification"), ("verification", "organization"),
    ("fraud", "donation"), ("fraud", "anomaly"), ("anomaly", "flag"), ("password", "lockout"), ("authenticator", "recovery"),
    ("two", "authenticator"), ("child", "safeguarding"), ("child", "career"), ("audit", "admin"), ("forecast", "need"),
    ("assistant", "knowledge"), ("confidence", "assistant"), ("suggestion", "donor"), ("suggestion", "volunteer"),
    ("suggestion", "admin"), ("health", "organization"), ("delivery", "allocation"), ("receipt", "donation"),
    ("priority", "urgency"), ("urgency", "need"), ("queue", "admin"), ("session", "password"), ("consent", "child"),
]
STOPCONCEPTS = {"want", "page", "use", "need", "make", "show", "see", "get", "also", "one", "set", "add", "new", "find", "work"}


class KnowledgeGraph:
    def __init__(self, entries: list):
        g = nx.Graph()
        df: Counter = Counter()
        per_entry: dict[int, Counter] = {}
        for e in entries:
            shown, hidden = split_hidden(e.content)
            tf = Counter(tokens(shown) + tokens(e.title) * 3 + tokens(hidden))
            per_entry[e.id] = tf
            df.update(tf.keys())
        n = max(1, len(entries))
        for e in entries:
            node = ("e", e.id)
            g.add_node(node, title=e.title)
            scored = sorted(((c, tf * (1 + (n / df[c]) ** 0.5)) for c, tf in per_entry[e.id].items() if c not in STOPCONCEPTS and len(c) > 2), key=lambda x: -x[1])[:14]
            for c, w in scored:
                g.add_edge(node, ("c", c), weight=w)
        for a, b in ONTOLOGY:
            sa, sb = stem(a), stem(b)
            if ("c", sa) in g and ("c", sb) in g:
                g.add_edge(("c", sa), ("c", sb), weight=6.0)
        self.g, self.entries = g, {e.id: e for e in entries}

    def rank(self, query: str) -> dict[int, float]:
        seeds = {t: w for t, w in expand(tokens(query)).items() if ("c", t) in self.g}
        if not seeds:
            return {}
        pers = {("c", t): w for t, w in seeds.items()}
        ppr = nx.pagerank(self.g, alpha=0.7, personalization=pers, weight="weight", max_iter=100)
        scores = {n[1]: s for n, s in ppr.items() if n[0] == "e"}
        top = max(scores.values()) or 1.0
        return {i: s / top for i, s in scores.items()}

    def concepts_linking(self, entry_id: int, query: str) -> list[str]:
        """Concepts that connect the question to an entry (used to explain why a passage was retrieved)."""
        q = set(expand(tokens(query)))
        node = ("e", entry_id)
        if node not in self.g:
            return []
        direct = [n[1] for n in self.g.neighbors(node) if n[1] in q]
        via = {c[1] for n in self.g.neighbors(node) for c in self.g.neighbors(n) if c[0] == "c" and c[1] in q and n[1] not in q}
        return sorted(set(direct)) or sorted(via)[:3]


_cache: dict[tuple, KnowledgeGraph] = {}


def knowledge_graph(entries: list) -> KnowledgeGraph | None:
    if nx is None:
        return None
    key = tuple(sorted((e.id, hash(e.content), hash(e.title)) for e in entries))
    if key not in _cache:
        if len(_cache) > 8:
            _cache.clear()
        _cache[key] = KnowledgeGraph(entries)
    return _cache[key]


# --------------------------------------------------------------------------- live graph over the database
def related_entities(db, viewer: dict, query: str, top_n: int = 6) -> list[dict]:
    """Walk organization -> needs -> category -> donors / volunteers / resources for the entities named in the query."""
    if nx is None:
        return []
    from ...models import Resource
    from ...services.live_retrieval import detect_entities, visible

    scope = visible(db, viewer)
    ents = detect_entities(db, viewer, query)
    seeds: dict[tuple, float] = {}
    g = nx.Graph()
    cats: dict[str, str] = {}
    for n in scope["needs"]:
        c = _normalize(n.category)
        if not c:
            continue
        cats[c] = n.category
        g.add_edge(("need", n.id), ("cat", c), weight=2.0)
        if n.org_id:
            g.add_edge(("org", n.org_id), ("need", n.id), weight=2.0)
    for d in scope["donors"]:
        for c in cats:
            s = max((_tag_match_score(c, p) for p in donor_ml._split_prefs(d.preferences)), default=0.0)
            if s > 0:
                g.add_edge(("donor", d.id), ("cat", c), weight=3.0 * s)
    from ...models import Volunteer
    vols = db.query(Volunteer).all() if viewer["role"] == "admin" else []
    for v in vols:
        for c in cats:
            s = max((_tag_match_score(c, p) for p in donor_ml._split_prefs(v.skills)), default=0.0)
            if s > 0:
                g.add_edge(("vol", v.id), ("cat", c), weight=3.0 * s)
    if viewer["role"] == "admin":
        for r in db.query(Resource).filter(Resource.status == "available").all():
            for c in cats:
                s = max(_tag_match_score(c, r.category or ""), _tag_match_score(c, r.name or ""))
                if s > 0:
                    g.add_edge(("res", r.id), ("cat", c), weight=3.0 * s)
    for o in ents["organizations"]:
        seeds[("org", o.id)] = 1.0
    for n in scope["needs"]:
        if _normalize(n.category) in {_normalize(c) for c in ents["categories"]}:
            seeds[("cat", _normalize(n.category))] = 1.0
    for d in ents["donors"]:
        seeds[("donor", d.id)] = 1.0
    if not seeds or not g:
        return []
    seeds = {k: v for k, v in seeds.items() if k in g}
    if not seeds:
        return []
    ppr = nx.pagerank(g, alpha=0.8, personalization=seeds, weight="weight")
    labels = {("org", o.id): o.name for o in scope["orgs"]}
    labels.update({("need", n.id): f"{n.category} ({n.urgency})" for n in scope["needs"]})
    labels.update({("donor", d.id): d.name for d in scope["donors"]})
    labels.update({("vol", v.id): v.name for v in vols})
    labels.update({("res", r.id): r.name for r in db.query(Resource).all()} if viewer["role"] == "admin" else {})
    labels.update({("cat", c): f"category: {name}" for c, name in cats.items()})
    out = []
    for node, score in sorted(ppr.items(), key=lambda kv: -kv[1]):
        if node in seeds or node not in labels or node[0] == "cat":
            continue
        out.append({"type": node[0], "id": node[1], "label": labels[node], "score": round(score, 4)})
        if len(out) >= top_n:
            break
    return out
