"""Password hashing (argon2id), JWT access tokens and opaque refresh/reset tokens."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings
from app.core.errors import UnauthorizedError

_hasher = PasswordHasher()  # argon2id with the library's current recommended parameters
# Verified against when the account does not exist, so login timing does not reveal accounts.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")

MIN_SECRET_LENGTH = 32
COMMON_PASSWORDS = {
    "password", "password1", "password123", "1234567890", "12345678910", "qwertyuiop", "iloveyou123",
    "letmein1234", "welcome1234", "admin12345", "changeme123", "passw0rd123",
}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-effort verify; a missing hash is checked against a dummy to equalise timing."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problems(password: str, email: str | None = None) -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("Password must be at least 10 characters long")
    if len(password) > 128:
        problems.append("Password must be at most 128 characters long")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("Password is too common")
    if email and password.lower() == email.lower():
        problems.append("Password must not be the same as the email address")
    return problems


def _secret() -> str:
    secret = get_settings().jwt_secret
    if len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError(f"JWT_SECRET must be set to at least {MIN_SECRET_LENGTH} characters")
    return secret


def create_access_token(user_id: int, now: datetime | None = None) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)``."""
    now = now or datetime.now(timezone.utc)
    ttl = timedelta(minutes=get_settings().access_token_minutes)
    payload = {"sub": str(user_id), "type": "access", "iat": now, "exp": now + ttl}
    return jwt.encode(payload, _secret(), algorithm="HS256"), int(ttl.total_seconds())


def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(
            token, _secret(), algorithms=["HS256"], options={"require": ["exp", "sub", "iat"]}
        )
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Access token expired") from None
    except jwt.InvalidTokenError:
        raise UnauthorizedError("Invalid access token") from None
    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid access token")
    try:
        return int(payload["sub"])
    except (TypeError, ValueError):
        raise UnauthorizedError("Invalid access token") from None


def new_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Tokens are high-entropy, so a fast hash is appropriate (and allows indexed lookup)."""
    return hashlib.sha256(token.encode()).hexdigest()
