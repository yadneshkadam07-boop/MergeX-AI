"""Authentication and password hashing security utilities.

Provides bcrypt password hashing/verification and signed JWT access token creation/validation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt with a salt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(
    data: dict[str, Any],
    secret: str,
    algorithm: str = "HS256",
    expires_delta: timedelta | None = None,
    expiry_minutes: int = 1440,
) -> str:
    """Encode payload claims into a signed JWT token."""
    to_encode = data.copy()
    now = datetime.now(UTC)
    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=expiry_minutes)

    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, secret, algorithm=algorithm)


def decode_access_token(
    token: str,
    secret: str,
    algorithm: str = "HS256",
) -> dict[str, Any]:
    """Decode and verify a signed JWT token.

    Raises jwt.ExpiredSignatureError or jwt.PyJWTError on invalid tokens.
    """
    return jwt.decode(token, secret, algorithms=[algorithm])
