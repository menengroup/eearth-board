"""
EEARTH Board App — Authentication utilities (JWT + bcrypt).
"""

import os
import time
from typing import Optional

from passlib.context import CryptContext
from jose import jwt, JWTError

SECRET_KEY = os.environ.get("SECRET_KEY", "eearth-board-super-secret-key-change-before-deploying-2026")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


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
