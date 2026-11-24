"""Mobile-number verification at registration, through the API. Run with:  python -m pytest tests/test_phone_verification_api.py -q"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.main import app
from app.services import sms

PW = "StrongPass1234"
PHONE = "+919876543210"
NEW = {"email": "new@x.org", "password": PW, "role": "donor", "name": "Nia", "phone_country_code": "+91", "phone": "98765 43210"}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 40)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SMS_DELIVERY", "outbox")
    monkeypatch.setenv("OTP_RESEND_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("OTP_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("REQUIRE_PHONE_VERIFICATION", "true")
    sms.OUTBOX.clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()

    def override():
        yield db
    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        yield client, db
    app.dependency_overrides.clear(); sms.OUTBOX.clear(); db.close(); engine.dispose()


def login(client, email="new@x.org"):
    return client.post("/auth/login", json={"email": email, "password": PW})


def code():
    return sms.OUTBOX[-1][1]


def request_code(client, email="new@x.org"):
    return client.post("/auth/verify-phone/request", json={"email": email})


def test_config_tells_the_signup_screen_what_to_do(env, monkeypatch):
    client, _ = env
    assert client.get("/auth/phone-verification/config").json() == {"required": True, "can_send_sms": True, "code_length": 6}
    monkeypatch.delenv("SMS_DELIVERY")
    assert client.get("/auth/phone-verification/config").json() == {"required": False, "can_send_sms": False, "code_length": 6}


def test_registration_stores_e164_marks_pending_and_never_returns_the_number(env):
    client, db = env
    res = client.post("/auth/register", json=NEW)
    assert res.status_code == 201 and "phone" not in res.text and "9876543210" not in res.text
    user = db.query(models.User).filter_by(email="new@x.org").one()
    assert user.phone_e164 == PHONE and user.phone_verification_pending is True and user.phone_verified_at is None


def test_a_number_is_required_when_verification_is_on_and_bad_numbers_are_refused(env):
    client, _ = env
    assert client.post("/auth/register", json={k: v for k, v in NEW.items() if k not in ("phone", "phone_country_code")}).status_code == 400
    for bad in ({"phone": "12345"}, {"phone": "98765 4321"}, {"phone": "5987654321"}, {"phone": "call me"}, {"phone_country_code": "", "phone": "9876543210"}):
        assert client.post("/auth/register", json={**NEW, **bad}).status_code == 422, bad


def test_requesting_a_code_does_not_activate_the_account_only_the_right_code_does(env):
    client, db = env
    client.post("/auth/register", json=NEW)
    assert login(client).status_code == 403 and "mobile" in login(client).json()["detail"].lower()
    res = request_code(client)
    assert res.status_code == 200 and len(sms.OUTBOX) == 1 and sms.OUTBOX[0][0] == PHONE
    assert code() not in res.text                                           # the code is never in a response
    assert login(client).status_code == 403                                 # requested, still not active
    assert client.post("/auth/verify-phone/confirm", json={"email": "new@x.org", "code": "000000" if code() != "000000" else "111111"}).status_code == 400
    assert login(client).status_code == 403
    assert client.post("/auth/verify-phone/confirm", json={"email": "new@x.org", "code": code()}).json() == {"verified": True}
    assert login(client).status_code == 200
    user = db.query(models.User).filter_by(email="new@x.org").one()
    assert user.phone_verification_pending is False and user.phone_verified_at is not None


def test_a_code_works_once(env):
    client, _ = env
    client.post("/auth/register", json=NEW); request_code(client)
    c = code()
    assert client.post("/auth/verify-phone/confirm", json={"email": "new@x.org", "code": c}).status_code == 200
    assert client.post("/auth/verify-phone/confirm", json={"email": "new@x.org", "code": c}).status_code == 400


def test_too_many_wrong_codes_burn_the_code(env):
    client, _ = env
    client.post("/auth/register", json=NEW); request_code(client)
    good = code(); wrong = "000000" if good != "000000" else "111111"
    for _ in range(3):
        assert client.post("/auth/verify-phone/confirm", json={"email": "new@x.org", "code": wrong}).status_code == 400
    assert client.post("/auth/verify-phone/confirm", json={"email": "new@x.org", "code": good}).status_code == 400
    assert login(client).status_code == 403


def test_an_expired_code_is_refused(env):
    client, db = env
    client.post("/auth/register", json=NEW); request_code(client)
    challenge = db.query(models.OtpChallenge).one()
    challenge.expires_at = challenge.expires_at - timedelta(hours=1); db.commit()
    assert client.post("/auth/verify-phone/confirm", json={"email": "new@x.org", "code": code()}).status_code == 400


def test_resending_replaces_the_earlier_code(env):
    client, _ = env
    client.post("/auth/register", json=NEW)
    request_code(client); first = code()
    request_code(client); second = code()
    assert len(sms.OUTBOX) == 2
    if first != second:
        assert client.post("/auth/verify-phone/confirm", json={"email": "new@x.org", "code": first}).status_code == 400
    assert client.post("/auth/verify-phone/confirm", json={"email": "new@x.org", "code": second}).status_code == 200


def test_unknown_and_already_verified_accounts_get_the_same_answer_and_no_sms(env):
    client, _ = env
    client.post("/auth/register", json=NEW)
    pending = request_code(client).json()
    sms.OUTBOX.clear()
    assert request_code(client, "nobody@x.org").json() == pending and sms.OUTBOX == []
    request_code(client); client.post("/auth/verify-phone/confirm", json={"email": "new@x.org", "code": code()})
    sms.OUTBOX.clear()
    assert request_code(client).json() == pending and sms.OUTBOX == []


def test_duplicate_numbers_and_duplicate_emails_cannot_register_twice(env):
    client, _ = env
    assert client.post("/auth/register", json=NEW).status_code == 201
    assert client.post("/auth/register", json={**NEW, "email": "other@x.org"}).status_code == 409        # same number
    assert client.post("/auth/register", json={**NEW, "phone": "98765 43211"}).status_code == 409        # same e-mail
    assert client.post("/auth/register", json={**NEW, "email": "third@x.org", "phone": "98765 43211"}).status_code == 201


def test_when_not_required_a_number_is_optional_and_nobody_is_blocked(env, monkeypatch):
    client, db = env
    monkeypatch.setenv("REQUIRE_PHONE_VERIFICATION", "false")
    assert client.post("/auth/register", json=NEW).status_code == 201
    assert login(client).status_code == 200
    assert db.query(models.User).filter_by(email="new@x.org").one().phone_verification_pending is None
    assert client.post("/auth/register", json={k: v for k, v in NEW.items() if k not in ("phone", "phone_country_code")} | {"email": "b@x.org"}).status_code == 201


def test_if_sms_cannot_be_delivered_verification_is_ignored_so_nobody_is_locked_out(env, monkeypatch):
    client, _ = env
    monkeypatch.delenv("SMS_DELIVERY")
    assert client.post("/auth/register", json=NEW).status_code == 201
    assert login(client).status_code == 200
    assert request_code(client).json()["delivery"] == "not_configured"
