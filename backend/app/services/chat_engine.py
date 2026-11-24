"""The chat assistant's engine.

Three kinds of message (see chat_intent):
  smalltalk   answered directly
  general     answered by the language model alone; no knowledge-base match is needed
  carebridge  live records + role-scoped facts + approved knowledge, then written from that evidence
Retrieval for CareBridge questions is the same logic `/assistant/ask` uses, with follow-ups resolved from THIS conversation."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from ..ai.rag import answer as ans
from . import live_assistant, live_facts, live_retrieval, rag, rag_hybrid

logger = logging.getLogger(__name__)

MIN_KB_SCORE_WITH_LIVE = 0.3
HISTORY_MESSAGES = 6          # recent messages sent to the model: enough for follow-ups, small enough to stay fast
HISTORY_CHARS = 700
MAX_CONTEXT_CHARS = 9000

GENERAL_SYSTEM = (
    "You are CareBridge AI, a friendly and knowledgeable assistant. Answer the user's question directly and clearly, the way a good chatbot would: "
    "lead with the answer, keep it concise, and use lists, tables or code blocks only when they genuinely help. If you are not sure, say so. "
    "In this reply you have no access to CareBridge's private records, so never invent facts about its needs, donors, donations or organizations."
)
CAREBRIDGE_SYSTEM = (
    "You are CareBridge AI, the assistant for a child-welfare support platform. Reply the way a helpful chatbot would: lead with the direct answer, "
    "keep it short and plain, and do not narrate your process. Use only the numbered SOURCES and the LIVE DATABASE FACTS supplied for every fact about "
    "CareBridge; they are authoritative for each number, name and date, so never estimate or invent a figure. When the data shows zero records, say none "
    "were found in the data the user can access. When a fact is marked as unavailable to the user's role, say it is not available to them; never report it as zero. "
    "If the material does not answer the question, say so plainly. You may add a brief general explanation when it helps, but keep it clearly separate from CareBridge facts. "
    "Cite knowledge sources as [1], [2]. Never reveal personal details about children, donors or volunteers beyond what the supplied material shows. "
    "Recommend, but remind the user that an administrator decides."
)
NO_MODEL_GENERAL = ("I can't answer general questions yet because no language model is connected. An administrator can connect one in the server settings "
                    "(for example LLM_API_KEY). I can still answer questions about your CareBridge data, such as urgent needs, donations or organization verifications.")
LIMIT_REACHED = "The daily limit for language model requests has been reached, so I can't answer general questions right now. Please try again tomorrow, or ask an administrator to raise the limit."
NO_EVIDENCE = "I couldn't find anything about that in the knowledge base or in the data you can access. Try rephrasing, or ask an administrator to add guidance on it."
LOW_CONFIDENCE = ("I'm not confident the knowledge base answers this, so I won't guess. The closest passages are listed under Sources. "
                  "Try rephrasing with specific words from the topic.")
GENERIC_FOLLOW_UPS = {
    "admin": ["Which needs are most urgent right now?", "Summarize pending organization verifications.", "Find donation requests that require attention."],
    "organization": ["What is our current status?", "Which of our needs are most urgent?", "How do donor matches get confirmed?"],
    "donor": ["What should I support first?", "How are donations tracked?"],
    "volunteer": ["What is the volunteer background check policy?"],
}


LANGUAGES = {"en": "English", "te": "Telugu", "hi": "Hindi", "ta": "Tamil", "kn": "Kannada", "ml": "Malayalam", "mr": "Marathi", "bn": "Bengali", "gu": "Gujarati",
             "pa": "Punjabi", "ur": "Urdu", "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese", "ar": "Arabic", "zh": "Chinese", "ja": "Japanese"}


def language_name(code: str | None) -> str | None:
    """Only codes from the fixed list are accepted, so a language value can never carry instructions into the prompt."""
    return LANGUAGES.get((code or "").lower()) if (code or "").lower() != "en" else None


def _language_line(code: str | None) -> str:
    name = language_name(code)
    return f"\n\nWrite your reply in {name}. Keep names, numbers and [1]-style citation markers unchanged." if name else ""


def _trim(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def empty_context(question: str) -> dict[str, Any]:
    return {"question": question, "effective": question, "follow_up_of": None, "entities": {"organizations": [], "donors": [], "categories": []}, "analysis": None, "records": [],
            "results": [], "live_context": None, "has_live": False, "kb_answerable": False, "notice": None, "live_sources": [], "facts_available": True, "follow_ups": []}


def prepare(db: Session, user: dict, question: str, history: list[dict]) -> dict[str, Any]:
    """Gather the evidence for a CareBridge question. Never calls a language model."""
    role = user["role"]
    organization_id = user.get("organization_id")
    live_allowed = role != "volunteer"
    effective, follow_up_of = question, None
    empty = {"organizations": [], "donors": [], "categories": []}
    entities = live_retrieval.detect_entities(db, user, question) if live_allowed else empty
    intents = live_assistant.classify(question) if live_allowed else []
    previous = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
    # follow-up: a question that names nothing on its own is read together with the previous question of THIS conversation
    if previous and not intents and not live_retrieval.has_entities(entities) and len(question.split()) <= 12:
        follow_up_of, effective = _trim(previous, 200), f"{previous} {question}"
        if live_allowed:
            entities = live_retrieval.detect_entities(db, user, effective)
            intents = live_assistant.classify(effective)
    if live_retrieval.has_entities(entities) and not intents:
        intents = ["selection"] if (entities["donors"] and not entities["organizations"] and not entities["categories"]) else ["health", "selection"]
    if entities["donors"]:
        intents = sorted(set(intents) | {"selection"})

    analysis = live_assistant.build_analysis(db, user, intents, focus=entities) if intents else None
    has_analysis = bool(analysis and live_assistant.has_content(analysis))
    records = live_retrieval.retrieve_records(db, user, effective) if live_allowed else []
    if not has_analysis:
        records = [r for r in records if r["score"] >= 0.3]
    facts = live_facts.build(db, user, effective)
    has_live = has_analysis or bool(records) or bool(facts)

    notice, results = None, []
    try:
        results = rag.retrieve(db, effective, top_k=3, organization_id=organization_id,
                               global_only=role != "admin" and (role != "organization" or organization_id is None))
    except Exception:
        logger.exception("Chat retrieval failed")
        notice = "Policy search is unavailable right now." + (" This answer uses live database data only." if has_live else "")
    if has_live:
        results = [r for r in results if r["score"] >= MIN_KB_SCORE_WITH_LIVE]

    parts = []
    if has_analysis:
        parts.append(live_assistant.live_context_text(analysis))
    if facts:
        parts.append(facts["text"])
    if records:
        parts.append("LIVE RECORDS: " + " | ".join(r["content"] for r in records[:4]) if has_analysis or facts else live_assistant.compose_records_answer(records))
    live_context = "\n\n".join(parts) or None
    kb_answerable = bool(results and results[0].get("answerable", True))
    return {
        "question": question, "effective": effective, "follow_up_of": follow_up_of, "entities": entities, "analysis": analysis if has_analysis else None,
        "records": records, "results": results, "live_context": live_context, "has_live": has_live, "kb_answerable": kb_answerable, "notice": notice,
        "live_sources": (analysis["sources"] if has_analysis else []) + (facts["sources"] if facts else []), "facts_available": (facts["available"] if facts else True),
        "follow_ups": live_assistant.follow_ups(analysis) if has_analysis else GENERIC_FOLLOW_UPS.get(role, [])[:3],
    }


def sources_payload(ctx: dict) -> dict:
    """What the interface may show as evidence. Passages are shortened; the full entry stays on the server."""
    kb = [{"id": r.get("id"), "title": r.get("title"), "source": r.get("source"), "content": _trim(r.get("content", ""), 420), "score": r.get("score"),
           "label": r.get("label"), "answerable": r.get("answerable", True)} for r in ctx["results"]]
    live = [{**s, "live": True} for s in ctx["live_sources"]]
    recs = [{"title": r.get("title"), "content": _trim(r.get("content", ""), 300), "score": r.get("score"), "live": True, "kind": r.get("kind"), "source": r.get("source")}
            for r in ctx["records"]]
    return {"knowledge": kb, "live": live, "records": recs, "focus": live_retrieval.focus_names(ctx["entities"]), "follow_up_of": ctx["follow_up_of"]}


def has_evidence(ctx: dict) -> bool:
    return bool(ctx["live_context"] or ctx["results"])


def _history_messages(history: list[dict]) -> list[dict]:
    return [{"role": m["role"], "content": _trim(m["content"], HISTORY_CHARS)} for m in history[-HISTORY_MESSAGES:]]


def build_general_messages(question: str, history: list[dict], language: str | None = None) -> list[dict]:
    return [{"role": "system", "content": GENERAL_SYSTEM + _language_line(language)}, *_history_messages(history), {"role": "user", "content": question}]


def build_messages(ctx: dict, history: list[dict], language: str | None = None) -> list[dict]:
    """System prompt + a few recent turns + the question with its evidence. Context is capped so prompts stay small and fast."""
    parts = []
    for i, r in enumerate(ctx["results"], start=1):
        parts.append(f"SOURCE {i}: {r.get('title') or 'Untitled'} ({r.get('source') or 'Knowledge base'})\n{r.get('content', '')}")
    block = "\n\n".join(parts) or "(no knowledge-base passages matched)"
    if ctx["live_context"]:
        block += f"\n\nLIVE DATABASE FACTS (authoritative):\n{ctx['live_context']}"
    block = block[:MAX_CONTEXT_CHARS]
    return [{"role": "system", "content": CAREBRIDGE_SYSTEM + _language_line(language)}, *_history_messages(history), {"role": "user", "content": f"Question: {ctx['question']}\n\nApproved material:\n{block}"}]


def fallback_answer(ctx: dict) -> tuple[str, str]:
    """Deterministic answer for CareBridge questions when no language model is configured or it failed. Makes no network call."""
    if ctx["live_context"]:
        text = ctx["live_context"].split("\nORG ")[0].split("\nNEED #")[0]
        return text, "live_analysis"
    if ctx["results"] and not ctx["kb_answerable"]:
        return LOW_CONFIDENCE, "low_confidence"
    if ctx["results"]:
        body = "\n\n".join(f"**{r.get('title') or 'Resource'}**: {_trim(r.get('content', ''), 700)}" for r in ctx["results"][:3])
        return "Here is what the approved knowledge base says:\n\n" + body, "retrieval_only"
    return NO_EVIDENCE, "no_sources"


def grounding_check(text: str, ctx: dict) -> dict:
    """Numbers in the answer that appear in none of the supplied material. Streamed text cannot be recalled, so the result is a
    warning shown with the finished answer, not a silent edit."""
    evidence = [r.get("content", "") for r in ctx["results"]] + [ctx["live_context"] or ""] + [r.get("content", "") for r in ctx["records"]]
    result = ans.numbers_grounded(text, evidence, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    return {"numbers_ok": result["ok"], "ungrounded_numbers": result["ungrounded"][:6]}


def confidence_payload(ctx: dict) -> dict | None:
    if not ctx["results"]:
        return None
    top = ctx["results"][0]
    return {"value": top.get("confidence", top.get("score")), "label": top.get("label"), "answerable": ctx["kb_answerable"], "threshold": rag_hybrid.threshold(),
            "note": "Retrieval match strength, not a probability."}
