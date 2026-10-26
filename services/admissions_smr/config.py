"""Runtime settings, read once from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

_DEV_SECRET = "dev-only-secret-change-me"


class ConfigurationError(RuntimeError):
    """Raised when the service is started with an unsafe configuration."""


@dataclass(frozen=True)
class OidcSettings:
    """OpenID Connect sign-in (Pro Santé Connect or the group's own identity provider)."""

    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str
    frontend_url: str
    scopes: str = "openid email profile"
    acr_values: str | None = None
    match_claim: str = "email"
    label: str = "Pro Santé Connect"
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    jwks_uri: str | None = None
    userinfo_endpoint: str | None = None


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str
    secret_key: str
    token_ttl_minutes: int
    password_iterations: int
    timezone: str
    cors_origins: tuple[str, ...]
    oidc: OidcSettings | None = None
    # Service accounts (role "ingestion") always keep password sign-in.
    password_login: bool = True

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def load_oidc() -> OidcSettings | None:
    issuer = os.getenv("ADM_OIDC_ISSUER")
    if not issuer:
        return None
    return OidcSettings(
        issuer=issuer.rstrip("/"),
        client_id=os.environ["ADM_OIDC_CLIENT_ID"],
        client_secret=os.environ["ADM_OIDC_CLIENT_SECRET"],
        redirect_uri=os.environ["ADM_OIDC_REDIRECT_URI"],
        frontend_url=os.getenv("ADM_FRONTEND_URL", "/").rstrip("/"),
        scopes=os.getenv("ADM_OIDC_SCOPES", "openid email profile"),
        acr_values=os.getenv("ADM_OIDC_ACR_VALUES") or None,
        match_claim=os.getenv("ADM_OIDC_MATCH_CLAIM", "email"),
        label=os.getenv("ADM_OIDC_LABEL", "Pro Santé Connect"),
        authorization_endpoint=os.getenv("ADM_OIDC_AUTHORIZATION_ENDPOINT") or None,
        token_endpoint=os.getenv("ADM_OIDC_TOKEN_ENDPOINT") or None,
        jwks_uri=os.getenv("ADM_OIDC_JWKS_URI") or None,
        userinfo_endpoint=os.getenv("ADM_OIDC_USERINFO_ENDPOINT") or None,
    )


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
        oidc=load_oidc(),
        password_login=os.getenv("ADM_PASSWORD_LOGIN", "1") != "0",
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
