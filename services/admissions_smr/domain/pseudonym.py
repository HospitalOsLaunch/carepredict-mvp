"""Pseudonymous references for patient (IPP) and encounter (NDA) identifiers.

HMAC-SHA256 keyed by ``settings.pseudonym_secret`` and bound to the tenant and the kind of
identifier: the same IPP gives the same reference within a group, a different one in
another group, and an IPP never collides with an NDA of the same value. The clear value
is only ever held in memory by the caller; it is neither stored nor logged.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Literal

Kind = Literal["ipp", "nda"]


def pseudonym(secret: str, group_id: int, kind: Kind, value: str) -> str:
    if kind not in ("ipp", "nda"):
        raise ValueError("kind must be 'ipp' or 'nda'")
    value = value.strip()
    if not value:
        raise ValueError("empty identifier")
    message = f"{group_id}\x1f{kind}\x1f{value}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
