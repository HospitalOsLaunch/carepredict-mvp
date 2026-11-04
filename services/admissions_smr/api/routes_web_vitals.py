"""Core Web Vitals of real visits (règle 30 de l'audit de performance).

The browser of each signed-in person reports how fast HospitalOS felt (LCP, INP, CLS, FCP,
TTFB) to the group's own API: no third party ever receives them. A measure carries the
screen as its route template (``/demandes/:id``, never an id), the device class and the
network type, nothing else: no user, no address, no browser, no time of day. Kept 90
days. The administrator reads the 75th percentile of each screen, the figure Google uses.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select

from services.admissions_smr.agent_replay import purge_due
from services.admissions_smr.api.deps import AdminCtx, Ctx, require
from services.admissions_smr.models import WebVital
from services.admissions_smr.vocab import READ_ROLES

router = APIRouter()

RETENTION_DAYS = 90
Metric = Literal["LCP", "INP", "CLS", "FCP", "TTFB"]
Device = Literal["mobile", "tablette", "bureau"]
Connection = Literal["slow-2g", "2g", "3g", "4g", "inconnu"]

# The screens of the application, as route templates; anything else is « autre ».
PAGES = frozenset(
    {
        "/",
        "/demandes",
        "/demandes/:id",
        "/lits",
        "/plan-des-lits",
        "/urgences",
        "/prevision",
        "/charge",
        "/groupe",
        "/indicateurs",
        "/ror",
        "/agents",
        "/agents/passages/:id",
        "/imports",
        "/parametres",
    }
)
# « Good » up to the first value, « poor » beyond the second (web.dev, Core Web Vitals).
THRESHOLDS: dict[str, tuple[float, float]] = {
    "LCP": (2500, 4000),
    "INP": (200, 500),
    "CLS": (0.1, 0.25),
    "FCP": (1800, 3000),
    "TTFB": (800, 1800),
}
# Reporting never takes the tenant's write lock: it only adds rows of its own.
ReportCtx = Annotated[Ctx, Depends(require(READ_ROLES, lock=False))]


class VitalIn(BaseModel):
    metric: Metric
    value: float = Field(ge=0, le=600_000)
    page: str = Field(max_length=60)
    device: Device
    connection: Connection = "inconnu"

    @model_validator(mode="after")
    def bounded(self) -> VitalIn:
        if self.metric == "CLS" and self.value > 50:
            raise ValueError("CLS hors bornes")
        return self


class VitalsIn(BaseModel):
    vitals: list[VitalIn] = Field(min_length=1, max_length=20)


class VitalSummaryOut(BaseModel):
    page: str
    metric: str
    p75: float
    samples: int
    rating: Literal["bon", "a_ameliorer", "mauvais"]


class VitalsSummaryOut(BaseModel):
    days: int
    samples: int
    rows: list[VitalSummaryOut]


def rating(metric: str, value: float) -> Literal["bon", "a_ameliorer", "mauvais"]:
    good, poor = THRESHOLDS[metric]
    return "bon" if value <= good else "mauvais" if value > poor else "a_ameliorer"


def p75(values: list[float]) -> float:
    """The 75th percentile, nearest rank (the value 75 % of visits do not exceed)."""
    ordered = sorted(values)
    return ordered[max(0, -(-len(ordered) * 3 // 4) - 1)]


@router.post("/web-vitals", status_code=status.HTTP_204_NO_CONTENT, tags=["meta"])
def report(body: VitalsIn, ctx: ReportCtx, request: Request) -> None:
    today = ctx.clock.today()
    ctx.session.add_all(
        WebVital(
            group_id=ctx.group.id,
            recorded_on=today,
            page=v.page if v.page in PAGES else "autre",
            metric=v.metric,
            value=round(v.value, 4) if v.metric == "CLS" else round(v.value),
            device=v.device,
            connection=v.connection,
        )
        for v in body.vitals
    )
    done = request.app.state.__dict__.setdefault("vitals_purged_at", {})
    if purge_due(done, ctx.group.id, ctx.clock.now()):
        ctx.session.execute(
            delete(WebVital).where(
                WebVital.group_id == ctx.group.id,
                WebVital.recorded_on < today - timedelta(days=RETENTION_DAYS),
            )
        )
    ctx.session.commit()


@router.get("/web-vitals", response_model=VitalsSummaryOut, tags=["meta"])
def summary(
    ctx: AdminCtx,
    days: int = Query(28, ge=1, le=RETENTION_DAYS),
    device: Device | None = None,
) -> VitalsSummaryOut:
    since = ctx.clock.today() - timedelta(days=days - 1)
    query = select(WebVital.page, WebVital.metric, WebVital.value).where(
        WebVital.group_id == ctx.group.id, WebVital.recorded_on >= since
    )
    if device is not None:
        query = query.where(WebVital.device == device)
    values: dict[tuple[str, str], list[float]] = defaultdict(list)
    for page, metric, value in ctx.session.execute(query):
        values[(page, metric)].append(value)
    rows = [
        VitalSummaryOut(
            page=page, metric=metric, p75=p75(vs), samples=len(vs), rating=rating(metric, p75(vs))
        )
        for (page, metric), vs in sorted(values.items())
    ]
    return VitalsSummaryOut(days=days, samples=sum(r.samples for r in rows), rows=rows)
