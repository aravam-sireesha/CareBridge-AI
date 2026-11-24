"""Registration e-mail verification through the API. Run with:  python -m pytest tests/test_email_verification_api.py -q"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.services import otp

PW = "StrongPass1234"
NEW = {"email": "new@x.org", "password": PW, "role": "donor", "name": "Nia"}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 40)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("OTP_DELIVERY", "outbox")
    monkeypatch.setenv("OTP_RESEND_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("OTP_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("REQUIRE_EMAIL_VERIFICATION", "true")
    otp.OUTBOX.clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    db.add_all([models.User(email="old@x.org", hashed_password=hash_password(PW), role="donor"),
                models.User(email="admin@x.org", hashed_password=hash_password(PW), role="admin")])
    db.commit()

    def override():
        yield db
    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        yield client, db
    app.dependency_overrides.clear(); otp.OUTBOX.clear(); db.close(); engine.dispose()


def login(client, email, pw=PW):
    return client.post("/auth/login", json={"email": email, "password": pw})


def code():
    return otp.OUTBOX[-1][1]


def test_the_config_tells_the_signup_screen_what_to_do(env, monkeypatch):
    client, _ = env
    assert client.get("/auth/verification/config").json()["required"] is True
    monkeypatch.delenv("OTP_DELIVERY")
    assert client.get("/auth/verification/config").json() == {"required": False, "can_send_email": False, "code_length": 6}   # cannot deliver: not required


def test_a_new_account_cannot_sign_in_until_it_verifies_but_a_wrong_password_still_says_the_same_thing_as_ever(env):
    client, db = env
    assert client.post("/auth/register", json=NEW).status_code == 201
    assert db.query(models.User).filter_by(email="new@x.org").one().email_verification_pending is True
    blocked = login(client, "new@x.org")
    assert blocked.status_code == 403 and "verify your email address" in blocked.json()["detail"]
    assert login(client, "new@x.org", "WrongPass9999!").status_code == 401           # without the password nothing is revealed about verification


def test_the_full_flow_request_confirm_then_sign_in(env):
    client, db = env
    client.post("/auth/register", json=NEW)
    res = client.post("/auth/verify-email/request", json={"email": "new@x.org"})
    assert res.status_code == 200 and code() not in res.text and len(otp.OUTBOX) == 1
    assert client.post("/auth/verify-email/confirm", json={"email": "new@x.org", "code": code()}).json() == {"verified": True}
    user = db.query(models.User).filter_by(email="new@x.org").one()
    assert user.email_verification_pending is False and user.email_verified_at is not None
    assert login(client, "new@x.org").status_code == 200


def test_the_code_works_once_and_expires_and_locks_after_wrong_guesses(env):
    client, db = env
    client.post("/auth/register", json=NEW); client.post("/auth/verify-email/request", json={"email": "new@x.org"})
    good = code(); bad = "000000" if good != "000000" else "111111"
    for _ in range(3):
        assert client.post("/auth/verify-email/confirm", json={"email": "new@x.org", "code": bad}).status_code == 400
    assert client.post("/auth/verify-email/confirm", json={"email": "new@x.org", "code": good}).status_code == 400      # burned by the guesses
    assert login(client, "new@x.org").status_code == 403
    client.post("/auth/verify-email/request", json={"email": "new@x.org"})                                             # a new code can be asked for
    assert client.post("/auth/verify-email/confirm", json={"email": "new@x.org", "code": code()}).status_code == 200
    assert client.post("/auth/verify-email/confirm", json={"email": "new@x.org", "code": code()}).status_code == 400    # replay refused


def test_existing_accounts_are_never_affected_and_get_no_codes(env):
    client, db = env
    assert login(client, "old@x.org").status_code == 200
    assert login(client, "admin@x.org").status_code == 200
    res = client.post("/auth/verify-email/request", json={"email": "old@x.org"})
    assert res.status_code == 200 and otp.OUTBOX == []                              # not pending: no code is sent
    assert client.post("/auth/verify-email/confirm", json={"email": "old@x.org", "code": "123456"}).status_code == 400


def test_unknown_and_verified_accounts_get_the_same_generic_answer(env):
    client, _ = env
    client.post("/auth/register", json=NEW)
    known = client.post("/auth/verify-email/request", json={"email": "new@x.org"}).json()
    for email in ("nobody@x.org", "old@x.org"):
        assert client.post("/auth/verify-email/request", json={"email": email}).json() == known


def test_nothing_changes_when_verification_is_switched_off(env, monkeypatch):
    client, db = env
    monkeypatch.setenv("REQUIRE_EMAIL_VERIFICATION", "false")
    client.post("/auth/register", json=NEW)
    assert db.query(models.User).filter_by(email="new@x.org").one().email_verification_pending is None
    assert login(client, "new@x.org").status_code == 200


def test_an_administrator_can_let_someone_in_when_e_mail_cannot_be_sent_and_it_is_recorded_honestly(env):
    client, db = env
    client.post("/auth/register", json=NEW)
    admin = {"Authorization": "Bearer " + login(client, "admin@x.org").json()["access_token"]}
    uid = db.query(models.User).filter_by(email="new@x.org").one().id
    assert client.post(f"/auth/verify-email/admin/{uid}", headers={"Authorization": "Bearer nope"}).status_code == 401
    res = client.post(f"/auth/verify-email/admin/{uid}", headers=admin)
    assert res.status_code == 200 and "not verified" in res.json()["note"]
    user = db.query(models.User).filter_by(id=uid).one()
    assert user.email_verification_pending is False and user.email_verified_at is None             # the ADDRESS was not verified
    assert login(client, "new@x.org").status_code == 200
    assert db.query(models.AuditLog).filter_by(action="auth.email_verification_waived_by_admin").count() == 1


def test_only_administrators_can_waive_verification(env):
    client, db = env
    client.post("/auth/register", json=NEW); client.post("/auth/register", json={**NEW, "email": "second@x.org"})
    uid = db.query(models.User).filter_by(email="second@x.org").one().id
    donor = {"Authorization": "Bearer " + login(client, "old@x.org").json()["access_token"]}
    assert client.post(f"/auth/verify-email/admin/{uid}", headers=donor).status_code == 403


def test_codes_are_never_returned_or_logged_and_the_audit_trail_has_no_secrets(env, caplog):
    import logging
    client, db = env
    caplog.set_level(logging.DEBUG)
    client.post("/auth/register", json=NEW)
    r = client.post("/auth/verify-email/request", json={"email": "new@x.org"}); c = code()
    client.post("/auth/verify-email/confirm", json={"email": "new@x.org", "code": c})
    assert c not in r.text and c not in caplog.text and c not in repr([a.detail for a in db.query(models.AuditLog).all()])
    assert {"otp.sent", "auth.email_verified"} <= {a.action for a in db.query(models.AuditLog).all()}
