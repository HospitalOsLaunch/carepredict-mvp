"""Authentication, users, audit trail and shared vocabularies."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from services.admissions_smr.api.deps import (
    UNPROCESSABLE,
    AdminCtx,
    ClockDep,
    ReadCtx,
    SessionDep,
    SettingsDep,
)
from services.admissions_smr.models import AuditEntry, Group, Site, User
from services.admissions_smr.schemas import (
    AuditOut,
    LoginIn,
    LoginOut,
    UserCreate,
    UserOut,
    UserUpdate,
    VocabularyOut,
)
from services.admissions_smr.security import hash_password, issue_token, verify_password
from services.admissions_smr.vocab import (
    CAPACITY_REASONS,
    LOSS_REASONS,
    MENTIONS,
    REFUSAL_REASONS,
    REQUEST_SOURCES,
    REQUEST_STATUSES,
    ROLES,
    SPECIAL_NEEDS,
)

router = APIRouter()


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        site_id=user.site_id,
        active=user.active,
    )


@router.post("/auth/login", response_model=LoginOut, tags=["auth"])
def login(body: LoginIn, session: SessionDep, settings: SettingsDep, clock: ClockDep) -> LoginOut:
    user = session.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None or not user.active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiants incorrects")
    group = session.get(Group, user.group_id)
    assert group is not None
    session.add(
        AuditEntry(
            group_id=group.id,
            user_id=user.id,
            at=clock.now(),
            action="auth.login",
            entity="user",
            entity_id=str(user.id),
        )
    )
    session.commit()
    token = issue_token(user.id, settings.secret_key, settings.token_ttl_minutes, clock.now())
    return LoginOut(token=token, user=user_out(user), group_name=group.name)


@router.get("/auth/me", response_model=LoginOut, tags=["auth"])
def me(ctx: ReadCtx) -> LoginOut:
    return LoginOut(token="", user=user_out(ctx.user), group_name=ctx.group.name)


@router.get("/vocabulary", response_model=VocabularyOut, tags=["meta"])
def vocabulary() -> VocabularyOut:
    return VocabularyOut(
        mentions=MENTIONS,
        sources=REQUEST_SOURCES,
        statuses=REQUEST_STATUSES,
        refusal_reasons=REFUSAL_REASONS,
        loss_reasons=LOSS_REASONS,
        capacity_reasons=CAPACITY_REASONS,
        special_needs=SPECIAL_NEEDS,
        roles=ROLES,
    )


@router.get("/users", response_model=list[UserOut], tags=["admin"])
def list_users(ctx: AdminCtx) -> list[UserOut]:
    users = ctx.session.scalars(
        select(User).where(User.group_id == ctx.group.id).order_by(User.full_name)
    )
    return [user_out(u) for u in users]


def _check_site(ctx: AdminCtx, site_id: int | None) -> None:
    if site_id is None:
        return
    site = ctx.session.get(Site, site_id)
    if site is None or site.group_id != ctx.group.id:
        raise HTTPException(UNPROCESSABLE, "Site inconnu")


@router.post("/users", response_model=UserOut, status_code=201, tags=["admin"])
def create_user(body: UserCreate, ctx: AdminCtx) -> UserOut:
    email = body.email.strip().lower()
    if ctx.session.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cet email est déjà utilisé")
    _check_site(ctx, body.site_id)
    user = User(
        group_id=ctx.group.id,
        email=email,
        full_name=body.full_name,
        password_hash=hash_password(body.password, ctx.settings.password_iterations),
        role=body.role,
        site_id=body.site_id,
        created_at=ctx.clock.now(),
    )
    ctx.session.add(user)
    ctx.session.flush()
    ctx.audit("user.create", "user", user.id, f"{email} ({body.role})")
    ctx.session.commit()
    return user_out(user)


@router.patch("/users/{user_id}", response_model=UserOut, tags=["admin"])
def update_user(user_id: int, body: UserUpdate, ctx: AdminCtx) -> UserOut:
    user = ctx.session.get(User, user_id)
    if user is None or user.group_id != ctx.group.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilisateur introuvable")
    if user.id == ctx.user.id and (
        body.active is False or (body.role and body.role != "admin_groupe")
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Vous ne pouvez pas retirer vos propres droits"
        )
    changes = body.model_dump(exclude_unset=True)
    if "site_id" in changes:
        _check_site(ctx, body.site_id)
        user.site_id = body.site_id
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.role is not None:
        user.role = body.role
    if body.active is not None:
        user.active = body.active
    if body.password is not None:
        user.password_hash = hash_password(body.password, ctx.settings.password_iterations)
    ctx.audit(
        "user.update",
        "user",
        user.id,
        ", ".join(k for k in changes if k != "password")
        + (" + mot de passe" if body.password else ""),
    )
    ctx.session.commit()
    return user_out(user)


@router.get("/audit", response_model=list[AuditOut], tags=["admin"])
def audit_log(ctx: AdminCtx, limit: int = Query(200, ge=1, le=2000)) -> list[AuditOut]:
    names = {
        u.id: u.full_name
        for u in ctx.session.scalars(select(User).where(User.group_id == ctx.group.id))
    }
    rows = ctx.session.scalars(
        select(AuditEntry)
        .where(AuditEntry.group_id == ctx.group.id)
        .order_by(AuditEntry.at.desc(), AuditEntry.id.desc())
        .limit(limit)
    )
    return [
        AuditOut(
            at=r.at,
            user=names.get(r.user_id) if r.user_id else None,
            action=r.action,
            entity=r.entity,
            entity_id=r.entity_id,
            detail=r.detail,
        )
        for r in rows
    ]
