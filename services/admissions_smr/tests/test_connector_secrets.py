"""AES-256-GCM of the connections' secrets, and the master key's configuration rules."""

from __future__ import annotations

import base64

import pytest

from services.admissions_smr.config import ConfigurationError, load_settings
from services.admissions_smr.domain.connector_secrets import SecretError, decrypt, encrypt

KEY = "k" * 32 + "-connector-master"
SECRET = "mot-de-passe-du-portail-é"


def test_round_trip_with_a_version_prefix_and_a_fresh_nonce() -> None:
    first = encrypt(KEY, 1, 7, SECRET)
    second = encrypt(KEY, 1, 7, SECRET)

    assert first.startswith("v1:") and second.startswith("v1:")
    assert first != second  # random 96-bit nonce
    assert decrypt(KEY, 1, 7, first) == SECRET == decrypt(KEY, 1, 7, second)


def test_ciphertext_contains_no_plaintext() -> None:
    stored = encrypt(KEY, 1, 7, SECRET)
    raw = base64.urlsafe_b64decode(stored[3:])

    assert SECRET not in stored and SECRET.encode() not in raw
    assert b"portail" not in raw and "portail" not in stored


@pytest.mark.parametrize(
    ("key", "group_id", "connection_id"),
    [
        (KEY, 1, 8),  # pasted on another connection (associated data)
        (KEY, 2, 7),  # another group (derived key and associated data)
        ("x" * 48, 1, 7),  # another master key
    ],
)
def test_wrong_connection_group_or_key_does_not_decrypt(
    key: str, group_id: int, connection_id: int
) -> None:
    stored = encrypt(KEY, 1, 7, SECRET)

    with pytest.raises(SecretError) as error:
        decrypt(key, group_id, connection_id, stored)
    assert SECRET not in str(error.value) and stored not in str(error.value)


def test_tampering_and_unknown_formats_fail() -> None:
    stored = encrypt(KEY, 1, 7, SECRET)
    raw = bytearray(base64.urlsafe_b64decode(stored[3:]))
    raw[-1] ^= 1
    tampered = "v1:" + base64.urlsafe_b64encode(bytes(raw)).decode()

    for value in (tampered, "v2:" + stored[3:], stored[3:], "v1:", "v1:!!!", "v1:AAAA"):
        with pytest.raises(SecretError):
            decrypt(KEY, 1, 7, value)


def production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADM_ENV", "production")
    monkeypatch.setenv("ADM_DATABASE_URL", "postgresql+psycopg://u:p@db/adm")
    monkeypatch.setenv("ADM_SECRET_KEY", "s" * 40)
    monkeypatch.setenv("ADM_PSEUDONYM_SECRET", "p" * 40)


@pytest.mark.parametrize("value", [None, "short", "s" * 40, "p" * 40])
def test_production_requires_its_own_connector_key(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    production(monkeypatch)
    if value is None:
        monkeypatch.delenv("ADM_CONNECTOR_KEY", raising=False)
    else:
        monkeypatch.setenv("ADM_CONNECTOR_KEY", value)

    with pytest.raises(ConfigurationError, match="ADM_CONNECTOR_KEY"):
        load_settings()


def test_production_accepts_a_distinct_connector_key(monkeypatch: pytest.MonkeyPatch) -> None:
    production(monkeypatch)
    monkeypatch.setenv("ADM_CONNECTOR_KEY", "c" * 40)

    assert load_settings().connector_key == "c" * 40


@pytest.mark.parametrize("environment", ["development", "test"])
def test_development_has_a_connector_key_by_default(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("ADM_ENV", environment)
    monkeypatch.delenv("ADM_CONNECTOR_KEY", raising=False)

    assert len(load_settings().connector_key) >= 16
