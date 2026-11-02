"""Connections of the computer-use agent: catalogue, schedule, task routing and claims.

A connection is one software the agent reads for a site (``agent_connections``). The API
decides the rhythm: ``next_run_at`` is computed from the interval, the active window (local
time) and the allowed days; when a worker that can run the connection sends its heartbeat
and a run is due, the sync task is created then (never twice while one is pending or
running). Pausing a connection keeps its pending tasks visible but no longer claimable;
resuming makes them claimable again.

Workers report the playbooks bundled with them. A connection names one of them; only a
worker whose catalogue contains it (and the assigned worker, when one is set) claims its
tasks. Legacy tasks without connection go to workers configured with environment
variables (``legacy`` claims).
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from services.admissions_smr.api.deps import Ctx
from services.admissions_smr.clock import local_time
from services.admissions_smr.models import AgentConnection, AgentTask, AgentWorker

CONNECTION_KINDS: dict[str, tuple[str, ...]] = {
    "portail_orientation": ("sync_inbox", "reply_portal"),
    "gestion_lits": ("sync_movements",),
}
SYNC_KINDS = ("sync_inbox", "sync_movements")
ALL_DAYS = [1, 2, 3, 4, 5, 6, 7]  # ISO weekdays, 1 = Monday
OPEN_STATUSES = ("pending", "running")

# Playbooks bundled with the agent image: accepted before any worker has reported its own
# catalogue (first set-up, demo seeds). Once a worker has reported, its catalogue rules.
BUNDLED_PLAYBOOKS: dict[str, dict[str, Any]] = {
    "demo_portal": {
        "name": "demo_portal",
        "label": "Portail d'orientation (démonstration)",
        "kind": "portail_orientation",
        "tasks": ["sync_inbox", "reply_portal"],
    },
    "demo_bedsoft": {
        "name": "demo_bedsoft",
        "label": "Gestion des lits (démonstration)",
        "kind": "gestion_lits",
        "tasks": ["sync_movements"],
    },
}


def loads(raw: str | None, default: Any) -> Any:
    try:
        value = json.loads(raw or "null")
    except ValueError:
        return default
    return default if value is None else value


def tasks_of(conn: AgentConnection) -> list[str]:
    return [str(t) for t in loads(conn.tasks_json, [])]


def hhmm(value: time | None) -> str | None:
    """Window bounds as the interface sends them: "HH:MM", local time."""
    return value.strftime("%H:%M") if value else None


def days_of(conn: AgentConnection) -> list[int]:
    return [int(d) for d in loads(conn.days_json, ALL_DAYS)]


def catalogue(worker: AgentWorker) -> dict[str, dict[str, Any]]:
    return {str(p["name"]): p for p in loads(worker.playbooks_json, []) if isinstance(p, dict)}


def group_catalogue(ctx: Ctx, agent_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Playbooks a connection may name: the assigned worker's, else every worker's of the
    group (latest heartbeat wins), else the bundled ones when no worker has reported."""
    query = select(AgentWorker).where(AgentWorker.group_id == ctx.group.id)
    if agent_id is not None:
        query = query.where(AgentWorker.agent_id == agent_id)
    merged: dict[str, dict[str, Any]] = {}
    workers = list(ctx.session.scalars(query.order_by(AgentWorker.last_heartbeat_at)))
    for worker in workers:
        merged.update(catalogue(worker))
    if not merged and agent_id is None:
        return dict(BUNDLED_PLAYBOOKS)
    return merged


# --- schedule ---------------------------------------------------------------------------


def next_run(conn: AgentConnection, after: datetime, ctx: Ctx) -> datetime | None:
    """Earliest instant at or after ``after`` inside the active window, on an allowed day
    (local time of the group, daylight saving handled). None: no allowed day."""
    zone = ctx.clock.zone
    days = set(days_of(conn))
    start_day = after.astimezone(zone).date()
    for offset in range(8):
        day = start_day + timedelta(days=offset)
        if day.isoweekday() not in days:
            continue
        start = local_time(day, conn.active_from or time.min, zone)
        end = (
            local_time(day, conn.active_to, zone)
            if conn.active_to
            else local_time(day + timedelta(days=1), time.min, zone)
        )
        start = max(start, after)
        if start < end:
            return start
    return None


def open_task(ctx: Ctx, conn: AgentConnection, kind: str) -> AgentTask | None:
    task: AgentTask | None = ctx.session.scalar(
        select(AgentTask).where(
            AgentTask.group_id == ctx.group.id,
            AgentTask.connection_id == conn.id,
            AgentTask.kind == kind,
            AgentTask.status.in_(OPEN_STATUSES),
        )
    )
    return task


def create_sync_task(ctx: Ctx, conn: AgentConnection, kind: str) -> AgentTask:
    """The connection's pending (or running) task of that kind, or a new one."""
    existing = open_task(ctx, conn, kind)
    if existing is not None:
        return existing
    now = ctx.clock.now()
    task = AgentTask(
        group_id=ctx.group.id,
        kind=kind,
        payload_json="{}",
        status="pending",
        created_at=now,
        updated_at=now,
        connection_id=conn.id,
    )
    ctx.session.add(task)
    ctx.session.flush()
    return task


def assignable(conn: AgentConnection, worker: AgentWorker) -> bool:
    return (
        conn.archived_at is None
        and conn.agent_id in (None, worker.agent_id)
        and conn.playbook in catalogue(worker)
    )


def worker_connections(ctx: Ctx, worker: AgentWorker) -> list[AgentConnection]:
    rows = ctx.session.scalars(
        select(AgentConnection)
        .where(AgentConnection.group_id == ctx.group.id, AgentConnection.archived_at.is_(None))
        .order_by(AgentConnection.id)
    )
    return [c for c in rows if assignable(c, worker)]


def schedule_due(ctx: Ctx, worker: AgentWorker, paused: bool) -> None:
    """On a worker's heartbeat: create the sync tasks that are due for the active
    connections this worker can run. Nothing is created during a group pause."""
    if paused:
        return
    now = ctx.clock.now()
    for conn in worker_connections(ctx, worker):
        if conn.status != "active":
            continue
        if conn.next_run_at is None:
            conn.next_run_at = next_run(conn, now, ctx)
        if conn.next_run_at is None or conn.next_run_at > now:
            continue
        if next_run(conn, now, ctx) != now:  # due, but the window closed meanwhile
            conn.next_run_at = next_run(conn, now, ctx)
            continue
        for kind in tasks_of(conn):
            if kind in SYNC_KINDS:
                create_sync_task(ctx, conn, kind)
        conn.next_run_at = next_run(conn, now + timedelta(minutes=conn.interval_minutes), ctx)


# --- routing ------------------------------------------------------------------------------


def portal_connection_for(ctx: Ctx, site_id: int | None) -> AgentConnection | None:
    """Where a reply goes: the portal connection (with ``reply_portal``) of the request's
    site, else the group-wide one, else any. An active one first; a paused or stopped one
    still takes the task, which then waits for it to be (re)started."""
    candidates = [
        c
        for c in ctx.session.scalars(
            select(AgentConnection)
            .where(
                AgentConnection.group_id == ctx.group.id,
                AgentConnection.kind == "portail_orientation",
                AgentConnection.archived_at.is_(None),
            )
            .order_by(AgentConnection.id)
        )
        if "reply_portal" in tasks_of(c)
    ]

    def rank(c: AgentConnection) -> tuple[int, int]:
        place = 0 if site_id is not None and c.site_id == site_id else 1 if c.site_id is None else 2
        return (0 if c.status == "active" else 1, place)

    return min(candidates, key=rank) if candidates else None


def claimable(ctx: Ctx, agent_id: str, legacy: bool) -> Any:
    """SQL condition on ``AgentTask``: legacy tasks for legacy workers; connection tasks for
    an ``ingestion`` account whose worker's catalogue has the connection's playbook, on an
    active connection assigned to that worker or to any."""
    worker = ctx.session.scalar(
        select(AgentWorker).where(
            AgentWorker.group_id == ctx.group.id, AgentWorker.agent_id == agent_id
        )
    )
    names = list(catalogue(worker)) if worker is not None else []
    conditions = []
    if legacy:
        conditions.append(AgentTask.connection_id.is_(None))
    if names and ctx.user.role == "ingestion":
        conditions.append(
            AgentTask.connection_id.in_(
                select(AgentConnection.id).where(
                    AgentConnection.group_id == ctx.group.id,
                    AgentConnection.status == "active",
                    AgentConnection.archived_at.is_(None),
                    AgentConnection.playbook.in_(names),
                    or_(AgentConnection.agent_id.is_(None), AgentConnection.agent_id == agent_id),
                )
            )
        )
    return or_(*conditions) if conditions else AgentTask.id.is_(None)


def task_counts(ctx: Ctx) -> dict[int, dict[str, int]]:
    """Open and needs-human tasks per connection, for the cards."""
    query = (
        select(AgentTask.connection_id, AgentTask.status, func.count())
        .where(
            AgentTask.group_id == ctx.group.id,
            AgentTask.connection_id.is_not(None),
            AgentTask.status.in_((*OPEN_STATUSES, "needs_human")),
        )
        .group_by(AgentTask.connection_id, AgentTask.status)
    )
    out: dict[int, dict[str, int]] = {}
    for connection_id, task_status, count in ctx.session.execute(query).tuples():
        bucket = out.setdefault(int(connection_id or 0), {"pending": 0, "needs_human": 0})
        key = "needs_human" if task_status == "needs_human" else "pending"
        bucket[key] += int(count)
    return out


def record_run(ctx: Ctx, task: AgentTask, outcome: str) -> None:
    """Last run of the connection, when one of its tasks ends (no screen value: the error
    is the agent's own message)."""
    if task.connection_id is None:
        return
    conn = ctx.session.get(AgentConnection, task.connection_id)
    if conn is None or conn.group_id != ctx.group.id:
        return
    conn.last_run_at = ctx.clock.now()
    conn.last_outcome = outcome
    conn.last_error = task.error if outcome != "done" else None
