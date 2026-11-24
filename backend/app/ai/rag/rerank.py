"""Cross-encoder reranking. Loads sentence-transformers' CrossEncoder lazily; returns None when it is not installed
(the feature reranker inside rag_hybrid then does the job). Set RAG_CROSS_ENCODER=off to disable, or to another model name."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)
DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_cached: dict[str, object] = {}


def get_cross_encoder():
    """Return callable(query, passages) -> list[float] logits, or None."""
    name = os.getenv("RAG_CROSS_ENCODER", DEFAULT_MODEL)
    if name.lower() in ("off", "false", "0", ""):
        return None
    if name in _cached:
        return _cached[name]
    try:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder(name)

        def score(query: str, passages: list[str]) -> list[float]:
            return [float(x) for x in model.predict([(query, p) for p in passages])]

        _cached[name] = score
    except Exception as exc:  # not installed, or no model files offline
        logger.info("Cross-encoder unavailable (%s); using the feature reranker", type(exc).__name__)
        _cached[name] = None
    return _cached[name]
