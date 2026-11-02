from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.admissions_smr.config import ConfigurationError, ensure_demo_allowed, load_settings
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
    monkeypatch.setenv("ADM_PSEUDONYM_SECRET", "p" * 40)
    assert load_settings().is_production


def test_production_requires_its_own_pseudonymisation_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADM_ENV", "production")
    monkeypatch.setenv("ADM_SECRET_KEY", "k" * 40)
    monkeypatch.setenv("ADM_DATABASE_URL", "postgresql+psycopg://u:p@db/adm")
    monkeypatch.delenv("ADM_PSEUDONYM_SECRET", raising=False)
    with pytest.raises(ConfigurationError, match="ADM_PSEUDONYM_SECRET"):
        load_settings()
    monkeypatch.setenv("ADM_PSEUDONYM_SECRET", "short")
    with pytest.raises(ConfigurationError, match="ADM_PSEUDONYM_SECRET"):
        load_settings()
    monkeypatch.setenv("ADM_PSEUDONYM_SECRET", "k" * 40)  # same as the token key
    with pytest.raises(ConfigurationError, match="ADM_PSEUDONYM_SECRET"):
        load_settings()
    monkeypatch.setenv("ADM_PSEUDONYM_SECRET", "p" * 40)
    assert load_settings().pseudonym_secret == "p" * 40


def test_development_has_a_pseudonymisation_secret_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADM_ENV", "development")
    monkeypatch.delenv("ADM_PSEUDONYM_SECRET", raising=False)
    assert len(load_settings().pseudonym_secret) >= 16


@pytest.mark.parametrize(
    "env", ["staging", "prod", "Development", "TEST", " development", "", "demo"]
)
def test_dev_keys_are_refused_unless_adm_env_is_exactly_development_or_test(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    # REVIEW S-M3: fail closed, whatever the database.
    monkeypatch.setenv("ADM_ENV", env)
    monkeypatch.setenv("ADM_DATABASE_URL", "postgresql+psycopg://u:p@db/adm")
    monkeypatch.delenv("ADM_SECRET_KEY", raising=False)
    monkeypatch.delenv("ADM_PSEUDONYM_SECRET", raising=False)
    with pytest.raises(ConfigurationError, match="ADM_ENV"):
        load_settings()
    monkeypatch.setenv("ADM_SECRET_KEY", "k" * 40)
    with pytest.raises(ConfigurationError, match="ADM_PSEUDONYM_SECRET"):
        load_settings()
    monkeypatch.setenv("ADM_PSEUDONYM_SECRET", "p" * 40)
    settings = load_settings()
    assert not settings.dev_defaults_allowed
    with pytest.raises(ConfigurationError, match="démonstration"):
        ensure_demo_allowed(settings)


@pytest.mark.parametrize("env", ["development", "test"])
@pytest.mark.parametrize("url", ["sqlite:///x.db", "postgresql+psycopg://u:p@db/adm"])
def test_dev_keys_and_demo_seeds_are_allowed_in_development_and_test(
    monkeypatch: pytest.MonkeyPatch, env: str, url: str
) -> None:
    monkeypatch.setenv("ADM_ENV", env)
    monkeypatch.setenv("ADM_DATABASE_URL", url)
    monkeypatch.delenv("ADM_SECRET_KEY", raising=False)
    monkeypatch.delenv("ADM_PSEUDONYM_SECRET", raising=False)
    settings = load_settings()
    assert settings.dev_defaults_allowed
    ensure_demo_allowed(settings)
