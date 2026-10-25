"""OpenID Connect: authorization code flow with PKCE, nonce and state, ID token checked against
the provider's JWKS (signature, issuer, audience, expiry, nonce).

Works with Pro Santé Connect (scopes ``openid scope_all``, ``acr_values`` set per
environment, endpoints given explicitly when discovery is not used) and with any
standard provider (Entra ID, Keycloak, Okta...). Accounts are never created on the fly:
an administrator creates the user, and the first sign-in links the provider identity.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from services.admissions_smr.config import OidcSettings
from services.admissions_smr.security import InvalidToken, _b64, _sign, _unb64

ALLOWED_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384"]
FLOW_TTL_SECONDS = 600
LEEWAY_SECONDS = 60


class OidcError(RuntimeError):
    pass


@dataclass(frozen=True)
class Flow:
    state: str
    nonce: str
    verifier: str

    @property
    def challenge(self) -> str:
        return _b64(hashlib.sha256(self.verifier.encode()).digest())


def new_flow() -> Flow:
    return Flow(secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48))


def pack_flow(flow: Flow, secret: str) -> str:
    body = _b64(
        json.dumps(
            {
                "s": flow.state,
                "n": flow.nonce,
                "v": flow.verifier,
                "e": int(time.time()) + FLOW_TTL_SECONDS,
            }
        ).encode()
    )
    return f"{body}.{_sign(body, secret)}"


def unpack_flow(cookie: str, secret: str) -> Flow:
    try:
        body, signature = cookie.split(".")
    except ValueError as exc:
        raise InvalidToken("cookie OIDC invalide") from exc
    if not secrets.compare_digest(signature, _sign(body, secret)):
        raise InvalidToken("cookie OIDC altéré")
    data = json.loads(_unb64(body))
    if int(data["e"]) < time.time():
        raise InvalidToken("connexion trop longue, recommencez")
    return Flow(data["s"], data["n"], data["v"])


class OidcProvider:
    def __init__(self, settings: OidcSettings, http: httpx.Client) -> None:
        self.settings = settings
        self.http = http
        self._metadata: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None

    def metadata(self) -> dict[str, Any]:
        if self._metadata is None:
            s = self.settings
            explicit = {
                "authorization_endpoint": s.authorization_endpoint,
                "token_endpoint": s.token_endpoint,
                "jwks_uri": s.jwks_uri,
                "userinfo_endpoint": s.userinfo_endpoint,
            }
            if all(explicit[k] for k in ("authorization_endpoint", "token_endpoint", "jwks_uri")):
                self._metadata = {"issuer": s.issuer, **explicit}
            else:
                r = self.http.get(f"{s.issuer}/.well-known/openid-configuration", timeout=10)
                if r.status_code != 200:
                    raise OidcError("fournisseur d'identité injoignable")
                discovered: dict[str, Any] = r.json()
                if discovered.get("issuer", "").rstrip("/") != s.issuer:
                    raise OidcError("l'émetteur annoncé ne correspond pas à la configuration")
                self._metadata = {**discovered, **{k: v for k, v in explicit.items() if v}}
        return self._metadata

    def authorize_url(self, flow: Flow) -> str:
        params = {
            "response_type": "code",
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "scope": self.settings.scopes,
            "state": flow.state,
            "nonce": flow.nonce,
            "code_challenge": flow.challenge,
            "code_challenge_method": "S256",
        }
        if self.settings.acr_values:
            params["acr_values"] = self.settings.acr_values
        return f"{self.metadata()['authorization_endpoint']}?{urlencode(params)}"

    def exchange(self, code: str, flow: Flow) -> dict[str, Any]:
        r = self.http.post(
            self.metadata()["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.redirect_uri,
                "code_verifier": flow.verifier,
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
            },
            timeout=15,
        )
        if r.status_code != 200:
            raise OidcError("le fournisseur d'identité a refusé l'échange du code")
        tokens: dict[str, Any] = r.json()
        if "id_token" not in tokens:
            raise OidcError("jeton d'identité absent")
        return tokens

    def _key_for(self, token: str) -> Any:
        header = jwt.get_unverified_header(token)
        if header.get("alg") not in ALLOWED_ALGORITHMS:
            raise OidcError("algorithme de signature refusé")
        for refresh in (False, True):
            if self._jwks is None or refresh:
                r = self.http.get(self.metadata()["jwks_uri"], timeout=10)
                if r.status_code != 200:
                    raise OidcError("clés du fournisseur indisponibles")
                self._jwks = r.json()
            for key in self._jwks.get("keys", []):
                if key.get("kid") == header.get("kid"):
                    return jwt.PyJWK(key).key
        raise OidcError("clé de signature inconnue")

    def verify_id_token(self, token: str, nonce: str) -> dict[str, Any]:
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                self._key_for(token),
                algorithms=ALLOWED_ALGORITHMS,
                audience=self.settings.client_id,
                issuer=self.settings.issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise OidcError(f"jeton d'identité invalide : {exc}") from exc
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise OidcError("nonce invalide")
        return claims

    def userinfo(self, access_token: str) -> dict[str, Any]:
        endpoint = self.metadata().get("userinfo_endpoint")
        if not endpoint:
            return {}
        r = self.http.get(endpoint, headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        if r.status_code != 200:
            raise OidcError("informations utilisateur indisponibles")
        if r.headers.get("content-type", "").startswith("application/jwt"):
            token = r.text.strip()
            try:
                info: dict[str, Any] = jwt.decode(
                    token,
                    self._key_for(token),
                    algorithms=ALLOWED_ALGORITHMS,
                    audience=self.settings.client_id,
                    options={"verify_aud": False},
                )
            except jwt.PyJWTError as exc:
                raise OidcError(f"informations utilisateur invalides : {exc}") from exc
            return info
        data: dict[str, Any] = r.json()
        return data


def claim_value(claims: dict[str, Any], name: str) -> str | None:
    value = claims.get(name)
    if value is None:
        return None
    return str(value).strip() or None
