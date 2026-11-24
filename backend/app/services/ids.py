"""Strict, friendly parsing of numeric identifiers taken from URLs."""
from __future__ import annotations

from fastapi import HTTPException


def parse_id(value: str, label: str) -> int:
    """'12' -> 12. Anything else is rejected with a message that says what was wrong, instead of an obscure validation error.
    Identifiers are never silently converted: '12abc', '-3', '1.5', a UUID or a sentence are all refused."""
    text = (value or "").strip()
    if not text.isdigit() or len(text) > 9 or int(text) < 1:
        raise HTTPException(status_code=422, detail=f"{label} must be a whole number such as 12 (received '{text[:40]}').")
    return int(text)
