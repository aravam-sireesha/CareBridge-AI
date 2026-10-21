"""Metadata filtering: narrow the candidate entries before ranking (topic, source, organization scope)."""
from __future__ import annotations

import re
from dataclasses import dataclass

TOPIC_BY_SOURCE = {"CareBridge guide": "platform", "Security guide": "security", "Safeguarding guidance (template)": "safeguarding"}
TOPIC_HINTS = {
    "security": r"\b(password|2fa|two[- ]step|authenticator|lock(?:ed|out)?|sign[- ]?in|log ?in|session|audit|recovery code|reset code|rate limit)\b",
    "safeguarding": r"\b(safeguard\w*|abuse|child protection|consent|photos?|background check|screening|report a concern|harm\w*|retention)\b",
}


def entry_topic(entry) -> str:
    if getattr(entry, "organization_id", None):
        return "organization"
    return TOPIC_BY_SOURCE.get(getattr(entry, "source", "") or "", "general")


@dataclass
class MetadataFilter:
    topics: set[str] | None = None            # keep only these topics
    organization_id: int | None = None        # include this organization's private entries (plus global ones)
    only_global: bool = False                 # exclude every organization-private entry
    source_contains: str | None = None
    title_contains: str | None = None

    def describe(self) -> str:
        parts = []
        if self.topics:
            parts.append("topic in " + "/".join(sorted(self.topics)))
        if self.source_contains:
            parts.append(f"source contains '{self.source_contains}'")
        if self.title_contains:
            parts.append(f"title contains '{self.title_contains}'")
        return ", ".join(parts) or "scope only"


def apply(entries: list, f: MetadataFilter | None) -> list:
    if f is None:
        return list(entries)
    out = []
    for e in entries:
        org = getattr(e, "organization_id", None)
        if org is not None and (f.only_global or org != f.organization_id):
            continue
        if f.topics and entry_topic(e) not in f.topics:
            continue
        if f.source_contains and f.source_contains.lower() not in (e.source or "").lower():
            continue
        if f.title_contains and f.title_contains.lower() not in (e.title or "").lower():
            continue
        out.append(e)
    return out


def infer(question: str, organization_id: int | None = None, only_global: bool = False) -> MetadataFilter | None:
    """Pick a topic filter when the question is clearly about one area. Returns None when it is not obvious."""
    q = (question or "").lower()
    hits = {topic for topic, pattern in TOPIC_HINTS.items() if re.search(pattern, q)}
    if len(hits) == 1:
        return MetadataFilter(topics=hits | {"organization"}, organization_id=organization_id, only_global=only_global)
    return None
