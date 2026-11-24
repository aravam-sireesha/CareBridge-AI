"""Decide what kind of message this is BEFORE any retrieval, so "hi" is greeted instead of being searched for in the knowledge base.

smalltalk  greetings, thanks, goodbyes, "who are you"        -> answered directly, no search, no model needed
general    anything not about the CareBridge platform         -> answered by the language model directly; no knowledge-base match is required
carebridge questions about needs, donors, donations, ...      -> live records + approved knowledge, then written from that evidence
Pure functions, no database: easy to test."""
from __future__ import annotations

import re

_GREETING = re.compile(r"^\s*(hi|hii+|hello+|hey+|hiya|howdy|yo|greetings|namaste|good\s+(morning|afternoon|evening|day))\b[\s!.,?]*(there|team|everyone|carebridge|assistant|bot)?[\s!.,?]*$", re.I)
_THANKS = re.compile(r"^\s*(ok(ay)?[\s,]*)?(thanks|thank\s*you|thx|ty|cheers|great|awesome|perfect|cool|got\s*it|nice)\b[\s!.,]*(so much|a lot|very much)?[\s!.,]*$", re.I)
_BYE = re.compile(r"^\s*(bye|goodbye|see\s*you|good\s*night|cya|take\s*care)\b[\s!.,]*$", re.I)
_HOW_ARE_YOU = re.compile(r"^\s*(hi|hello|hey)?[\s,]*(how\s+are\s+(you|u)|how'?s\s+it\s+going|what'?s\s+up|sup)\b[\s?!.]*$", re.I)
_WHO = re.compile(r"^\s*(who\s+are\s+you|what\s+are\s+you|what\s+can\s+you\s+do|what\s+do\s+you\s+do|help|help\s+me|what\s+is\s+your\s+name)\b[\s?!.]*$", re.I)

# Words that make a message about CareBridge's own data. The bare word "need" is deliberately absent ("I need help with Python").
_PLATFORM = re.compile(
    r"\b(carebridge|care\s*bridge|donations?|donors?|volunteers?|organi[sz]ations?|orphan\w*|children'?s?\s+home|verification|verified|unverified|"
    r"needs|open\s+need|urgent\s+need|unfulfilled|unmet|shortages?|fraud\s+flags?|anomal\w+|review\s+queue|delivery|deliveries|delivered|"
    r"need\s+alerts?|knowledge\s+base|matching\s+review|donor\s+suggestions?|our\s+needs|my\s+needs|ai\s+lab)\b", re.I)


def classify(question: str, previous_route: str | None = None) -> str:
    """Return 'smalltalk', 'general' or 'carebridge'."""
    q = (question or "").strip()
    if not q:
        return "smalltalk"
    if len(q) <= 60 and (_GREETING.match(q) or _THANKS.match(q) or _BYE.match(q) or _HOW_ARE_YOU.match(q) or _WHO.match(q)):
        return "smalltalk"
    if _PLATFORM.search(q):
        return "carebridge"
    # a short follow-up ("and the second one?", "why?") continues the topic of the previous answer
    if previous_route == "carebridge" and len(q.split()) <= 7:
        return "carebridge"
    return "general"


def smalltalk_kind(question: str) -> str:
    q = (question or "").strip()
    if _THANKS.match(q):
        return "thanks"
    if _BYE.match(q):
        return "bye"
    if _HOW_ARE_YOU.match(q):
        return "how_are_you"
    if _WHO.match(q):
        return "who"
    return "greeting"


_EXAMPLES = {
    "admin": "which needs are most urgent, which organizations are awaiting verification, or how donations are progressing",
    "organization": "your open needs, incoming donations, or how to improve your organization",
    "donor": "which needs you could support, or how your donations are tracked",
    "volunteer": "how volunteering works on CareBridge",
}


def smalltalk_reply(question: str, role: str, llm_ready: bool) -> str:
    kind = smalltalk_kind(question)
    ex = _EXAMPLES.get(role, _EXAMPLES["volunteer"])
    if kind == "thanks":
        return "You're welcome! Anything else I can help with?"
    if kind == "bye":
        return "Goodbye! I'm here whenever you need me."
    if kind == "how_are_you":
        return "I'm doing well, thank you. How can I help you today?"
    if kind == "who":
        general = "answer general questions, " if llm_ready else ""
        tail = "" if llm_ready else " General-knowledge answers need a language model to be connected by an administrator."
        return (f"I'm CareBridge AI, the assistant for the CareBridge platform. I can {general}look up the live data your role can access, and explain how CareBridge works. "
                f"For example, ask about {ex}. For multi-step tasks, use the AI agent.{tail}")
    return f"Hi! I'm CareBridge AI. Ask me anything, or try questions about {ex}. What would you like to know?"


_VERIFICATION = re.compile(r"\b(verif\w*|awaiting\s+approval|pending\s+organi[sz]ations?)\b", re.I)
_DONATIONS = re.compile(r"\b(donations?|deliver\w*|receipts?|pledges?)\b", re.I)
_ATTENTION = re.compile(r"\b(attention|unfulfilled|unmet|overdue|stale|remain(ed|ing)?\s+(open|unfulfilled)|waiting|neglected|stuck|longest)\b", re.I)


def facts_wanted(question: str) -> list[str]:
    """Which live-data fact sets a question asks for: verification, donations, attention (needs that have waited)."""
    q = question or ""
    out = []
    if _VERIFICATION.search(q):
        out.append("verification")
    if _DONATIONS.search(q):
        out.append("donations")
    if _ATTENTION.search(q) and re.search(r"\b(needs?|requests?|donations?)\b", q, re.I):
        out.append("attention")
    return out
