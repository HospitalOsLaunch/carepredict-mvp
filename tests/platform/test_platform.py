"""Pilot accounts, sessions, settings, administration, per-account isolation and the authenticated
gateway.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from hospitalos.platform import security
from hospitalos.platform.app import CSRF_VALUE, USER_HEADER, create_app
from hospitalos.platform.config import ConfigError, Settings, from_env
from hospitalos.platform.emails import ConsoleMailer
from hospitalos.platform.store import Store

H = {"X-Requested-With": CSRF_VALUE}
PASSWORD = "correct-horse-battery-42"


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 24, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw: float) -> None:
        self.t += timedelta(**kw)


def settings(environment: str = "development", **kw: Any) -> Settings:
    base = Settings(
        environment=environment,  # type: ignore[arg-type]
        public_base_url="https://pilote.example.org"
        if environment != "development"
        else "http://localhost:5173",
        database_path=Path(":memory:"),
        hybrid_url="http://hybrid",
        decision_url="http://decision",
        email_from="HospitalOS <no-reply@example.org>",
        email_backend="console",
        ga_measurement_id="G-TEST12345",
        trusted_origins=("https://pilote.example.org",),
    )
    return replace(base, **kw)


class Env:
    def __init__(self, environment: str = "development") -> None:
        self.clock = Clock()
        self.store = Store(":memory:", clock=self.clock)
        self.mailer = ConsoleMailer()
        self.upstream: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            self.upstream.append(request)
            return httpx.Response(
                200, json={"echo": str(request.url), "user": request.headers.get(USER_HEADER)}
            )

        self.settings = settings(environment)
        self.app = create_app(self.settings, self.store, self.mailer, httpx.MockTransport(handler))
        base = "http://testserver" if environment == "development" else "https://testserver"
        self.base = base

    def client(self) -> TestClient:
        return TestClient(self.app, base_url=self.base)

    def link_token(self) -> str:
        match = re.search(r"token=([A-Za-z0-9_\-]+)", self.mailer.sent[-1].text)
        assert match
        return match.group(1)

    def bootstrap_admin(self, email: str = "admin@chu.example") -> TestClient:
        user = self.store.create_invited(email, "admin", "Admin", None)
        token = self.store.create_token(user.id, "invite", timedelta(days=7))
        c = self.client()
        r = c.post(
            "/api/auth/invitation/accept", json={"token": token, "password": PASSWORD}, headers=H
        )
        assert r.status_code == 200, r.text
        return c

    def pilot(self, admin: TestClient, email: str) -> TestClient:
        assert (
            admin.post(
                "/api/admin/users", json={"email": email, "display_name": "Pilote"}, headers=H
            ).status_code
            == 201
        )
        c = self.client()
        r = c.post(
            "/api/auth/invitation/accept",
            json={"token": self.link_token(), "password": PASSWORD},
            headers=H,
        )
        assert r.status_code == 200, r.text
        return c


@pytest.fixture()
def env() -> Env:
    return Env()


# ---------------------------------------------------------------------------- passwords and tokens
def test_password_hash_roundtrip_and_policy() -> None:
    h = security.hash_password(PASSWORD)
    assert h.startswith("scrypt$") and PASSWORD not in h
    assert security.verify_password(PASSWORD, h) and not security.verify_password(
        "wrong-password-123", h
    )
    assert not security.verify_password(PASSWORD, None) and not security.verify_password(
        PASSWORD, "garbage"
    )
    assert security.password_problem("short", "a@b.fr")
    assert security.password_problem("aaaaaaaaaaaaaaaa", "a@b.fr")
    assert security.password_problem("jean.dupont-2026!", "jean.dupont@chu.fr")
    assert security.password_problem(PASSWORD, "x@y.fr") is None
    assert security.token_hash("t") != "t" and len(security.new_token()) >= 40


# ---------------------------------------------------------------------------- invitation, login,
# logout
def test_invitation_flow_login_logout(env: Env) -> None:
    admin = env.bootstrap_admin()
    me = admin.get("/api/auth/me").json()["user"]
    assert me["role"] == "admin" and me["status"] == "active" and "password_hash" not in me
    assert (
        admin.post("/api/admin/users", json={"email": "Pilote@CHU.example"}, headers=H).status_code
        == 201
    )
    msg = env.mailer.sent[-1]
    assert msg.to == "pilote@chu.example" and "#/invitation?token=" in msg.text
    token = env.link_token()
    anon = env.client()
    assert (
        anon.get("/api/auth/invitation", params={"token": token}).json()["email"]
        == "pilote@chu.example"
    )
    weak = anon.post(
        "/api/auth/invitation/accept", json={"token": token, "password": "short"}, headers=H
    )
    assert weak.status_code == 422  # the token is not consumed by a refused password
    ok = anon.post(
        "/api/auth/invitation/accept",
        json={"token": token, "password": PASSWORD, "display_name": "Nadia"},
        headers=H,
    )
    assert ok.status_code == 200 and ok.json()["user"]["display_name"] == "Nadia"
    reuse = env.client().post(
        "/api/auth/invitation/accept", json={"token": token, "password": PASSWORD}, headers=H
    )
    assert reuse.status_code == 404  # single use
    assert anon.post("/api/auth/logout", headers=H).status_code == 200
    assert anon.get("/api/auth/me").status_code == 401
    fresh = env.client()
    assert (
        fresh.post(
            "/api/auth/login", json={"email": "pilote@chu.example", "password": PASSWORD}, headers=H
        ).status_code
        == 200
    )
    assert fresh.get("/api/auth/me").json()["user"]["email"] == "pilote@chu.example"


def test_invitation_expires(env: Env) -> None:
    admin = env.bootstrap_admin()
    admin.post("/api/admin/users", json={"email": "late@chu.example"}, headers=H)
    token = env.link_token()
    env.clock.advance(days=8)
    assert (
        env.client()
        .post("/api/auth/invitation/accept", json={"token": token, "password": PASSWORD}, headers=H)
        .status_code
        == 404
    )


def test_login_errors_are_generic_and_throttled(env: Env) -> None:
    env.bootstrap_admin()
    c = env.client()
    unknown = c.post(
        "/api/auth/login", json={"email": "nobody@chu.example", "password": PASSWORD}, headers=H
    )
    wrong = c.post(
        "/api/auth/login",
        json={"email": "admin@chu.example", "password": "wrong-password-xx"},
        headers=H,
    )
    assert unknown.status_code == wrong.status_code == 401 and unknown.json() == wrong.json()
    for _ in range(4):
        c.post(
            "/api/auth/login",
            json={"email": "admin@chu.example", "password": "wrong-password-xx"},
            headers=H,
        )
    locked = c.post(
        "/api/auth/login", json={"email": "admin@chu.example", "password": PASSWORD}, headers=H
    )
    assert locked.status_code == 429  # even the right password, until the window passes
    env.clock.advance(minutes=16)
    assert (
        c.post(
            "/api/auth/login", json={"email": "admin@chu.example", "password": PASSWORD}, headers=H
        ).status_code
        == 200
    )
    events = [e["action"] for e in env.store.audit_trail()]
    assert "login.failed" in events and "login.throttled" in events
    assert all("password" not in json.dumps(e["detail"]) for e in env.store.audit_trail())


def test_invited_account_cannot_log_in(env: Env) -> None:
    admin = env.bootstrap_admin()
    admin.post("/api/admin/users", json={"email": "pending@chu.example"}, headers=H)
    r = env.client().post(
        "/api/auth/login", json={"email": "pending@chu.example", "password": PASSWORD}, headers=H
    )
    assert r.status_code == 401


def test_session_idle_and_absolute_expiry(env: Env) -> None:
    c = env.bootstrap_admin()
    env.clock.advance(minutes=8 * 60 + 1)
    assert c.get("/api/auth/me").status_code == 401  # idle
    c2 = env.client()
    c2.post("/api/auth/login", json={"email": "admin@chu.example", "password": PASSWORD}, headers=H)
    for _ in range(5):
        env.clock.advance(hours=5)
        last = c2.get("/api/auth/me").status_code
    assert last == 401  # absolute limit (24 h) despite activity


# ---------------------------------------------------------------------------- CSRF and origin
def test_state_changing_requests_need_the_header_and_a_trusted_origin(env: Env) -> None:
    c = env.bootstrap_admin()
    assert c.put("/api/settings", json={"job_title": "Cadre"}).status_code == 403
    bad = c.put(
        "/api/settings",
        json={"job_title": "Cadre"},
        headers={**H, "Origin": "https://evil.example"},
    )
    assert bad.status_code == 403
    assert (
        c.put(
            "/api/settings",
            json={"job_title": "Cadre"},
            headers={**H, "Origin": "http://localhost:5173"},
        ).status_code
        == 200
    )


def test_secure_cookie_outside_development() -> None:
    env = Env("staging")
    c = env.bootstrap_admin()
    cookie = next(cj for cj in c.cookies.jar)
    assert cookie.name == "__Host-hos_session" and cookie.secure
    assert c.get("/api/auth/me").status_code == 200


# ---------------------------------------------------------------------------- password reset and
# change
def test_password_reset_flow_revokes_sessions(env: Env) -> None:
    admin = env.bootstrap_admin()
    pilot = env.pilot(admin, "p@chu.example")
    r = env.client().post("/api/auth/password/forgot", json={"email": "p@chu.example"}, headers=H)
    assert r.status_code == 202
    unknown = env.client().post(
        "/api/auth/password/forgot", json={"email": "nobody@chu.example"}, headers=H
    )
    assert unknown.status_code == 202 and unknown.json() == r.json()  # no account enumeration
    token = env.link_token()
    assert "#/reinitialisation?token=" in env.mailer.sent[-1].text
    new = "another-strong-passphrase-7"
    assert (
        env.client()
        .post("/api/auth/password/reset", json={"token": token, "password": new}, headers=H)
        .status_code
        == 200
    )
    assert pilot.get("/api/auth/me").status_code == 401  # existing sessions revoked
    assert (
        env.client()
        .post("/api/auth/password/reset", json={"token": token, "password": new}, headers=H)
        .status_code
        == 404
    )
    c = env.client()
    assert (
        c.post(
            "/api/auth/login", json={"email": "p@chu.example", "password": new}, headers=H
        ).status_code
        == 200
    )


def test_reset_link_expires(env: Env) -> None:
    admin = env.bootstrap_admin()
    env.pilot(admin, "p@chu.example")
    env.client().post("/api/auth/password/forgot", json={"email": "p@chu.example"}, headers=H)
    token = env.link_token()
    env.clock.advance(minutes=61)
    r = env.client().post(
        "/api/auth/password/reset",
        json={"token": token, "password": "another-strong-passphrase-7"},
        headers=H,
    )
    assert r.status_code == 404


def test_change_password_requires_current_and_keeps_this_session(env: Env) -> None:
    admin = env.bootstrap_admin()
    other_device = env.client()
    other_device.post(
        "/api/auth/login", json={"email": "admin@chu.example", "password": PASSWORD}, headers=H
    )
    bad = admin.post(
        "/api/settings/password",
        json={"current_password": "nope-nope-nope", "new_password": "x" * 13},
        headers=H,
    )
    assert bad.status_code == 403
    ok = admin.post(
        "/api/settings/password",
        json={"current_password": PASSWORD, "new_password": "brand-new-passphrase-9"},
        headers=H,
    )
    assert ok.status_code == 200
    assert admin.get("/api/auth/me").status_code == 200
    assert other_device.get("/api/auth/me").status_code == 401


# ---------------------------------------------------------------------------- settings
def test_profile_and_analytics_consent(env: Env) -> None:
    c = env.bootstrap_admin()
    r = c.put(
        "/api/settings",
        json={
            "display_name": " Sophie L. ",
            "job_title": "Cadre de santé",
            "establishment": "CHU",
            "default_unit": "U2",
            "analytics_consent": True,
        },
        headers=H,
    )
    user = r.json()["user"]
    assert (
        user["display_name"],
        user["job_title"],
        user["default_unit"],
        user["analytics_consent"],
    ) == ("Sophie L.", "Cadre de santé", "U2", True)
    assert (
        c.put("/api/settings", json={"clear_analytics_consent": True}, headers=H).json()["user"][
            "analytics_consent"
        ]
        is None
    )
    assert c.put("/api/settings", json={"job_title": "x" * 81}, headers=H).status_code == 422


# ---------------------------------------------------------------------------- administration
def test_admin_only_and_last_admin_protection(env: Env) -> None:
    admin = env.bootstrap_admin()
    pilot = env.pilot(admin, "p@chu.example")
    assert pilot.get("/api/admin/users").status_code == 403
    assert (
        pilot.post("/api/admin/users", json={"email": "x@chu.example"}, headers=H).status_code
        == 403
    )
    users = admin.get("/api/admin/users").json()["users"]
    me = next(u for u in users if u["role"] == "admin")
    assert (
        admin.patch(
            f"/api/admin/users/{me['id']}", json={"status": "disabled"}, headers=H
        ).status_code
        == 409
    )
    assert (
        admin.post("/api/admin/users", json={"email": "p@chu.example"}, headers=H).status_code
        == 409
    )
    assert (
        admin.post("/api/admin/users", json={"email": "not-an-email"}, headers=H).status_code == 422
    )


def test_disabling_a_pilot_revokes_access(env: Env) -> None:
    admin = env.bootstrap_admin()
    pilot = env.pilot(admin, "p@chu.example")
    pid = pilot.get("/api/auth/me").json()["user"]["id"]
    assert (
        admin.patch(f"/api/admin/users/{pid}", json={"status": "disabled"}, headers=H).json()[
            "user"
        ]["status"]
        == "disabled"
    )
    assert pilot.get("/api/auth/me").status_code == 401
    assert (
        env.client()
        .post("/api/auth/login", json={"email": "p@chu.example", "password": PASSWORD}, headers=H)
        .status_code
        == 401
    )
    assert (
        admin.patch(f"/api/admin/users/{pid}", json={"status": "active"}, headers=H).status_code
        == 200
    )


def test_resend_invitation_invalidates_previous_link(env: Env) -> None:
    admin = env.bootstrap_admin()
    admin.post("/api/admin/users", json={"email": "p@chu.example"}, headers=H)
    first = env.link_token()
    pid = next(
        u["id"]
        for u in admin.get("/api/admin/users").json()["users"]
        if u["email"] == "p@chu.example"
    )
    assert admin.post(f"/api/admin/users/{pid}/resend", headers=H).status_code == 200
    second = env.link_token()
    assert (
        env.client()
        .post("/api/auth/invitation/accept", json={"token": first, "password": PASSWORD}, headers=H)
        .status_code
        == 404
    )
    assert (
        env.client()
        .post(
            "/api/auth/invitation/accept", json={"token": second, "password": PASSWORD}, headers=H
        )
        .status_code
        == 200
    )


# ---------------------------------------------------------------------------- isolation
def test_journals_are_isolated_and_revisioned(env: Env) -> None:
    admin = env.bootstrap_admin()
    a, b = env.pilot(admin, "a@chu.example"), env.pilot(admin, "b@chu.example")
    assert a.put(
        "/api/journal", json={"base_revision": 0, "records": [{"id": "r1"}]}, headers=H
    ).json() == {"revision": 1}
    assert b.get("/api/journal").json() == {"revision": 0, "records": []}
    stale = a.put(
        "/api/journal", json={"base_revision": 0, "records": [{"id": "other"}]}, headers=H
    )
    assert stale.status_code == 409 and stale.json()["detail"]["revision"] == 1
    assert a.get("/api/journal").json()["records"] == [{"id": "r1"}]
    big = a.put(
        "/api/journal",
        content=b'{"base_revision":1,"records":["' + b"x" * (3 * 1024 * 1024) + b'"]}',
        headers={**H, "Content-Type": "application/json"},
    )
    assert big.status_code == 413
    assert env.client().get("/api/journal").status_code == 401


def test_gateway_requires_a_session_and_sets_the_account_header(env: Env) -> None:
    admin = env.bootstrap_admin()
    a, b = env.pilot(admin, "a@chu.example"), env.pilot(admin, "b@chu.example")
    assert env.client().get("/api/health").status_code == 401
    assert env.upstream == []
    spoof = {USER_HEADER: "someone-else"}
    ra = a.get("/api/decision/auto", params={"unit": "nominal_auto"}, headers=spoof).json()
    rb = b.post("/api/hybrid/plan", json={"x": 1}, headers={**H, **spoof}).json()
    assert ra["echo"] == "http://decision/api/auto?unit=nominal_auto"
    assert rb["echo"] == "http://hybrid/hybrid/plan"
    ida, idb = (
        a.get("/api/auth/me").json()["user"]["id"],
        b.get("/api/auth/me").json()["user"]["id"],
    )
    assert (ra["user"], rb["user"]) == (ida, idb) and ida != idb  # client-sent header is replaced


def test_engine_down_is_a_502(env: Env) -> None:
    async def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    app = create_app(env.settings, env.store, env.mailer, httpx.MockTransport(down))
    c = TestClient(app)
    user = env.store.create_invited("x@chu.example", "pilot", "", None)
    env.store.activate(user.id, security.hash_password(PASSWORD))
    c.post("/api/auth/login", json={"email": "x@chu.example", "password": PASSWORD}, headers=H)
    assert c.get("/api/health").status_code == 502


# ---------------------------------------------------------------------------- configuration
def test_analytics_only_exposed_in_production() -> None:
    for environment, expected in (
        ("development", None),
        ("staging", None),
        ("production", "G-TEST12345"),
    ):
        cfg = TestClient(Env(environment).app).get("/api/config").json()
        assert (cfg["analytics"] or {}).get("measurement_id") == expected
        assert cfg["environment"] == environment


def test_from_env_refuses_unsafe_production(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "APP_ENV",
        "PUBLIC_BASE_URL",
        "EMAIL_BACKEND",
        "PLATFORM_DB",
        "EMAIL_FROM",
        "GA_MEASUREMENT_ID",
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ConfigError):
        from_env()  # no base URL, database, sender
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://pilote.example.org")
    monkeypatch.setenv("PLATFORM_DB", "/data/platform.sqlite3")
    monkeypatch.setenv("EMAIL_FROM", "x@y.fr")
    with pytest.raises(ConfigError, match="https"):
        from_env()
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://pilote.example.org")
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    with pytest.raises(ConfigError, match="console"):
        from_env()
    monkeypatch.setenv("EMAIL_BACKEND", "smtp")
    with pytest.raises(ConfigError, match="SMTP_HOST"):
        from_env()
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("SMTP_USERNAME", "u")
    monkeypatch.setenv("SMTP_PASSWORD", "p")
    monkeypatch.setenv("GA_MEASUREMENT_ID", "UA-123")
    with pytest.raises(ConfigError, match="GA_MEASUREMENT_ID"):
        from_env()
    monkeypatch.setenv("GA_MEASUREMENT_ID", "G-ABC123")
    assert from_env().analytics_id == "G-ABC123"


def test_store_migrations_are_idempotent_and_backup_works(tmp_path: Path) -> None:
    store = Store(tmp_path / "p.sqlite3")
    store.create_invited("a@b.fr", "pilot", "", None)
    assert store.migrate() == store.migrate()
    store.backup(tmp_path / "copy.sqlite3")
    assert Store(tmp_path / "copy.sqlite3").user_by_email("a@b.fr") is not None
