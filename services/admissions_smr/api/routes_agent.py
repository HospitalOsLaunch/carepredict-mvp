"""Server side of the computer-use agent: policy, task queue, attempts, costs, calibration.

The agent runs next to the portals (inside the group's network or HDS hosting) and only
talks to this API with an ``ingestion`` service account. Every attempt by every engine
is recorded with its cost, so routing decisions and budgets are auditable.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import case, func, select

from services.admissions_smr.agent_policy import (
    ENGINE_NAMES,
    TASK_KINDS,
    AgentPolicy,
    parse_policy,
)
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


class ClaimIn(BaseModel):
    agent_id: str = Field(min_length=1, max_length=120)
    kinds: list[str] = Field(default_factory=lambda: list(TASK_KINDS))
    limit: int = Field(default=1, ge=1, le=20)


class TaskOut(BaseModel):
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


class AttemptIn(BaseModel):
    engine: str
    outcome: Literal["success", "failure", "refused"]
    cost_usd: float = Field(default=0.0, ge=0)
    steps: int = Field(default=0, ge=0)
    duration_s: float = Field(default=0.0, ge=0)
    error: str | None = Field(default=None, max_length=4000)


class CompleteIn(BaseModel):
    status: Literal["done", "failed", "needs_human"]
    engine: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = Field(default=None, max_length=4000)


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
        .order_by(AgentCalibration.at)
    ):
        out[c.engine] = c
    return out


def get_task(ctx: Ctx, task_id: int) -> AgentTask:
    task = ctx.session.get(AgentTask, task_id)
    if task is None or task.group_id != ctx.group.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tâche introuvable")
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
    if req.status == "accord":
        assert req.proposed_date is not None
        payload = {
            "external_ref": req.external_ref,
            "decision": "accord",
            "proposed_date": req.proposed_date.isoformat(),
            "proposed_date_fr": f"{req.proposed_date:%d/%m/%Y}",
            "site_name": site_name,
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
            "message": refusal_message(site_name, reason, req.patient_ref, None, None),
        }
    else:
        return None
    task = AgentTask(
        group_id=ctx.group.id,
        kind="reply_portal",
        request_id=req.id,
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
    )


@router.post("/tasks/claim", response_model=list[TaskOut])
def claim(body: ClaimIn, ctx: IngestCtx) -> list[TaskOut]:
    state = get_state(ctx)
    assert state is not None
    if state.paused:
        return []
    policy = policy_of(state)
    now = ctx.clock.now()
    candidates = ctx.session.scalars(
        select(AgentTask)
        .where(
            AgentTask.group_id == ctx.group.id,
            AgentTask.kind.in_(body.kinds),
            (AgentTask.status == "pending")
            | ((AgentTask.status == "running") & (AgentTask.lease_until < now)),
        )
        .order_by(AgentTask.created_at)
        .limit(body.limit * 3)
    )
    claimed: list[AgentTask] = []
    for task in candidates:
        if task.attempts >= policy.max_attempts:
            task.status = "needs_human"
            task.error = (task.error or "") + " Nombre maximal de tentatives atteint."
            task.updated_at = now
            continue
        task.status = "running"
        task.claimed_by = body.agent_id
        task.lease_until = now + timedelta(minutes=LEASE_MINUTES)
        task.attempts += 1
        task.updated_at = now
        claimed.append(task)
        if len(claimed) >= body.limit:
            break
    ctx.session.commit()
    return [task_out(t) for t in claimed]


@router.post("/tasks/{task_id}/attempts", response_model=TaskOut)
def record_attempt(task_id: int, body: AttemptIn, ctx: IngestCtx) -> TaskOut:
    task = get_task(ctx, task_id)
    if body.engine not in ENGINE_NAMES:
        raise HTTPException(UNPROCESSABLE, "Moteur inconnu")
    now = ctx.clock.now()
    ctx.session.add(
        AgentAttempt(
            group_id=ctx.group.id,
            task_id=task.id,
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
    task.lease_until = now + timedelta(minutes=LEASE_MINUTES)
    task.updated_at = now
    ctx.session.commit()
    return task_out(task)


@router.post("/tasks/{task_id}/complete", response_model=TaskOut)
def complete(task_id: int, body: CompleteIn, ctx: IngestCtx) -> TaskOut:
    task = get_task(ctx, task_id)
    if task.status != "running":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Tâche à l'état {task.status}")
    now = ctx.clock.now()
    task.status = "pending" if body.status == "failed" else body.status
    task.engine_used = body.engine
    task.result_json = json.dumps(body.result, ensure_ascii=False) if body.result else None
    task.error = body.error
    task.lease_until = None
    task.updated_at = now
    if body.status in ("done", "needs_human"):
        task.finished_at = now
    ctx.audit(f"agent.{body.status}", "agent_task", task.id, body.engine or "")
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
    recent = ctx.session.scalars(
        select(AgentTask)
        .where(AgentTask.group_id == ctx.group.id)
        .order_by(AgentTask.updated_at.desc())
        .limit(20)
    )
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
    query = select(AgentTask).where(AgentTask.group_id == ctx.group.id)
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
    task.status = "pending"
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
    task.status = "manual"
    task.finished_at = ctx.clock.now()
    task.updated_at = ctx.clock.now()
    ctx.audit("agent.manuel", "agent_task", task.id, "saisie faite à la main")
    ctx.session.commit()
    return task_out(task)
