"""Delivery state machine: pure Python, no database. Run with:  python -m pytest tests/test_delivery_flow.py -q"""
from datetime import datetime, timedelta, timezone

from app.services import delivery_flow as f
from app.services.delivery_flow import Actor, FlowError, TaskView

NOW = datetime(2026, 10, 25, 12, 0, 0)
ORG, DONOR, VOL = Actor("organization", 10, org_id=1), Actor("donor", 11, donor_id=5), Actor("volunteer", 12, volunteer_id=9)
ADMIN = Actor("admin", 1)
OTHER_ORG, OTHER_DONOR, OTHER_VOL = Actor("organization", 20, org_id=2), Actor("donor", 21, donor_id=6), Actor("volunteer", 22, volunteer_id=8)


def task(status, volunteer=9, qty=10, exception_from=None):
    return TaskView(status, org_id=1, donor_id=5, volunteer_id=volunteer, quantity=qty, exception_from=exception_from)


def run(status, action, actor, payload=None, **kw):
    return f.apply(task(status, **{k: v for k, v in kw.items() if k in ("volunteer", "qty", "exception_from")}), action, actor, payload, NOW, kw.get("approval", True))


def refused(status, action, actor, payload=None, code=None, **kw):
    try:
        run(status, action, actor, payload, **kw)
    except FlowError as e:
        assert code is None or e.code == code, (e.code, e.message)
        return e
    raise AssertionError(f"{action} by {actor.role} in {status} should have been refused")


# ------------------------------------------------------------------ the whole journey
def test_the_full_happy_path_in_order():
    t = task(f.PROPOSED, volunteer=None)
    steps = [("submit", ORG, None, f.AWAITING_APPROVAL), ("approve", ADMIN, None, f.APPROVED), ("commit", DONOR, None, f.COMMITTED),
             ("offer", ORG, {"volunteer_id": 9}, f.OFFERED), ("accept", VOL, None, f.ACCEPTED),
             ("schedule_pickup", VOL, {"pickup_at": NOW + timedelta(days=1)}, f.PICKUP_SCHEDULED), ("pick_up", VOL, None, f.PICKED_UP),
             ("start_transit", VOL, None, f.IN_TRANSIT), ("deliver", VOL, {"note": "Left with the matron, signed"}, f.DELIVERED),
             ("confirm_receipt", ORG, {"received_quantity": 10}, f.RECEIPT_CONFIRMED)]
    for action, actor, payload, expected in steps:
        res = f.apply(t, action, actor, payload, NOW)
        assert res.status == expected, action
        vol = res.updates.get("volunteer_id", t.volunteer_id) if "volunteer_id" in res.updates else (9 if expected not in (f.COMMITTED, f.PROPOSED, f.AWAITING_APPROVAL, f.APPROVED) else None)
        t = TaskView(res.status, 1, 5, 9 if action in ("offer",) or t.volunteer_id == 9 or expected in f.IN_MOTION | {f.OFFERED} else None, 10)
    assert t.status == f.RECEIPT_CONFIRMED


# ------------------------------------------------------------------ consent
def test_a_volunteer_is_only_offered_a_task_never_assigned_and_must_accept():
    offered = run(f.COMMITTED, "offer", ORG, {"volunteer_id": 9}, volunteer=None)
    assert offered.status == f.OFFERED and "accepted_at" not in offered.updates
    refused(f.OFFERED, "pick_up", VOL, code="invalid_state")                       # cannot skip acceptance
    refused(f.OFFERED, "accept", OTHER_VOL, code="forbidden")                      # only the offered volunteer
    refused(f.OFFERED, "accept", ORG, code="forbidden")                            # an organization cannot accept for them
    refused(f.OFFERED, "accept", ADMIN, code="forbidden")                          # nor an administrator


def test_declining_or_stepping_back_releases_the_volunteer_without_cancelling_the_delivery():
    for status, action, payload in [(f.OFFERED, "decline", None), (f.ACCEPTED, "withdraw", {"reason": "Car broke down"}), (f.PICKUP_SCHEDULED, "withdraw", {"reason": "Ill"})]:
        res = run(status, action, VOL, payload)
        assert res.status == f.COMMITTED and res.updates["volunteer_id"] is None
        assert "org" in res.notify
    refused(f.PICKED_UP, "withdraw", VOL, {"reason": "x y z"}, code="invalid_state")      # once items are collected, use "report a problem"


def test_a_donation_is_only_a_commitment_after_the_donor_commits():
    refused(f.APPROVED, "offer", ORG, {"volunteer_id": 9}, code="invalid_state")           # cannot offer before the donor commits
    refused(f.APPROVED, "commit", OTHER_DONOR, code="forbidden")
    refused(f.APPROVED, "commit", ORG, code="forbidden")
    assert run(f.APPROVED, "commit", DONOR).status == f.COMMITTED


# ------------------------------------------------------------------ approval
def test_unapproved_deliveries_cannot_move_forward():
    for status in (f.PROPOSED, f.AWAITING_APPROVAL):
        refused(status, "commit", DONOR, code="invalid_state")
    refused(f.AWAITING_APPROVAL, "approve", ORG, code="forbidden")                         # the organization cannot approve its own delivery
    refused(f.AWAITING_APPROVAL, "approve", DONOR, code="forbidden")


def test_rejecting_and_asking_for_clarification_need_a_recorded_reason():
    for action in ("reject", "request_clarification"):
        refused(f.AWAITING_APPROVAL, action, ADMIN, {}, code="invalid_input")
        refused(f.AWAITING_APPROVAL, action, ADMIN, {"reason": "  "}, code="invalid_input")
    r = run(f.AWAITING_APPROVAL, "reject", ADMIN, {"reason": "Quantity looks too high"})
    assert r.status == f.REJECTED and r.updates["decision_reason"] == "Quantity looks too high"
    c = run(f.AWAITING_APPROVAL, "request_clarification", ADMIN, {"reason": "Which children is this for?"})
    assert c.status == f.PROPOSED                                                          # back to the organization to fix and resubmit


def test_approval_can_be_switched_off_by_policy_without_a_bottleneck():
    res = run(f.PROPOSED, "submit", ORG, approval=False)
    assert res.status == f.APPROVED and "admins" not in res.notify
    assert run(f.PROPOSED, "submit", ORG).status == f.AWAITING_APPROVAL


def test_only_the_owning_organization_can_submit():
    refused(f.PROPOSED, "submit", OTHER_ORG, code="forbidden")
    refused(f.PROPOSED, "submit", ADMIN, code="forbidden")


# ------------------------------------------------------------------ pickup and delivery
def test_pickup_time_validation():
    refused(f.ACCEPTED, "schedule_pickup", VOL, {}, code="invalid_input")
    refused(f.ACCEPTED, "schedule_pickup", VOL, {"pickup_at": "not a date"}, code="invalid_input")
    refused(f.ACCEPTED, "schedule_pickup", VOL, {"pickup_at": NOW - timedelta(days=1)}, code="invalid_input")
    refused(f.ACCEPTED, "schedule_pickup", VOL, {"pickup_at": NOW + timedelta(days=200)}, code="invalid_input")
    ok = run(f.ACCEPTED, "schedule_pickup", VOL, {"pickup_at": (NOW + timedelta(hours=3)).isoformat()})
    assert ok.status == f.PICKUP_SCHEDULED and ok.updates["pickup_at"] == NOW + timedelta(hours=3)
    aware = (datetime(2026, 10, 26, 6, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))).isoformat()
    assert run(f.ACCEPTED, "schedule_pickup", VOL, {"pickup_at": aware}).updates["pickup_at"] == datetime(2026, 10, 26, 0, 30)   # stored as UTC
    assert run(f.PICKUP_SCHEDULED, "schedule_pickup", DONOR, {"pickup_at": NOW + timedelta(days=2)}).status == f.PICKUP_SCHEDULED   # rescheduling by the donor


def test_milestones_set_their_own_timestamps_and_cannot_be_skipped():
    assert run(f.PICKUP_SCHEDULED, "pick_up", VOL).updates["picked_up_at"] == NOW
    assert run(f.PICKED_UP, "start_transit", VOL).updates["in_transit_at"] == NOW
    refused(f.PICKUP_SCHEDULED, "deliver", VOL, {"note": "done"}, code="invalid_state")
    refused(f.ACCEPTED, "pick_up", VOL, code="invalid_state")                              # a pickup must be scheduled first
    refused(f.PICKUP_SCHEDULED, "pick_up", OTHER_VOL, code="forbidden")


def test_delivery_requires_proof_and_only_the_assigned_volunteer_can_record_it():
    refused(f.IN_TRANSIT, "deliver", VOL, {}, code="invalid_input")
    refused(f.IN_TRANSIT, "deliver", VOL, {"note": "ok"}, code="invalid_input")           # too short to be proof
    refused(f.IN_TRANSIT, "deliver", ORG, {"note": "we got it"}, code="forbidden")
    res = run(f.IN_TRANSIT, "deliver", VOL, {"note": "Handed to the warden"})
    assert res.status == f.DELIVERED and res.updates["delivery_note"] == "Handed to the warden"


# ------------------------------------------------------------------ receipt
def test_only_the_receiving_organization_confirms_receipt_and_only_after_delivery():
    for who in (VOL, DONOR, ADMIN, OTHER_ORG):
        refused(f.DELIVERED, "confirm_receipt", who, {"received_quantity": 10}, code="forbidden")
    refused(f.IN_TRANSIT, "confirm_receipt", ORG, {"received_quantity": 10}, code="invalid_state")


def test_receipt_records_the_quantity_actually_received():
    res = run(f.DELIVERED, "confirm_receipt", ORG, {"received_quantity": 10})
    assert res.status == f.RECEIPT_CONFIRMED and res.updates["received_quantity"] == 10 and "admins" not in res.notify
    for bad in ({}, {"received_quantity": -1}, {"received_quantity": "ten"}, {"received_quantity": 2.5}, {"received_quantity": True}):
        refused(f.DELIVERED, "confirm_receipt", ORG, bad, code="invalid_input")


def test_a_quantity_mismatch_needs_an_explanation_and_alerts_administrators():
    refused(f.DELIVERED, "confirm_receipt", ORG, {"received_quantity": 7}, code="invalid_input")
    res = run(f.DELIVERED, "confirm_receipt", ORG, {"received_quantity": 7, "note": "Three boxes were damaged"})
    assert res.updates["received_quantity"] == 7 and "admins" in res.notify
    assert run(f.DELIVERED, "confirm_receipt", ORG, {"received_quantity": 0, "note": "Nothing arrived"}).updates["received_quantity"] == 0


# ------------------------------------------------------------------ exceptions and cancellation
def test_problems_can_be_reported_by_the_parties_during_the_delivery_but_not_by_outsiders():
    for status in (f.ACCEPTED, f.PICKUP_SCHEDULED, f.PICKED_UP, f.IN_TRANSIT, f.DELIVERED):
        for who in (VOL, ORG, DONOR):
            res = run(status, "raise_exception", who, {"reason": "Items damaged"})
            assert res.status == f.EXCEPTION and res.updates["exception_from"] == status and "admins" in res.notify
    refused(f.IN_TRANSIT, "raise_exception", OTHER_VOL, {"reason": "x y z"}, code="forbidden")
    refused(f.IN_TRANSIT, "raise_exception", VOL, {}, code="invalid_input")
    refused(f.COMMITTED, "raise_exception", ORG, {"reason": "something"}, code="invalid_state")      # nothing to report before a volunteer is involved


def test_only_an_administrator_resolves_an_exception_and_the_options_are_safe():
    refused(f.EXCEPTION, "resolve_exception", ORG, {"resolution": "cancel"}, code="forbidden")
    refused(f.EXCEPTION, "resolve_exception", ADMIN, {"resolution": "delete"}, code="invalid_input")
    assert run(f.EXCEPTION, "resolve_exception", ADMIN, {"resolution": "cancel", "note": "Donor withdrew"}, exception_from=f.ACCEPTED).status == f.CANCELLED
    assert run(f.EXCEPTION, "resolve_exception", ADMIN, {"resolution": "resume"}, exception_from=f.IN_TRANSIT).status == f.IN_TRANSIT
    again = run(f.EXCEPTION, "resolve_exception", ADMIN, {"resolution": "reoffer"}, exception_from=f.PICKUP_SCHEDULED)
    assert again.status == f.COMMITTED and again.updates["volunteer_id"] is None
    refused(f.EXCEPTION, "resolve_exception", ADMIN, {"resolution": "reoffer"}, exception_from=f.IN_TRANSIT, code="invalid_state")   # goods already collected


def test_cancellation_needs_a_reason_and_is_not_possible_once_goods_are_collected():
    refused(f.COMMITTED, "cancel", ORG, {}, code="invalid_input")
    for who in (ORG, DONOR, ADMIN):
        assert run(f.COMMITTED, "cancel", who, {"reason": "No longer needed"}).status == f.CANCELLED
    refused(f.COMMITTED, "cancel", VOL, {"reason": "can't make it"}, code="forbidden")        # a volunteer steps back instead
    refused(f.COMMITTED, "cancel", OTHER_ORG, {"reason": "x y z"}, code="forbidden")
    for status in (f.PICKED_UP, f.IN_TRANSIT, f.DELIVERED):
        refused(status, "cancel", ORG, {"reason": "changed my mind"}, code="invalid_state")


def test_terminal_deliveries_accept_no_actions():
    for status in f.TERMINAL:
        for who in (ORG, DONOR, VOL, ADMIN):
            assert f.allowed_actions(task(status), who) == []


# ------------------------------------------------------------------ what the UI offers
def test_allowed_actions_match_what_apply_accepts_for_every_state_and_person():
    people = [ORG, DONOR, VOL, ADMIN, OTHER_ORG, OTHER_DONOR, OTHER_VOL]
    payloads = {"reason": "A good reason", "volunteer_id": 9, "pickup_at": NOW + timedelta(days=1), "note": "Delivered safely", "received_quantity": 10, "resolution": "cancel"}
    for status in f.STATUSES:
        for who in people:
            t = task(status, exception_from=f.ACCEPTED)
            offered = {a["action"] for a in f.allowed_actions(t, who)}
            for action in f.RULES:
                try:
                    f.apply(t, action, who, payloads, NOW); ok = True
                except FlowError as e:
                    assert e.code != "invalid_input" or action in offered, (status, who.role, action, e.message)
                    ok = e.code == "invalid_input"
                assert (action in offered) == ok or (not ok and action not in offered), (status, who.role, action)


def test_strangers_are_offered_nothing_at_any_stage():
    for status in f.STATUSES:
        for who in (OTHER_ORG, OTHER_DONOR, OTHER_VOL):
            assert f.allowed_actions(task(status), who) == [], (status, who.role)


# ------------------------------------------------------------------ quantities
def test_remaining_quantity_ignores_rejected_and_cancelled_and_counts_receipts_once():
    tasks = [(f.APPROVED, 30, None), (f.CANCELLED, 50, None), (f.REJECTED, 40, None), (f.RECEIPT_CONFIRMED, 20, 15), (f.DELIVERED, 10, None)]
    assert f.reserved_quantity(tasks) == 30 + 15 + 10
    assert f.remaining_for_need(100, tasks) == 45 and f.remaining_for_need(40, tasks) == 0


def test_a_delivery_cannot_exceed_what_the_need_still_requires():
    others = [(f.COMMITTED, 60, None)]
    f.check_quantity(40, 100, others)
    for q in (41, 0, -3, True, "5", 2.5):
        try:
            f.check_quantity(q, 100, others)
        except FlowError as e:
            assert e.code == "invalid_input"
        else:
            raise AssertionError(q)
    try:
        f.check_quantity(1, 100, [(f.IN_TRANSIT, 100, None)])
    except FlowError as e:
        assert "fully covered" in e.message
    else:
        raise AssertionError("over-allocation allowed")


def test_a_cancelled_delivery_frees_its_quantity_again():
    assert f.remaining_for_need(50, [(f.COMMITTED, 50, None)]) == 0
    assert f.remaining_for_need(50, [(f.CANCELLED, 50, None)]) == 50


# ------------------------------------------------------------------ privacy
def test_addresses_are_hidden_from_a_volunteer_until_they_accept():
    for status in (f.OFFERED, f.COMMITTED):
        assert f.can_see_addresses(task(status), VOL) == {"pickup": False, "delivery": False}
    for status in (f.ACCEPTED, f.IN_TRANSIT, f.DELIVERED):
        assert f.can_see_addresses(task(status), VOL) == {"pickup": True, "delivery": True}
    for status in (f.RECEIPT_CONFIRMED, f.CANCELLED):                                     # no lingering access after the job
        assert f.can_see_addresses(task(status), VOL) == {"pickup": False, "delivery": False}


def test_other_parties_see_only_what_their_role_needs():
    assert f.can_see_addresses(task(f.COMMITTED), ORG) == {"pickup": False, "delivery": True}
    assert f.can_see_addresses(task(f.COMMITTED), DONOR) == {"pickup": True, "delivery": True}
    assert f.can_see_addresses(task(f.ACCEPTED), OTHER_VOL) == {"pickup": False, "delivery": False}
    assert f.can_see_addresses(task(f.ACCEPTED), OTHER_ORG) == {"pickup": False, "delivery": False}


# ------------------------------------------------------------------ reporting
def test_summary_puts_every_task_in_exactly_one_bucket_and_counts_receipts_by_what_was_received():
    rows = [(f.PROPOSED, 5, None), (f.APPROVED, 5, None), (f.COMMITTED, 10, None), (f.OFFERED, 10, None), (f.ACCEPTED, 4, None),
            (f.IN_TRANSIT, 6, None), (f.DELIVERED, 8, None), (f.RECEIPT_CONFIRMED, 20, 17), (f.CANCELLED, 99, None), (f.REJECTED, 99, None), (f.EXCEPTION, 7, None)]
    s = f.summarize(rows)
    assert s["quantities"] == {"planned": 10, "committed": 20, "in_progress": 10, "delivered": 8, "confirmed": 17}
    assert s["counts"] == {"total": 11, "open_exceptions": 1, "cancelled": 1, "rejected": 1, "confirmed": 1}
    assert f.summarize([])["quantities"]["confirmed"] == 0


def test_a_partial_or_zero_receipt_never_inflates_the_confirmed_total():
    assert f.summarize([(f.RECEIPT_CONFIRMED, 50, 30)])["quantities"]["confirmed"] == 30
    assert f.summarize([(f.RECEIPT_CONFIRMED, 50, 0)])["quantities"]["confirmed"] == 0


def test_approval_policy_switch():
    assert f.approval_required({}) is True
    for off in ("false", "0", "NO", "off"):
        assert f.approval_required({"DELIVERY_APPROVAL_REQUIRED": off}) is False
    assert f.approval_required({"DELIVERY_APPROVAL_REQUIRED": "true"}) is True
