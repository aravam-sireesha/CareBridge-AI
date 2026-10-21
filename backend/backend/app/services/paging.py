"""Small pure helpers shared by the list endpoints (no database or web-framework imports)."""
from __future__ import annotations


def like_pattern(text: str | None, max_len: int = 100) -> str:
    """Turn user search text into a safe SQL LIKE pattern: % and _ typed by the user are matched literally.
    Use with ``column.ilike(pattern, escape="\\\\")``."""
    cleaned = (text or "").strip()[:max_len]
    escaped = cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def page_meta(page: int, page_size: int, total: int) -> dict:
    pages = max(1, -(-total // page_size)) if page_size else 1
    return {"page": page, "page_size": page_size, "total": total, "pages": pages}


def age_group(age: int | None) -> str:
    """Coarse band used instead of an exact age wherever a general-purpose list is shown."""
    if age is None or age < 0:
        return "unknown"
    if age <= 5:
        return "0-5"
    if age <= 11:
        return "6-11"
    if age <= 14:
        return "12-14"
    if age <= 17:
        return "15-17"
    return "18+"
