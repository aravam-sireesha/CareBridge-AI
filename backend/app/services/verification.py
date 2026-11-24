"""Organization verification decisions.

The database keeps two related fields: the boolean ``Organization.verified`` (what donors and volunteers are filtered on)
and the descriptive ``Organization.verification_status``. This module is the single place that decides how a reviewer's
decision changes both, so they cannot drift apart. It has no database or web-framework imports.
"""
from __future__ import annotations

from dataclasses import dataclass

STATUSES = ("draft", "pending", "under_review", "info_requested", "verified", "rejected")
DECISIONS = ("approve", "reject", "request_info", "under_review")
STATUS_FOR = {"approve": "verified", "reject": "rejected", "request_info": "info_requested", "under_review": "under_review"}
NOTE_REQUIRED = ("reject", "request_info")
MAX_NOTE = 2000


class DecisionError(ValueError):
    """The requested decision is not allowed (the router turns this into HTTP 409/422)."""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Outcome:
    new_status: str
    verified: bool
    note: str | None


def current_status(verification_status: str | None, verified: bool | None) -> str:
    """Resolve the effective status. A verified flag always wins over a stale status string."""
    if verified:
        return "verified"
    status = (verification_status or "pending").lower()
    return status if status in STATUSES and status != "verified" else "pending"


def clean_note(note: str | None) -> str | None:
    text = "".join(ch for ch in (note or "") if ch == "\n" or ch == "\t" or ord(ch) >= 32).strip()
    return text[:MAX_NOTE] or None


def plan_decision(verification_status: str | None, verified: bool | None, decision: str, note: str | None) -> Outcome:
    if decision not in DECISIONS:
        raise DecisionError("Unknown decision. Use one of: " + ", ".join(DECISIONS) + ".", 422)
    note = clean_note(note)
    if decision in NOTE_REQUIRED and not note:
        raise DecisionError("A reason is required when rejecting an organization or asking for more information.", 422)
    before = current_status(verification_status, verified)
    after = STATUS_FOR[decision]
    if before == after:
        raise DecisionError(f"This organization is already marked “{after.replace('_', ' ')}”.")
    return Outcome(new_status=after, verified=(after == "verified"), note=note)
