"""Account-recovery codes end to end. Uses the in-memory dev outbox, so no e-mail server is needed.
Run with:  python -m pytest tests/test_otp_api.py -q"""
import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.routers.otp import _now
from app.services import otp

OLD, NEW = "StrongPass1234", "N3w-Strong-Pass-9921"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 40)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("OTP_DELIVERY", "outbox")
    monkeypatch.setenv("OTP_RESEND_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("OTP_MAX_ATTEMPTS", "3")
    otp.OUTBOX.clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    db.add_all([models.User(email="dana@x.org", hashed_password=hash_password(OLD), role="donor"),
                models.User(email="gone@x.org", hashed_password=hash_password(OLD), role="donor", is_active=False)])
    db.commit()

    def override():
        yield db
    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        yield client, db
    app.dependency_overrides.clear(); otp.OUTBOX.clear(); db.close(); engine.dispose()


def _ask(client, email="dana@x.org"):
    return client.post("/auth/otp/request", json={"email": email})


def _code():
    return otp.OUTBOX[-1][1]


def test_a_known_account_gets_a_code_and_the_response_never_contains_it(env):
    client, _ = env
    res = _ask(client)
    assert res.status_code == 200 and len(otp.OUTBOX) == 1
    assert _code() not in res.text and res.json()["delivery"] == "requested"


def test_unknown_and_inactive_accounts_get_an_identical_answer_and_no_code(env):
    client, _ = env
    known = _ask(client).json()
    for email in ("nobody@x.org", "gone@x.org"):
        other = _ask(client, email)
        assert other.status_code == 200 and other.json() == known       # nothing reveals whether the account exists
    assert len(otp.OUTBOX) == 1


def test_when_no_delivery_is_configured_the_api_says_so_and_stores_nothing(env, monkeypatch):
    client, db = env
    monkeypatch.delenv("OTP_DELIVERY"); monkeypatch.delenv("SMTP_HOST", raising=False)
    body = _ask(client).json()
    assert body["delivery"] == "not_configured" and "administrator" in body["message"].lower()
    assert db.query(models.OtpChallenge).count() == 0 and otp.OUTBOX == []


def test_dev_outbox_is_refused_in_production(env, monkeypatch):
    client, db = env
    monkeypatch.setenv("APP_ENV", "production")
    assert _ask(client).json()["delivery"] == "not_configured" and otp.OUTBOX == []


def test_the_code_is_stored_only_as_a_keyed_hash(env):
    client, db = env
    _ask(client)
    row = db.query(models.OtpChallenge).one()
    assert _code() not in (row.code_hash, row.salt) and len(row.code_hash) == 64


def test_full_recovery_flow_changes_the_password_and_old_credentials_stop_working(env):
    client, _ = env
    _ask(client)
    grant = client.post("/auth/otp/verify", json={"email": "dana@x.org", "code": _code()})
    assert grant.status_code == 200
    done = client.post("/auth/password-reset/complete", json={"token": grant.json()["reset_token"], "new_password": NEW})
    assert done.status_code == 200
    assert client.post("/auth/login", json={"email": "dana@x.org", "password": NEW}).status_code == 200
    assert client.post("/auth/login", json={"email": "dana@x.org", "password": OLD}).status_code in (400, 401)


def test_a_code_works_once_and_a_grant_works_once(env):
    client, _ = env
    _ask(client); code = _code()
    grant = client.post("/auth/otp/verify", json={"email": "dana@x.org", "code": code}).json()["reset_token"]
    assert client.post("/auth/otp/verify", json={"email": "dana@x.org", "code": code}).status_code == 400      # replay
    assert client.post("/auth/password-reset/complete", json={"token": grant, "new_password": NEW}).status_code == 200
    assert client.post("/auth/password-reset/complete", json={"token": grant, "new_password": NEW + "x"}).status_code == 400


def test_code_formatting_variants_are_accepted(env):
    client, _ = env
    _ask(client); c = _code()
    assert client.post("/auth/otp/verify", json={"email": " DANA@x.org ", "code": f"{c[:3]} {c[3:]}"}).status_code == 200


def test_wrong_guesses_burn_the_code_so_the_right_one_no_longer_works(env):
    client, db = env
    _ask(client); good = _code(); bad = "000000" if good != "000000" else "111111"
    for _ in range(3):
        assert client.post("/auth/otp/verify", json={"email": "dana@x.org", "code": bad}).status_code == 400
    assert client.post("/auth/otp/verify", json={"email": "dana@x.org", "code": good}).status_code == 400
    assert db.query(models.OtpChallenge).one().used_at is not None


def test_an_expired_code_is_refused(env):
    client, db = env
    _ask(client)
    row = db.query(models.OtpChallenge).one(); row.expires_at = _now() - timedelta(seconds=1); db.commit()
    assert client.post("/auth/otp/verify", json={"email": "dana@x.org", "code": _code()}).status_code == 400


def test_asking_again_retires_the_earlier_code(env):
    client, _ = env
    _ask(client); first = _code(); _ask(client); second = _code()
    assert first != second
    assert client.post("/auth/otp/verify", json={"email": "dana@x.org", "code": first}).status_code == 400
    assert client.post("/auth/otp/verify", json={"email": "dana@x.org", "code": second}).status_code == 200


def test_resend_cooldown_silently_suppresses_a_second_code(env, monkeypatch):
    client, _ = env
    monkeypatch.setenv("OTP_RESEND_COOLDOWN_SECONDS", "60")
    first = _ask(client); second = _ask(client)
    assert first.json() == second.json() and len(otp.OUTBOX) == 1 and first.json()["resend_in_seconds"] == 60


def test_hourly_cap_stops_a_flood_of_codes_to_one_account(env, monkeypatch):
    client, db = env
    monkeypatch.setenv("OTP_MAX_PER_HOUR", "2")
    for _ in range(5):
        _ask(client)
    assert len(otp.OUTBOX) == 2
    assert db.query(models.AuditLog).filter(models.AuditLog.action == "otp.rate_limited").count() >= 1


def test_nothing_secret_reaches_the_audit_log_or_the_server_log(env, caplog):
    client, db = env
    caplog.set_level(logging.DEBUG)
    _ask(client); code = _code()
    client.post("/auth/otp/verify", json={"email": "dana@x.org", "code": code})
    assert code not in caplog.text
    assert code not in repr([r.detail for r in db.query(models.AuditLog).all()])
    assert {"otp.sent", "otp.verified"} <= {r.action for r in db.query(models.AuditLog).all()}


def test_verify_with_no_active_code_looks_the_same_as_a_wrong_code(env):
    client, _ = env
    a = client.post("/auth/otp/verify", json={"email": "nobody@x.org", "code": "123456"})
    _ask(client)
    b = client.post("/auth/otp/verify", json={"email": "dana@x.org", "code": "999999" if _code() != "999999" else "888888"})
    assert a.status_code == b.status_code == 400 and a.json() == b.json()
