"""Deliveries: a donor's gift travelling to an organization's need, with a recorded actor and time at every step.

All decisions come from services/delivery_flow.py (pure, unit-tested). This module loads rows, locks them, applies the
decision, writes the event, the audit entry and the notifications.

    POST /deliveries/                              organization/admin: propose a delivery
    GET  /deliveries/                              the caller's deliveries
    GET  /deliveries/candidates/{need_id}          donors and volunteers an organization may pick for a need
    GET  /deliveries/impact                        quantities by stage (offered, committed, delivered, confirmed kept apart)
    GET  /deliveries/{id}                          one delivery with its history
    POST /deliveries/{id}/actions/{action}         submit | approve | reject | commit | offer | accept | ... (see RULES)
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictInt
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_user
from ..services import audit, availability, delivery_flow as flow, events as live, ratelimit, tracking
from ..services.notify import notify

router = APIRouter(prefix="/deliveries", tags=["deliveries"])
HTTP = {"forbidden": 403, "invalid_state": 409, "invalid_input": 422}
SETTABLE = {"submitted_at", "decided_at", "decision_reason", "committed_at", "offered_at", "accepted_at", "pickup_at", "picked_up_at",
            "in_transit_at", "delivered_at", "delivery_note", "confirmed_at", "received_quantity", "receipt_note", "cancelled_at",
            "cancel_reason", "exception_reason", "exception_from", "exception_at", "volunteer_id"}


class DeliveryCreate(BaseModel):
    need_id: StrictInt
    donor_id: StrictInt
    quantity: StrictInt = Field(ge=1, le=1_000_000)
    item_description: Optional[str] = Field(default=None, max_length=300)
    estimated_weight_kg: Optional[FiniteFloat] = Field(default=None, gt=0, le=availability.MAX_CAPACITY_KG)
    match_id: Optional[StrictInt] = None


class ActionBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reason: Optional[str] = Field(default=None, max_length=500)
    note: Optional[str] = Field(default=None, max_length=500)
    volunteer_id: Optional[StrictInt] = None
    pickup_at: Optional[str] = Field(default=None, max_length=40)
    received_quantity: Optional[StrictInt] = None
    resolution: Optional[str] = Field(default=None, max_length=20)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fail(error: flow.FlowError):
    raise HTTPException(status_code=HTTP[error.code], detail=error.message)


def _actor(user: dict) -> flow.Actor:
    return flow.Actor(role=user["role"], user_id=user.get("id"), org_id=user.get("organization_id"),
                      donor_id=user.get("donor_id"), volunteer_id=user.get("volunteer_id"))


def _view(task) -> flow.TaskView:
    return flow.TaskView(task.status, task.org_id, task.donor_id, task.volunteer_id, task.quantity, task.exception_from)


def _others(db: Session, need_id: int, exclude_id: Optional[int] = None) -> list[tuple]:
    q = db.query(models.DeliveryTask.status, models.DeliveryTask.quantity, models.DeliveryTask.received_quantity).filter(models.DeliveryTask.need_id == need_id)
    if exclude_id is not None:
        q = q.filter(models.DeliveryTask.id != exclude_id)
    return [tuple(r) for r in q.all()]


def _iso(value):
    return value.isoformat() if value else None


def _serialize(db: Session, task, actor: flow.Actor, events: bool = False) -> dict:
    view, rel = _view(task), flow.relations(_view(task), actor)
    seen = flow.can_see_addresses(view, actor)
    need, org = db.get(models.Need, task.need_id), db.get(models.Organization, task.org_id)
    donor = db.get(models.Donor, task.donor_id) if task.donor_id else None
    volunteer = db.get(models.Volunteer, task.volunteer_id) if task.volunteer_id else None
    # A volunteer learns the donor's name only when they may see the pickup place; a donor learns the volunteer's name
    # only once the volunteer has accepted.
    show_donor = "assigned_volunteer" not in rel or seen["pickup"]
    show_volunteer = bool(rel & {"admin", "org_owner", "assigned_volunteer"}) or (task.status in flow.ADDRESS_STAGES or task.status == flow.RECEIPT_CONFIRMED)
    out = {
        "id": task.id, "status": task.status, "status_label": flow.LABELS.get(task.status, task.status),
        "need": {"id": task.need_id, "title": getattr(need, "title", None), "category": getattr(need, "category", None), "urgency": getattr(need, "urgency", None)},
        "organization": {"id": task.org_id, "name": getattr(org, "name", None)},
        "donor": {"id": donor.id, "name": donor.name} if donor and show_donor else None,
        "volunteer": {"id": volunteer.id, "name": volunteer.name} if volunteer and show_volunteer else None,
        "quantity": task.quantity, "estimated_weight_kg": task.estimated_weight_kg, "received_quantity": task.received_quantity, "item_description": task.item_description,
        "pickup_area": getattr(donor, "location", None) if seen["pickup"] else None,
        "delivery_area": getattr(org, "address", None) if seen["delivery"] else None,
        "addresses_visible": seen,
        # Coordinates for navigation, under the SAME stage rules as the address text. Only places people chose to share exist.
        "points": {
            "pickup": ({"latitude": donor.latitude, "longitude": donor.longitude, "label": getattr(donor, "location", None)} if seen["pickup"] and donor and donor.latitude is not None else None),
            "delivery": ({"latitude": org.latitude, "longitude": org.longitude, "label": getattr(org, "address", None)} if seen["delivery"] and org and org.latitude is not None else None),
        },
        "tracking": _tracking_flags(db, task, rel),
        "pickup_at": _iso(task.pickup_at), "created_at": _iso(task.created_at), "updated_at": _iso(task.updated_at),
        "milestones": {k: _iso(getattr(task, k)) for k in ("submitted_at", "decided_at", "committed_at", "offered_at", "accepted_at", "picked_up_at", "in_transit_at", "delivered_at", "confirmed_at", "cancelled_at")},
        "decision_reason": task.decision_reason, "cancel_reason": task.cancel_reason, "exception_reason": task.exception_reason,
        "delivery_note": task.delivery_note, "receipt_note": task.receipt_note,
        "quantity_mismatch": task.received_quantity is not None and task.received_quantity != task.quantity,
        "allowed_actions": flow.allowed_actions(view, actor),
    }
    if events:
        rows = db.query(models.DeliveryEvent).filter(models.DeliveryEvent.task_id == task.id).order_by(models.DeliveryEvent.id).all()
        out["events"] = [{"action": e.action, "from": e.from_status, "to": e.to_status, "actor_role": e.actor_role, "note": e.note, "at": _iso(e.created_at)} for e in rows]
    return out


def _tracking_flags(db: Session, task, rel: set) -> dict:
    row = db.query(models.DeliveryLocation).filter(models.DeliveryLocation.task_id == task.id).first()
    sharing = bool(row and row.stopped_at is None)
    can_share = "assigned_volunteer" in rel and task.status in tracking.HOLDING_STATUSES
    flags = {"can_share": can_share, "sharing": sharing and can_share, "can_watch": tracking.can_view(task.status, rel)}
    if flags["sharing"]:
        sess = _open_session(db, task)
        flags["paused"] = bool(sess and sess.status == "paused")
        flags["tracking_session_id"] = sess.public_id if sess else None
        flags["retain_history"] = bool(sess and sess.retain_history)
    return flags


def _scoped(db: Session, user: dict):
    q = db.query(models.DeliveryTask)
    role = user["role"]
    if role == "admin":
        return q
    key = {"organization": ("org_id", "organization_id"), "donor": ("donor_id", "donor_id"), "volunteer": ("volunteer_id", "volunteer_id")}.get(role)
    owner = user.get(key[1]) if key else None
    if not key or owner is None:                 # never filter on NULL: that would match every unowned row
        return q.filter(models.DeliveryTask.id == -1)
    return q.filter(getattr(models.DeliveryTask, key[0]) == owner)


def _linked_person(db: Session, model, person_id: int, need) -> bool:
    """A donor/volunteer an organization may use for a need: one of its own, or one recommended for this need."""
    person = db.get(model, person_id)
    if person is None:
        return False
    if person.organization_id == need.org_id:
        return True
    column = models.Match.donor_id if model is models.Donor else models.Match.volunteer_id
    return db.query(models.Match.id).filter(models.Match.need_id == need.id, column == person_id).first() is not None


def _record(db: Session, task, action: str, from_status: Optional[str], note: Optional[str], user: dict) -> None:
    db.add(models.DeliveryEvent(task_id=task.id, action=action, from_status=from_status, to_status=task.status,
                                actor_user_id=user.get("id"), actor_role=user["role"], note=note))
    audit.record(db, user, f"delivery.{action}", "delivery_task", task.id, {"from": from_status, "to": task.status})


def _tell(db: Session, task, prior_volunteer_id: Optional[int], targets, actor_user_id, message: str) -> None:
    ids: set[int] = set()
    U = models.User
    if "org" in targets:
        ids |= {u for (u,) in db.query(U.id).filter(U.organization_id == task.org_id).all()}
    if "donor" in targets and task.donor_id:
        ids |= {u for (u,) in db.query(U.id).filter(U.donor_id == task.donor_id).all()}
    volunteer_id = task.volunteer_id or prior_volunteer_id
    if "volunteer" in targets and volunteer_id:
        ids |= {u for (u,) in db.query(U.id).filter(U.volunteer_id == volunteer_id).all()}
    if "admins" in targets:
        ids |= {u for (u,) in db.query(U.id).filter(U.role == "admin", U.is_active.isnot(False)).all()}
    ids.discard(actor_user_id)
    for uid in ids:
        notify(db, uid, "donation", f"Delivery #{task.id}: {flow.LABELS.get(task.status, task.status)}", message, f"/deliveries?open={task.id}")


# --------------------------------------------------------------------------- create
@router.post("/", status_code=201)
def propose_delivery(body: DeliveryCreate, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if user["role"] not in ("organization", "admin"):
        raise HTTPException(status_code=403, detail="Only organizations and administrators can propose a delivery")
    need = db.query(models.Need).filter(models.Need.id == body.need_id).with_for_update().first()   # lock: serialises quantity checks
    if need is None or (user["role"] == "organization" and need.org_id != user.get("organization_id")):
        raise HTTPException(status_code=404, detail="Need not found")
    org = db.get(models.Organization, need.org_id)
    if org is None or not org.verified:
        raise HTTPException(status_code=409, detail="The organization must be verified before deliveries can be arranged")
    if (need.status or "open") in ("fulfilled", "closed"):
        raise HTTPException(status_code=409, detail="This need is already closed or fulfilled")
    if not _linked_person(db, models.Donor, body.donor_id, need):
        raise HTTPException(status_code=422, detail="That donor is not one of your donors and has not been recommended for this need")
    try:
        flow.check_quantity(body.quantity, need.quantity, _others(db, need.id))
    except flow.FlowError as e:
        _fail(e)
    task = models.DeliveryTask(need_id=need.id, org_id=need.org_id, donor_id=body.donor_id, quantity=body.quantity, status=flow.PROPOSED,
                               item_description=(body.item_description or "").strip() or None, estimated_weight_kg=body.estimated_weight_kg, match_id=body.match_id, created_by=user.get("id"))
    db.add(task)
    db.flush()
    _record(db, task, "create", None, None, user)
    db.commit()
    db.refresh(task)
    return _serialize(db, task, _actor(user), events=True)


# --------------------------------------------------------------------------- read
@router.get("/")
def list_deliveries(status: Optional[str] = Query(None, max_length=30), limit: int = Query(100, ge=1, le=200),
                    user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    q = _scoped(db, user)
    if status:
        q = q.filter(models.DeliveryTask.status == status)
    rows = q.order_by(models.DeliveryTask.updated_at.desc(), models.DeliveryTask.id.desc()).limit(limit).all()
    actor = _actor(user)
    return [_serialize(db, t, actor) for t in rows]


@router.get("/candidates/{need_id}")
def candidates(need_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Donors and volunteers an organization can choose for a need: its own, plus any recommended for this need."""
    if user["role"] not in ("organization", "admin"):
        raise HTTPException(status_code=403, detail="Only organizations and administrators can choose people for a delivery")
    need = db.get(models.Need, need_id)
    if need is None or (user["role"] == "organization" and need.org_id != user.get("organization_id")):
        raise HTTPException(status_code=404, detail="Need not found")
    recommended = db.query(models.Match).filter(models.Match.need_id == need_id).all()
    d_ids = {m.donor_id for m in recommended if m.donor_id}
    v_ids = {m.volunteer_id for m in recommended if m.volunteer_id}

    def pick(model, ids):
        rows = db.query(model).filter((model.organization_id == need.org_id) | (model.id.in_(ids or {-1}))).all()
        return [{"id": r.id, "name": r.name, "recommended": r.id in ids} for r in rows]

    return {"need_id": need_id, "remaining_quantity": flow.remaining_for_need(need.quantity, _others(db, need_id)),
            "donors": pick(models.Donor, d_ids), "volunteers": pick(models.Volunteer, v_ids)}


@router.get("/impact")
def impact(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = [(t.status, t.quantity, t.received_quantity) for t in _scoped(db, user).all()]
    return {**flow.summarize(rows), "note": "Quantities are kept apart by stage. Only 'confirmed' counts what an organization actually received."}


@router.get("/{task_id}")
def get_delivery(task_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    task = _scoped(db, user).filter(models.DeliveryTask.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Delivery not found")        # also what a stranger gets: existence is not revealed
    return _serialize(db, task, _actor(user), events=True)


# --------------------------------------------------------------------------- act
@router.post("/{task_id}/actions/{action}")
def act(task_id: int, action: str, body: ActionBody, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.query(models.DeliveryTask).filter(models.DeliveryTask.id == task_id).with_for_update().first()
    actor = _actor(user)
    if task is None or not flow.relations(_view(task), actor):
        raise HTTPException(status_code=404, detail="Delivery not found")
    payload = body.model_dump(exclude_none=True)
    need = db.query(models.Need).filter(models.Need.id == task.need_id).with_for_update().first()
    try:
        if action == "submit":                                   # re-check against everything arranged since it was proposed
            flow.check_quantity(task.quantity, need.quantity if need else None, _others(db, task.need_id, exclude_id=task.id))
        if action == "offer":
            volunteer = db.get(models.Volunteer, payload.get("volunteer_id") or -1)
            if volunteer is None or need is None or not _linked_person(db, models.Volunteer, volunteer.id, need):
                raise flow.FlowError("invalid_input", "Choose one of your volunteers, or one recommended for this need.")
            if db.query(models.User.id).filter(models.User.volunteer_id == volunteer.id, models.User.is_active.isnot(False)).first() is None:
                raise flow.FlowError("invalid_input", "That volunteer has no active account, so they could not accept the task.")
            if availability.capacity_status(task.estimated_weight_kg, volunteer.carry_capacity_kg) == "exceeds":
                raise flow.FlowError("invalid_input", f"This delivery is about {task.estimated_weight_kg:g} kg, but that volunteer said they can carry {volunteer.carry_capacity_kg:g} kg per trip (self-declared). Choose someone else or split the delivery.")
        before, prior_volunteer = task.status, task.volunteer_id
        result = flow.apply(_view(task), action, actor, payload, _now(), flow.approval_required())
        if action == "schedule_pickup" and task.volunteer_id:             # a volunteer cannot be in two places
            when = result.updates["pickup_at"]
            others = [r[0] for r in db.query(models.DeliveryTask.pickup_at).filter(
                models.DeliveryTask.volunteer_id == task.volunteer_id, models.DeliveryTask.id != task.id,
                models.DeliveryTask.status.in_(["pickup_scheduled", "picked_up", "in_transit"])).all()]
            clash = availability.has_conflict(others, when)
            if clash is not None:
                raise flow.FlowError("invalid_state", f"The volunteer already has another pickup around {clash.strftime('%d %b, %H:%M')} (UTC). Choose a time at least {availability.CONFLICT_WINDOW_MINUTES // 60} hours apart.")
            if "donor_owner" in flow.relations(_view(task), actor):         # a donor must not book outside hours the volunteer declared
                vol = db.get(models.Volunteer, task.volunteer_id)
                if vol is not None and availability.is_available(vol.availability_slots, vol.availability_timezone, when) is False:
                    raise flow.FlowError("invalid_input", "That time is outside the hours the volunteer said they are available. Ask them to choose the time.")
    except flow.FlowError as e:
        _fail(e)
    for key, value in result.updates.items():
        if key in SETTABLE:
            setattr(task, key, value)
    task.status = result.status
    _record(db, task, action, before, result.note, user)
    if not tracking.keeps_position(task.status):                  # the shared position never outlives the active stages
        db.query(models.DeliveryLocation).filter(models.DeliveryLocation.task_id == task.id).delete(synchronize_session=False)
        db.query(models.TrackingSession).filter(models.TrackingSession.task_id == task.id, models.TrackingSession.status.in_(("active", "paused"))) \
            .update({"status": "stopped", "stopped_at": _now()}, synchronize_session=False)
    if action == "confirm_receipt" and need is not None:
        db.flush()
        received = sum((r or 0) for (s, _q, r) in _others(db, need.id, exclude_id=task.id) if s == flow.RECEIPT_CONFIRMED) + (task.received_quantity or 0)   # this task counted once
        if need.quantity and received >= need.quantity:
            need.status, need.fulfilled_at = "fulfilled", _now()
            audit.record(db, user, "need.fulfilled", "need", need.id, {"received": received})
    _tell(db, task, prior_volunteer, result.notify, user.get("id"), result.message)
    live.publish_after_commit(db, "delivery.status", {"task_id": task.id, "status": task.status, "label": flow.LABELS.get(task.status, task.status)},
                              live.audience(orgs=[task.org_id], donors=[task.donor_id], volunteers=[task.volunteer_id, prior_volunteer], roles=["admin"]))
    db.commit()
    db.refresh(task)
    return _serialize(db, task, actor, events=True)


# --------------------------------------------------------------------------- live tracking (opt-in, one delivery at a time)
class StartBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    retain_history: bool = False          # a SEPARATE, explicit consent: may a movement trail be kept (for LOCATION_RETENTION_DAYS)?


class FixBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    latitude: FiniteFloat = Field(ge=-90, le=90)
    longitude: FiniteFloat = Field(ge=-180, le=180)
    accuracy_m: Optional[FiniteFloat] = Field(default=None, ge=0)
    heading: Optional[FiniteFloat] = None                      # degrees, 0-360 (range checked with a clear message)
    speed: Optional[FiniteFloat] = None                        # metres per second
    timestamp: Optional[FiniteFloat] = None                    # device time of the fix, epoch milliseconds
    seq: Optional[StrictInt] = Field(default=None, ge=0)       # increases by one per fix; a repeat is acknowledged, not stored twice
    tracking_session_id: Optional[str] = Field(default=None, max_length=36)
    delivery_id: Optional[StrictInt] = None                    # optional echo of the path id; a mismatch is refused


def _track_error(e: "tracking.TrackingError"):
    codes = {"forbidden": 403, "invalid_state": 409, "invalid_input": 422, "too_soon": 429}
    raise HTTPException(status_code=codes[e.code], detail=e.message, headers={"Retry-After": str(e.retry_after)} if e.retry_after else None)


def _locked_task(db: Session, user: dict, task_id: int):
    task = db.query(models.DeliveryTask).filter(models.DeliveryTask.id == task_id).with_for_update().first()
    rel = flow.relations(_view(task), _actor(user)) if task else set()
    if task is None or not rel:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return task, rel


def _open_session(db: Session, task):
    return (db.query(models.TrackingSession)
            .filter(models.TrackingSession.task_id == task.id, models.TrackingSession.status.in_(("active", "paused")))
            .order_by(models.TrackingSession.id.desc()).first())


def _viewer_audience(task):
    """Who may be told about this delivery's live position: the organization, the donor and administrators (not the volunteer:
    they already know where they are). Position events are only ever sent during the stages the viewing rules allow."""
    return live.audience(orgs=[task.org_id], donors=[task.donor_id], roles=["admin"])


def _announce_tracking(db: Session, task, state: str) -> None:
    payload = {"task_id": task.id, "state": state}
    live.publish_after_commit(db, "delivery.tracking", payload, live.audience(volunteers=[task.volunteer_id]))
    if task.status in tracking.VIEWER_STATUSES:
        live.publish_after_commit(db, "delivery.tracking", payload, _viewer_audience(task))


def _erase_position(row) -> None:
    row.latitude = row.longitude = row.accuracy_m = row.recorded_at = None


@router.post("/{task_id}/tracking/start")
def start_sharing(task_id: int, body: Optional[StartBody] = None, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """The assigned volunteer chooses to share their live position for this delivery. Nothing is stored before this."""
    task, rel = _locked_task(db, user, task_id)
    try:
        tracking.can_start(task.status, rel)
    except tracking.TrackingError as e:
        _track_error(e)
    now = _now()
    for old in db.query(models.TrackingSession).filter(models.TrackingSession.task_id == task.id, models.TrackingSession.status.in_(("active", "paused"))).all():
        old.status, old.stopped_at = "stopped", now                      # a restart replaces the earlier session
    retain = bool(body and body.retain_history) and tracking.history_enabled()
    sess = models.TrackingSession(public_id=str(uuid.uuid4()), task_id=task.id, volunteer_id=task.volunteer_id, status="active",
                                  consent_version=tracking.CONSENT_VERSION, consented_at=now, retain_history=retain,
                                  expires_at=tracking.session_expiry(now), last_seq=-1)
    db.add(sess)
    row = db.query(models.DeliveryLocation).filter(models.DeliveryLocation.task_id == task.id).with_for_update().first()
    if row is None:
        row = models.DeliveryLocation(task_id=task.id, volunteer_id=task.volunteer_id, consented_at=now)
        db.add(row)
    row.volunteer_id, row.consented_at, row.stopped_at = task.volunteer_id, now, None
    _erase_position(row)                                                  # a new session starts with no position
    audit.record(db, user, "delivery.tracking_started", "delivery_task", task.id,
                 {"session": sess.public_id, "retain_history": retain, "consent_version": sess.consent_version})
    _announce_tracking(db, task, "started")
    db.commit()
    return {"sharing": True, "paused": False, "tracking_session_id": sess.public_id, "retain_history": retain, "expires_at": _iso(sess.expires_at)}


@router.put("/{task_id}/location")
def report_position(task_id: int, body: FixBody, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    ok, retry = ratelimit.limiter.hit(f"loc:u{user['id']}", 60, 60)      # burst guard on top of the per-delivery interval
    if not ok:
        raise HTTPException(status_code=429, detail="Too many position updates. Please slow down.", headers={"Retry-After": str(retry)})
    task, rel = _locked_task(db, user, task_id)
    try:
        tracking.can_start(task.status, rel)
        row = db.query(models.DeliveryLocation).filter(models.DeliveryLocation.task_id == task.id).with_for_update().first()
        if row is None or row.stopped_at is not None:
            raise tracking.TrackingError("invalid_state", "Live sharing is off for this delivery. Start sharing first.")
        if body.delivery_id is not None and body.delivery_id != task.id:
            raise tracking.TrackingError("invalid_input", "This position belongs to a different delivery.")
        sess = _open_session(db, task)
        if sess is None:                                                  # sharing began before sessions existed: adopt it, keeping its consent time
            sess = models.TrackingSession(public_id=str(uuid.uuid4()), task_id=task.id, volunteer_id=task.volunteer_id, status="active",
                                          consent_version="legacy", consented_at=row.consented_at, retain_history=False,
                                          expires_at=tracking.session_expiry(_now()), last_seq=-1)
            db.add(sess)
            db.flush()
        if body.tracking_session_id and body.tracking_session_id != sess.public_id:
            raise tracking.TrackingError("invalid_state", "That sharing session has ended. Start sharing again.")
        now = _now()
        if tracking.session_expired(sess.expires_at, now):
            sess.status, sess.stopped_at, row.stopped_at = "expired", now, now
            _erase_position(row)
            audit.record(db, user, "delivery.tracking_expired", "delivery_task", task.id, {"session": sess.public_id})
            _announce_tracking(db, task, "stopped")
            db.commit()
            raise tracking.TrackingError("invalid_state", "The sharing time limit was reached and sharing has stopped. Start sharing again if you are still delivering.")
        if sess.status == "paused":
            raise tracking.TrackingError("invalid_state", "Sharing is paused. Resume it to continue.")
        lat, lon, acc = tracking.validate_fix(body.latitude, body.longitude, body.accuracy_m)
        heading, speed = tracking.validate_motion(body.heading, body.speed)
        taken = tracking.client_time(body.timestamp, now)
        if not tracking.is_new_sequence(sess.last_seq, body.seq):         # a network retry: acknowledge without storing or broadcasting twice
            return {"recorded_at": _iso(row.recorded_at), "duplicate": True}
        wait = tracking.seconds_to_wait(row.recorded_at, now)
        if wait:
            raise tracking.TrackingError("too_soon", "Positions are accepted every few seconds. Please slow down.", retry_after=wait)
        jump = tracking.is_implausible_jump({"latitude": row.latitude, "longitude": row.longitude, "recorded_at": row.recorded_at}, lat, lon, now)
    except tracking.TrackingError as e:
        _track_error(e)
    row.latitude, row.longitude, row.accuracy_m, row.recorded_at = lat, lon, acc, now      # the SERVER clock decides freshness
    seq = body.seq if body.seq is not None else sess.last_seq + 1
    sess.last_seq, sess.stale_notified_at = seq, None
    if sess.retain_history and tracking.history_enabled():
        db.add(models.LocationHistory(session_id=sess.id, task_id=task.id, seq=seq, latitude=lat, longitude=lon, accuracy_m=acc,
                                      heading=heading, speed_mps=speed, client_time=taken, recorded_at=now, flagged=jump))
    if jump:
        audit.record(db, user, "delivery.location_jump", "delivery_task", task.id, {"session": sess.public_id})
        if ratelimit.limiter.hit(f"jump:{sess.id}", 1, 600)[0]:           # at most one admin alert per session per 10 minutes
            live.publish_after_commit(db, "risk.alert", {"task_id": task.id, "kind": "location_jump", "severity": "medium"}, live.audience(roles=["admin"]))
    elif task.status in tracking.VIEWER_STATUSES:
        shown = tracking.present({"latitude": lat, "longitude": lon, "accuracy_m": acc, "recorded_at": now}, now, {"org_owner"})   # rounded for viewers
        live.publish_after_commit(db, "delivery.location",
                                  {"task_id": task.id, "latitude": shown["latitude"], "longitude": shown["longitude"], "accuracy_m": acc,
                                   "recorded_at": _iso(now), "status": task.status}, _viewer_audience(task))
    db.commit()
    return {"recorded_at": _iso(now), "seq": seq}


def _own_open_session(db: Session, user: dict, task_id: int):
    task, rel = _locked_task(db, user, task_id)
    if "assigned_volunteer" not in rel:
        raise HTTPException(status_code=403, detail="Only the volunteer sharing their location can change it")
    return task, _open_session(db, task), db.query(models.DeliveryLocation).filter(models.DeliveryLocation.task_id == task.id).first()


@router.post("/{task_id}/tracking/pause")
def pause_sharing(task_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Pause: viewers stop seeing a position at once (it is erased), and the volunteer can resume without a new consent."""
    task, sess, row = _own_open_session(db, user, task_id)
    if sess is None or row is None or row.stopped_at is not None:
        raise HTTPException(status_code=409, detail="Live sharing is not on for this delivery")
    if sess.status == "active":
        sess.status, sess.paused_at = "paused", _now()
        _erase_position(row)
        audit.record(db, user, "delivery.tracking_paused", "delivery_task", task.id, {"session": sess.public_id})
        _announce_tracking(db, task, "paused")
        db.commit()
    return {"sharing": True, "paused": True}


@router.post("/{task_id}/tracking/resume")
def resume_sharing(task_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    task, sess, row = _own_open_session(db, user, task_id)
    if sess is None or row is None or row.stopped_at is not None:
        raise HTTPException(status_code=409, detail="Live sharing is not on for this delivery")
    if task.status not in tracking.HOLDING_STATUSES:
        raise HTTPException(status_code=409, detail="Live location can only be shared while you are carrying out this delivery.")
    if tracking.session_expired(sess.expires_at, _now()):
        raise HTTPException(status_code=409, detail="The sharing time limit was reached. Start sharing again.")
    if sess.status == "paused":
        sess.status, sess.paused_at = "active", None
        audit.record(db, user, "delivery.tracking_resumed", "delivery_task", task.id, {"session": sess.public_id})
        _announce_tracking(db, task, "resumed")
        db.commit()
    return {"sharing": True, "paused": False}


@router.post("/{task_id}/tracking/stop")
def stop_sharing(task_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    task, sess, row = _own_open_session(db, user, task_id)
    now = _now()
    if sess is not None:
        sess.status, sess.stopped_at = "stopped", now
    if row is not None and row.stopped_at is None:
        row.stopped_at = now
        _erase_position(row)                                              # stopping erases the position immediately
        audit.record(db, user, "delivery.tracking_stopped", "delivery_task", task.id, {"session": sess.public_id if sess else None})
        _announce_tracking(db, task, "stopped")
    db.commit()
    return {"sharing": False}


@router.get("/{task_id}/location")
def get_position(task_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """The latest shared position, if the volunteer is sharing and this person may see it right now."""
    task = _scoped(db, user).filter(models.DeliveryTask.id == task_id).first()
    rel = flow.relations(_view(task), _actor(user)) if task else set()
    if task is None or not rel:
        raise HTTPException(status_code=404, detail="Delivery not found")
    if not tracking.can_view(task.status, rel):
        return {"sharing": False, "has_position": False}
    row = db.query(models.DeliveryLocation).filter(models.DeliveryLocation.task_id == task.id).first()
    if row is None or row.stopped_at is not None:
        return {"sharing": False, "has_position": False}
    sess = _open_session(db, task)
    fix = {"latitude": row.latitude, "longitude": row.longitude, "accuracy_m": row.accuracy_m, "recorded_at": row.recorded_at}
    return {"sharing": True, "paused": bool(sess and sess.status == "paused"), **tracking.present(fix, _now(), rel)}


@router.get("/{task_id}/history")
def location_history(task_id: int, limit: int = Query(500, ge=1, le=2000), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Administrators only: the movement trail of a delivery whose volunteer agreed to keep one. EVERY read is audited."""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrators only")
    task = db.get(models.DeliveryTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    rows = (db.query(models.LocationHistory).filter(models.LocationHistory.task_id == task_id)
            .order_by(models.LocationHistory.recorded_at).limit(limit).all())
    audit.record(db, user, "delivery.history_viewed", "delivery_task", task_id, {"points": len(rows)})
    db.commit()
    return {"task_id": task_id, "retention_days": tracking.retention_days(),
            "points": [{"latitude": r.latitude, "longitude": r.longitude, "accuracy_m": r.accuracy_m, "heading": r.heading,
                        "speed_mps": r.speed_mps, "recorded_at": _iso(r.recorded_at), "flagged": bool(r.flagged)} for r in rows]}
