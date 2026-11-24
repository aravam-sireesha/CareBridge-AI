"""Query decomposition: split a multi-part question into sub-questions that are retrieved separately."""
from __future__ import annotations

import re

WH = r"(?:what|how|why|who|which|when|where|can|could|does|do|is|are|should|will)"
REFERENCE = re.compile(r"^(?:and|also|then|what about|how about)\b|^\b(?:it|that|they|them|those|this)\b", re.I)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" ,;.")


def _split(q: str) -> list[str]:
    parts = re.split(r"(?<=[?])\s+|;\s+|\.\s+(?=[A-Z])", q.strip())
    out: list[str] = []
    for p in parts:
        pieces = re.split(rf"(?i),?\s+(?:and|then|also|and also|as well as)\s+(?={WH}\b)", p)
        out.extend(pieces)
    return [_clean(x) for x in out if _clean(x)]


def _compare(q: str) -> list[str] | None:
    m = re.match(r"(?i)^\s*(?:compare|difference between|what(?:'s| is) the difference between)\s+(.+?)\s+(?:and|vs\.?|versus|with)\s+(.+?)\??\s*$", q)
    if not m:
        return None
    a, b = _clean(m.group(1)), _clean(m.group(2))
    return [f"What is {a}?", f"What is {b}?"]


def decompose(question: str, llm=None, max_parts: int = 4) -> list[dict]:
    """Returns [{"text", "depends_on"}]. `llm` (optional) is a callable(question) -> list[str]; invalid output falls back to rules."""
    q = _clean(question)
    if not q:
        return []
    parts: list[str] | None = None
    from_llm = False
    if llm is not None:
        try:
            cand = llm(q)
            if isinstance(cand, list) and 1 <= len(cand) <= max_parts and all(isinstance(c, str) and 3 <= len(c.strip()) <= 240 for c in cand):
                parts, from_llm = [_clean(c) for c in cand], True
        except Exception:
            parts = None
    if parts is None:
        parts = _compare(q) or _split(q)
    parts = parts[:max_parts] or [q]
    out: list[dict] = []
    for i, p in enumerate(parts):
        dep = None
        if i > 0 and not from_llm and (REFERENCE.search(p) or len(p.split()) <= 2):
            dep = i - 1
            prev = re.sub(rf"(?i)^{WH}\s+(?:is|are|do|does|can|should|will|to|i|we)?\s*", "", out[i - 1]["text"]).rstrip("?")
            p = f"{p.rstrip('?')} (about: {prev})?"
        out.append({"text": p if p.endswith("?") or i == 0 and not p.endswith(".") else p, "depends_on": dep})
    return out
