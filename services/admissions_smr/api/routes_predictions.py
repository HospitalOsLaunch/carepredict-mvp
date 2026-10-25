"""Predictions beyond discharges: care workload against planned staff, and its replay."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from services.admissions_smr.api.deps import UNPROCESSABLE, Ctx, ReadCtx, WriteCtx
from services.admissions_smr.domain.forecast import HazardModel, fit_hazard
from services.admissions_smr.domain.workload import (
    Arrival,
    CareMinutes,
    admission_rate_by_weekday,
    backtest_workload,
    forecast_workload,
)
from services.admissions_smr.models import Site, StaffPlan
from services.admissions_smr.schemas import (
    DayStaffIn,
    PoolWorkloadOut,
    StaffPoolOut,
    WeeklyStaffIn,
    WorkloadBacktestOut,
    WorkloadDayOut,
    WorkloadOut,
)
from services.admissions_smr.service import (
    HORIZON_DAYS,
    build_forecast,
    get_site,
    group_sites,
    reserved_arrivals,
)
from services.admissions_smr.vocab import MENTIONS

router = APIRouter(tags=["predictions"])

OVERRIDE_WINDOW_DAYS = 60


def care_minutes_of(ctx: Ctx) -> CareMinutes:
    try:
        raw = json.loads(ctx.group.care_minutes_json or "{}")
    except json.JSONDecodeError:
        raw = {}
    return CareMinutes.from_settings(
        {str(k): float(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    )


def care_minutes_dict(minutes: CareMinutes) -> dict[str, float]:
    return {
        **{str(k): v for k, v in minutes.per_level.items()},
        "entree": minutes.admission,
        "sortie": minutes.discharge,
    }


def staff_minutes_by_pool(
    ctx: Ctx, site_ids: list[int], start: date, days: int
) -> dict[tuple[int, str], dict[date, float]]:
    """Care minutes available per pool and day: a dated override wins over the weekly pattern."""
    rows = list(
        ctx.session.scalars(
            select(StaffPlan).where(
                StaffPlan.group_id == ctx.group.id, StaffPlan.site_id.in_(site_ids)
            )
        )
    )
    weekly: dict[tuple[int, str], dict[int, float]] = defaultdict(dict)
    dated: dict[tuple[int, str], dict[date, float]] = defaultdict(dict)
    for r in rows:
        key = (r.site_id, r.mention)
        if r.day is not None:
            dated[key][r.day] = r.care_hours
        elif r.weekday is not None:
            weekly[key][r.weekday] = r.care_hours
    out: dict[tuple[int, str], dict[date, float]] = defaultdict(dict)
    for key in set(weekly) | set(dated):
        for k in range(days):
            d = start + timedelta(days=k)
            hours = dated[key].get(d, weekly[key].get(d.weekday()))
            if hours is not None:
                out[key][d] = hours * 60.0
    return out


@router.get("/forecast/workload", response_model=WorkloadOut)
def workload(
    ctx: ReadCtx,
    site_id: int | None = None,
    horizon: int = Query(HORIZON_DAYS, ge=1, le=28),
) -> WorkloadOut:
    today = ctx.clock.today()
    sites = group_sites(ctx)
    if site_id is not None:
        sites = [s for s in sites if s.id == site_id]
        if not sites:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Site introuvable")
    minutes = care_minutes_of(ctx)
    fc = build_forecast(ctx.session, ctx.group.id, sites, today, horizon)
    promised = reserved_arrivals(ctx.session, ctx.group.id)
    staff = staff_minutes_by_pool(ctx, [s.id for s in sites], today, horizon)
    pools: list[PoolWorkloadOut] = []
    known = total = 0
    for site in sites:
        for pool in site.pools:
            key = (site.id, pool.mention)
            active = fc.active_by_pool.get(key, [])
            known += sum(1 for s in active if s.care_level)
            total += len(active)
            history = [r for r in fc.records if (r.site_id, r.mention) == key]
            days = forecast_workload(
                active,
                pool.beds_open,
                today,
                horizon,
                fc.model,
                minutes,
                arrivals=[Arrival(d, lvl) for d, lvl in promised.get(key, [])],
                admission_rate=admission_rate_by_weekday(history, today),
                staff_minutes=staff.get(key),
                plan_slip=fc.slip.weights,
            )
            pools.append(
                PoolWorkloadOut(
                    site_id=site.id,
                    site_name=site.name,
                    mention=pool.mention,
                    beds_open=pool.beds_open,
                    occupied_now=len(active),
                    staffing_configured=bool(staff.get(key)),
                    days=[WorkloadDayOut(**d.__dict__) for d in days],
                )
            )
    return WorkloadOut(
        as_of=today,
        horizon=horizon,
        care_minutes=care_minutes_dict(minutes),
        plan_slip_is_prior=not fc.slip.measured,
        plan_slip_samples=fc.slip.samples,
        care_level_known_share=round(known / total, 3) if total else None,
        pools=pools,
    )


@router.get("/staffing", response_model=list[StaffPoolOut])
def list_staffing(ctx: ReadCtx, site_id: int | None = None) -> list[StaffPoolOut]:
    sites = group_sites(ctx)
    if site_id is not None:
        sites = [s for s in sites if s.id == site_id]
    today = ctx.clock.today()
    rows = list(
        ctx.session.scalars(
            select(StaffPlan).where(
                StaffPlan.group_id == ctx.group.id,
                StaffPlan.site_id.in_([s.id for s in sites]),
            )
        )
    )
    out: list[StaffPoolOut] = []
    for site in sites:
        for pool in site.pools:
            mine = [r for r in rows if r.site_id == site.id and r.mention == pool.mention]
            weekly: list[float | None] = [None] * 7
            overrides: dict[str, float] = {}
            for r in mine:
                if r.weekday is not None:
                    weekly[r.weekday] = r.care_hours
                elif r.day is not None and today <= r.day <= today + timedelta(
                    days=OVERRIDE_WINDOW_DAYS
                ):
                    overrides[r.day.isoformat()] = r.care_hours
            out.append(
                StaffPoolOut(
                    site_id=site.id,
                    site_name=site.name,
                    mention=pool.mention,
                    weekly_hours=weekly,
                    overrides=dict(sorted(overrides.items())),
                )
            )
    return out


def _pool_site(ctx: Ctx, site_id: int, mention: str) -> Site:
    if mention not in MENTIONS:
        raise HTTPException(UNPROCESSABLE, "Mention inconnue")
    site = get_site(ctx, site_id)
    if not ctx.can_see_site(site.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Site hors de votre périmètre")
    if not any(p.mention == mention for p in site.pools):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mention absente de ce site")
    return site


@router.put("/staffing/{site_id}/{mention}/weekly", response_model=list[StaffPoolOut])
def put_weekly(
    site_id: int, mention: str, body: WeeklyStaffIn, ctx: WriteCtx
) -> list[StaffPoolOut]:
    site = _pool_site(ctx, site_id, mention)
    existing = {
        r.weekday: r
        for r in ctx.session.scalars(
            select(StaffPlan).where(
                StaffPlan.site_id == site.id,
                StaffPlan.mention == mention,
                StaffPlan.weekday.is_not(None),
            )
        )
    }
    for weekday, hours in enumerate(body.hours):
        row = existing.get(weekday)
        if hours is None:
            if row is not None:
                ctx.session.delete(row)
            continue
        if row is None:
            row = StaffPlan(
                group_id=ctx.group.id,
                site_id=site.id,
                mention=mention,
                weekday=weekday,
                care_hours=hours,
            )
            ctx.session.add(row)
        row.care_hours = hours
        row.comment = body.comment
        row.updated_at = ctx.clock.now()
    ctx.audit("effectif.semaine", "staff_plan", f"{site.id}:{mention}", json.dumps(body.hours))
    ctx.session.commit()
    return list_staffing(ctx, site.id)


@router.put("/staffing/{site_id}/{mention}/days/{day}", response_model=list[StaffPoolOut])
def put_day(
    site_id: int, mention: str, day: date, body: DayStaffIn, ctx: WriteCtx
) -> list[StaffPoolOut]:
    site = _pool_site(ctx, site_id, mention)
    row = ctx.session.scalar(
        select(StaffPlan).where(
            StaffPlan.site_id == site.id, StaffPlan.mention == mention, StaffPlan.day == day
        )
    )
    if body.care_hours is None:
        if row is not None:
            ctx.session.delete(row)
    else:
        if row is None:
            row = StaffPlan(
                group_id=ctx.group.id,
                site_id=site.id,
                mention=mention,
                day=day,
                care_hours=body.care_hours,
            )
            ctx.session.add(row)
        row.care_hours = body.care_hours
        row.comment = body.comment
        row.updated_at = ctx.clock.now()
    ctx.audit("effectif.jour", "staff_plan", f"{site.id}:{mention}:{day}", str(body.care_hours))
    ctx.session.commit()
    return list_staffing(ctx, site.id)


@router.get("/metrics/backtest/workload", response_model=WorkloadBacktestOut)
def workload_backtest(
    ctx: ReadCtx, site_id: int | None = None, weeks: int = Query(8, ge=2, le=26)
) -> WorkloadBacktestOut:
    today = ctx.clock.today()
    sites = group_sites(ctx)
    if site_id is not None:
        sites = [s for s in sites if s.id == site_id]
    minutes = care_minutes_of(ctx)
    fc = build_forecast(ctx.session, ctx.group.id, sites, today)
    models: dict[date, HazardModel] = {}

    def model_for(as_of: date) -> HazardModel:
        if as_of not in models:
            models[as_of] = fit_hazard(fc.records, as_of)
        return models[as_of]

    as_of_dates = [today - timedelta(days=7 + 7 * k) for k in range(weeks)][::-1]
    totals: dict[tuple[date, int], list[float]] = {}
    all_points = []
    for site in sites:
        for pool in site.pools:
            stays = [r for r in fc.records if (r.site_id, r.mention) == (site.id, pool.mention)]
            result = backtest_workload(
                stays, pool.beds_open, as_of_dates, today, minutes, model_for
            )
            all_points.extend(result.points)
            for as_of, k, mean, p10, p90, actual in result.points:
                agg = totals.setdefault((as_of, k), [0.0, 0.0, 0.0, 0.0])
                agg[0] += mean
                agg[1] += actual
                agg[2] += p10
                agg[3] += p90
    useful = [p for p in all_points if p[5] > 0]
    n = len(useful)
    mape = sum(abs(p[2] - p[5]) / p[5] for p in useful) / n if n else None
    bias = sum((p[2] - p[5]) / p[5] for p in useful) / n if n else None
    cover = sum(1 for p in useful if p[3] <= p[5] <= p[4]) / n if n else None
    points: list[dict[str, float | str]] = [
        {
            "as_of": as_of.isoformat(),
            "k": float(k),
            "predicted_hours": round(v[0] / 60, 1),
            "actual_hours": round(v[1] / 60, 1),
        }
        for (as_of, k), v in sorted(totals.items())
        if k in (0, 3, 6)
    ]
    return WorkloadBacktestOut(
        points=points,
        mape=None if mape is None else round(mape, 4),
        bias_pct=None if bias is None else round(bias, 4),
        coverage_80=None if cover is None else round(cover, 3),
        note=(
            "Rejeu à J+0..J+6 avec les seules données connues chaque matin, sans les promesses "
            "d'admission (non historisées). La charge réelle est recalculée avec les mêmes minutes "
            "par niveau : ce rejeu mesure la prévision des présences et des admissions, pas la "
            "justesse des minutes par niveau, qui reste à calibrer avec l'outil de charge "
            "des unités."
        ),
    )
