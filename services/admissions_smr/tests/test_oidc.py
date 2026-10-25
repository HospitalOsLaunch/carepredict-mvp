from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from services.admissions_smr.clock import Clock
from services.admissions_smr.config import OidcSettings, Settings
from services.admissions_smr.main import create_app
from services.admissions_smr.models import Group, User
from services.admissions_smr.security import hash_password

ISSUER = "https://idp.test/realms/sante"
CLIENT = "hospitalos-admissions"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {
    **json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())),
    "kid": "k1",
    "use": "sig",
}


class FakeIdp:
    def __init__(self) -> None:
        self.challenge = ""
        self.nonce_override: str | None = None
        self.claims: dict[str, Any] = {"sub": "psc-123", "email": "coord@g.fr"}
        self.audience = CLIENT
        self.nonce = ""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/auth",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/certs",
                    "userinfo_endpoint": f"{ISSUER}/userinfo",
                },
            )
        if path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [JWK]})
        if path.endswith("/token"):
            form = parse_qs(request.content.decode())
            verifier = form["code_verifier"][0]
            digest = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .rstrip(b"=")
                .decode()
            )
            if digest != self.challenge or form["client_secret"][0] != "secret":
                return httpx.Response(400, json={"error": "invalid_grant"})
            now = int(time.time())
            token = jwt.encode(
                {
                    "iss": ISSUER,
                    "aud": self.audience,
                    "iat": now,
                    "exp": now + 300,
                    "nonce": self.nonce_override or self.nonce,
                    **self.claims,
                },
                KEY,
                algorithm="RS256",
                headers={"kid": "k1"},
            )
            return httpx.Response(200, json={"id_token": token, "access_token": "at"})
        if path.endswith("/userinfo"):
            return httpx.Response(200, json={"SubjectNameID": "810000000001"})
        return httpx.Response(404)


@pytest.fixture
def idp() -> FakeIdp:
    return FakeIdp()


def make_client(
    tmp_path: Path, idp: FakeIdp, match_claim: str = "email", password_login: bool = True
) -> TestClient:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'o.db'}",
        secret_key="s" * 40,
        token_ttl_minutes=60,
        password_iterations=1000,
        timezone="Europe/Paris",
        cors_origins=(),
        oidc=OidcSettings(
            issuer=ISSUER,
            client_id=CLIENT,
            client_secret="secret",
            redirect_uri="https://app.test/api/auth/oidc/callback",
            frontend_url="https://app.test",
            scopes="openid scope_all",
            acr_values="eidas2",
            match_claim=match_claim,
        ),
        password_login=password_login,
    )
    app = create_app(settings, Clock())
    app.state.oidc_http = httpx.Client(transport=httpx.MockTransport(idp))
    session = app.state.session_factory()
    group = Group(name="g", created_at=Clock().now())
    session.add(group)
    session.flush()
    for email, role, subject in (
        ("coord@g.fr", "coordination", None),
        ("agent@g.fr", "ingestion", None),
        ("rpps@g.fr", "coordination", "810000000001"),
    ):
        session.add(
            User(
                group_id=group.id,
                email=email,
                full_name=email,
                role=role,
                oidc_subject=subject,
                password_hash=hash_password("mot-de-passe-solide", 1000),
                created_at=Clock().now(),
            )
        )
    session.commit()
    session.close()
    return TestClient(app, base_url="https://app.test")


def start(client: TestClient, idp: FakeIdp) -> str:
    r = client.get("/api/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 303
    target = urlparse(r.headers["location"])
    params: dict[str, str] = {k: v[0] for k, v in parse_qs(target.query).items()}
    assert target.netloc == "idp.test" and params["code_challenge_method"] == "S256"
    assert params["scope"] == "openid scope_all" and params["acr_values"] == "eidas2"
    idp.challenge = params["code_challenge"]
    idp.nonce = params["nonce"]
    return params["state"]


def finish(client: TestClient, state: str) -> str:
    r = client.get(f"/api/auth/oidc/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code == 303
    return str(r.headers["location"])


def test_sign_in_links_the_identity_and_issues_a_session(tmp_path: Path, idp: FakeIdp) -> None:
    with make_client(tmp_path, idp) as client:
        assert client.get("/api/auth/methods").json() == {
            "password": True,
            "oidc_label": "Pro Santé Connect",
        }
        location = finish(client, start(client, idp))
        assert location.startswith("https://app.test/#oidc_token=")
        token = location.split("=", 1)[1]
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert me["user"]["email"] == "coord@g.fr" and me["user"]["oidc_subject"] == "psc-123"
        # Second sign-in matches on the linked subject even if the email changed upstream.
        idp.claims = {"sub": "psc-123", "email": "autre@ailleurs.fr"}
        assert "#oidc_token=" in finish(client, start(client, idp))


def test_professional_identifier_from_userinfo(tmp_path: Path, idp: FakeIdp) -> None:
    idp.claims = {"sub": "psc-999"}  # no email: the RPPS comes from userinfo
    with make_client(tmp_path, idp, match_claim="SubjectNameID") as client:
        location = finish(client, start(client, idp))
        token = location.split("=", 1)[1]
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert me["user"]["email"] == "rpps@g.fr"


@pytest.mark.parametrize(
    "tamper", ["state", "nonce", "audience", "unknown_user", "service_account"]
)
def test_rejections(tmp_path: Path, idp: FakeIdp, tamper: str) -> None:
    with make_client(tmp_path, idp) as client:
        state = start(client, idp)
        if tamper == "state":
            state = "autre-etat"
        elif tamper == "nonce":
            idp.nonce_override = "rejoue"
        elif tamper == "audience":
            idp.audience = "un-autre-client"
        elif tamper == "unknown_user":
            idp.claims = {"sub": "x", "email": "inconnu@g.fr"}
        elif tamper == "service_account":
            idp.claims = {"sub": "y", "email": "agent@g.fr"}
        location = finish(client, state)
        assert "#oidc_error=" in location and "oidc_token" not in location


def test_password_sign_in_can_be_reserved_to_service_accounts(tmp_path: Path, idp: FakeIdp) -> None:
    with make_client(tmp_path, idp, password_login=False) as client:
        people = client.post(
            "/api/auth/login", json={"email": "coord@g.fr", "password": "mot-de-passe-solide"}
        )
        assert people.status_code == 403
        agent = client.post(
            "/api/auth/login", json={"email": "agent@g.fr", "password": "mot-de-passe-solide"}
        )
        assert agent.status_code == 200


def test_disabled_when_not_configured(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'n.db'}",
        secret_key="s" * 40,
        token_ttl_minutes=60,
        password_iterations=1000,
        timezone="Europe/Paris",
        cors_origins=(),
    )
    with TestClient(create_app(settings, Clock())) as client:
        assert client.get("/api/auth/methods").json() == {"password": True, "oidc_label": None}
        assert client.get("/api/auth/oidc/login", follow_redirects=False).status_code == 404
