"""Encryption of the agent connections' secrets (portal or bed-software password).

AES-256-GCM (``cryptography``). One key per group, derived with HKDF-SHA256 (RFC 5869,
``domain.pseudonym.hkdf_sha256``) from the master key ``ADM_CONNECTOR_KEY``:
``salt = "hospitalos-connector"``, ``info = "connector/group/<group_id>"``. A random 96-bit
nonce per encryption. Associated data ``"<group_id>|<connection_id>"``: a ciphertext copied
onto another connection, or into another group, does not decrypt.

Stored form: ``v1:`` + base64url(nonce ‖ ciphertext ‖ tag). The prefix names the format and
the derivation, so a later rotation can re-encrypt ``v1`` values into ``v2``.

The clear secret is returned only by ``decrypt``; callers never log, audit or return it to
the interface (only to the claim of one of the connection's tasks).
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from services.admissions_smr.domain.pseudonym import hkdf_sha256

VERSION = "v1"
_SALT = b"hospitalos-connector"
_NONCE_BYTES = 12


class SecretError(ValueError):
    """Unreadable ciphertext: wrong key, wrong connection, tampered or unknown format.
    Its message never contains the secret nor the ciphertext."""


def _key(master_key: str, group_id: int) -> bytes:
    return hkdf_sha256(master_key.encode(), _SALT, f"connector/group/{group_id}".encode())


def _aad(group_id: int, connection_id: int) -> bytes:
    return f"{group_id}|{connection_id}".encode()


def encrypt(master_key: str, group_id: int, connection_id: int, secret: str) -> str:
    nonce = os.urandom(_NONCE_BYTES)
    sealed = AESGCM(_key(master_key, group_id)).encrypt(
        nonce, secret.encode(), _aad(group_id, connection_id)
    )
    return f"{VERSION}:" + base64.urlsafe_b64encode(nonce + sealed).decode()


def decrypt(master_key: str, group_id: int, connection_id: int, stored: str) -> str:
    version, _, body = stored.partition(":")
    if version != VERSION or not body:
        raise SecretError("format de secret inconnu")
    try:
        raw = base64.urlsafe_b64decode(body.encode())
        nonce, sealed = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
        clear = AESGCM(_key(master_key, group_id)).decrypt(
            nonce, sealed, _aad(group_id, connection_id)
        )
    except (InvalidTag, ValueError) as exc:
        raise SecretError("secret illisible avec cette clé pour cette connexion") from exc
    return clear.decode()
