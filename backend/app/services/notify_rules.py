"""Notification preference and link rules (pure: no database or web-framework imports)."""
from __future__ import annotations

KINDS = ("verification", "donation", "need", "volunteer", "security", "admin")
DEFAULT_PREFS = {"in_app": True, "push": True, "email": False, "whatsapp": False, "verification": True, "donation": True, "need": True, "volunteer": True, "admin": True}


def safe_link(link: str | None) -> str | None:
    """Only same-site paths are allowed, so a notification can never carry javascript:, data: or off-site links."""
    if not link:
        return None
    link = link.strip()
    if not link.startswith("/") or link.startswith("//") or "\\" in link or any(ord(c) < 32 for c in link):
        return None
    return link[:300]


def wants_in_app(prefs: dict | None, kind: str) -> bool:
    """Security notifications can never be switched off; everything else follows the person's choices."""
    if kind == "security":
        return True
    prefs = prefs or {}
    if prefs.get("in_app") is False:
        return False
    return prefs.get(kind) is not False


def wants_push(prefs: dict | None, kind: str) -> bool:
    """Whether a Web Push may be sent for this kind. A device only receives pushes if the person subscribed it (their consent);
    this adds their per-category choices and a master "push" switch. Security notices can never be switched off."""
    if kind == "security":
        return True
    prefs = prefs or {}
    if prefs.get("push") is False:
        return False
    return prefs.get(kind) is not False


def wants_email(prefs: dict | None, kind: str) -> bool:
    """E-mail notifications are OPT-IN (default off): only when the person switched "email" on, and not for categories they muted.
    (Security e-mails such as password changes are sent by the account flows, not by this channel.)"""
    prefs = prefs or {}
    return prefs.get("email") is True and prefs.get(kind) is not False


def wants_whatsapp(prefs: dict | None, kind: str) -> bool:
    """WhatsApp needs the person's explicit opt-in (default off) and respects muted categories."""
    prefs = prefs or {}
    return prefs.get("whatsapp") is True and prefs.get(kind) is not False


def merge_prefs(existing: dict | None, updates: dict) -> dict:
    merged = {**DEFAULT_PREFS, **{k: v for k, v in (existing or {}).items() if k in DEFAULT_PREFS and isinstance(v, bool)}}
    for key, value in updates.items():
        if key not in DEFAULT_PREFS:
            raise ValueError(f"Unknown preference: {key}")
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        merged[key] = value
    return merged
