"""Delivery workflow: from a proposed delivery to a receipt the organization has confirmed.

A pure state machine. It knows nothing about the database or the web framework, so every rule is unit-tested in
tests/test_delivery_flow.py. The router (routers/deliveries.py) loads a task, asks this module whether an action is
allowed and what changes, then saves the result. The UI buttons come from `allowed_actions`, so the screen can never
offer something the server would refuse.

Consent rules built in:
  * A recommendation never assigns anyone. A volunteer is only OFFERED a task; it becomes theirs when THEY accept.
  * A donor's offer is only a commitment after the donor presses commit.
  * Receipt is confirmed only by the receiving organization, with the quantity actually received.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

# --------------------------------------------------------------------------- states
PROPOSED = "proposed"
AWAITING_APPROVAL = "awaiting_approval"
APPROVED = "approved"
REJECTED = "rejected"
COMMITTED = "committed"
OFFERED = "offered"
ACCEPTED = "accepted"
PICKUP_SCHEDULED = "pickup_scheduled"
PICKED_UP = "picked_up"
IN_TRANSIT = "in_transit"
DELIVERED = "delivered"
RECEIPT_CONFIRMED = "receipt_confirmed"
CANCELLED = "cancelled"
EXCEPTION = "exception"

STATUSES = [PROPOSED, AWAITING_APPROVAL, APPROVED, REJECTED, COMMITTED, OFFERED, ACCEPTED, PICKUP_SCHEDULED,
            PICKED_UP, IN_TRANSIT, DELIVERED, RECEIPT_CONFIRMED, CANCELLED, EXCEPTION]
TERMINAL = {REJECTED, CANCELLED, RECEIPT_CONFIRMED}
IN_MOTION = {ACCEPTED, PICKUP_SCHEDULED, PICKED_UP, IN_TRANSIT, DELIVERED}     # a volunteer holds the task
# stages in which an assigned volunteer may see the pickup and delivery addresses
ADDRESS_STAGES = {ACCEPTED, PICKUP_SCHEDULED, PICKED_UP, IN_TRANSIT, DELIVERED}

LABELS = {
    PROPOSED: "Proposed", AWAITING_APPROVAL: "Awaiting approval", APPROVED: "Approved", REJECTED: "Rejected",
    COMMITTED: "Donor committed", OFFERED: "Offered to volunteer", ACCEPTED: "Volunteer accepted",
    PICKUP_SCHEDULED: "Pickup scheduled", PICKED_UP: "Picked up", IN_TRANSIT: "In transit", DELIVERED: "Delivered",
    RECEIPT_CONFIRMED: "Receipt confirmed", CANCELLED: "Cancelled", EXCEPTION: "Exception raised",
}


class FlowError(Exception):
    """code: forbidden (403) | invalid_state (409) | invalid_input (422)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


# --------------------------------------------------------------------------- people and tasks
@dataclass(frozen=True)
class Actor:
    role: str
    user_id: Optional[int] = None
    org_id: Optional[int] = None
    donor_id: Optional[int] = None
    volunteer_id: Optional[int] = None


@dataclass(frozen=True)
class TaskView:
    status: str
    org_id: Optional[int]
    donor_id: Optional[int]
    volunteer_id: Optional[int]
    quantity: int
    exception_from: Optional[str] = None


def relations(task: TaskView, actor: Actor) -> set[str]:
    """How this actor relates to this task. Ownership is by record id, never by name or email."""
    rel: set[str] = set()
    if actor.role == "admin":
        rel.add("admin")
    if actor.role == "organization" and actor.org_id is not None and actor.org_id == task.org_id:
        rel.add("org_owner")
    if actor.role == "donor" and actor.donor_id is not None and actor.donor_id == task.donor_id:
        rel.add("donor_owner")
    if actor.role == "volunteer" and actor.volunteer_id is not None and actor.volunteer_id == task.volunteer_id:
        rel.add("assigned_volunteer")
    return rel


# --------------------------------------------------------------------------- rules
@dataclass(frozen=True)
class Rule:
    from_: frozenset
    who: frozenset
    label: str
    fields: tuple = ()          # payload fields the UI must collect
    tone: str = "primary"       # primary | danger | secondary


def _r(from_, who, label, fields=(), tone="primary") -> Rule:
    return Rule(frozenset(from_), frozenset(who), label, tuple(fields), tone)


_IN_MOTION_OR_DELIVERED = [ACCEPTED, PICKUP_SCHEDULED, PICKED_UP, IN_TRANSIT, DELIVERED]

RULES: dict[str, Rule] = {
    "submit": _r([PROPOSED], ["org_owner"], "Submit for approval"),
    "approve": _r([AWAITING_APPROVAL], ["admin"], "Approve"),
    "reject": _r([AWAITING_APPROVAL], ["admin"], "Reject", ["reason"], "danger"),
    "request_clarification": _r([AWAITING_APPROVAL], ["admin"], "Ask for clarification", ["reason"], "secondary"),
    "commit": _r([APPROVED], ["donor_owner"], "Commit to this donation"),
    "offer": _r([COMMITTED], ["org_owner", "admin"], "Offer to a volunteer", ["volunteer_id"]),
    "accept": _r([OFFERED], ["assigned_volunteer"], "Accept this task"),
    "decline": _r([OFFERED], ["assigned_volunteer"], "Decline", [], "secondary"),
    "withdraw": _r([ACCEPTED, PICKUP_SCHEDULED], ["assigned_volunteer"], "Step back from this task", ["reason"], "secondary"),
    "schedule_pickup": _r([ACCEPTED, PICKUP_SCHEDULED], ["assigned_volunteer", "donor_owner"], "Schedule pickup", ["pickup_at"]),
    "pick_up": _r([PICKUP_SCHEDULED], ["assigned_volunteer"], "Confirm pickup"),
    "start_transit": _r([PICKED_UP], ["assigned_volunteer"], "Start delivery"),
    "deliver": _r([IN_TRANSIT], ["assigned_volunteer"], "Mark delivered", ["note"]),
    "confirm_receipt": _r([DELIVERED], ["org_owner"], "Confirm receipt", ["received_quantity"]),
    "raise_exception": _r(_IN_MOTION_OR_DELIVERED, ["assigned_volunteer", "org_owner", "donor_owner"], "Report a problem", ["reason"], "danger"),
    "resolve_exception": _r([EXCEPTION], ["admin"], "Resolve", ["resolution"]),
    "cancel": _r([PROPOSED, AWAITING_APPROVAL, APPROVED, COMMITTED, OFFERED, ACCEPTED, PICKUP_SCHEDULED],
                 ["org_owner", "donor_owner", "admin"], "Cancel", ["reason"], "danger"),
}

RESOLUTIONS = ("cancel", "reoffer", "resume")


def allowed_actions(task: TaskView, actor: Actor) -> list[dict]:
    """What this person may do now, for the UI. Each entry: {action, label, fields, tone}."""
    rel = relations(task, actor)
    out = []
    for name, rule in RULES.items():
        if task.status in rule.from_ and rel & rule.who:
            out.append({"action": name, "label": rule.label, "fields": list(rule.fields), "tone": rule.tone})
    return out


# --------------------------------------------------------------------------- result of an action
@dataclass
class Transition:
    status: str
    updates: dict = field(default_factory=dict)      # columns to set on the task
    note: Optional[str] = None                        # recorded on the event
    notify: tuple = ()                                # who to tell: "org" | "donor" | "volunteer" | "admins"
    message: str = ""


def _text(payload: dict, key: str, minimum: int = 1, maximum: int = 500) -> str:
    value = str((payload or {}).get(key) or "").strip()
    if len(value) < minimum:
        raise FlowError("invalid_input", f"Please give a {key.replace('_', ' ')}" + (f" of at least {minimum} characters." if minimum > 1 else "."))
    if len(value) > maximum:
        raise FlowError("invalid_input", f"The {key.replace('_', ' ')} is too long (at most {maximum} characters).")
    return value


def _int(payload: dict, key: str, minimum: int = 0) -> int:
    raw = (payload or {}).get(key)
    if isinstance(raw, bool) or raw is None or str(raw).strip() == "":
        raise FlowError("invalid_input", f"Enter a whole number for {key.replace('_', ' ')}.")
    try:
        number = int(str(raw).strip())
        if str(number) != str(raw).strip().lstrip("+"):
            raise ValueError
    except ValueError:
        raise FlowError("invalid_input", f"Enter a whole number for {key.replace('_', ' ')}.") from None
    if number < minimum:
        raise FlowError("invalid_input", f"{key.replace('_', ' ').capitalize()} cannot be below {minimum}.")
    return number


def _when(payload: dict, key: str, now: datetime, horizon_days: int = 90) -> datetime:
    raw = (payload or {}).get(key)
    if isinstance(raw, datetime):
        value = raw
    else:
        try:
            value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            raise FlowError("invalid_input", "Enter a valid date and time for the pickup.") from None
        if value.tzinfo is not None:                       # store naive UTC like every other timestamp in the schema
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
    if value < now - timedelta(minutes=5):
        raise FlowError("invalid_input", "The pickup time cannot be in the past.")
    if value > now + timedelta(days=horizon_days):
        raise FlowError("invalid_input", f"The pickup must be within the next {horizon_days} days.")
    return value


def apply(task: TaskView, action: str, actor: Actor, payload: Optional[dict] = None, now: Optional[datetime] = None,
          approval_required: bool = True) -> Transition:
    """Decide one action. Raises FlowError when it is not allowed or the input is invalid; otherwise returns what to save."""
    payload = payload or {}
    now = now or datetime.utcnow()
    rule = RULES.get(action)
    if rule is None:
        raise FlowError("invalid_input", "Unknown action.")
    rel = relations(task, actor)
    if not rel & rule.who:
        raise FlowError("forbidden", "You are not allowed to do this on this delivery.")
    if task.status not in rule.from_:
        raise FlowError("invalid_state", f"This cannot be done while the delivery is “{LABELS.get(task.status, task.status)}”.")

    if action == "submit":
        if task.quantity < 1:
            raise FlowError("invalid_input", "The quantity must be at least 1.")
        if approval_required:
            return Transition(AWAITING_APPROVAL, {"submitted_at": now}, None, ("admins",), "A delivery is waiting for your approval.")
        return Transition(APPROVED, {"submitted_at": now, "decided_at": now}, "Approval not required by policy", ("donor",), "A delivery was approved. Please commit to it.")
    if action == "approve":
        return Transition(APPROVED, {"decided_at": now, "decision_reason": (payload.get("reason") or None)}, payload.get("reason") or None, ("org", "donor"), "The delivery was approved.")
    if action == "reject":
        reason = _text(payload, "reason", 3)
        return Transition(REJECTED, {"decided_at": now, "decision_reason": reason}, reason, ("org",), "The delivery was not approved.")
    if action == "request_clarification":
        reason = _text(payload, "reason", 3)
        return Transition(PROPOSED, {"decision_reason": reason}, reason, ("org",), "An administrator asked for clarification.")
    if action == "commit":
        return Transition(COMMITTED, {"committed_at": now}, None, ("org",), "The donor committed to the delivery.")
    if action == "offer":
        volunteer_id = _int(payload, "volunteer_id", 1)
        return Transition(OFFERED, {"volunteer_id": volunteer_id, "offered_at": now}, None, ("volunteer",), "You were offered a delivery task. Accept it only if you can do it.")
    if action == "accept":
        return Transition(ACCEPTED, {"accepted_at": now}, None, ("org", "donor"), "The volunteer accepted the delivery.")
    if action == "decline":
        return Transition(COMMITTED, {"volunteer_id": None, "offered_at": None}, "Volunteer declined", ("org",), "The volunteer declined. Offer it to someone else.")
    if action == "withdraw":
        reason = _text(payload, "reason", 3)
        return Transition(COMMITTED, {"volunteer_id": None, "offered_at": None, "accepted_at": None, "pickup_at": None}, reason, ("org", "donor"), "The volunteer stepped back. The delivery needs a new volunteer.")
    if action == "schedule_pickup":
        when = _when(payload, "pickup_at", now)
        return Transition(PICKUP_SCHEDULED, {"pickup_at": when}, None, ("org", "donor", "volunteer"), "A pickup time was set.")
    if action == "pick_up":
        return Transition(PICKED_UP, {"picked_up_at": now}, None, ("org", "donor"), "The items were picked up.")
    if action == "start_transit":
        return Transition(IN_TRANSIT, {"in_transit_at": now}, None, ("org",), "The delivery is on its way.")
    if action == "deliver":
        proof = _text(payload, "note", 3)
        return Transition(DELIVERED, {"delivered_at": now, "delivery_note": proof}, proof, ("org", "donor"), "The items were delivered. Please confirm receipt.")
    if action == "confirm_receipt":
        received = _int(payload, "received_quantity", 0)
        mismatch = received != task.quantity
        note = (str(payload.get("note") or "").strip() or None)
        if mismatch and not note:
            raise FlowError("invalid_input", "The quantity received differs from the quantity expected. Please add a note explaining the difference.")
        return Transition(RECEIPT_CONFIRMED, {"confirmed_at": now, "received_quantity": received, "receipt_note": note},
                          f"Received {received} of {task.quantity}" + (f": {note}" if note else ""), ("donor", "volunteer", "admins") if mismatch else ("donor", "volunteer"),
                          "Receipt was confirmed with a different quantity." if mismatch else "Receipt was confirmed. Thank you.")
    if action == "raise_exception":
        reason = _text(payload, "reason", 3)
        return Transition(EXCEPTION, {"exception_reason": reason, "exception_from": task.status, "exception_at": now}, reason, ("admins", "org", "donor", "volunteer"), "A problem was reported on a delivery.")
    if action == "resolve_exception":
        resolution = str(payload.get("resolution") or "")
        if resolution not in RESOLUTIONS:
            raise FlowError("invalid_input", "Choose how to resolve it: cancel, offer again, or resume.")
        note = (str(payload.get("note") or "").strip() or None)
        keep = {"exception_reason": None, "exception_from": None}
        if resolution == "cancel":
            return Transition(CANCELLED, {**keep, "cancelled_at": now, "cancel_reason": note or "Cancelled after a reported problem"}, note, ("org", "donor", "volunteer"), "The delivery was cancelled after review.")
        if resolution == "reoffer":
            if task.exception_from not in (ACCEPTED, PICKUP_SCHEDULED):
                raise FlowError("invalid_state", "Items may already have been collected, so this cannot be offered again. Cancel it or resume it.")
            return Transition(COMMITTED, {**keep, "volunteer_id": None, "offered_at": None, "accepted_at": None, "pickup_at": None}, note, ("org", "donor"), "The delivery needs a new volunteer.")
        return Transition(task.exception_from or ACCEPTED, keep, note, ("org", "donor", "volunteer"), "The problem was resolved and the delivery continues.")
    if action == "cancel":
        reason = _text(payload, "reason", 3)
        return Transition(CANCELLED, {"cancelled_at": now, "cancel_reason": reason}, reason, ("org", "donor", "volunteer"), "A delivery was cancelled.")
    raise FlowError("invalid_input", "Unknown action.")      # unreachable: every rule is handled above


# --------------------------------------------------------------------------- quantities (no over-allocation, no double counting)
def reserved_quantity(tasks: Iterable[tuple]) -> int:
    """Units already spoken for. tasks = (status, quantity, received_quantity). Rejected and cancelled reserve nothing;
    a confirmed receipt counts what was actually received, once."""
    total = 0
    for status, quantity, received in tasks:
        if status in (REJECTED, CANCELLED):
            continue
        total += (received if status == RECEIPT_CONFIRMED and received is not None else quantity) or 0
    return total


def remaining_for_need(need_quantity: Optional[int], tasks: Iterable[tuple]) -> int:
    return max(0, int(need_quantity or 0) - reserved_quantity(tasks))


def check_quantity(quantity: int, need_quantity: Optional[int], other_tasks: Iterable[tuple]) -> None:
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise FlowError("invalid_input", "The quantity must be a whole number of at least 1.")
    left = remaining_for_need(need_quantity, other_tasks)
    if quantity > left:
        raise FlowError("invalid_input", f"Only {left} more can be arranged for this need (the rest is already in other deliveries)." if left else "This need is already fully covered by other deliveries.")


# --------------------------------------------------------------------------- privacy: who sees which address, and when
def can_see_addresses(task: TaskView, actor: Actor) -> dict:
    """pickup = the donor's pickup place; delivery = the organization's place. A volunteer sees them only after
    accepting and until the delivery is done. The donor sees where they are giving to; the organization sees its own."""
    rel = relations(task, actor)
    stage = task.status in ADDRESS_STAGES
    return {
        "pickup": "admin" in rel or "donor_owner" in rel or ("assigned_volunteer" in rel and stage),
        "delivery": "admin" in rel or "org_owner" in rel or "donor_owner" in rel or ("assigned_volunteer" in rel and stage),
    }


# --------------------------------------------------------------------------- reporting (offers, commitments and confirmed quantities kept apart)
def approval_required(env: Optional[dict] = None) -> bool:
    """Admin approval is a policy switch, not hard-wired: DELIVERY_APPROVAL_REQUIRED=false removes the bottleneck."""
    import os
    value = (os.environ if env is None else env).get("DELIVERY_APPROVAL_REQUIRED", "true")
    return str(value).strip().lower() not in ("false", "0", "no", "off")


def summarize(tasks: Iterable[tuple]) -> dict:
    """tasks = (status, quantity, received_quantity). Every task lands in exactly one bucket, so nothing is counted twice.

    planned     = proposed, awaiting approval, approved (nobody has committed yet)
    committed   = donor committed and/or volunteer offered (no volunteer has accepted yet)
    in_progress = volunteer accepted through in transit
    delivered   = delivered but the organization has not confirmed receipt yet
    confirmed   = receipt confirmed: counts the quantity ACTUALLY RECEIVED
    """
    buckets = {"planned": 0, "committed": 0, "in_progress": 0, "delivered": 0, "confirmed": 0}
    counts = {"total": 0, "open_exceptions": 0, "cancelled": 0, "rejected": 0, "confirmed": 0}
    where = {PROPOSED: "planned", AWAITING_APPROVAL: "planned", APPROVED: "planned", COMMITTED: "committed", OFFERED: "committed",
             ACCEPTED: "in_progress", PICKUP_SCHEDULED: "in_progress", PICKED_UP: "in_progress", IN_TRANSIT: "in_progress", DELIVERED: "delivered"}
    for status, quantity, received in tasks:
        counts["total"] += 1
        if status == EXCEPTION:
            counts["open_exceptions"] += 1
        elif status == CANCELLED:
            counts["cancelled"] += 1
        elif status == REJECTED:
            counts["rejected"] += 1
        elif status == RECEIPT_CONFIRMED:
            counts["confirmed"] += 1
            buckets["confirmed"] += (received if received is not None else 0)
        elif status in where:
            buckets[where[status]] += quantity or 0
    return {"quantities": buckets, "counts": counts}
