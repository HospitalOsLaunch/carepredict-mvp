"""Password hashing, opaque tokens and password policy (standard library only).

Passwords: scrypt (n=2^15, r=8, p=1, 64-byte key, 16-byte random salt), stored as
``scrypt$n$r$p$salt_b64$hash_b64``; verification is constant-time. Session, invitation and reset
tokens are random 32-byte URL-safe strings; only their SHA-256 is stored, so a database leak does
not reveal usable tokens.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

N, R, P, DKLEN = 2**15, 8, 1, 64
MAXMEM = 64 * 1024 * 1024
MIN_PASSWORD = 12
MAX_PASSWORD = 256
_COMMON = {
    "motdepasse123",
    "password1234",
    "123456789012",
    "azertyuiop12",
    "hospitalos123",
    "qwertyuiop12",
    "000000000000",
    "111111111111",
    "abcdefghijkl",
    "changeme1234",
}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=DKLEN, maxmem=MAXMEM)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        # Same cost as a real check, so that unknown accounts are not distinguishable by timing.
        hashlib.scrypt(
            password.encode(), salt=b"\0" * 16, n=N, r=R, p=P, dklen=DKLEN, maxmem=MAXMEM
        )
        return False
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(digest)
        actual = hashlib.scrypt(
            password.encode(),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def password_problem(password: str, email: str) -> str | None:
    """French message describing why a password is refused, or None when it is acceptable."""
    if len(password) < MIN_PASSWORD:
        return f"Le mot de passe doit contenir au moins {MIN_PASSWORD} caractères."
    if len(password) > MAX_PASSWORD:
        return f"Le mot de passe doit contenir au plus {MAX_PASSWORD} caractères."
    lowered = password.lower()
    local = email.split("@", 1)[0].lower()
    if lowered in _COMMON or len(set(password)) < 5:
        return "Ce mot de passe est trop courant ou trop répétitif."
    if local and len(local) >= 4 and local in lowered:
        return "Le mot de passe ne doit pas contenir votre adresse email."
    return None
