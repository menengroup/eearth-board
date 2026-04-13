"""
EEARTH Board App -- Authentication utilities (JWT + hashlib).
Replaced passlib/bcrypt with hashlib for Python 3.14 compatibility.
"""

import os
import time
import hashlib
import secrets
from typing import Optional

from jose import jwt, JWTError

SECRET_KEY = os.environ.get("SECRET_KEY", "eearth-board-super-secret-key-change-before-deploying-2026")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 30


def hash_password(password: str) -> str:
    """Hash a password using SHA-256 with a random salt."""
    salt = secrets.token_hex(16)
    hash_val = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${hash_val}"


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a salted SHA-256 hash."""
    try:
        salt, hash_val = hashed.split("$", 1)
        return hashlib.sha256((salt + plain).encode("utf-8")).hexdigest() == hash_val
    except (ValueError, AttributeError):
        return False


def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": time.time() + (TOKEN_EXPIRE_DAYS * 86400),
        "iat": time.time(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if time.time() > payload.get("exp", 0):
            return None
        return int(payload["sub"])
    except (JWTError, ValueError, KeyError, TypeError):
        return None
