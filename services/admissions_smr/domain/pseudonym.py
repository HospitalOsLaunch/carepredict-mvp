"""Pseudonymous references for patient (IPP) and encounter (NDA) identifiers, and keyed
digests of received movements.

Keys: one per group and per purpose, derived from ``settings.pseudonym_secret`` with
HKDF-SHA256 (RFC 5869), ``info = "hospitalos/v1/<purpose>/group/<id>"``. A pseudonym key
never serves as a digest key, and a key leaked for one group says nothing about another.

Pseudonym: HMAC-SHA256 of ``kind ␟ domain ␟ value`` with the group's pseudonym key, where
``domain`` is the identification domain (assigning authority of the identifier, or else
the sending system): the same NDA issued by two establishments of a group gives two
references. The clear value is only ever held in memory by the caller; it is neither
stored nor logged.

Changing ``VERSION``, the derivation or the domain rule changes every reference (re-key):
stored references would no longer match the new ones. Nothing is released yet; after
release such a change needs a migration plan.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Literal

Kind = Literal["ipp", "nda"]
Purpose = Literal["pseudonym", "digest"]
VERSION = 1
_SALT = b"hospitalos-pseudonymisation"
_SEPARATOR = "\x1f"  # control characters are refused in received identifiers


def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    """RFC 5869 extract-then-expand, with the standard library only."""
    prk = hmac.new(salt or bytes(32), ikm, hashlib.sha256).digest()
    out, block = b"", b""
    for counter in range(1, -(-length // 32) + 1):
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block
    return out[:length]


def group_key(secret: str, group_id: int, purpose: Purpose) -> bytes:
    info = f"hospitalos/v{VERSION}/{purpose}/group/{group_id}".encode()
    return hkdf_sha256(secret.encode(), _SALT, info)


def pseudonym(secret: str, group_id: int, kind: Kind, domain: str, value: str) -> str:
    if kind not in ("ipp", "nda"):
        raise ValueError("kind must be 'ipp' or 'nda'")
    value, domain = value.strip(), domain.strip()
    if not value or not domain:
        raise ValueError("empty identifier or identification domain")
    message = _SEPARATOR.join((kind, domain, value)).encode()
    return hmac.new(group_key(secret, group_id, "pseudonym"), message, hashlib.sha256).hexdigest()


def keyed_digest(secret: str, group_id: int, payload: bytes) -> str:
    """Audit digest of a received message: keyed, so it cannot be brute-forced back to
    the identifiers it contains."""
    return hmac.new(group_key(secret, group_id, "digest"), payload, hashlib.sha256).hexdigest()
