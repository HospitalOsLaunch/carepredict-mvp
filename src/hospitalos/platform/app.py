"""HospitalOS platform API and authenticated gateway.

Everything under ``/api`` goes through this service:

* ``/api/auth/*``      login, logout, current account, invitation acceptance, password reset
* ``/api/settings*``   the account's own profile, preferences, password and sessions
* ``/api/admin/*``     account administration (role ``admin``): invite, resend, role/status, audit
trail
* ``/api/journal``     the account's decision journal (one document per account, optimistic
revisions)
* ``/api/config``      public runtime configuration (environment, release, analytics id in
production only)
* ``/api/platform/health``  liveness for deployment smoke tests
* ``/api/decision/*``  -> 24-hour planner engine, ``/api/*`` (other) -> hybrid engine;
authenticated, with the
  account's opaque id in ``X-HospitalOS-User`` so that each pilot works in an isolated space.

Sessions: random token in an HttpOnly, SameSite=Strict cookie (``__Host-`` prefixed and Secure
outside
development), stored hashed, idle and absolute expiry. Every state-changing request must carry
``X-Requested-With: HospitalOS`` (not sendable cross-site without CORS, which is not enabled) and,
when the
browser sends an Origin, a trusted one.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated, Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import emails, security
from .config import Settings, from_env
from .store import RevisionConflict, Role, Store, User, normalise_email

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "HospitalOS"
USER_HEADER = "X-HospitalOS-User"
MAX_JOURNAL_BYTES = 2 * 1024 * 1024
LOGIN_WINDOW = timedelta(minutes=15)
MAX_FAILURES_PER_EMAIL = 5
MAX_FAILURES_PER_IP = 30
GENERIC_LOGIN_ERROR = "Adresse email ou mot de passe incorrect."
INVALID_LINK = "Ce lien n'est plus valable. Demandez-en un nouveau."
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


# ---------------------------------------------------------------------------- request bodies
class LoginBody(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=security.MAX_PASSWORD)


class AcceptBody(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=security.MAX_PASSWORD)
    display_name: str | None = Field(default=None, max_length=80)


class ForgotBody(BaseModel):
    email: str = Field(max_length=254)


class ResetBody(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=security.MAX_PASSWORD)


class ProfileBody(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    job_title: str | None = Field(default=None, max_length=80)
    establishment: str | None = Field(default=None, max_length=120)
    default_unit: str | None = Field(default=None, max_length=80)
    analytics_consent: bool | None = None
    clear_analytics_consent: bool = False


class PasswordBody(BaseModel):
    current_password: str = Field(max_length=security.MAX_PASSWORD)
    new_password: str = Field(max_length=security.MAX_PASSWORD)


class InviteBody(BaseModel):
    email: str = Field(max_length=254)
    role: Role = "pilot"
    display_name: str = Field(default="", max_length=80)


class AdminUpdateBody(BaseModel):
    role: Role | None = None
    status: Literal["active", "disabled"] | None = None


class JournalBody(BaseModel):
    base_revision: int = Field(ge=0)
    records: list[Any]


def _valid_email(email: str) -> bool:
    local, _, domain = email.partition("@")
    return bool(local) and "." in domain and " " not in email and len(email) <= 254


# ---------------------------------------------------------------------------- application
def create_app(
    settings: Settings,
    store: Store | None = None,
    mailer: emails.Mailer | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    store = store or Store(settings.database_path)
    mailer = mailer or emails.mailer_for(settings)
    upstream = httpx.AsyncClient(transport=transport, timeout=30.0)
    cookie = "__Host-hos_session" if settings.cookie_secure else "hos_session"

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await upstream.aclose()

    app = FastAPI(
        title="HospitalOS platform",
        version=settings.release,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings, app.state.store, app.state.mailer = settings, store, mailer

    # ------------------------------------------------------------------ cross-cutting checks
    @app.middleware("http")
    async def guard(request: Request, call_next: Any) -> Response:
        if request.method in UNSAFE and request.url.path.startswith("/api/"):
            if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
                return Response(
                    json.dumps({"detail": "Requête refusée (en-tête de sécurité manquant)."}),
                    403,
                    media_type="application/json",
                )
            origin = request.headers.get("origin")
            allowed = set(settings.trusted_origins)
            if settings.environment == "development":
                allowed |= {"http://localhost:5173", "http://127.0.0.1:5173"}
            if origin is not None and origin not in allowed:
                return Response(
                    json.dumps({"detail": "Origine non autorisée."}),
                    403,
                    media_type="application/json",
                )
        response: Response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    def client_ip(request: Request) -> str:
        # Set by the cockpit proxy from the edge's X-Forwarded-For (only the edge is reachable from
        # outside).
        return request.headers.get("x-client-ip") or (
            request.client.host if request.client else "unknown"
        )

    def set_session_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            cookie,
            token,
            max_age=settings.session_absolute_hours * 3600,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            path="/",
        )

    def current_user(request: Request) -> User:
        token = request.cookies.get(cookie)
        user = store.session_user(token, settings.session_idle_minutes) if token else None
        if user is None:
            raise HTTPException(401, "Session expirée ou absente. Connectez-vous.")
        return user

    def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role != "admin":
            raise HTTPException(403, "Réservé aux administrateurs.")
        return user

    CurrentUser = Annotated[User, Depends(current_user)]
    AdminUser = Annotated[User, Depends(admin_user)]

    def me_payload(user: User) -> dict[str, Any]:
        return {"user": user.public(), "environment": settings.environment}

    def link(path: str, token: str) -> str:
        return f"{settings.public_base_url}/#/{path}?token={token}"

    # ------------------------------------------------------------------ public
    @app.get("/api/platform/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment, "release": settings.release}

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        ga = settings.analytics_id
        return {
            "environment": settings.environment,
            "release": settings.release,
            "analytics": {"provider": "ga4", "measurement_id": ga} if ga else None,
        }

    # ------------------------------------------------------------------ authentication
    @app.post("/api/auth/login")
    def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
        email, ip = normalise_email(body.email), client_ip(request)
        by_email, by_ip = store.failures(email, ip, LOGIN_WINDOW)
        if by_email >= MAX_FAILURES_PER_EMAIL or by_ip >= MAX_FAILURES_PER_IP:
            store.audit(None, "login.throttled", None, {"ip": ip})
            raise HTTPException(429, "Trop de tentatives. Réessayez dans 15 minutes.")
        user = store.user_by_email(email)
        ok = security.verify_password(body.password, user.password_hash if user else None)
        if not ok or user is None or user.status != "active":
            store.record_failure(email, ip)
            store.audit(
                user.id if user else None, "login.failed", user.id if user else None, {"ip": ip}
            )
            raise HTTPException(401, GENERIC_LOGIN_ERROR)
        store.clear_failures(email)
        set_session_cookie(
            response,
            store.create_session(
                user.id, settings.session_absolute_hours, request.headers.get("user-agent", "")
            ),
        )
        return me_payload(user)

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        token = request.cookies.get(cookie)
        if token:
            store.delete_session(token)
        response.delete_cookie(
            cookie, path="/", secure=settings.cookie_secure, httponly=True, samesite="strict"
        )
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(user: CurrentUser) -> dict[str, Any]:
        return me_payload(user)

    @app.get("/api/auth/invitation")
    def invitation(token: str) -> dict[str, str]:
        user = store.peek_token(token, "invite")
        if user is None or user.status != "invited":
            raise HTTPException(404, INVALID_LINK)
        return {"email": user.email, "display_name": user.display_name}

    @app.post("/api/auth/invitation/accept")
    def accept(body: AcceptBody, request: Request, response: Response) -> dict[str, Any]:
        pending = store.peek_token(body.token, "invite")
        if pending is None or pending.status != "invited":
            raise HTTPException(404, INVALID_LINK)
        problem = security.password_problem(body.password, pending.email)
        if problem:
            raise HTTPException(422, problem)
        user = store.consume_token(body.token, "invite")
        if user is None:
            raise HTTPException(404, INVALID_LINK)
        store.activate(user.id, security.hash_password(body.password))
        if body.display_name:
            store.update_profile(user.id, {"display_name": body.display_name.strip()})
        active = store.user_by_id(user.id)
        assert active is not None
        set_session_cookie(
            response,
            store.create_session(
                active.id, settings.session_absolute_hours, request.headers.get("user-agent", "")
            ),
        )
        return me_payload(active)

    @app.post("/api/auth/password/forgot", status_code=202)
    def forgot(body: ForgotBody, request: Request) -> dict[str, str]:
        ip = client_ip(request)
        _, by_ip = store.failures("", ip, LOGIN_WINDOW)
        if by_ip >= MAX_FAILURES_PER_IP:
            raise HTTPException(429, "Trop de demandes. Réessayez dans 15 minutes.")
        store.record_failure(
            "", ip
        )  # counts towards the per-IP throttle; never reveals whether the account exists
        user = store.user_by_email(body.email)
        if user is not None and user.status == "active":
            token = store.create_token(user.id, "reset", timedelta(minutes=settings.reset_minutes))
            mailer.send(
                emails.password_reset(
                    user.email, link("reinitialisation", token), settings.reset_minutes
                )
            )
            store.audit(user.id, "password.reset_requested", user.id, {})
        return {
            "detail": "Si un compte actif correspond à cette adresse, un email vient d'être envoyé."
        }

    @app.post("/api/auth/password/reset")
    def reset(body: ResetBody) -> dict[str, str]:
        pending = store.peek_token(body.token, "reset")
        if pending is None or pending.status != "active":
            raise HTTPException(404, INVALID_LINK)
        problem = security.password_problem(body.password, pending.email)
        if problem:
            raise HTTPException(422, problem)
        user = store.consume_token(body.token, "reset")
        if user is None:
            raise HTTPException(404, INVALID_LINK)
        store.set_password(user.id, security.hash_password(body.password), user.id, "reset")
        store.clear_failures(user.email)
        return {"detail": "Mot de passe modifié. Vous pouvez vous connecter."}

    # ------------------------------------------------------------------ the account's own settings
    @app.get("/api/settings")
    def settings_get(user: CurrentUser) -> dict[str, Any]:
        return me_payload(user)

    @app.put("/api/settings")
    def settings_put(body: ProfileBody, user: CurrentUser) -> dict[str, Any]:
        fields: dict[str, Any] = {
            k: v.strip()
            for k, v in body.model_dump(exclude_none=True).items()
            if isinstance(v, str)
        }
        if body.analytics_consent is not None:
            fields["analytics_consent"] = body.analytics_consent
        if body.clear_analytics_consent:
            fields["analytics_consent"] = None
        return me_payload(store.update_profile(user.id, fields))

    @app.post("/api/settings/password")
    def settings_password(
        body: PasswordBody, user: CurrentUser, request: Request, response: Response
    ) -> dict[str, Any]:
        if not security.verify_password(body.current_password, user.password_hash):
            raise HTTPException(403, "Mot de passe actuel incorrect.")
        problem = security.password_problem(body.new_password, user.email)
        if problem:
            raise HTTPException(422, problem)
        store.set_password(
            user.id, security.hash_password(body.new_password), user.id, "changed"
        )  # revokes all sessions
        set_session_cookie(
            response,
            store.create_session(
                user.id, settings.session_absolute_hours, request.headers.get("user-agent", "")
            ),
        )
        return me_payload(user)

    @app.post("/api/settings/sessions/revoke-others")
    def revoke_others(user: CurrentUser, request: Request) -> dict[str, bool]:
        store.delete_sessions_except(user.id, request.cookies.get(cookie))
        store.audit(user.id, "session.revoked_others", user.id, {})
        return {"ok": True}

    # ------------------------------------------------------------------ administration
    @app.get("/api/admin/users")
    def admin_users(admin: AdminUser) -> dict[str, Any]:
        return {"users": [u.public() for u in store.users()]}

    @app.post("/api/admin/users", status_code=201)
    def admin_invite(body: InviteBody, admin: AdminUser) -> dict[str, Any]:
        email = normalise_email(body.email)
        if not _valid_email(email):
            raise HTTPException(422, "Adresse email invalide.")
        if store.user_by_email(email) is not None:
            raise HTTPException(409, "Un compte existe déjà pour cette adresse.")
        user = store.create_invited(email, body.role, body.display_name, admin.id)
        token = store.create_token(user.id, "invite", timedelta(days=settings.invitation_days))
        mailer.send(
            emails.invitation(
                email,
                link("invitation", token),
                admin.display_name or admin.email,
                settings.invitation_days,
            )
        )
        return {"user": user.public()}

    def target(public_id: str) -> User:
        user = store.user_by_public_id(public_id)
        if user is None:
            raise HTTPException(404, "Compte introuvable.")
        return user

    @app.post("/api/admin/users/{public_id}/resend")
    def admin_resend(public_id: str, admin: AdminUser) -> dict[str, Any]:
        user = target(public_id)
        if user.status != "invited":
            raise HTTPException(409, "Ce compte n'est plus en attente d'invitation.")
        token = store.create_token(user.id, "invite", timedelta(days=settings.invitation_days))
        mailer.send(
            emails.invitation(
                user.email,
                link("invitation", token),
                admin.display_name or admin.email,
                settings.invitation_days,
            )
        )
        store.audit(admin.id, "user.invitation_resent", user.id, {})
        return {"user": user.public()}

    @app.patch("/api/admin/users/{public_id}")
    def admin_update(public_id: str, body: AdminUpdateBody, admin: AdminUser) -> dict[str, Any]:
        user = target(public_id)
        if user.id == admin.id and (body.status == "disabled" or body.role == "pilot"):
            raise HTTPException(
                409, "Vous ne pouvez pas retirer vos propres droits ni désactiver votre compte."
            )
        demoting = (
            user.role == "admin"
            and user.status == "active"
            and (body.role == "pilot" or body.status == "disabled")
        )
        if demoting and store.admin_count() <= 1:
            raise HTTPException(409, "Il doit rester au moins un administrateur actif.")
        status = body.status
        if status == "active" and user.status == "invited":
            raise HTTPException(409, "Un compte invité devient actif en acceptant son invitation.")
        return {"user": store.set_role_status(user.id, admin.id, body.role, status).public()}

    @app.get("/api/admin/audit")
    def admin_audit(admin: AdminUser) -> dict[str, Any]:
        return {"events": store.audit_trail()}

    # ------------------------------------------------------------------ the account's journal
    @app.get("/api/journal")
    def journal_get(user: CurrentUser) -> dict[str, Any]:
        revision, records = store.journal(user.id)
        return {"revision": revision, "records": records}

    @app.put("/api/journal")
    async def journal_put(request: Request, user: CurrentUser) -> dict[str, Any]:
        raw = await request.body()
        if len(raw) > MAX_JOURNAL_BYTES:
            raise HTTPException(413, "Journal trop volumineux.")
        try:
            body = JournalBody.model_validate_json(raw)
        except ValueError as error:
            raise HTTPException(422, "Journal invalide.") from error
        try:
            revision = store.save_journal(user.id, body.base_revision, body.records)
        except RevisionConflict as error:
            current, records = store.journal(user.id)
            raise HTTPException(
                409,
                {
                    "message": "Le journal a changé ailleurs.",
                    "revision": current,
                    "records": records,
                },
            ) from error
        return {"revision": revision}

    # ------------------------------------------------------------------ authenticated gateway to
    # the engines
    async def forward(base: str, path: str, request: Request, user: User) -> Response:
        headers = {
            k: v for k, v in request.headers.items() if k.lower() in ("content-type", "accept")
        }
        headers[USER_HEADER] = user.public_id
        try:
            upstream_response = await upstream.request(
                request.method,
                f"{base}/{path}",
                params=request.query_params,
                content=await request.body(),
                headers=headers,
            )
        except httpx.HTTPError as error:
            raise HTTPException(502, "Moteur indisponible.") from error
        kind = upstream_response.headers.get("content-type", "application/json")
        return Response(upstream_response.content, upstream_response.status_code, media_type=kind)

    @app.api_route("/api/decision/{path:path}", methods=["GET", "POST"])
    async def decision(path: str, request: Request, user: CurrentUser) -> Response:
        return await forward(f"{settings.decision_url}/api", path, request, user)

    @app.api_route("/api/{path:path}", methods=["GET", "POST"])
    async def hybrid(path: str, request: Request, user: CurrentUser) -> Response:
        return await forward(settings.hybrid_url, path, request, user)

    return app


def app_from_env() -> FastAPI:
    """Entry point for ``uvicorn --factory hospitalos.platform.app:app_from_env``."""
    return create_app(from_env())
