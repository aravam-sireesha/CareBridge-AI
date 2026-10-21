"""Authentication hardening: lockout, rate limiting, two-step verification (TOTP), recovery codes, password rules.

* Lockout     - 5 wrong passwords lock the account for 15 minutes (LOGIN_MAX_ATTEMPTS / LOGIN_LOCK_MINUTES).
* Rate limit  - per client address, in memory (AUTH_RATE_LIMIT per AUTH_RATE_WINDOW seconds). Use a shared store
                or the reverse proxy for multi-process deployments.
* TOTP        - RFC 6238 (SHA-1, 30 s, 6 digits), +/-1 step tolerance, a used step can never be replayed.
                Secrets are encrypted at rest with a key derived from SECRET_KEY.
* Recovery    - 8 one-time codes, stored only as SHA-256 hashes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import struct
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .. import auth as auth_service
from ..models import Administrator, RevokedToken, User


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# --------------------------------------------------------------------------- rate limiting
_hits: dict[str, deque] = defaultdict(deque)


def reset_rate_limits() -> None:
    _hits.clear()


def client_address(request: Request) -> str:
    if os.getenv("TRUST_PROXY", "").lower() == "true":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def auth_rate_limit(request: Request) -> None:
    """FastAPI dependency for sign-in, sign-up and password-reset endpoints."""
    limit, window = _int_env("AUTH_RATE_LIMIT", 40), _int_env("AUTH_RATE_WINDOW", 300)
    key, now = f"{client_address(request)}:{request.url.path}", time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        retry = max(1, int(window - (now - q[0])))
        raise HTTPException(status_code=429, detail=f"Too many attempts. Try again in {retry // 60 + 1} minute(s).",
                            headers={"Retry-After": str(retry)})
    q.append(now)


def public_rate_limit(request: Request) -> None:
    """Generous per-address limit for the unauthenticated landing-page endpoints (PUBLIC_RATE_LIMIT per minute)."""
    limit, window = _int_env("PUBLIC_RATE_LIMIT", 120), 60
    key, now = f"public:{client_address(request)}", time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.", headers={"Retry-After": "30"})
    q.append(now)


# --------------------------------------------------------------------------- lockout
def check_not_locked(user: User, now: datetime | None = None) -> None:
    now = now or _now()
    if user.locked_until and user.locked_until > now:
        minutes = int((user.locked_until - now).total_seconds() // 60) + 1
        raise HTTPException(status_code=429, detail=f"Too many failed sign-in attempts. Try again in {minutes} minute(s).",
                            headers={"Retry-After": str(minutes * 60)})


def record_failure(db: Session, user: User) -> bool:
    """Count a wrong password or code. Returns True when this failure locked the account."""
    user.failed_login_count = (user.failed_login_count or 0) + 1
    locked = user.failed_login_count >= _int_env("LOGIN_MAX_ATTEMPTS", 5)
    if locked:
        user.locked_until = _now() + timedelta(minutes=_int_env("LOGIN_LOCK_MINUTES", 15))
        user.failed_login_count = 0
    db.commit()
    return locked


def record_success(db: Session, user: User) -> None:
    if user.failed_login_count or user.locked_until:
        user.failed_login_count, user.locked_until = 0, None
        db.commit()


# a throw-away hash so unknown e-mail addresses cost the same time as wrong passwords
_DUMMY_HASH = auth_service.hash_password("not-a-real-password")


def burn_time(password: str) -> None:
    auth_service.verify_password(password, _DUMMY_HASH)


# --------------------------------------------------------------------------- passwords
def password_problems(password: str, email: str = "") -> list[str]:
    problems = []
    if len(password) < 12:
        problems.append("use at least 12 characters")
    if len(set(password)) < 5:
        problems.append("use more different characters")
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w\s]"))
    if classes < 3:
        problems.append("mix upper case, lower case, numbers and symbols (at least three kinds)")
    local = email.split("@", 1)[0].lower()
    if len(local) >= 4 and local in password.lower():
        problems.append("do not include your email name")
    return problems


# --------------------------------------------------------------------------- TOTP
def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{value:06d}"


def totp_now(secret: str, at: float | None = None) -> str:
    return _hotp(secret, int((at or time.time()) // 30))


def verify_totp(secret: str, code: str, last_step: int | None = None, at: float | None = None) -> int | None:
    """Return the matching 30-second step, or None. A step at or before `last_step` is rejected (replay)."""
    code = re.sub(r"\s", "", code or "")
    if not re.fullmatch(r"\d{6}", code):
        return None
    step = int((at or time.time()) // 30)
    for candidate in (step - 1, step, step + 1):
        if hmac.compare_digest(_hotp(secret, candidate), code) and (last_step is None or candidate > last_step):
            return candidate
    return None


def provisioning_uri(secret: str, email: str, issuer: str = "CareBridge AI") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}&issuer={quote(issuer)}"
            "&algorithm=SHA1&digits=6&period=30")


def _fernet() -> Fernet:
    key = hashlib.sha256((auth_service.get_secret_key() + ":totp").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


# --------------------------------------------------------------------------- recovery codes
def _norm(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def _hash_code(code: str) -> str:
    return hashlib.sha256(_norm(code).encode()).hexdigest()


def new_recovery_codes(count: int = 8) -> tuple[list[str], list[str]]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    plain = ["".join(secrets.choice(alphabet) for _ in range(10)) for _ in range(count)]
    plain = [f"{c[:5]}-{c[5:]}" for c in plain]
    return plain, [_hash_code(c) for c in plain]


def consume_recovery_code(hashes: list[str] | None, code: str) -> list[str] | None:
    """Return the remaining hashes when `code` was valid (and is now used up), else None."""
    target = _hash_code(code)
    for h in hashes or []:
        if hmac.compare_digest(h, target):
            return [x for x in hashes if x != h]
    return None


# --------------------------------------------------------------------------- two-step sign-in
def create_mfa_token(user_id: int) -> str:
    return auth_service.create_access_token({"user_id": user_id, "purpose": "mfa"}, expires_minutes=5)


def read_mfa_token(token: str) -> int:
    try:
        payload = jwt.decode(token, auth_service.get_secret_key(), algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="This verification step expired. Sign in again.") from exc
    if payload.get("purpose") != "mfa" or not payload.get("user_id"):
        raise HTTPException(status_code=401, detail="Invalid verification token")
    return int(payload["user_id"])


def admin_requires_mfa(db: Session, user: User) -> bool:
    if user.role != "admin":
        return False
    admin = db.query(Administrator).filter(Administrator.user_id == user.id).first()
    return bool(admin and admin.totp_enabled)


# --------------------------------------------------------------------------- sign out of one session
def revoke_session(db: Session, user: dict) -> bool:
    """Block the token this request used. Returns False for old tokens that carry no id (use logout-all for those)."""
    jti, exp = user.get("jti"), user.get("exp")
    if not jti:
        return False
    expires = datetime.fromtimestamp(int(exp), tz=timezone.utc).replace(tzinfo=None) if exp else _now() + timedelta(days=2)
    if db.get(RevokedToken, str(jti)) is None:
        db.add(RevokedToken(jti=str(jti), user_id=user.get("id"), expires_at=expires))
    db.query(RevokedToken).filter(RevokedToken.expires_at < _now()).delete(synchronize_session=False)   # expired anyway
    return True
