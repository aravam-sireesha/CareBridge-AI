"""Password hashing and JWT helpers.

Passwords are hashed with the ``bcrypt`` library directly. The previous version used
``passlib``, which is unmaintained and breaks on newer ``bcrypt`` / Python releases
(the failure only shows up on the first hash/verify call, which is why it can look like
"register works but login returns 500"). Hashes are standard ``$2b$`` bcrypt strings, so
every account created with the old code keeps working.
"""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from dotenv import load_dotenv
from jose import jwt

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

logger = logging.getLogger(__name__)

# bcrypt only looks at the first 72 bytes of a password.
_BCRYPT_MAX_BYTES = 72


def _prepare(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    """Return True only for a matching password. A malformed/legacy hash is a failed
    login (401), never a server error."""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(_prepare(plain), hashed.strip().encode("utf-8"))
    except (ValueError, TypeError):
        logger.warning("Stored password hash is not a valid bcrypt hash")
        return False


def get_secret_key() -> str:
    secret_key = (os.getenv("SECRET_KEY") or "").strip()
    if not secret_key:
        raise RuntimeError(
            "SECRET_KEY is not configured. Add SECRET_KEY=<long random string> to backend/.env"
        )
    return secret_key


def create_access_token(data: dict, expires_minutes: int = 60 * 24) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    to_encode.setdefault("jti", secrets.token_urlsafe(16))   # lets one session be signed out on its own
    return jwt.encode(to_encode, get_secret_key(), algorithm="HS256")
