"""Secure authentication: lockout, rate limiting, change password, sign-out everywhere, two-step verification, audit."""
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from admin_factory import make_admin
from app import models
from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.services import security

PASSWORD = "StrongPass1234!"
NEW_PASSWORD = "Another-Strong-9876"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("ADMIN_SIGNUP_CODE", "invite-123")
    monkeypatch.delenv("AUTH_RATE_LIMIT", raising=False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()

    def override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        yield client, db
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def make_user(db, email="org@x.org", role="organization"):
    u = models.User(email=email, hashed_password=hash_password(PASSWORD), role=role)
    db.add(u)
    db.commit()
    return u


def login(client, email="org@x.org", password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def bearer(res):
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def actions(db):
    return [a.action for a in db.query(models.AuditLog).order_by(models.AuditLog.id).all()]


# ---------------------------------------------------------------- primitives
def test_totp_matches_the_rfc_6238_test_vector_and_rejects_replays():
    import base64
    rfc = base64.b32encode(b"12345678901234567890").decode()
    assert security.totp_now(rfc, at=59) == "287082"
    secret = security.new_totp_secret()
    step = security.verify_totp(secret, security.totp_now(secret))
    assert step is not None
    assert security.verify_totp(secret, security.totp_now(secret), last_step=step) is None  # replay
    assert security.verify_totp(secret, "12345") is None and security.verify_totp(secret, "abcdef") is None


def test_password_rules_and_recovery_codes():
    assert security.password_problems("short") and security.password_problems("aaaaaaaaaaaaaaaa")
    assert security.password_problems("alllowercaseletters")  # one character class only
    assert security.password_problems("Jammi-Reddy-2026!", "jammi@x.org")  # contains the email name
    assert security.password_problems(NEW_PASSWORD) == []
    plain, hashed = security.new_recovery_codes()
    assert len(plain) == 8 and all("-" in c for c in plain) and plain[0] not in str(hashed)
    left = security.consume_recovery_code(hashed, plain[0].lower())  # case-insensitive
    assert left is not None and len(left) == 7
    assert security.consume_recovery_code(left, plain[0]) is None  # one-time


# ---------------------------------------------------------------- lockout and rate limit
def test_account_locks_after_five_wrong_passwords_and_unlocks_later(api):
    client, db = api
    user = make_user(db)
    for _ in range(4):
        assert login(client, password="wrong-password-1").status_code == 401
    fifth = login(client, password="wrong-password-1")  # the 5th failure locks the account and says so
    assert fifth.status_code == 429 and "Try again" in fifth.json()["detail"]
    locked = login(client)  # even the right password is refused now
    assert locked.status_code == 429 and "Try again" in locked.json()["detail"] and "Retry-After" in locked.headers
    assert "auth.account_locked" in actions(db)
    user.locked_until = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    assert login(client).status_code == 200
    db.refresh(user)
    assert user.failed_login_count == 0 and user.locked_until is None


def test_a_good_login_resets_the_failure_counter(api):
    client, db = api
    user = make_user(db)
    for _ in range(3):
        login(client, password="wrong-password-1")
    assert login(client).status_code == 200
    for _ in range(4):
        login(client, password="wrong-password-1")
    assert login(client).status_code == 200  # 4 new failures is still under the limit


def test_unknown_accounts_look_the_same_and_are_audited(api):
    client, db = api
    res = login(client, "nobody@x.org")
    assert res.status_code == 401 and res.json()["detail"] == "Invalid email or password"
    row = db.query(models.AuditLog).filter_by(action="auth.login_failed").one()
    assert row.actor_user_id is None and row.detail["reason"] == "unknown account" and row.ip == "testclient"


def test_rate_limit_blocks_floods_per_client(api, monkeypatch):
    client, db = api
    make_user(db)
    monkeypatch.setenv("AUTH_RATE_LIMIT", "3")
    codes = [login(client, password="wrong-password-1").status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3] == 429


# ---------------------------------------------------------------- sessions and passwords
def test_change_password_rules_and_session_handling(api):
    client, db = api
    make_user(db)
    old = login(client)
    h = bearer(old)
    assert client.post("/auth/change-password", headers=h, json={"current_password": "wrong", "new_password": NEW_PASSWORD}).status_code == 400
    weak = client.post("/auth/change-password", headers=h, json={"current_password": PASSWORD, "new_password": "alllowercaseletters"})
    assert weak.status_code == 422 and "stronger" in weak.json()["detail"]
    same = client.post("/auth/change-password", headers=h, json={"current_password": PASSWORD, "new_password": PASSWORD})
    assert same.status_code == 422
    ok = client.post("/auth/change-password", headers=h, json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert ok.status_code == 200, ok.text
    assert client.get("/auth/me", headers=h).status_code == 401  # old session revoked
    assert client.get("/auth/me", headers=bearer(ok)).status_code == 200  # this session continues
    assert login(client).status_code == 401 and login(client, password=NEW_PASSWORD).status_code == 200
    assert "auth.password_changed" in actions(db)


def test_sign_out_of_all_other_devices(api):
    client, db = api
    make_user(db)
    laptop, phone = login(client), login(client)
    res = client.post("/auth/logout-all", headers=bearer(laptop))
    assert res.status_code == 200
    assert client.get("/auth/me", headers=bearer(phone)).status_code == 401
    assert client.get("/auth/me", headers=bearer(laptop)).status_code == 401  # the old token too
    assert client.get("/auth/me", headers=bearer(res)).status_code == 200


# ---------------------------------------------------------------- administrator two-step verification
def admin_session(client, db, email="boss@x.org"):
    assert make_admin(client, email, PASSWORD).status_code == 201
    res = client.post("/admin/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200
    return bearer(res)


def enable_2fa(client, h):
    setup = client.post("/admin/2fa/setup", headers=h).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/") and setup["secret"] in setup["otpauth_uri"]
    assert client.post("/admin/2fa/enable", headers=h, json={"code": "000000"}).status_code == 400
    enabled = client.post("/admin/2fa/enable", headers=h, json={"code": security.totp_now(setup["secret"])})
    assert enabled.status_code == 200, enabled.text
    return setup["secret"], enabled.json()["recovery_codes"]


def next_code(secret):
    return security.totp_now(secret, at=time.time() + 30)  # the next 30-second step: valid, and never used before


def test_two_step_login_flow_end_to_end(api):
    client, db = api
    h = admin_session(client, db)
    assert client.get("/admin/2fa/status", headers=h).json() == {"enabled": False, "recovery_codes_left": 0}
    secret, codes = enable_2fa(client, h)
    assert len(codes) == 8
    admin = db.query(models.Administrator).one()
    assert admin.totp_enabled and admin.totp_secret != secret and secret not in str(admin.totp_secret)  # encrypted at rest
    assert codes[0] not in str(admin.recovery_codes)  # only hashes are stored

    step1 = client.post("/admin/login", json={"email": "boss@x.org", "password": PASSWORD}).json()
    assert step1["mfa_required"] is True and "access_token" not in step1
    # the normal sign-in cannot be used to skip the second step
    assert login(client, "boss@x.org").status_code == 403
    # the short-lived token is not a session
    assert client.get("/admin/me", headers={"Authorization": f"Bearer {step1['mfa_token']}"}).status_code == 401

    wrong = client.post("/admin/login/verify", json={"mfa_token": step1["mfa_token"], "code": "123456"})
    assert wrong.status_code == 401
    good_code = next_code(secret)
    ok = client.post("/admin/login/verify", json={"mfa_token": step1["mfa_token"], "code": good_code})
    assert ok.status_code == 200 and ok.json()["admin"]["full_name"] == "Asha"
    assert client.get("/admin/me", headers=bearer(ok)).status_code == 200
    # the same code cannot be used twice
    again = client.post("/admin/login/verify", json={"mfa_token": step1["mfa_token"], "code": good_code})
    assert again.status_code == 401
    assert {"admin.2fa_enabled", "admin.mfa_failed", "admin.login"} <= set(actions(db))


def test_recovery_code_works_once_and_wrong_codes_lock_the_account(api):
    client, db = api
    h = admin_session(client, db)
    secret, codes = enable_2fa(client, h)
    token = client.post("/admin/login", json={"email": "boss@x.org", "password": PASSWORD}).json()["mfa_token"]
    assert client.post("/admin/login/verify", json={"mfa_token": token, "code": codes[0]}).status_code == 200
    assert client.get("/admin/2fa/status", headers=h).json()["recovery_codes_left"] == 7
    token2 = client.post("/admin/login", json={"email": "boss@x.org", "password": PASSWORD}).json()["mfa_token"]
    assert client.post("/admin/login/verify", json={"mfa_token": token2, "code": codes[0]}).status_code == 401  # used up
    for _ in range(4):
        client.post("/admin/login/verify", json={"mfa_token": token2, "code": "999999"})
    locked = client.post("/admin/login", json={"email": "boss@x.org", "password": PASSWORD})
    assert locked.status_code == 429
    assert "auth.account_locked" in actions(db)


def test_disable_and_regenerate_need_password_and_code(api):
    client, db = api
    h = admin_session(client, db)
    secret, codes = enable_2fa(client, h)
    assert client.post("/admin/2fa/setup", headers=h).status_code == 409  # already on
    assert client.post("/admin/2fa/disable", headers=h, json={"password": "wrong", "code": next_code(secret)}).status_code == 400
    new = client.post("/admin/2fa/recovery-codes", headers=h, json={"password": PASSWORD})
    assert new.status_code == 200 and new.json()["recovery_codes"][0] != codes[0]
    assert client.post("/admin/2fa/disable", headers=h, json={"password": PASSWORD, "code": next_code(secret)}).status_code == 200
    admin = db.query(models.Administrator).one()
    assert not admin.totp_enabled and admin.totp_secret is None and admin.recovery_codes is None
    assert client.post("/admin/login", json={"email": "boss@x.org", "password": PASSWORD}).json().get("access_token")  # back to one step


# ---------------------------------------------------------------- headers
def test_security_headers_on_every_response(api):
    client, _ = api
    for path in ("/", "/auth/me"):
        r = client.get(path)
        assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "no-referrer"
    assert client.get("/auth/me").headers["Cache-Control"] == "no-store"
