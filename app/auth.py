"""Проста автентифікація без зовнішніх бібліотек.

Паролі хешуються PBKDF2-SHA256 із сіллю, а токен — це user_id + час дії,
підписані HMAC із SECRET_KEY. Клієнт надсилає його в заголовку
Authorization: Bearer <token>.
"""
import base64
import hashlib
import hmac
import os
import time
import warnings

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import User

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    SECRET_KEY = "dev-only-secret-change-me"
    warnings.warn("SECRET_KEY не задано — використовується небезпечний ключ для розробки.")

TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 днів
_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, iterations, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_token(user_id: int) -> str:
    payload = f"{user_id}:{int(time.time()) + TOKEN_TTL_SECONDS}"
    raw = f"{payload}:{_sign(payload)}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_token(token: str) -> int | None:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        user_id, expires, signature = raw.split(":")
    except (ValueError, UnicodeDecodeError):
        return None
    if not hmac.compare_digest(_sign(f"{user_id}:{expires}"), signature):
        return None
    if int(expires) < time.time():
        return None
    return int(user_id)


_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    user_id = decode_token(creds.credentials) if creds else None
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Потрібно увійти")
    return user
