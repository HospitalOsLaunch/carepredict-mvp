"""Password hashing (PBKDF2-SHA256) and signed, expiring bearer tokens (HMAC-SHA256).

Standard-library only, so the service has no crypto dependency to audit.
Pro Santé Connect / SSO is the intended replacement for passwords in production.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta

_ALGO = "pbkdf2_sha256"


class InvalidToken(Exception):
    pass


def hash_password(password: str, iterations: int) -> str:
    if len(password) < 10:
        raise ValueError("le mot de passe doit contenir au moins 10 caractères")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{_ALGO}${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iterations_s, salt_s, digest_s = encoded.split("$")
    except ValueError:
        return False
    if algo != _ALGO:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt_s), int(iterations_s))
    return hmac.compare_digest(digest, _unb64(digest_s))


def issue_token(user_id: int, secret: str, ttl_minutes: int, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(minutes=ttl_minutes)).timestamp()),
        "jti": secrets.token_hex(8),
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body, secret)}"


def read_token(token: str, secret: str, now: datetime | None = None) -> int:
    try:
        body, signature = token.split(".")
    except ValueError as exc:
        raise InvalidToken("malformed token") from exc
    if not hmac.compare_digest(signature, _sign(body, secret)):
        raise InvalidToken("bad signature")
    try:
        payload = json.loads(_unb64(body))
        user_id = int(payload["sub"])
        expires = int(payload["exp"])
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidToken("bad payload") from exc
    current = now or datetime.now(UTC)
    if current.timestamp() >= expires:
        raise InvalidToken("expired")
    return user_id


def _sign(body: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
