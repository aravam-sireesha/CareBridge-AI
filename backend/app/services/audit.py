"""Append-only audit trail: who did what, when, from where. Nothing here updates or deletes rows."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog

client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)


def record(db: Session, actor: dict | None, action: str, entity_type: str | None = None,
           entity_id: int | None = None, detail: dict[str, Any] | None = None) -> AuditLog:
    """Add an audit row to the caller's transaction (it is saved when the caller commits)."""
    row = AuditLog(
        actor_user_id=(actor or {}).get("id"), actor_email=(actor or {}).get("email"), actor_role=(actor or {}).get("role"),
        action=action, entity_type=entity_type, entity_id=entity_id, detail=detail or None, ip=client_ip.get(),
    )
    db.add(row)
    return row


def record_now(db: Session, actor: dict | None, action: str, entity_type: str | None = None,
               entity_id: int | None = None, detail: dict[str, Any] | None = None) -> AuditLog:
    """Save immediately. Used for failures, where the request is about to end in an error."""
    row = record(db, actor, action, entity_type, entity_id, detail)
    db.commit()
    return row
