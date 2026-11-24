"""Who may upload/read/delete which document. Every role against every owner type."""
import itertools

import pytest

from app.services import document_access as acc

ADMIN = {"id": 1, "role": "admin"}
ORG_A = {"id": 2, "role": "organization", "organization_id": 10}
ORG_B = {"id": 3, "role": "organization", "organization_id": 11}
VOL_A = {"id": 4, "role": "volunteer", "volunteer_id": 20}
VOL_B = {"id": 5, "role": "volunteer", "volunteer_id": 21}
DONOR = {"id": 6, "role": "donor", "donor_id": 30}
NOBODY = {"id": 7, "role": "organization", "organization_id": None}
TASK = {"id": 50, "org_id": 10, "volunteer_id": 20, "status": "in_transit"}


# ---------------------------------------------------------------- reading
def test_organizations_read_only_their_own_documents():
    assert acc.read_allowed(ORG_A, "organization", 10) and not acc.read_allowed(ORG_B, "organization", 10)


def test_volunteers_read_only_their_own_documents():
    assert acc.read_allowed(VOL_A, "volunteer", 20) and not acc.read_allowed(VOL_B, "volunteer", 20)


@pytest.mark.parametrize("who", [ORG_A, ORG_B, DONOR, NOBODY])
def test_a_volunteers_identity_and_police_documents_are_never_readable_by_organizations_donors_or_strangers(who):
    assert not acc.read_allowed(who, "volunteer", 20)


def test_a_volunteer_cannot_read_an_organizations_documents_nor_the_reverse():
    assert not acc.read_allowed(VOL_A, "organization", 10) and not acc.read_allowed(ORG_A, "volunteer", 20)


def test_delivery_proof_is_visible_to_the_receiving_organization_the_assigned_volunteer_and_admins_only():
    assert acc.read_allowed(ORG_A, "delivery", 50, TASK) and acc.read_allowed(VOL_A, "delivery", 50, TASK) and acc.read_allowed(ADMIN, "delivery", 50, TASK)
    assert not acc.read_allowed(ORG_B, "delivery", 50, TASK) and not acc.read_allowed(VOL_B, "delivery", 50, TASK)
    assert not acc.read_allowed(DONOR, "delivery", 50, TASK)                           # photos may show people: donors do not get them
    assert not acc.read_allowed(ORG_A, "delivery", 50, None)                           # no such delivery


def test_donors_read_nothing_and_admins_read_everything():
    for ot in ("organization", "volunteer", "delivery"):
        assert not acc.read_allowed(DONOR, ot, 10, TASK) and acc.read_allowed(ADMIN, ot, 10, TASK)


def test_an_account_without_an_organization_does_not_match_a_document_without_one():
    assert not acc.read_allowed(NOBODY, "organization", None) and not acc.read_allowed({"role": "volunteer"}, "volunteer", None)


# ---------------------------------------------------------------- uploading
def test_an_organization_uploads_its_own_registration_documents_only():
    assert acc.upload_allowed(ORG_A, "organization", 10, "darpan")
    assert not acc.upload_allowed(ORG_A, "organization", 11, "darpan")                 # another organization's record
    assert not acc.upload_allowed(ORG_A, "organization", 10, "police_verification")    # a volunteer-only kind
    assert not acc.upload_allowed(ORG_A, "volunteer", 20, "id_document")


def test_a_volunteer_uploads_their_own_identity_documents_only():
    for kind in ("id_document", "police_verification", "code_of_conduct"):
        assert acc.upload_allowed(VOL_A, "volunteer", 20, kind) and not acc.upload_allowed(VOL_B, "volunteer", 20, kind)
    assert not acc.upload_allowed(VOL_A, "volunteer", 20, "darpan")


@pytest.mark.parametrize("status,ok", [("accepted", False), ("pickup_scheduled", False), ("picked_up", True), ("in_transit", True), ("delivered", True), ("receipt_confirmed", False), ("cancelled", False)])
def test_delivery_proof_only_once_the_volunteer_holds_the_items(status, ok):
    assert acc.upload_allowed(VOL_A, "delivery", 50, "delivery_proof", {**TASK, "status": status}) is ok


def test_only_the_assigned_volunteer_can_add_delivery_proof():
    assert not acc.upload_allowed(VOL_B, "delivery", 50, "delivery_proof", TASK)
    assert not acc.upload_allowed(ORG_A, "delivery", 50, "delivery_proof", TASK) and not acc.upload_allowed(DONOR, "delivery", 50, "delivery_proof", TASK)
    assert not acc.upload_allowed(VOL_A, "delivery", 50, "delivery_proof", None)


def test_donors_upload_nothing_and_unknown_kinds_are_refused_for_everyone():
    for ot, kinds in (("organization", ["darpan"]), ("volunteer", ["id_document"]), ("delivery", ["delivery_proof"])):
        for k in kinds:
            assert not acc.upload_allowed(DONOR, ot, 10, k, TASK)
    for who in (ADMIN, ORG_A, VOL_A):
        assert not acc.upload_allowed(who, "organization", 10, "../../etc/passwd") and not acc.upload_allowed(who, "organization", 10, "")


def test_an_administrator_can_attach_to_organizations_and_volunteers_but_delivery_proof_needs_a_real_delivery():
    assert acc.upload_allowed(ADMIN, "organization", 10, "supporting") and acc.upload_allowed(ADMIN, "volunteer", 20, "supporting")
    assert acc.upload_allowed(ADMIN, "delivery", 50, "delivery_proof", TASK) and not acc.upload_allowed(ADMIN, "delivery", 50, "delivery_proof", None)


# ---------------------------------------------------------------- deleting
def doc(**kw):
    return {"owner_type": "organization", "owner_id": 10, "uploaded_by": 2, "review_status": "pending", **kw}


def test_the_uploader_can_delete_until_the_document_is_approved():
    assert acc.delete_allowed(ORG_A, doc()) and acc.delete_allowed(ORG_A, doc(review_status="rejected"))
    assert not acc.delete_allowed(ORG_A, doc(review_status="approved"))
    assert acc.delete_allowed(ADMIN, doc(review_status="approved"))                    # an administrator can always remove


def test_nobody_else_can_delete_it():
    assert not acc.delete_allowed(ORG_B, doc()) and not acc.delete_allowed(DONOR, doc())
    assert not acc.delete_allowed({**ORG_A, "id": 99}, doc())                          # same organization, but not the uploader


def test_a_user_who_lost_access_cannot_delete_their_old_upload():
    assert not acc.delete_allowed({"id": 2, "role": "organization", "organization_id": 55}, doc())


def test_the_full_role_by_owner_matrix_never_lets_a_donor_through():
    for who, (ot, task) in itertools.product([DONOR], [("organization", None), ("volunteer", None), ("delivery", TASK)]):
        assert not acc.read_allowed(who, ot, 10, task) and not acc.delete_allowed(who, doc(owner_type=ot), task)
