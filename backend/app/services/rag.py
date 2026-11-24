import json
import os
from math import sqrt
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from ..models import KnowledgeBase
from . import rag_hybrid
from .embeddings import embed_text


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    denominator = sqrt(sum(value * value for value in a) * sum(value * value for value in b))
    if denominator == 0:
        return 0.0
    return sum(left * right for left, right in zip(a, b)) / denominator


def retrieve(
    db: Session,
    query: str,
    top_k: int = 3,
    organization_id: int | None = None,
    global_only: bool = False,
) -> list[dict]:
    """Hybrid retrieval: BM25 + typo-tolerant n-grams + dense vectors, fused, reranked and given a confidence.

    Same signature and result keys as before (id, title, content, source, score); each result also carries
    `confidence`, `label`, `answerable`, `signals` and the whole entry in `full_content`."""
    return rag_hybrid.retrieve(db, query, top_k=top_k, organization_id=organization_id, global_only=global_only,
                               embed=embed_text)


def generate_grounded_answer(question: str, matches: list[dict], live_context: str | None = None) -> tuple[str, str]:
    if not matches and not live_context:
        return "I could not find a relevant entry in the approved knowledge base. Please check with your safeguarding or program lead.", "no_sources"

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key and live_context:
        return live_context.split("\nORG ")[0].split("\nNEED #")[0], "live_analysis"
    if not api_key:
        excerpts = "\n".join(
            f"{index}. {match['title'] or 'Resource'}: {match['content']}"
            for index, match in enumerate(matches, start=1)
        )
        return (
            "Here are the most relevant passages from your approved knowledge base. "
            "Use the source cards below to review the original guidance.\n\n" + excerpts,
            "retrieval_only",
        )

    endpoint = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    live_block = f"\n\nLIVE DATABASE FACTS (authoritative for every number, name and date):\n{live_context}" if live_context else ""
    context = "\n\n".join(
        f"SOURCE {index}: {match['title'] or 'Untitled'} ({match['source'] or 'Knowledge base'})\n{match['content']}"
        for index, match in enumerate(matches, start=1)
    )
    payload = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a careful child-welfare support assistant. Answer only using the supplied sources. "
                    "If they do not support an answer, say so. Do not make case decisions or invent policy. "
                    "Cite sources by their SOURCE number and remind the user that an administrator decides. "
                    "When LIVE DATABASE FACTS are supplied, use them for all figures, never estimate or invent numbers, "
                    "and give concrete, prioritized next steps."
                ),
            },
            {"role": "user", "content": f"Question: {question}\n\nApproved retrieved context:\n{context}{live_block}"},
        ],
    }
    request = Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = json.loads(response.read())
        answer = body["choices"][0]["message"]["content"].strip()
        if answer:
            return answer, "live_grounded_generation" if live_context else "grounded_generation"
    except Exception:
        pass

    if live_context:
        return live_context.split("\nORG ")[0].split("\nNEED #")[0], "live_analysis"
    excerpts = "\n".join(
        f"{index}. {match['title'] or 'Resource'}: {match['content']}"
        for index, match in enumerate(matches, start=1)
    )
    return "The answer service is temporarily unavailable. Here are the retrieved source passages instead:\n\n" + excerpts, "retrieval_fallback"