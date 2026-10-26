"""Server side of the computer-use agent: policy, task queue, attempts, costs, calibration.

The agent runs next to the portals (inside the group's network or HDS hosting) and only
talks to this API with an ``ingestion`` service account. Every attempt by every engine
is recorded with its cost, so routing decisions and budgets are auditable.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import Select, case, func, or_, select

from services.admissions_smr.agent_policy import (
    ENGINE_NAMES,
    TASK_KINDS,
    AgentPolicy,
    parse_policy,
)
from services.admissions_smr.agent_trace import RouteStepOut, public_route, safe_reason
from services.admissions_smr.api.deps import (
    UNPROCESSABLE,
    AdminCtx,
    Ctx,
    IngestCtx,
    ReadCtx,
    SyncCtx,
    WriteCtx,
)
from services.admissions_smr.domain.messages import accord_message, refusal_message
from services.admissions_smr.models import (
    AdmissionRequest,
    AgentAttempt,
    AgentCalibration,
    AgentState,
    AgentTask,
    Site,
)
from services.admissions_smr.task_state import decision_is_current
from services.admissions_smr.vocab import REFUSAL_REASONS

router = APIRouter(prefix="/agent", tags=["agent"])

LEASE_MINUTES = 10
ONLINE_MINUTES = 5
PORTAL_SOURCES = frozenset({"viatrajectoire", "portail"})


# --- schemas ---------------------------------------------------------------


class EngineReport(BaseModel):
    name: str
    configured: bool
    detail: str | None = None


class HeartbeatIn(BaseModel):
    agent_id: str = Field(min_length=1, max_length=120)
    version: str = Field(max_length=40)
    engines: list[EngineReport] = Field(default_factory=list)


class HeartbeatOut(BaseModel):
    paused: bool
    policy: AgentPolicy
    spent_today_usd: float
    calibrations: dict[str, float]
    calibration_details: dict[str, dict[str, Any]]


class ClaimIn(BaseModel):
    protocol_version: Literal[2]
    agent_id: str = Field(min_length=1, max_length=120)
    kinds: list[str] = Field(default_factory=lambda: list(TASK_KINDS))
    limit: int = Field(default=1, ge=1, le=20)


class TaskOut(BaseModel):
    route: list[RouteStepOut] = Field(default_factory=list)
    summary: str | None = None
    id: int
    kind: str
    request_id: int | None
    payload: dict[str, Any]
    status: str
    attempts: int
    engine_used: str | None
    cost_usd: float
    error: str | None
    result: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    available_at: datetime | None
    reconcile_only: bool


class ClaimedTaskOut(TaskOut):
    # A capability, returned ONLY to the worker that claimed the task, never to readers.
    lease_token: str


class LeaseIn(BaseModel):
    agent_id: str = Field(min_length=1, max_length=120)
    lease_token: str = Field(min_length=32, max_length=64)


class AttemptIn(LeaseIn):
    report_key: str = Field(min_length=1, max_length=80)
    engine: str
    outcome: Literal["success", "failure", "refused"]
    cost_usd: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    steps: int = Field(default=0, ge=0)
    duration_s: float = Field(default=0.0, ge=0)
    error: str | None = Field(default=None, max_length=4000)


class CompleteIn(LeaseIn):
    status: Literal["done", "failed", "needs_human"]
    engine: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = Field(default=None, max_length=4000)


class AuthorizeIn(LeaseIn):
    engine: str


class AuthorizationOut(BaseModel):
    budget_usd: float


class CalibrationIn(BaseModel):
    engine: str
    model: str = Field(max_length=200)
    convention: str | None = Field(default=None, max_length=40)
    hit_rate: float = Field(ge=0, le=1)
    trials: int = Field(ge=1, le=1000)


class EngineSpend(BaseModel):
    engine: str
    attempts: int
    successes: int
    cost_usd: float


class AgentStatusOut(BaseModel):
    paused: bool
    online: bool
    last_heartbeat_at: datetime | None
    agent_id: str | None
    agent_version: str | None
    engines: list[EngineReport]
    policy: AgentPolicy
    counts: dict[str, int]
    spent_today_usd: float
    spend_30d: list[EngineSpend]
    calibrations: dict[str, dict[str, Any]]
    recent: list[TaskOut]


# --- helpers ---------------------------------------------------------------


def get_state(ctx: Ctx, create: bool = True) -> AgentState | None:
    state = ctx.session.get(AgentState, ctx.group.id)
    if state is None and create:
        state = AgentState(group_id=ctx.group.id, updated_at=ctx.clock.now())
        ctx.session.add(state)
        ctx.session.flush()
    return state


def policy_of(state: AgentState | None) -> AgentPolicy:
    return parse_policy(state.policy_json if state else None)


def task_out(t: AgentTask) -> TaskOut:
    return TaskOut(
        id=t.id,
        route=public_route(t.result_json, t.status),
        summary=safe_reason(t.error) if t.error else None,
        kind=t.kind,
        request_id=t.request_id,
        payload=json.loads(t.payload_json or "{}"),
        status=t.status,
        attempts=t.attempts,
        engine_used=t.engine_used,
        cost_usd=round(t.cost_usd, 4),
        error=t.error,
        result=json.loads(t.result_json) if t.result_json else None,
        created_at=t.created_at,
        updated_at=t.updated_at,
        finished_at=t.finished_at,
        available_at=t.available_at,
        reconcile_only=t.write_started_at is not None,
    )


def spent_since(ctx: Ctx, since: datetime) -> float:
    total = ctx.session.scalar(
        select(func.coalesce(func.sum(AgentAttempt.cost_usd), 0.0)).where(
            AgentAttempt.group_id == ctx.group.id, AgentAttempt.at >= since
        )
    )
    return float(total or 0.0)


def local_midnight(ctx: Ctx) -> datetime:
    return datetime.combine(ctx.clock.today(), time.min, tzinfo=ctx.clock.zone).astimezone(UTC)


def latest_calibrations(ctx: Ctx) -> dict[str, AgentCalibration]:
    out: dict[str, AgentCalibration] = {}
    for c in ctx.session.scalars(
        select(AgentCalibration)
        .where(AgentCalibration.group_id == ctx.group.id)
        .order_by(AgentCalibration.at, AgentCalibration.id)
    ):
        out[c.engine] = c
    return out


def scoped_tasks(ctx: Ctx) -> Select[Any]:
    query = select(AgentTask).where(AgentTask.group_id == ctx.group.id)
    if ctx.site_scope is not None:
        query = query.where(
            AgentTask.request_id.in_(
                select(AdmissionRequest.id).where(
                    AdmissionRequest.group_id == ctx.group.id,
                    or_(
                        AdmissionRequest.site_id == ctx.site_scope,
                        AdmissionRequest.site_id.is_(None),
                    ),
                )
            )
        )
    return query


def get_task(ctx: Ctx, task_id: int) -> AgentTask:
    task: AgentTask | None = ctx.session.scalar(scoped_tasks(ctx).where(AgentTask.id == task_id))
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tâche introuvable")
    return task


def owned_task(ctx: Ctx, task_id: int, body: LeaseIn, *, check_work: bool = True) -> AgentTask:
    task = get_task(ctx, task_id)
    if (
        task.status != "running"
        or task.claimed_by != body.agent_id
        or task.claimed_user_id != ctx.user.id
        or task.lease_until is None
        or task.lease_until <= ctx.clock.now()
        or task.lease_token is None
        or not secrets.compare_digest(task.lease_token, body.lease_token)
    ):
        raise HTTPException(409, "Tâche expirée ou attribuée à un autre agent")
    if check_work:
        state = get_state(ctx, create=False)
        if state is not None and state.paused:
            raise HTTPException(409, "Agent en pause")
        if not decision_is_current(ctx, task):
            raise HTTPException(409, "Décision remplacée : ne pas écrire sur le portail")
    return task


def enqueue_portal_reply(ctx: Ctx, req: AdmissionRequest) -> AgentTask | None:
    """Queue the answer the coordinator just gave, so the agent types it into the portal.

    Only for requests that came from a portal, and only once an agent has been set up for
    the group (otherwise the coordinator keeps answering in the portal by hand).
    """
    if req.source not in PORTAL_SOURCES or not req.external_ref:
        return None
    state = get_state(ctx, create=False)
    if state is None:
        return None
    now = ctx.clock.now()
    for previous in ctx.session.scalars(
        select(AgentTask).where(
            AgentTask.request_id == req.id,
            AgentTask.kind == "reply_portal",
            AgentTask.status.in_(("pending", "failed", "needs_human")),
        )
    ):
        previous.status = "cancelled"
        previous.updated_at = now
        previous.finished_at = now
    site = ctx.session.get(Site, req.site_id) if req.site_id else None
    site_name = site.name if site else "notre établissement"
    if req.status in ("accord", "confirmee"):
        assert req.proposed_date is not None
        payload = {
            "external_ref": req.external_ref,
            "decision": "accord",
            "proposed_date": req.proposed_date.isoformat(),
            "proposed_date_fr": f"{req.proposed_date:%d/%m/%Y}",
            "site_name": site_name,
            "site_id": req.site_id,
            "message": accord_message(
                site_name,
                req.mention_requested,
                req.proposed_date,
                req.patient_ref,
                req.referrer_unit,
            ),
        }
    elif req.status == "refusee":
        reason = req.refusal_reason or "autre"
        payload = {
            "external_ref": req.external_ref,
            "decision": "refus",
            "reason_code": reason,
            "reason_label": REFUSAL_REASONS.get(reason, reason),
            "site_name": site_name,
            "site_id": req.site_id,
            "message": refusal_message(site_name, reason, req.patient_ref, None, None),
        }
    else:
        return None
    task = AgentTask(
        group_id=ctx.group.id,
        kind="reply_portal",
        request_id=req.id,
        decision_version=req.decision_version,
        payload_json=json.dumps(payload, ensure_ascii=False),
        status="pending",
        created_at=now,
        updated_at=now,
    )
    ctx.session.add(task)
    ctx.audit("agent.tache", "agent_task", None, f"réponse portail pour la demande {req.id}")
    return task


# --- routes used by the agent ------------------------------------------------


@router.post("/heartbeat", response_model=HeartbeatOut)
def heartbeat(body: HeartbeatIn, ctx: IngestCtx) -> HeartbeatOut:
    state = get_state(ctx)
    assert state is not None
    state.last_heartbeat_at = ctx.clock.now()
    state.agent_id = body.agent_id
    state.agent_version = body.version
    state.engines_json = json.dumps([e.model_dump() for e in body.engines])
    state.updated_at = ctx.clock.now()
    ctx.session.commit()
    return HeartbeatOut(
        paused=state.paused,
        policy=policy_of(state),
        spent_today_usd=round(spent_since(ctx, local_midnight(ctx)), 4),
        calibrations={k: v.hit_rate for k, v in latest_calibrations(ctx).items()},
        calibration_details={
            k: {
                "model": v.model,
                "convention": v.convention,
                "hit_rate": v.hit_rate,
                "trials": v.trials,
            }
            for k, v in latest_calibrations(ctx).items()
        },
    )


@router.post("/tasks/claim", response_model=list[ClaimedTaskOut])
def claim(body: ClaimIn, ctx: IngestCtx) -> list[ClaimedTaskOut]:
    # All mutations hold the tenant lock from deps.require, including decision changes.
    state = get_state(ctx)
    assert state is not None
    if state.paused:
        return []
    policy, now = policy_of(state), ctx.clock.now()
    expired = list(
        ctx.session.scalars(
            select(AgentTask).where(
                AgentTask.group_id == ctx.group.id,
                AgentTask.status == "running",
                AgentTask.lease_until < now,
            )
        )
    )
    for task in expired:
        task.status = "needs_human" if task.write_started_at else "pending"
        task.error = (
            "Agent interrompu : vérifier le portail"
            if task.write_started_at
            else "Agent interrompu : reprise autorisée"
        )
        task.lease_token = task.lease_until = None
        # Keep a reservation after an ambiguous paid attempt: its cost may still be incurred.
        if task.write_started_at is None:
            task.budget_reserved_usd = 0.0
        task.updated_at = now
        if task.status == "needs_human":
            task.finished_at = now
        ctx.audit("agent.bail_expire", "agent_task", task.id, task.status)
    ctx.session.flush()
    candidates = ctx.session.scalars(
        select(AgentTask)
        .where(
            AgentTask.group_id == ctx.group.id,
            AgentTask.kind.in_(body.kinds),
            AgentTask.status == "pending",
            or_(AgentTask.available_at.is_(None), AgentTask.available_at <= now),
        )
        .order_by(
            case((AgentTask.kind == "reply_portal", 0), else_=1), AgentTask.created_at, AgentTask.id
        )
    )
    claimed: list[ClaimedTaskOut] = []
    for task in candidates:
        if not decision_is_current(ctx, task):
            task.status, task.error = (
                "cancelled",
                "Décision remplacée ou créée par une ancienne version de l'agent",
            )
            task.finished_at = task.updated_at = now
            task.budget_reserved_usd = 0.0
            continue
        if task.attempts >= policy.max_attempts:
            task.status, task.error = "needs_human", "Nombre maximal de tentatives atteint"
            task.finished_at = task.updated_at = now
            continue
        task.status, task.claimed_by = "running", body.agent_id
        task.claimed_user_id = ctx.user.id
        task.lease_token = secrets.token_hex(32)
        task.lease_until = now + timedelta(minutes=LEASE_MINUTES)
        task.attempts += 1
        task.updated_at = now
        claimed.append(ClaimedTaskOut(**task_out(task).model_dump(), lease_token=task.lease_token))
        if len(claimed) >= body.limit:
            break
    ctx.session.commit()
    return claimed


@router.post("/tasks/{task_id}/renew", response_model=TaskOut)
def renew(task_id: int, body: LeaseIn, ctx: IngestCtx) -> TaskOut:
    task = owned_task(ctx, task_id, body)
    task.lease_until = ctx.clock.now() + timedelta(minutes=LEASE_MINUTES)
    ctx.session.commit()
    return task_out(task)


@router.post("/tasks/{task_id}/begin-write", response_model=TaskOut)
def begin_write(task_id: int, body: LeaseIn, ctx: IngestCtx) -> TaskOut:
    task = owned_task(ctx, task_id, body)
    if task.kind != "reply_portal":
        raise HTTPException(409, "Cette tâche n'autorise aucune réponse sur le portail")
    if task.write_started_at is not None and task.write_lease_token != body.lease_token:
        raise HTTPException(
            409, "Reprise en vérification seule : aucune nouvelle écriture autorisée"
        )
    if task.write_started_at is None:
        task.write_started_at = ctx.clock.now()
        task.write_lease_token = body.lease_token
        ctx.audit("agent.ecriture", "agent_task", task.id, "décision vérifiée, écriture autorisée")
    task.lease_until = ctx.clock.now() + timedelta(minutes=LEASE_MINUTES)
    ctx.session.commit()
    return task_out(task)


@router.post("/tasks/{task_id}/authorize", response_model=AuthorizationOut)
def authorize(task_id: int, body: AuthorizeIn, ctx: IngestCtx) -> AuthorizationOut:
    """Reserve a budget atomically across workers before invoking a paid engine."""
    task = owned_task(ctx, task_id, body)
    policy = policy_of(get_state(ctx, create=False))
    engine = policy.engines.get(body.engine)
    if engine is None or not engine.enabled or body.engine not in policy.routes.get(task.kind, []):
        raise HTTPException(409, "Moteur désactivé ou absent de la route")
    if engine.kind == "playbook":
        return AuthorizationOut(budget_usd=0.0)
    if not engine.identifiable_data_allowed:
        raise HTTPException(409, "Moteur non autorisé à voir les écrans du portail")
    reserved = float(
        ctx.session.scalar(
            select(func.coalesce(func.sum(AgentTask.budget_reserved_usd), 0.0)).where(
                AgentTask.group_id == ctx.group.id,
                AgentTask.id != task.id,
            )
        )
        or 0.0
    )
    left = min(
        policy.task_budget_usd.get(task.kind, 1.0) - task.cost_usd,
        policy.daily_budget_usd - spent_since(ctx, local_midnight(ctx)) - reserved,
    )
    if left <= 0:
        raise HTTPException(409, "Budget épuisé ou réservé par un autre agent")
    task.budget_reserved_usd = left
    ctx.session.commit()
    return AuthorizationOut(budget_usd=left)


@router.post("/tasks/{task_id}/attempts", response_model=TaskOut)
def record_attempt(task_id: int, body: AttemptIn, ctx: IngestCtx) -> TaskOut:
    task = owned_task(ctx, task_id, body, check_work=False)
    if body.engine not in ENGINE_NAMES:
        raise HTTPException(UNPROCESSABLE, "Moteur inconnu")
    existing = ctx.session.scalar(
        select(AgentAttempt).where(
            AgentAttempt.task_id == task.id, AgentAttempt.report_key == body.report_key
        )
    )
    if existing is not None:
        return task_out(task)
    now = ctx.clock.now()
    ctx.session.add(
        AgentAttempt(
            group_id=ctx.group.id,
            task_id=task.id,
            report_key=body.report_key,
            engine=body.engine,
            outcome=body.outcome,
            cost_usd=body.cost_usd,
            steps=body.steps,
            duration_s=body.duration_s,
            error=body.error,
            at=now,
        )
    )
    task.cost_usd += body.cost_usd
    task.budget_reserved_usd = 0.0
    task.lease_until = now + timedelta(minutes=LEASE_MINUTES)
    task.updated_at = now
    ctx.session.commit()
    return task_out(task)


@router.post("/tasks/{task_id}/complete", response_model=TaskOut)
def complete(task_id: int, body: CompleteIn, ctx: IngestCtx) -> TaskOut:
    task = get_task(ctx, task_id)
    # A lost HTTP response must not turn a successfully completed task into a retry.
    if (
        task.lease_until is None
        and (
            task.status == body.status
            or (body.status == "failed" and task.status in ("pending", "needs_human"))
        )
        and task.claimed_by == body.agent_id
        and task.claimed_user_id == ctx.user.id
        and task.lease_token
        and secrets.compare_digest(task.lease_token, body.lease_token)
    ):
        return task_out(task)
    task = owned_task(ctx, task_id, body, check_work=False)
    now = ctx.clock.now()
    if (
        body.status == "done"
        and task.kind == "reply_portal"
        and (not decision_is_current(ctx, task) or not (body.result or {}).get("verification"))
    ):
        raise HTTPException(
            409, "Une réponse ne peut être terminée sans décision valide et relecture"
        )
    task.status = body.status
    if body.status == "failed":
        if (
            task.write_started_at
            or task.attempts >= policy_of(get_state(ctx, create=False)).max_attempts
        ):
            task.status = "needs_human"
        else:
            task.status = "pending"
            task.available_at = now + timedelta(seconds=min(30 * 2 ** (task.attempts - 1), 900))
    task.engine_used = body.engine
    task.result_json = json.dumps(body.result, ensure_ascii=False) if body.result else None
    task.error = body.error
    task.lease_until = None
    task.updated_at = now
    if task.status in ("done", "needs_human"):
        task.finished_at = now
    if task.status == "done":
        task.budget_reserved_usd = 0.0
    ctx.audit(f"agent.{task.status}", "agent_task", task.id, body.engine or "")
    ctx.session.commit()
    return task_out(task)


@router.post("/calibrations", status_code=201)
def calibration(body: CalibrationIn, ctx: IngestCtx) -> dict[str, float]:
    if body.engine not in ENGINE_NAMES:
        raise HTTPException(UNPROCESSABLE, "Moteur inconnu")
    ctx.session.add(
        AgentCalibration(
            group_id=ctx.group.id,
            engine=body.engine,
            model=body.model,
            convention=body.convention,
            hit_rate=body.hit_rate,
            trials=body.trials,
            at=ctx.clock.now(),
        )
    )
    ctx.audit("agent.calibration", "agent", body.engine, f"{body.model} {body.hit_rate:.0%}")
    ctx.session.commit()
    return {"hit_rate": body.hit_rate}


# --- routes used by people -------------------------------------------------------


@router.get("/status", response_model=AgentStatusOut)
def agent_status(ctx: ReadCtx) -> AgentStatusOut:
    state = get_state(ctx, create=False)
    now = ctx.clock.now()
    counts = dict(
        ctx.session.execute(
            select(AgentTask.status, func.count())
            .where(AgentTask.group_id == ctx.group.id)
            .group_by(AgentTask.status)
        )
        .tuples()
        .all()
    )
    since = now - timedelta(days=30)
    rows = ctx.session.execute(
        select(
            AgentAttempt.engine,
            func.count(),
            func.sum(case((AgentAttempt.outcome == "success", 1), else_=0)),
            func.sum(AgentAttempt.cost_usd),
        )
        .where(AgentAttempt.group_id == ctx.group.id, AgentAttempt.at >= since)
        .group_by(AgentAttempt.engine)
    ).tuples()
    spend = [
        EngineSpend(
            engine=str(engine),
            attempts=int(n),
            successes=int(ok or 0),
            cost_usd=round(float(cost or 0), 4),
        )
        for engine, n, ok, cost in rows
    ]
    recent = ctx.session.scalars(scoped_tasks(ctx).order_by(AgentTask.updated_at.desc()).limit(20))
    engines = [EngineReport(**e) for e in json.loads(state.engines_json)] if state else []
    return AgentStatusOut(
        paused=state.paused if state else False,
        online=bool(
            state
            and state.last_heartbeat_at
            and now - state.last_heartbeat_at < timedelta(minutes=ONLINE_MINUTES)
        ),
        last_heartbeat_at=state.last_heartbeat_at if state else None,
        agent_id=state.agent_id if state else None,
        agent_version=state.agent_version if state else None,
        engines=engines,
        policy=policy_of(state),
        counts={k: int(v) for k, v in counts.items()},
        spent_today_usd=round(spent_since(ctx, local_midnight(ctx)), 4),
        spend_30d=spend,
        calibrations={
            k: {
                "model": v.model,
                "hit_rate": v.hit_rate,
                "trials": v.trials,
                "at": v.at.isoformat(),
                "convention": v.convention,
            }
            for k, v in latest_calibrations(ctx).items()
        },
        recent=[task_out(t) for t in recent],
    )


@router.put("/policy", response_model=AgentPolicy)
def put_policy(body: dict[str, Any], ctx: AdminCtx) -> AgentPolicy:
    try:
        policy = AgentPolicy.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(UNPROCESSABLE, str(exc.errors()[0].get("msg"))) from exc
    state = get_state(ctx)
    assert state is not None
    state.policy_json = policy.model_dump_json()
    state.updated_at = ctx.clock.now()
    ctx.audit("agent.politique", "agent", None, policy.model_dump_json()[:1000])
    ctx.session.commit()
    return policy


@router.post("/pause", response_model=AgentStatusOut)
def pause(ctx: AdminCtx) -> AgentStatusOut:
    state = get_state(ctx)
    assert state is not None
    state.paused = True
    ctx.audit("agent.pause", "agent", None, None)
    ctx.session.commit()
    return agent_status(ctx)


@router.post("/resume", response_model=AgentStatusOut)
def resume(ctx: AdminCtx) -> AgentStatusOut:
    state = get_state(ctx)
    assert state is not None
    state.paused = False
    ctx.audit("agent.reprise", "agent", None, None)
    ctx.session.commit()
    return agent_status(ctx)


@router.post("/sync", response_model=TaskOut, status_code=201)
def sync_now(ctx: SyncCtx) -> TaskOut:
    if ctx.site_scope is not None:
        raise HTTPException(
            403, "La synchronisation du groupe est réservée à la coordination groupe"
        )
    get_state(ctx)
    existing = ctx.session.scalar(
        select(AgentTask).where(
            AgentTask.group_id == ctx.group.id,
            AgentTask.kind == "sync_inbox",
            AgentTask.status.in_(("pending", "running")),
        )
    )
    if existing is not None:
        return task_out(existing)
    now = ctx.clock.now()
    task = AgentTask(
        group_id=ctx.group.id,
        kind="sync_inbox",
        payload_json="{}",
        status="pending",
        created_at=now,
        updated_at=now,
    )
    ctx.session.add(task)
    ctx.audit("agent.synchro", "agent", None, "demandée")
    ctx.session.commit()
    return task_out(task)


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    ctx: ReadCtx,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> list[TaskOut]:
    query = scoped_tasks(ctx)
    if status_filter:
        query = query.where(AgentTask.status == status_filter)
    return [
        task_out(t)
        for t in ctx.session.scalars(query.order_by(AgentTask.updated_at.desc()).limit(limit))
    ]


@router.post("/tasks/{task_id}/retry", response_model=TaskOut)
def retry(task_id: int, ctx: WriteCtx) -> TaskOut:
    task = get_task(ctx, task_id)
    if task.status not in ("needs_human", "failed"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Seule une tâche en échec peut être relancée")
    if not decision_is_current(ctx, task):
        raise HTTPException(409, "Décision remplacée : cette tâche ne peut pas être relancée")
    task.status = "pending"
    task.available_at = None
    task.lease_token = None
    task.attempts = 0
    task.error = None
    task.finished_at = None
    task.updated_at = ctx.clock.now()
    ctx.audit("agent.relance", "agent_task", task.id, None)
    ctx.session.commit()
    return task_out(task)


@router.post("/tasks/{task_id}/manual", response_model=TaskOut)
def done_by_hand(task_id: int, ctx: WriteCtx) -> TaskOut:
    task = get_task(ctx, task_id)
    if task.status in ("done", "cancelled", "manual"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Tâche déjà close")
    if task.status == "running" and task.lease_until and task.lease_until > ctx.clock.now():
        raise HTTPException(409, "Un agent travaille encore sur cette tâche : attendez son arrêt")
    task.status = "manual"
    task.lease_token = task.lease_until = None
    task.budget_reserved_usd = 0.0
    task.finished_at = ctx.clock.now()
    task.updated_at = ctx.clock.now()
    ctx.audit("agent.manuel", "agent_task", task.id, "saisie faite à la main")
    ctx.session.commit()
    return task_out(task)
