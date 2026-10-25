"""Runtime settings, read once from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

_DEV_SECRET = "dev-only-secret-change-me"


class ConfigurationError(RuntimeError):
    """Raised when the service is started with an unsafe configuration."""


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str
    secret_key: str
    token_ttl_minutes: int
    password_iterations: int
    timezone: str
    cors_origins: tuple[str, ...]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def load_settings() -> Settings:
    settings = Settings(
        environment=os.getenv("ADM_ENV", "development"),
        database_url=os.getenv("ADM_DATABASE_URL", "sqlite:///./admissions_smr.db"),
        secret_key=os.getenv("ADM_SECRET_KEY", _DEV_SECRET),
        token_ttl_minutes=int(os.getenv("ADM_TOKEN_TTL_MINUTES", "720")),
        password_iterations=int(os.getenv("ADM_PASSWORD_ITERATIONS", "210000")),
        timezone=os.getenv("ADM_TIMEZONE", "Europe/Paris"),
        cors_origins=tuple(
            origin.strip()
            for origin in os.getenv("ADM_CORS_ORIGINS", "http://localhost:5174").split(",")
            if origin.strip()
        ),
    )
    if settings.is_production:
        if settings.secret_key == _DEV_SECRET or len(settings.secret_key) < 32:
            raise ConfigurationError(
                "ADM_SECRET_KEY must be set to a 32+ char secret in production"
            )
        if settings.database_url.startswith("sqlite"):
            raise ConfigurationError("SQLite is not allowed in production; use PostgreSQL (HDS)")
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
