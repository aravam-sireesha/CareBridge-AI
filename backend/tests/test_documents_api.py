"""/documents through the real API with IN-MEMORY storage (no bucket). Needs FastAPI + SQLAlchemy like the other API tests."""
import base64

import pytest

from app import models
from app.routers import documents as docs_router
from app.services import storage
from test_deliveries_api import _to_transit, env, journey_to  # noqa: F401  (env is a fixture)

VOL, ORG, DONOR, ADMIN = "vol@x.org", "org@x.org", "donor@x.org", "admin@x.org"
OUT_ORG, OUT_VOL = "org2@x.org", "vol2@x.org"
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def store(monkeypatch):
    s = storage.MemoryStorage()
    monkeypatch.setattr(docs_router.storage, "get_storage", lambda env: s)
    return s


def up(client, h, who, owner_type, owner_id, kind, data=PDF, ctype="application/pdf", name="scan.pdf"):
    return client.post("/documents", headers=h(who), json={"owner_type": owner_type, "owner_id": owner_id, "kind": kind, "filename": name, "content_type": ctype, "data_base64": base64.b64encode(data).decode()})


def ids_of(db, email):
    u = db.query(models.User).filter_by(email=email).one()
    return u


def test_everything_needs_a_signed_in_user_and_storage_must_be_configured(env, monkeypatch):
    client, db, h, ids = env
    assert client.post("/documents", json={}).status_code == 401 and client.get("/documents/1/url").status_code == 401
    monkeypatch.delenv("S3_BUCKET", raising=False)
    org = ids_of(db, ORG).organization_id
    assert up(client, h, ORG, "organization", org, "darpan").status_code == 503


def test_an_organization_uploads_and_the_file_is_stored_privately_under_a_random_key(env, store):
    client, db, h, ids = env
    org = ids_of(db, ORG).organization_id
    r = up(client, h, ORG, "organization", org, "darpan", name="../../my darpan.pdf")
    assert r.status_code == 200 and r.json()["review_status"] == "pending" and r.json()["original_name"] == "my darpan.pdf"
    row = db.query(models.StoredDocument).one()
    assert row.object_key in store.objects and "darpan.pdf" not in row.object_key and row.object_key.startswith(f"organization/{org}/darpan/")
    assert "object_key" not in r.text and "sha256" not in r.text                        # storage internals are never returned
    assert db.query(models.AuditLog).filter_by(action="document.uploaded").count() == 1


@pytest.mark.parametrize("data,ctype,name", [(b"MZ not a pdf", "application/pdf", "a.pdf"), (PDF, "image/png", "a.pdf"), (PDF + b"/JavaScript (x)", "application/pdf", "a.pdf"), (b"", "application/pdf", "a.pdf")])
def test_bad_files_are_refused_and_nothing_is_stored(env, store, data, ctype, name):
    client, db, h, ids = env
    r = up(client, h, ORG, "organization", ids_of(db, ORG).organization_id, "darpan", data, ctype, name)
    assert r.status_code == 422 and not store.objects and db.query(models.StoredDocument).count() == 0


def test_oversized_and_garbled_uploads_are_refused(env, store, monkeypatch):
    client, db, h, ids = env
    org = ids_of(db, ORG).organization_id
    monkeypatch.setenv("UPLOAD_MAX_MB", "0.1")
    assert up(client, h, ORG, "organization", org, "darpan", PDF + b"0" * 200_000).status_code == 422
    bad = client.post("/documents", headers=h(ORG), json={"owner_type": "organization", "owner_id": org, "kind": "darpan", "filename": "a.pdf", "content_type": "application/pdf", "data_base64": "***not base64***"})
    assert bad.status_code == 422


def test_nobody_can_upload_for_someone_else_or_with_the_wrong_kind(env, store):
    client, db, h, ids = env
    org, vol = ids_of(db, ORG).organization_id, ids_of(db, VOL).volunteer_id
    assert up(client, h, OUT_ORG, "organization", org, "darpan").status_code == 403           # another organization's record
    assert up(client, h, ORG, "organization", org, "police_verification").status_code == 403
    assert up(client, h, ORG, "volunteer", vol, "id_document").status_code == 403
    assert up(client, h, DONOR, "organization", org, "darpan").status_code == 403
    assert up(client, h, OUT_VOL, "volunteer", vol, "id_document").status_code == 403
    assert not store.objects


def test_a_volunteers_police_document_is_invisible_to_organizations_and_donors_and_only_the_volunteer_and_admin_get_links(env, store):
    client, db, h, ids = env
    vol = ids_of(db, VOL).volunteer_id
    doc_id = up(client, h, VOL, "volunteer", vol, "police_verification").json()["id"]
    for who in (ORG, OUT_ORG, DONOR, OUT_VOL):
        assert client.get(f"/documents/{doc_id}/url", headers=h(who)).status_code == 404, who
        assert client.get("/documents", params={"owner_type": "volunteer", "owner_id": vol}, headers=h(who)).status_code == 404, who
    for who in (VOL, ADMIN):
        assert client.get(f"/documents/{doc_id}/url", headers=h(who)).status_code == 200


def test_every_signed_link_is_short_lived_a_download_and_audited(env, store):
    client, db, h, ids = env
    org = ids_of(db, ORG).organization_id
    doc_id = up(client, h, ORG, "organization", org, "darpan").json()["id"]
    r = client.get(f"/documents/{doc_id}/url", headers=h(ADMIN)).json()
    assert r["expires_in"] == 300 and "expires=300" in r["url"]
    entry = db.query(models.AuditLog).filter_by(action="document.url_issued").one()
    assert str(doc_id) in str(entry.entity_id) or entry.entity_id == doc_id


def test_a_missing_document_and_someone_elses_look_identical(env, store):
    client, db, h, ids = env
    doc_id = up(client, h, ORG, "organization", ids_of(db, ORG).organization_id, "darpan").json()["id"]
    assert client.get(f"/documents/{doc_id}/url", headers=h(OUT_ORG)).status_code == client.get("/documents/99999/url", headers=h(OUT_ORG)).status_code == 404


def test_review_is_admin_only_requires_a_reason_to_reject_and_notifies_the_owner(env, store):
    client, db, h, ids = env
    org = ids_of(db, ORG).organization_id
    doc_id = up(client, h, ORG, "organization", org, "darpan").json()["id"]
    assert client.post(f"/documents/{doc_id}/review", headers=h(ORG), json={"decision": "approved"}).status_code == 403
    assert client.post(f"/documents/{doc_id}/review", headers=h(ADMIN), json={"decision": "rejected"}).status_code == 422
    r = client.post(f"/documents/{doc_id}/review", headers=h(ADMIN), json={"decision": "rejected", "note": "The scan is cut off"})
    assert r.status_code == 200 and r.json()["review_status"] == "rejected" and r.json()["review_note"] == "The scan is cut off"
    assert db.query(models.Notification).filter_by(user_id=ids_of(db, ORG).id, kind="verification").count() == 1
    assert client.post(f"/documents/{doc_id}/review", headers=h(ADMIN), json={"decision": "approved"}).json()["review_status"] == "approved"


def test_approving_a_document_does_not_verify_the_organization(env, store):
    client, db, h, ids = env
    org_id = ids_of(db, ORG).organization_id
    before = db.get(models.Organization, org_id).verification_status
    doc_id = up(client, h, ORG, "organization", org_id, "darpan").json()["id"]
    client.post(f"/documents/{doc_id}/review", headers=h(ADMIN), json={"decision": "approved"})
    db.expire_all()
    assert db.get(models.Organization, org_id).verification_status == before


def test_an_approved_document_cannot_be_deleted_by_its_owner_but_a_pending_one_can(env, store):
    client, db, h, ids = env
    org = ids_of(db, ORG).organization_id
    a = up(client, h, ORG, "organization", org, "darpan").json()["id"]; b = up(client, h, ORG, "organization", org, "cert_12a").json()["id"]
    client.post(f"/documents/{a}/review", headers=h(ADMIN), json={"decision": "approved"})
    assert client.delete(f"/documents/{a}", headers=h(ORG)).status_code == 409
    assert client.delete(f"/documents/{b}", headers=h(ORG)).status_code == 200 and len(store.deleted) == 1
    assert client.get(f"/documents/{b}/url", headers=h(ORG)).status_code == 404                  # a deleted document is gone
    assert client.delete(f"/documents/{a}", headers=h(ADMIN)).status_code == 200


def test_delivery_proof_follows_the_delivery_rules(env, store):
    client, db, h, ids = env
    tid = journey_to(client, h, ids, "accept")
    assert up(client, h, VOL, "delivery", tid, "delivery_proof", PNG, "image/png", "p.png").status_code == 403      # not carrying yet
    tid = _to_transit(client, h, ids)
    ok = up(client, h, VOL, "delivery", tid, "delivery_proof", PNG, "image/png", "p.png")
    assert ok.status_code == 200
    assert up(client, h, OUT_VOL, "delivery", tid, "delivery_proof", PNG, "image/png", "p.png").status_code == 403
    for who in (ORG, VOL, ADMIN):
        assert client.get(f"/documents/{ok.json()['id']}/url", headers=h(who)).status_code == 200
    for who in (DONOR, OUT_ORG, OUT_VOL):
        assert client.get(f"/documents/{ok.json()['id']}/url", headers=h(who)).status_code == 404, who


def test_a_failed_database_write_does_not_leave_the_file_behind(env, store, monkeypatch):
    client, db, h, ids = env
    org = ids_of(db, ORG).organization_id
    monkeypatch.setattr(docs_router.audit, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    with pytest.raises(RuntimeError):
        up(client, h, ORG, "organization", org, "darpan")
    assert not store.objects and len(store.deleted) == 1
