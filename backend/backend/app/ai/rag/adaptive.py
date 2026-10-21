"""Adaptive RAG: route each question to the cheapest tool that can answer it well.

    chitchat    no retrieval
    knowledge   hybrid retrieval over the knowledge base
    live_data   the live database (role scoped)
    prediction  ML models / forecasts
    optimization constraint solvers (allocation, matching, routing)
    calculation exact arithmetic and aggregates in Python (never by the language model)
    anomaly     unusual donations, needs, hours, sign-ins

Rule scores are transparent and tested. An LLM router can replace them, but its output is validated against the same labels."""
from __future__ import annotations

import re

ROUTES = ("chitchat", "knowledge", "live_data", "prediction", "optimization", "calculation", "anomaly")
PATTERNS = {
    "chitchat": [(r"^\s*(hi|hello|hey|thanks|thank you|good (morning|afternoon|evening)|who are you|what can you do)\b", 3.0)],
    "prediction": [(r"\b(forecast|predict\w*|projected?|expected|likely|probability|chance|risk|shortage|run short|next (week|month|quarter)|will (it|this|we|the))\b", 1.6),
                   (r"\b(fulfil\w*|funded)\b.*\b(within|by|in)\b", 1.0)],
    "optimization": [(r"\b(match|pair|assign)\w*\s+(the\s+|all\s+)?(donors?|volunteers?|sponsors?)\b", 2.0),
                     (r"\b(optimi[sz]\w*|allocate|allocation plan|distribute|assign\w*|best (way|plan|assignment)|fair(ly|ness)?|constraint\w*|route|routing|deliver\w* plan|schedule)\b", 1.7),
                     (r"\b(maximi[sz]e|minimi[sz]e|limited (stock|budget|supply))\b", 1.5)],
    "calculation": [(r"\b(calculate|compute|sum|total|average|median|percent\w*|how (much|many) (needs?|donors?|volunteers?|children|donations?|organi[sz]ations?|resources?|units?)|ratio|per (child|need|donor)|\d+\s*[%x*/+\-]\s*\d+)\b", 1.5)],
    "anomaly": [(r"\b(anomal\w+|outlier\w*|unusual|suspicious|fraud\w*|strange|odd|irregular)\b", 1.8)],
    "live_data": [(r"\b(urgent|priority|right now|currently|today|latest|status|open needs|donors? (have|who)|stopped giving|compare (all )?organi[sz]ations|health score|which (donors?|needs?|volunteers?))\b", 1.4)],
    "knowledge": [(r"\b(how (do|does|can|to)|what (is|are|does)|why|where|policy|rule|steps?|guide|explain|meaning|mean|define|difference)\b", 1.0)],
}


def classify(question: str, live_intents: list[str] | None = None, entities: bool = False) -> dict:
    q = (question or "").lower()
    scores = {r: 0.0 for r in ROUTES}
    for route, pats in PATTERNS.items():
        for pat, w in pats:
            if re.search(pat, q):
                scores[route] += w
    if live_intents:
        scores["live_data"] += 1.5
    if entities:
        scores["live_data"] += 1.0
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top, second = ranked[0], ranked[1]
    if top[1] == 0:
        top = ("knowledge", 0.5)
    # a strongly-signalled top route only gets a second route when that one is also strongly signalled
    need = 1.4 if top[1] < 2.0 else 1.8
    routes = [top[0]] + ([second[0]] if second[1] >= need and second[0] != top[0] and top[0] != "chitchat" else [])
    complexity = "multi" if len(routes) > 1 or len(re.findall(r"\?", q)) > 1 or re.search(r"\b(and|then|also)\s+(what|how|why|who|which)\b", q) else "simple"
    return {"route": routes[0], "routes": routes, "complexity": complexity, "scores": {k: round(v, 2) for k, v in scores.items() if v}}
