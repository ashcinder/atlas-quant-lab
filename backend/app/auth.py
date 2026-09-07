from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.config import AUTH_ENABLED, SESSION_SECONDS, SESSION_SECRET

COOKIE_NAME = "atlas_session"
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@dataclass(frozen=True)
class User:
    id: str
    email: str | None
    session_version: int = 0


def normalize_email(value: object) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def valid_email(email: str) -> bool:
    return len(email) <= 254 and bool(_EMAIL.fullmatch(email))


def valid_password(password: object) -> bool:
    return isinstance(password, str) and 8 <= len(password) <= 128


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    encoded = hashlib.scrypt(password.encode(), salt=salt.encode(), n=2**14, r=8, p=1, dklen=64)
    return f"{salt}:{encoded.hex()}"


def verify_password(password: object, stored: str) -> bool:
    if not isinstance(password, str):
        return False
    try:
        salt, encoded = stored.split(":")
        expected = bytes.fromhex(encoded)
        actual = hashlib.scrypt(
            password.encode(), salt=salt.encode(), n=2**14, r=8, p=1, dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_session(user: User) -> str:
    if not AUTH_ENABLED:
        return ""
    payload = _b64(
        json.dumps(
            {
                "userId": user.id,
                "email": user.email,
                "sessionVersion": user.session_version,
                "expires": int(time.time()) + SESSION_SECONDS,
            },
            separators=(",", ":"),
        ).encode()
    )
    signature = _b64(hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def parse_session(request: Request, lookup: callable) -> User | None:
    if not AUTH_ENABLED:
        return User("local", None)
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload, supplied = token.split(".")
        expected = _b64(
            hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied, expected):
            return None
        session = json.loads(_unb64(payload))
        if (
            not isinstance(session["userId"], str)
            or not isinstance(session["email"], str)
            or not isinstance(session["sessionVersion"], int)
            or session["expires"] <= time.time()
        ):
            return None
        user = lookup(session["userId"], session["email"], session["sessionVersion"])
        return User(user["id"], user["email"], user["session_version"]) if user else None
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None


def require_user(request: Request, store) -> User:
    user = parse_session(request, store.find_session_user)
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "需要登录"})
    return user
