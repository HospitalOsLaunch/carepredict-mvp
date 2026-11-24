"""Runtime configuration, read once from the environment (12-factor). No secret has a default."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Environment = Literal["development", "staging", "production"]
ENVIRONMENTS: tuple[Environment, ...] = ("development", "staging", "production")


class ConfigError(ValueError):
    """Raised at start-up when the environment is incomplete or inconsistent."""


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    username: str
    password: str
    starttls: bool = True


@dataclass(frozen=True)
class Settings:
    environment: Environment
    public_base_url: str
    database_path: Path
    hybrid_url: str
    decision_url: str
    email_from: str
    email_backend: Literal["console", "smtp"]
    smtp: SmtpSettings | None = None
    ga_measurement_id: str | None = None
    session_idle_minutes: int = 8 * 60
    session_absolute_hours: int = 24
    invitation_days: int = 7
    reset_minutes: int = 60
    release: str = "dev"
    trusted_origins: tuple[str, ...] = field(default=())

    @property
    def cookie_secure(self) -> bool:
        return self.environment != "development"

    @property
    def analytics_id(self) -> str | None:
        """Google Analytics is only ever exposed in production."""
        return self.ga_measurement_id if self.environment == "production" else None


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise ConfigError(f"{name} must be set")
    return value


def from_env() -> Settings:
    environment = _env("APP_ENV", "development")
    if environment not in ENVIRONMENTS:
        raise ConfigError(f"APP_ENV must be one of {ENVIRONMENTS}")
    env: Environment = environment
    dev = env == "development"
    base = _env("PUBLIC_BASE_URL", "http://localhost:5173" if dev else None).rstrip("/")
    if not dev and not base.startswith("https://"):
        raise ConfigError("PUBLIC_BASE_URL must be https:// outside development")
    backend = _env("EMAIL_BACKEND", "console" if dev else "smtp")
    if backend not in ("console", "smtp"):
        raise ConfigError("EMAIL_BACKEND must be console or smtp")
    if backend == "console" and env == "production":
        raise ConfigError("EMAIL_BACKEND=console is not allowed in production")
    smtp = None
    if backend == "smtp":
        smtp = SmtpSettings(
            host=_env("SMTP_HOST"),
            port=int(_env("SMTP_PORT", "587")),
            username=_env("SMTP_USERNAME"),
            password=_env("SMTP_PASSWORD"),
            starttls=_env("SMTP_STARTTLS", "true").lower() == "true",
        )
    ga = os.environ.get("GA_MEASUREMENT_ID") or None
    if ga is not None and not (ga.startswith("G-") and ga[2:].isalnum()):
        raise ConfigError("GA_MEASUREMENT_ID must look like G-XXXXXXXXXX")
    return Settings(
        environment=env,
        public_base_url=base,
        database_path=Path(_env("PLATFORM_DB", "var/platform.sqlite3" if dev else None)),
        hybrid_url=_env("HYBRID_URL", "http://127.0.0.1:8000").rstrip("/"),
        decision_url=_env("DECISION_URL", "http://127.0.0.1:8765").rstrip("/"),
        email_from=_env("EMAIL_FROM", "HospitalOS <no-reply@localhost>" if dev else None),
        email_backend=backend,  # type: ignore[arg-type]
        smtp=smtp,
        ga_measurement_id=ga,
        release=os.environ.get("RELEASE", "dev"),
        trusted_origins=(base,),
    )
