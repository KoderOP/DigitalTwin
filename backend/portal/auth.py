"""JWT authentication and role-based access control.

Roles
    doctor     can provision only patients assigned to them
    patient    sees only their own twin, only while the interface is ACTIVE, from the bound device
    caregiver  read-only summary, only if the patient consented and the doctor enabled it
    preview    the doctor's read-only "view as patient", for assigned patients only

Secrets come from ``DT_JWT_SECRET`` or a random secret generated once into ``data/.jwt_secret``.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
import uuid
from collections import defaultdict, deque

import jwt
from fastapi import Header, HTTPException, Request

from common import path_of

ALGO = "HS256"


def _secret() -> str:
    env = os.environ.get("DT_JWT_SECRET")
    if env:
        return env
    p = path_of("data_dir") / ".jwt_secret"
    if not p.exists():
        p.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return p.read_text(encoding="utf-8").strip()


SECRET = _secret()


def issue(claims: dict, ttl_s: int) -> str:
    now = int(time.time())
    return jwt.encode({**claims, "iat": now, "exp": now + ttl_s, "jti": claims.get("jti", uuid.uuid4().hex)}, SECRET, algorithm=ALGO)


def decode(token: str, typ: str | None = None) -> dict:
    """Verify signature and expiry; raise 401 on any problem (never leak why in detail)."""
    try:
        c = jwt.decode(token, SECRET, algorithms=[ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token expired") from None
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid token") from None
    if typ and c.get("typ") != typ:
        raise HTTPException(401, "wrong token type")
    return c


def hash_secret(value: str) -> str:
    """Salted hash for OTPs and device ids (only hashes are stored)."""
    return hashlib.sha256((SECRET + "|" + value).encode()).hexdigest()


def bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def doctor_claims(authorization: str | None = Header(None)) -> dict:
    """FastAPI dependency: a valid doctor token."""
    c = decode(bearer(authorization), "access")
    if c.get("role") != "doctor":
        raise HTTPException(403, "doctor role required")
    return c


def any_claims(authorization: str | None = Header(None)) -> dict:
    return decode(bearer(authorization), "access")


class RateLimiter:
    """Sliding-window limiter (in memory; a deployment would use Redis or the gateway)."""

    def __init__(self, max_calls: int, window_s: float) -> None:
        self.max, self.window = max_calls, window_s
        self.calls: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        q = self.calls[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max:
            raise HTTPException(429, "too many attempts, please wait a minute")
        q.append(now)


def client_key(request: Request, extra: str = "") -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}|{extra}"
