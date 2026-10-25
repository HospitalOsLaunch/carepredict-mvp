"""Request-scoped dependencies: session, clock, authenticated user and tenant scope."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from services.admissions_smr.clock import Clock
from services.admissions_smr.config import Settings
from services.admissions_smr.models import AuditEntry, Group, User
from services.admissions_smr.security import InvalidToken, read_token
from services.admissions_smr.vocab import READ_ROLES, WRITE_ROLES

# Plain value: the Starlette constant was renamed across versions.
UNPROCESSABLE = 422


def get_session(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ClockDep = Annotated[Clock, Depends(get_clock)]


@dataclass
class Ctx:
    session: Session
    user: User
    group: Group
    clock: Clock
    settings: Settings

    @property
    def site_scope(self) -> int | None:
        """A site id when the user is restricted to one site, otherwise None (all sites)."""
        return self.user.site_id if self.user.role == "coordination" else None

    def can_see_site(self, site_id: int | None) -> bool:
        return self.site_scope is None or site_id == self.site_scope

    def audit(
        self, action: str, entity: str, entity_id: object | None = None, detail: str | None = None
    ) -> None:
        self.session.add(
            AuditEntry(
                group_id=self.group.id,
                user_id=self.user.id,
                at=self.clock.now(),
                action=action,
                entity=entity,
                entity_id=None if entity_id is None else str(entity_id),
                detail=detail,
            )
        )


def _authenticate(
    session: Session,
    settings: Settings,
    clock: Clock,
    authorization: str | None,
) -> tuple[User, Group]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentification requise")
    try:
        user_id = read_token(authorization[7:].strip(), settings.secret_key, clock.now())
    except InvalidToken as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expirée ou invalide") from exc
    user = session.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Compte inactif")
    group = session.get(Group, user.group_id)
    if group is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Groupe introuvable")
    return user, group


def require(roles: frozenset[str]) -> Callable[..., Ctx]:
    def dependency(
        session: SessionDep,
        settings: SettingsDep,
        clock: ClockDep,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Ctx:
        user, group = _authenticate(session, settings, clock, authorization)
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Action non autorisée pour ce rôle")
        return Ctx(session=session, user=user, group=group, clock=clock, settings=settings)

    return dependency


ReadCtx = Annotated[Ctx, Depends(require(READ_ROLES))]
WriteCtx = Annotated[Ctx, Depends(require(WRITE_ROLES))]
AdminCtx = Annotated[Ctx, Depends(require(frozenset({"admin_groupe"})))]
IngestCtx = Annotated[Ctx, Depends(require(frozenset({"ingestion", "admin_groupe"})))]
SyncCtx = Annotated[Ctx, Depends(require(WRITE_ROLES | {"ingestion"}))]
