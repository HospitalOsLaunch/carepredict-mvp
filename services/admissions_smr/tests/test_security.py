from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.admissions_smr.config import ConfigurationError, load_settings
from services.admissions_smr.security import (
    InvalidToken,
    hash_password,
    issue_token,
    read_token,
    verify_password,
)


def test_password_hash_roundtrip_and_minimum_length() -> None:
    encoded = hash_password("correct horse battery", 1000)
    assert verify_password("correct horse battery", encoded)
    assert not verify_password("wrong password!!", encoded)
    assert not verify_password("x", "garbage")
    with pytest.raises(ValueError):
        hash_password("short", 1000)


def test_token_signature_and_expiry() -> None:
    now = datetime(2026, 10, 25, 9, tzinfo=UTC)
    token = issue_token(42, "s" * 40, 60, now)
    assert read_token(token, "s" * 40, now + timedelta(minutes=59)) == 42
    with pytest.raises(InvalidToken):
        read_token(token, "s" * 40, now + timedelta(minutes=61))
    with pytest.raises(InvalidToken):
        read_token(token, "t" * 40, now)
    body, sig = token.split(".")
    with pytest.raises(InvalidToken):
        read_token(body[:-2] + "AA." + sig, "s" * 40, now)


def test_production_refuses_default_secret_and_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADM_ENV", "production")
    monkeypatch.delenv("ADM_SECRET_KEY", raising=False)
    with pytest.raises(ConfigurationError):
        load_settings()
    monkeypatch.setenv("ADM_SECRET_KEY", "k" * 40)
    monkeypatch.setenv("ADM_DATABASE_URL", "sqlite:///x.db")
    with pytest.raises(ConfigurationError):
        load_settings()
    monkeypatch.setenv("ADM_DATABASE_URL", "postgresql+psycopg://u:p@db/adm")
    assert load_settings().is_production
