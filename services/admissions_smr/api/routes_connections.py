"""Computer use piloted from the interface: workers ("postes") and connections.

Rights (docs/agent/CONNEXIONS_SPEC.md):

* ``admin_groupe`` creates, edits and archives connections (and their secret);
* ``coordination`` starts, pauses, resumes and syncs the connections of its site (all of
  them when it is not limited to a site; group-wide connections only then);
* ``direction`` reads. Another group's connection is a 404.

The secret is write-only: responses carry ``secret_set`` and ``secret_updated_at``, never
the value, and audit entries only say that it changed.
"""

from __future__ import annotations

import ipaddress
import json
import re
from datetime import datetime, time, timedelta
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from services.admissions_smr import agent_connections as connections
from services.admissions_smr.api.deps import UNPROCESSABLE, AdminCtx, Ctx, ReadCtx, WriteCtx
from services.admissions_smr.api.routes_agent import (
    ONLINE_MINUTES,
    ConnectionKind,
    EngineReport,
    PlaybookInfo,
    TaskKind,
    TaskOut,
    get_state,
    task_out,
)
from services.admissions_smr.api.routes_replay import can_watch
from services.admissions_smr.domain.connector_secrets import encrypt
from services.admissions_smr.models import (
    AdmissionRequest,
    AgentConnection,
    AgentTask,
    AgentTaskStep,
    AgentWorker,
    Site,
    User,
)

router = APIRouter(prefix="/agent", tags=["agent"])

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOST = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})*$")
_SOURCE = re.compile(r"^[A-Za-z0-9_./^-]{1,60}$")


# --- schemas ---------------------------------------------------------------------------


class WorkerOut(BaseModel):
    agent_id: str
    site_id: int | None
    online: bool
    last_heartbeat_at: datetime | None
    version: str | None
    engines: list[EngineReport]
    playbooks: list[PlaybookInfo]


class ConnectionOut(BaseModel):
    id: int
    name: str
    kind: str
    site_id: int | None
    site_name: str | None
    url: str
    allowed_hosts: list[str]
    username: str | None
    secret_set: bool
    secret_updated_at: datetime | None
    playbook: str
    tasks: list[str]
    source_system: str | None
    interval_minutes: int
    active_from: str | None  # "HH:MM", local time; null = from midnight
    active_to: str | None  # "HH:MM", local time; null = until midnight
    days: list[int]  # ISO weekdays, 1 = Monday
    agent_id: str | None
    status: str
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_outcome: str | None
    last_error: str | None
    pending_tasks: int
    needs_human: int
    running_task_id: int | None  # the task in progress (player: "Regarder en direct")
    can_control: bool
    can_edit: bool


class RunOut(TaskOut):
    """A run of a connection, with what the player can show of it to this viewer."""

    has_replay: bool
    steps_count: int


Day = Literal[1, 2, 3, 4, 5, 6, 7]


class ConnectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    kind: ConnectionKind
    site_id: int | None = None
    url: str = Field(min_length=1, max_length=500)
    allowed_hosts: list[str] = Field(default_factory=list, max_length=10)
    username: str | None = Field(default=None, max_length=200)
    secret: str | None = Field(default=None, min_length=1, max_length=500)
    playbook: str = Field(min_length=1, max_length=80)
    tasks: list[TaskKind] = Field(min_length=1, max_length=3)
    source_system: str | None = Field(default=None, max_length=60)
    interval_minutes: int = Field(default=10, ge=1, le=1440)
    active_from: time | None = None
    active_to: time | None = None
    days: list[Day] | None = Field(default=None, min_length=1)  # null: every day
    agent_id: str | None = Field(default=None, min_length=1, max_length=120)


class ConnectionPatch(BaseModel):
    """Partial update: only the fields sent change. ``secret`` replaces the stored one,
    ``clear_secret: true`` erases it."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: ConnectionKind | None = None
    site_id: int | None = None
    url: str | None = Field(default=None, min_length=1, max_length=500)
    allowed_hosts: list[str] | None = Field(default=None, max_length=10)
    username: str | None = Field(default=None, max_length=200)
    secret: str | None = Field(default=None, min_length=1, max_length=500)
    clear_secret: bool = False
    playbook: str | None = Field(default=None, min_length=1, max_length=80)
    tasks: list[TaskKind] | None = Field(default=None, min_length=1, max_length=3)
    source_system: str | None = Field(default=None, max_length=60)
    interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    active_from: time | None = None
    active_to: time | None = None
    days: list[Day] | None = Field(default=None, min_length=1)
    agent_id: str | None = Field(default=None, min_length=1, max_length=120)


# Fields that cannot be erased with null in a PATCH.
REQUIRED = ("name", "kind", "url", "allowed_hosts", "playbook", "tasks", "interval_minutes")
EDITABLE = (
    *REQUIRED,
    "days",
    "site_id",
    "username",
    "source_system",
    "active_from",
    "active_to",
    "agent_id",
)


# --- helpers ---------------------------------------------------------------------------


def invalid(message: str) -> HTTPException:
    return HTTPException(UNPROCESSABLE, message)


def visible(ctx: Ctx, conn: AgentConnection) -> bool:
    """A coordinator limited to a site sees its site's connections and the group-wide ones."""
    return ctx.site_scope is None or conn.site_id in (None, ctx.site_scope)


def can_control(ctx: Ctx, conn: AgentConnection) -> bool:
    if ctx.user.role == "admin_groupe":
        return True
    if ctx.user.role != "coordination":
        return False
    return ctx.site_scope is None or conn.site_id == ctx.site_scope


def get_connection(ctx: Ctx, connection_id: int) -> AgentConnection:
    conn = ctx.session.get(AgentConnection, connection_id)
    if conn is None or conn.group_id != ctx.group.id or conn.archived_at or not visible(ctx, conn):
        raise HTTPException(404, "Connexion introuvable")
    return conn


def controlled(ctx: Ctx, connection_id: int) -> AgentConnection:
    conn = get_connection(ctx, connection_id)
    if not can_control(ctx, conn):
        raise HTTPException(403, "Cette connexion relève d'un autre site ou de tout le groupe")
    return conn


def connection_out(
    ctx: Ctx, conn: AgentConnection, counts: dict[int, dict[str, int]] | None = None
) -> ConnectionOut:
    if counts is None:
        counts = connections.task_counts(ctx)
    site = ctx.session.get(Site, conn.site_id) if conn.site_id else None
    tally = counts.get(conn.id, {})
    return ConnectionOut(
        id=conn.id,
        name=conn.name,
        kind=conn.kind,
        site_id=conn.site_id,
        site_name=site.name if site else None,
        url=conn.url,
        allowed_hosts=connections.loads(conn.allowed_hosts_json, []),
        username=conn.username,
        secret_set=bool(conn.secret_ciphertext),
        secret_updated_at=conn.secret_updated_at,
        playbook=conn.playbook,
        tasks=connections.tasks_of(conn),
        source_system=conn.source_system,
        interval_minutes=conn.interval_minutes,
        active_from=connections.hhmm(conn.active_from),
        active_to=connections.hhmm(conn.active_to),
        days=connections.days_of(conn),
        agent_id=conn.agent_id,
        status=conn.status,
        last_run_at=conn.last_run_at,
        next_run_at=conn.next_run_at,
        last_outcome=conn.last_outcome,
        last_error=conn.last_error,
        pending_tasks=tally.get("pending", 0),
        needs_human=tally.get("needs_human", 0),
        running_task_id=tally.get("running_task_id"),
        can_control=can_control(ctx, conn),
        can_edit=ctx.user.role == "admin_groupe",
    )


def url_host(url: str) -> str:
    """https, or http to this machine or to an internal name without a dot (a compose
    service): the same rule as the agent's AGENT_API_URL. The password is typed on it."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    internal = bool(host) and "." not in host and ":" not in host
    if host and (parsed.scheme == "https" or (parsed.scheme == "http" and (loopback or internal))):
        return host
    raise invalid(
        "L'adresse doit être en https (http accepté seulement vers la machine locale "
        "ou un nom de service interne)"
    )


def checked(ctx: Ctx, values: dict[str, Any]) -> dict[str, Any]:
    """Validate a complete connection (creation, or current values with a patch applied)
    and normalise it. 422 with a French message on the first problem."""
    out = dict(values)
    if out.get("site_id") is not None:
        site = ctx.session.get(Site, out["site_id"])
        if site is None or site.group_id != ctx.group.id:
            raise invalid("Site inconnu dans ce groupe")
    host = url_host(out["url"])
    extras = []
    for raw in out.get("allowed_hosts") or []:
        extra = str(raw).strip().lower()
        if not _HOST.match(extra):
            raise invalid("Hôte autorisé invalide (nom de domaine ou adresse attendu)")
        extras.append(extra)
    out["allowed_hosts"] = list(dict.fromkeys([host.lower(), *extras]))
    allowed_tasks = connections.CONNECTION_KINDS[out["kind"]]
    tasks = list(dict.fromkeys(out["tasks"]))
    if any(t not in allowed_tasks for t in tasks):
        raise invalid(f"Tâches possibles pour ce type de logiciel : {', '.join(allowed_tasks)}")
    out["tasks"] = tasks
    # Optional: without it the agent sends the playbook's own source_system.
    source = (out.get("source_system") or "").strip() or None
    if source and out["kind"] != "gestion_lits":
        raise invalid("Le système source ne concerne que la gestion des lits")
    if source and not _SOURCE.match(source):
        raise invalid("Système source : lettres, chiffres et _ . / ^ - seulement")
    out["source_system"] = source
    if out.get("active_from") and out.get("active_to") and out["active_from"] >= out["active_to"]:
        raise invalid("La plage horaire doit finir après son début (même jour)")
    out["days"] = sorted(set(out.get("days") or connections.ALL_DAYS))
    agent_id = out.get("agent_id")
    if agent_id is not None and not ctx.session.scalar(
        select(AgentWorker.id).where(
            AgentWorker.group_id == ctx.group.id, AgentWorker.agent_id == agent_id
        )
    ):
        raise invalid("Poste inconnu dans ce groupe : il apparaît à son premier signal")
    entry = connections.group_catalogue(ctx, agent_id).get(out["playbook"])
    if entry is None:
        raise invalid("Script absent du catalogue des postes de ce groupe")
    if entry.get("kind") != out["kind"] or any(t not in entry.get("tasks", []) for t in tasks):
        raise invalid("Ce script ne correspond pas au type de logiciel ou aux tâches choisis")
    return out


def apply(conn: AgentConnection, values: dict[str, Any]) -> None:
    for field in EDITABLE:
        if field in ("allowed_hosts", "tasks", "days"):
            setattr(conn, f"{field}_json", json.dumps(values[field]))
        else:
            setattr(conn, field, values[field])


def current_values(conn: AgentConnection) -> dict[str, Any]:
    return {
        "name": conn.name,
        "kind": conn.kind,
        "site_id": conn.site_id,
        "url": conn.url,
        # Extras only: the URL's host is added back by ``checked``.
        "allowed_hosts": connections.loads(conn.allowed_hosts_json, [])[1:],
        "username": conn.username,
        "playbook": conn.playbook,
        "tasks": connections.tasks_of(conn),
        "source_system": conn.source_system,
        "interval_minutes": conn.interval_minutes,
        "active_from": conn.active_from,
        "active_to": conn.active_to,
        "days": connections.days_of(conn),
        "agent_id": conn.agent_id,
    }


def set_secret(ctx: Ctx, conn: AgentConnection, secret: str | None) -> None:
    conn.secret_ciphertext = (
        encrypt(ctx.settings.connector_key, ctx.group.id, conn.id, secret) if secret else None
    )
    conn.secret_updated_at = ctx.clock.now() if secret else None


def allow_source(ctx: Ctx, conn: AgentConnection) -> None:
    """The bed software's ``source_system`` is added to the group's ingestion accounts that
    are limited to a list of sources (an empty list already accepts any source)."""
    if not conn.source_system:
        return
    for user in ctx.session.scalars(
        select(User).where(
            User.group_id == ctx.group.id, User.role == "ingestion", User.active.is_(True)
        )
    ):
        allowed = connections.loads(user.allowed_sources, [])
        if isinstance(allowed, list) and allowed and conn.source_system not in allowed:
            user.allowed_sources = json.dumps([*allowed, conn.source_system])
            ctx.audit(
                "agent.sources",
                "user",
                user.id,
                f"système source {conn.source_system} autorisé (connexion {conn.id})",
            )


def cancel_pending(ctx: Ctx, conn: AgentConnection, reason: str) -> None:
    now = ctx.clock.now()
    for task in ctx.session.scalars(
        select(AgentTask).where(AgentTask.connection_id == conn.id, AgentTask.status == "pending")
    ):
        task.status, task.error = "cancelled", reason
        task.updated_at = task.finished_at = now
        task.budget_reserved_usd = 0.0


def touch(ctx: Ctx, conn: AgentConnection) -> None:
    conn.updated_at = ctx.clock.now()
    conn.updated_by = ctx.user.id


# --- reading -----------------------------------------------------------------------------


@router.get("/workers", response_model=list[WorkerOut])
def list_workers(ctx: ReadCtx) -> list[WorkerOut]:
    query = select(AgentWorker).where(AgentWorker.group_id == ctx.group.id)
    if ctx.site_scope is not None:
        query = query.where(
            or_(AgentWorker.site_id.is_(None), AgentWorker.site_id == ctx.site_scope)
        )
    now = ctx.clock.now()
    return [
        WorkerOut(
            agent_id=w.agent_id,
            site_id=w.site_id,
            online=bool(
                w.last_heartbeat_at
                and now - w.last_heartbeat_at < timedelta(minutes=ONLINE_MINUTES)
            ),
            last_heartbeat_at=w.last_heartbeat_at,
            version=w.version,
            engines=[EngineReport(**e) for e in connections.loads(w.engines_json, [])],
            playbooks=[PlaybookInfo(**p) for p in connections.loads(w.playbooks_json, [])],
        )
        for w in ctx.session.scalars(query.order_by(AgentWorker.agent_id))
    ]


@router.get("/connections", response_model=list[ConnectionOut])
def list_connections(ctx: ReadCtx) -> list[ConnectionOut]:
    counts = connections.task_counts(ctx)
    rows = ctx.session.scalars(
        select(AgentConnection)
        .where(AgentConnection.group_id == ctx.group.id, AgentConnection.archived_at.is_(None))
        .order_by(AgentConnection.name, AgentConnection.id)
    )
    return [connection_out(ctx, c, counts) for c in rows if visible(ctx, c)]


@router.get("/connections/{connection_id}/runs", response_model=list[RunOut])
def connection_runs(
    connection_id: int, ctx: ReadCtx, limit: int = Query(20, ge=1, le=100)
) -> list[RunOut]:
    conn = get_connection(ctx, connection_id)
    query = select(AgentTask).where(
        AgentTask.group_id == ctx.group.id, AgentTask.connection_id == conn.id
    )
    if ctx.site_scope is not None:  # replies of a group-wide portal for other sites: hidden
        query = query.where(
            or_(
                AgentTask.request_id.is_(None),
                AgentTask.request_id.in_(
                    select(AdmissionRequest.id).where(
                        AdmissionRequest.group_id == ctx.group.id,
                        or_(
                            AdmissionRequest.site_id == ctx.site_scope,
                            AdmissionRequest.site_id.is_(None),
                        ),
                    )
                ),
            )
        )
    rows = list(
        ctx.session.scalars(
            query.order_by(AgentTask.created_at.desc(), AgentTask.id.desc()).limit(limit)
        )
    )
    steps = dict(
        ctx.session.execute(
            select(AgentTaskStep.task_id, func.count())
            .where(AgentTaskStep.task_id.in_([t.id for t in rows]))
            .group_by(AgentTaskStep.task_id)
        )
        .tuples()
        .all()
    )
    watch = can_watch(ctx, conn)
    return [
        RunOut(
            **task_out(t).model_dump(),
            steps_count=int(steps.get(t.id, 0)),
            has_replay=watch and bool(steps.get(t.id)),
        )
        for t in rows
    ]


# --- administration ---------------------------------------------------------------------


@router.post("/connections", response_model=ConnectionOut, status_code=201)
def create_connection(body: ConnectionIn, ctx: AdminCtx) -> ConnectionOut:
    values = checked(ctx, body.model_dump(exclude={"secret"}))
    now = ctx.clock.now()
    conn = AgentConnection(
        group_id=ctx.group.id,
        status="arretee",
        created_at=now,
        updated_at=now,
        created_by=ctx.user.id,
        updated_by=ctx.user.id,
    )
    apply(conn, values)
    ctx.session.add(conn)
    ctx.session.flush()  # the id is part of the secret's associated data
    set_secret(ctx, conn, body.secret)
    allow_source(ctx, conn)
    detail = f"{conn.name} ({conn.kind}, script {conn.playbook})"
    ctx.audit(
        "agent.connexion.creation",
        "agent_connection",
        conn.id,
        detail + ("; secret défini" if body.secret else ""),
    )
    ctx.session.commit()
    return connection_out(ctx, conn)


@router.patch("/connections/{connection_id}", response_model=ConnectionOut)
def update_connection(connection_id: int, body: ConnectionPatch, ctx: AdminCtx) -> ConnectionOut:
    conn = get_connection(ctx, connection_id)
    sent = body.model_fields_set - {"secret", "clear_secret"}
    if body.secret is not None and body.clear_secret:
        raise invalid("Saisir un nouveau secret ou l'effacer, pas les deux")
    if "kind" in sent and body.kind != conn.kind:
        raise invalid("Le type de logiciel d'une connexion ne change pas : créez-en une autre")
    nulled = [f for f in REQUIRED if f in sent and getattr(body, f) is None]
    if nulled:
        raise invalid(f"Champ obligatoire : {nulled[0]}")
    values = current_values(conn)
    values.update({f: getattr(body, f) for f in sent})
    apply(conn, checked(ctx, values))
    changed = sorted(sent)  # field names only, never a value
    if body.secret is not None:
        set_secret(ctx, conn, body.secret)
        changed.append("secret modifié")
    elif body.clear_secret and conn.secret_ciphertext:
        set_secret(ctx, conn, None)
        changed.append("secret effacé")
    if conn.status == "active" and {"interval_minutes", "active_from", "active_to", "days"} & sent:
        conn.next_run_at = connections.next_run(conn, ctx.clock.now(), ctx)
    touch(ctx, conn)
    allow_source(ctx, conn)
    ctx.audit("agent.connexion.modification", "agent_connection", conn.id, ", ".join(changed))
    ctx.session.commit()
    return connection_out(ctx, conn)


@router.delete("/connections/{connection_id}", status_code=204)
def archive_connection(connection_id: int, ctx: AdminCtx) -> Response:
    """Archive: no longer listed nor run, pending tasks cancelled, secret erased."""
    conn = get_connection(ctx, connection_id)
    conn.archived_at = ctx.clock.now()
    conn.status = "arretee"
    conn.next_run_at = None
    set_secret(ctx, conn, None)
    cancel_pending(ctx, conn, "Connexion archivée")
    touch(ctx, conn)
    ctx.audit("agent.connexion.archivage", "agent_connection", conn.id, conn.name)
    ctx.session.commit()
    return Response(status_code=204)


# --- control (admin, or coordination of the connection's site) ---------------------------


def run_now(ctx: Ctx, conn: AgentConnection) -> None:
    conn.status = "active"
    conn.next_run_at = connections.next_run(conn, ctx.clock.now(), ctx)
    touch(ctx, conn)


@router.post("/connections/{connection_id}/start", response_model=ConnectionOut)
def start_connection(connection_id: int, ctx: WriteCtx) -> ConnectionOut:
    conn = controlled(ctx, connection_id)
    if conn.status != "active":
        run_now(ctx, conn)
        ctx.audit("agent.connexion.demarrage", "agent_connection", conn.id, conn.name)
    ctx.session.commit()
    return connection_out(ctx, conn)


@router.post("/connections/{connection_id}/pause", response_model=ConnectionOut)
def pause_connection(connection_id: int, ctx: WriteCtx) -> ConnectionOut:
    """Nothing is created nor claimed while paused; a task in progress stops at its next
    checkpoint (its lease can no longer be renewed). Pending tasks stay visible."""
    conn = controlled(ctx, connection_id)
    if conn.status == "arretee":
        raise HTTPException(409, "Connexion arrêtée : démarrez-la d'abord")
    if conn.status == "active":
        conn.status = "en_pause"
        touch(ctx, conn)
        ctx.audit("agent.connexion.pause", "agent_connection", conn.id, conn.name)
    ctx.session.commit()
    return connection_out(ctx, conn)


@router.post("/connections/{connection_id}/resume", response_model=ConnectionOut)
def resume_connection(connection_id: int, ctx: WriteCtx) -> ConnectionOut:
    """Pending tasks become claimable again; the next run is due now (or at the start of
    the next active window), without duplicating a pending sync."""
    conn = controlled(ctx, connection_id)
    if conn.status == "arretee":
        raise HTTPException(409, "Connexion arrêtée : démarrez-la d'abord")
    if conn.status == "en_pause":
        run_now(ctx, conn)
        ctx.audit("agent.connexion.reprise", "agent_connection", conn.id, conn.name)
    ctx.session.commit()
    return connection_out(ctx, conn)


@router.post("/connections/{connection_id}/sync", response_model=TaskOut, status_code=201)
def sync_connection(connection_id: int, ctx: WriteCtx) -> TaskOut:
    """A sync now, outside the schedule (and outside the active window)."""
    conn = controlled(ctx, connection_id)
    state = get_state(ctx, create=False)
    if state is not None and state.paused:
        raise HTTPException(409, "Agent en pause générale")
    if conn.status != "active":
        raise HTTPException(409, "Connexion arrêtée ou en pause : démarrez-la ou reprenez-la")
    kinds = [k for k in connections.tasks_of(conn) if k in connections.SYNC_KINDS]
    if not kinds:
        raise HTTPException(409, "Aucune relève prévue pour cette connexion")
    task = connections.create_sync_task(ctx, conn, kinds[0])
    ctx.audit("agent.connexion.releve", "agent_connection", conn.id, f"demandée ({kinds[0]})")
    ctx.session.commit()
    return task_out(task)
