"""Who may upload or read which stored document. Pure (plain dicts), so every rule is unit-tested.

* A document is owned by an organization, a volunteer, or a delivery. A person reaches only their OWN organization's/own volunteer record's
  documents, and delivery proof for deliveries they are part of. Administrators can read everything (every URL they obtain is audited).
* A volunteer's identity and police-verification documents are NEVER readable by an organization or a donor.
* Donors cannot upload or read documents at all, and delivery proof (photos may show people) is not shown to donors.
* Delivery proof can only be added by the assigned volunteer, and only once they hold the items.
"""
from __future__ import annotations

from typing import Optional

from .storage import KINDS

PROOF_STATUSES = ("picked_up", "in_transit", "delivered")


def upload_allowed(user: dict, owner_type: str, owner_id: int, kind: str, task: Optional[dict] = None) -> bool:
    if kind not in KINDS.get(owner_type, set()):
        return False
    role = user.get("role")
    if role == "admin":
        return owner_type in ("organization", "volunteer") or task is not None
    if role == "organization":
        return owner_type == "organization" and user.get("organization_id") == owner_id
    if role == "volunteer":
        if owner_type == "volunteer":
            return user.get("volunteer_id") is not None and user.get("volunteer_id") == owner_id
        return owner_type == "delivery" and task is not None and user.get("volunteer_id") is not None and task.get("volunteer_id") == user.get("volunteer_id") and task.get("status") in PROOF_STATUSES
    return False


def read_allowed(user: dict, owner_type: str, owner_id: int, task: Optional[dict] = None) -> bool:
    role = user.get("role")
    if role == "admin":
        return True
    if role == "organization":
        if owner_type == "organization":
            return user.get("organization_id") is not None and user.get("organization_id") == owner_id
        return owner_type == "delivery" and task is not None and user.get("organization_id") is not None and task.get("org_id") == user.get("organization_id")
    if role == "volunteer":
        if owner_type == "volunteer":
            return user.get("volunteer_id") is not None and user.get("volunteer_id") == owner_id
        return owner_type == "delivery" and task is not None and user.get("volunteer_id") is not None and task.get("volunteer_id") == user.get("volunteer_id")
    return False


def delete_allowed(user: dict, doc: dict, task: Optional[dict] = None) -> bool:
    """Admins always; the owner only while the document is not approved (an approved verification document stays on record)."""
    if user.get("role") == "admin":
        return True
    return doc.get("uploaded_by") == user.get("id") and doc.get("review_status") != "approved" and read_allowed(user, doc["owner_type"], doc["owner_id"], task)
