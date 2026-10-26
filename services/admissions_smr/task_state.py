"""Decision fencing shared by human workflows and the portal task queue."""

from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy import select

from services.admissions_smr.api.deps import Ctx
from services.admissions_smr.models import AdmissionRequest, AgentTask

OPEN_TASKS = ("pending", "running", "failed", "needs_human")


def decision_changed(ctx: Ctx, req: AdmissionRequest) -> None:
    """Called under the tenant mutation lock, before committing any changed decision.

    Once a submission may be in flight, humans must reconcile it before replacing it.
    A portal is not transactional with our database: never pretend it can be rolled back.
    """
    tasks = list(
        ctx.session.scalars(
            select(AgentTask).where(
                AgentTask.group_id == ctx.group.id,
                AgentTask.request_id == req.id,
                AgentTask.kind == "reply_portal",
                AgentTask.status.in_(OPEN_TASKS),
            )
        )
    )
    if any(t.write_started_at is not None for t in tasks):
        raise HTTPException(
            409,
            "Une réponse est en cours ou reste à vérifier sur le portail. "
            "Vérifiez son résultat avant de modifier la décision.",
        )
    for task in tasks:
        task.status = "cancelled"
        task.error = "Décision remplacée : cette réponse ne doit plus être envoyée"
        task.lease_token = None
        task.lease_until = None
        task.budget_reserved_usd = 0.0
        task.updated_at = task.finished_at = ctx.clock.now()
    req.decision_version += 1


def decision_is_current(ctx: Ctx, task: AgentTask) -> bool:
    if task.kind != "reply_portal":
        return True
    req = ctx.session.get(AdmissionRequest, task.request_id)
    if req is None or req.group_id != ctx.group.id or req.decision_version != task.decision_version:
        return False
    payload = json.loads(task.payload_json)
    if payload.get("external_ref") != req.external_ref or payload.get("site_id") != req.site_id:
        return False
    if payload.get("decision") == "accord":
        return bool(
            req.status in ("accord", "confirmee")
            and req.proposed_date
            and payload.get("proposed_date") == req.proposed_date.isoformat()
        )
    return req.status == "refusee" and payload.get("reason_code") == req.refusal_reason
