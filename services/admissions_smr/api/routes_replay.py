"""Agent player: steps sent by the worker, replay and frames read by people.

docs/agent/PLAYER_SPEC.md. The worker (``ingestion`` account, holding the task's lease)
posts one step at a time: a plain-French label without any value read on screen, the
gesture, and optionally a JPEG frame already masked on the worker. People with the right
(``admin_groupe``, or ``coordination`` within its site scope) watch the steps live or
later, for ``ADM_AGENT_REPLAY_DAYS`` days; every viewing is audited (once per user, task
and hour). ``direction`` gets 403, another group 404.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import defer
from starlette.types import ASGIApp, Receive, Scope, Send

from services.admissions_smr.agent_policy import ENGINE_NAMES
from services.admissions_smr.agent_replay import forbidden_text
from services.admissions_smr.api.deps import (
    UNPROCESSABLE,
    Ctx,
    IngestCtx,
    lock_tenant,
    require,
)
from services.admissions_smr.api.routes_agent import LeaseIn, owned_task
from services.admissions_smr.models import (
    AgentConnection,
    AgentTask,
    AgentTaskStep,
    AuditEntry,
    Site,
)

router = APIRouter(prefix="/agent", tags=["agent"])

MAX_FRAME_BYTES = 512 * 1024
MAX_META_CHARS = 16 * 1024
# Whole multipart body, checked from Content-Length before it is read (StepUploadLimit).
MAX_BODY_BYTES = MAX_FRAME_BYTES + MAX_META_CHARS + 4096
MAX_STEPS_PER_TASK = 2000
PAGE = 500
AUDIT_EVERY = timedelta(hours=1)
NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
JPEG_MAGIC = b"\xff\xd8\xff"

WatchCtx = Annotated[Ctx, Depends(require(frozenset({"admin_groupe", "coordination"})))]

StepKind = Literal[
    "login",
    "navigate",
    "click",
    "fill",
    "select",
    "read",
    "wait",
    "scroll",
    "key",
    "verify",
    "model_action",
    "info",
    "error",
]
# CSS pixels of the viewport; an element above the fold may start at a negative offset.
Coord = Annotated[float, Field(ge=-20000, le=20000, allow_inf_nan=False)]
Size = Annotated[float, Field(ge=0, le=20000, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0, le=100_000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Point(Strict):
    x: Coord
    y: Coord


class Box(Strict):
    x: Coord
    y: Coord
    w: Size
    h: Size


class Viewport(Strict):
    w: int = Field(ge=1, le=10000)
    h: int = Field(ge=1, le=10000)


class MaskRect(Box):
    reason: Literal["identite", "secret", "autre"]


class Transmitted(Strict):
    """What a reading step sent to HospitalOS: a count and field NAMES, never values."""

    count: Count
    fields: list[Annotated[str, Field(pattern=r"^[A-Za-z0-9_]{1,60}$")]] = Field(
        default_factory=list, max_length=60
    )
    applied: Count | None = None
    duplicates: Count | None = None
    rejected: Count | None = None


class StepIn(LeaseIn):
    """The ``meta`` part of a step upload; the lease fields fence it like every task call."""

    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=1, le=2_000_000_000)
    at: AwareDatetime
    engine: str = Field(max_length=60)
    kind: StepKind
    label: str = Field(min_length=1, max_length=300)
    target: str | None = Field(default=None, max_length=200)
    pointer: Point | None = None
    box: Box | None = None
    outcome: Literal["ok", "fail", "info"]
    duration_ms: int = Field(ge=0, le=86_400_000)
    viewport: Viewport
    masks: list[MaskRect] = Field(default_factory=list, max_length=200)
    transmitted: Transmitted | None = None


class StepCreated(BaseModel):
    id: int
    seq: int


class StepOut(BaseModel):
    id: int
    seq: int
    at: datetime
    engine: str
    kind: str
    label: str
    target: str | None
    pointer: dict[str, float] | None
    box: dict[str, float] | None
    outcome: str
    duration_ms: int
    viewport: dict[str, int]
    masks: list[dict[str, Any]]
    transmitted: dict[str, Any] | None
    has_frame: bool


class ReplayTask(BaseModel):
    id: int
    kind: str
    status: str
    engine_used: str | None
    created_at: datetime
    finished_at: datetime | None
    connection_id: int | None
    connection_name: str | None
    site_name: str | None


class ReplayOut(BaseModel):
    task: ReplayTask
    live: bool
    retention_until: datetime
    steps: list[StepOut]


class StepUploadLimit:
    """Refuse a step upload larger than the limit before its body is read or spooled."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and str(scope["path"]).endswith("/steps")
        ):
            length = dict(scope["headers"]).get(b"content-length", b"")
            if not length.isdigit():
                response = JSONResponse({"detail": "Longueur de la requête requise"}, 411)
                return await response(scope, receive, send)
            if int(length) > MAX_BODY_BYTES:
                response = JSONResponse({"detail": "Étape trop volumineuse (512 Ko)"}, 413)
                return await response(scope, receive, send)
        await self.app(scope, receive, send)


# --- rights -----------------------------------------------------------------------------


def can_watch(ctx: Ctx, conn: AgentConnection | None) -> bool:
    """A task's site is its connection's site. Group-wide connections and legacy tasks
    (no connection): admin and coordination not limited to a site."""
    if ctx.user.role == "admin_groupe":
        return True
    if ctx.user.role != "coordination":
        return False
    return ctx.site_scope is None or (conn is not None and conn.site_id == ctx.site_scope)


def watched_task(ctx: Ctx, task_id: int) -> tuple[AgentTask, AgentConnection | None]:
    task = ctx.session.get(AgentTask, task_id)
    if task is None or task.group_id != ctx.group.id:
        raise HTTPException(404, "Passage introuvable")
    conn = ctx.session.get(AgentConnection, task.connection_id) if task.connection_id else None
    if can_watch(ctx, conn):
        return task, conn
    if conn is not None and conn.site_id is not None:
        raise HTTPException(404, "Passage introuvable")  # another site: not visible
    raise HTTPException(403, "Passage de tout le groupe : réservé à la coordination groupe")


def audit_view(ctx: Ctx, task_id: int) -> None:
    """``agent.replay.view`` at most once per user, task and hour (checked under the
    tenant lock, so two polls in the same second cannot both write it)."""

    def seen() -> bool:
        return (
            ctx.session.scalar(
                select(AuditEntry.id)
                .where(
                    AuditEntry.group_id == ctx.group.id,
                    AuditEntry.user_id == ctx.user.id,
                    AuditEntry.action == "agent.replay.view",
                    AuditEntry.entity_id == str(task_id),
                    AuditEntry.at > ctx.clock.now() - AUDIT_EVERY,
                )
                .limit(1)
            )
            is not None
        )

    if seen():
        return
    ctx.session.rollback()
    lock_tenant(ctx.session, ctx.group.id)
    if not seen():
        ctx.audit("agent.replay.view", "agent_task", task_id, None)
    ctx.session.commit()


# --- worker -----------------------------------------------------------------------------


def parse_meta(raw: str) -> StepIn:
    try:
        return StepIn.model_validate_json(raw)
    except ValidationError as exc:
        # Field and rule only: a refused value is never echoed (REVIEW S-M2).
        detail = [
            {"loc": ["meta", *e["loc"]], "msg": e["msg"], "type": e["type"]} for e in exc.errors()
        ]
        raise HTTPException(UNPROCESSABLE, detail[:10]) from exc


@router.post("/tasks/{task_id}/steps", response_model=StepCreated, status_code=201)
def post_step(
    task_id: int,
    ctx: IngestCtx,
    response: Response,
    meta: Annotated[str, Form(max_length=MAX_META_CHARS)],
    frame: Annotated[UploadFile | None, File()] = None,
) -> StepCreated:
    body = parse_meta(meta)
    task = owned_task(ctx, task_id, body, check_work=False)
    if body.engine not in ENGINE_NAMES:
        raise HTTPException(UNPROCESSABLE, "Moteur inconnu")
    if forbidden_text(body.label) or forbidden_text(body.target):
        raise HTTPException(UNPROCESSABLE, "Libellé refusé : il ressemble à un NIR ou à une date")
    image: bytes | None = None
    if frame is not None:
        if frame.content_type != "image/jpeg":
            raise HTTPException(415, "Image JPEG attendue")
        image = frame.file.read(MAX_FRAME_BYTES + 1)
        if len(image) > MAX_FRAME_BYTES:
            raise HTTPException(413, "Image trop volumineuse (512 Ko)")
        if not image.startswith(JPEG_MAGIC):
            raise HTTPException(415, "Image JPEG attendue")
    existing = ctx.session.scalar(
        select(AgentTaskStep.id).where(
            AgentTaskStep.task_id == task.id, AgentTaskStep.seq == body.seq
        )
    )
    if existing is not None:  # a retried upload whose answer was lost
        response.status_code = 200
        return StepCreated(id=existing, seq=body.seq)
    count = ctx.session.scalar(
        select(func.count()).select_from(AgentTaskStep).where(AgentTaskStep.task_id == task.id)
    )
    if int(count or 0) >= MAX_STEPS_PER_TASK:
        raise HTTPException(409, "Nombre maximal d'étapes atteint pour ce passage")

    def dump(model: BaseModel | None) -> str | None:
        return model.model_dump_json() if model is not None else None

    step = AgentTaskStep(
        group_id=ctx.group.id,
        task_id=task.id,
        seq=body.seq,
        at=body.at,
        engine=body.engine,
        kind=body.kind,
        label=body.label,
        target=body.target,
        pointer_json=dump(body.pointer),
        box_json=dump(body.box),
        outcome=body.outcome,
        duration_ms=body.duration_ms,
        viewport_json=body.viewport.model_dump_json(),
        masks_json=json.dumps([m.model_dump() for m in body.masks]),
        transmitted_json=dump(body.transmitted),
        frame=image,
        created_at=ctx.clock.now(),
    )
    ctx.session.add(step)
    ctx.session.commit()
    return StepCreated(id=step.id, seq=step.seq)


# --- people -----------------------------------------------------------------------------


def step_out(step: AgentTaskStep, has_frame: bool) -> StepOut:
    def load(raw: str | None) -> Any:
        return json.loads(raw) if raw else None

    return StepOut(
        id=step.id,
        seq=step.seq,
        at=step.at,
        engine=step.engine,
        kind=step.kind,
        label=step.label,
        target=step.target,
        pointer=load(step.pointer_json),
        box=load(step.box_json),
        outcome=step.outcome,
        duration_ms=step.duration_ms,
        viewport=load(step.viewport_json),
        masks=load(step.masks_json) or [],
        transmitted=load(step.transmitted_json),
        has_frame=has_frame,
    )


@router.get("/tasks/{task_id}/replay", response_model=ReplayOut)
def replay(
    task_id: int,
    ctx: WatchCtx,
    response: Response,
    after_seq: int = Query(0, ge=0, le=2_000_000_000),
) -> ReplayOut:
    task, conn = watched_task(ctx, task_id)
    site = ctx.session.get(Site, conn.site_id) if conn and conn.site_id else None
    rows = ctx.session.execute(
        select(AgentTaskStep, AgentTaskStep.frame.is_not(None))
        .options(defer(AgentTaskStep.frame))
        .where(AgentTaskStep.task_id == task.id, AgentTaskStep.seq > after_seq)
        .order_by(AgentTaskStep.seq)
        .limit(PAGE)
    ).tuples()
    steps = [step_out(s, bool(has_frame)) for s, has_frame in rows]
    oldest = ctx.session.scalar(
        select(func.min(AgentTaskStep.created_at)).where(AgentTaskStep.task_id == task.id)
    )
    if isinstance(oldest, datetime) and oldest.tzinfo is None:  # SQLite aggregate: naive UTC
        oldest = oldest.replace(tzinfo=task.created_at.tzinfo)
    out = ReplayOut(
        task=ReplayTask(
            id=task.id,
            kind=task.kind,
            status=task.status,
            engine_used=task.engine_used,
            created_at=task.created_at,
            finished_at=task.finished_at,
            connection_id=task.connection_id,
            connection_name=conn.name if conn else None,
            site_name=site.name if site else None,
        ),
        live=task.status == "running",
        retention_until=(oldest or task.created_at)
        + timedelta(days=ctx.settings.agent_replay_days),
        steps=steps,
    )
    audit_view(ctx, task.id)
    response.headers.update(NO_STORE)
    return out


@router.get("/steps/{step_id}/frame", response_class=Response)
def frame(step_id: int, ctx: WatchCtx) -> Response:
    step = ctx.session.get(AgentTaskStep, step_id)
    if step is None or step.group_id != ctx.group.id:
        raise HTTPException(404, "Image introuvable")
    watched_task(ctx, step.task_id)
    image, task_id = step.frame, step.task_id
    if image is None:
        raise HTTPException(404, "Image introuvable")
    audit_view(ctx, task_id)
    return Response(content=image, media_type="image/jpeg", headers=NO_STORE)
