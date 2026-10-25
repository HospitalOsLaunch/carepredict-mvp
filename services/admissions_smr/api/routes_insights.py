"""Forecast, group dashboard, pilot indicators, backtest and group settings."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.admissions_smr.api.deps import UNPROCESSABLE, AdminCtx, Ctx, ReadCtx
from services.admissions_smr.domain.forecast import StayRecord, backtest
from services.admissions_smr.domain.metrics import (
    CapacityPoint,
    PoolCapacity,
    PoolSeries,
    RequestRecord,
    daily_capacity,
    daily_occupancy,
    date_range,
    north_star,
    pool_capacity,
    summarise_occupancy,
    summarise_requests,
)
from services.admissions_smr.domain.scoring import DEFAULT_WEIGHTS
from services.admissions_smr.models import AdmissionRequest, CapacityChange, RequestEvent
from services.admissions_smr.schemas import (
    BacktestOut,
    BacktestPointOut,
    BaselineIn,
    BaselineOut,
    DayForecastOut,
    ForecastBasis,
    ForecastOut,
    GroupDashboardOut,
    GroupSettingsIn,
    GroupSettingsOut,
    NorthStarOut,
    OccupancyOut,
    PilotMetricsOut,
    PoolForecastOut,
    RequestsSummaryOut,
    SiteCardOut,
)
from services.admissions_smr.service import (
    HORIZON_DAYS,
    build_forecast,
    get_site,
    group_sites,
    stay_records,
    weights_of,
)
from services.admissions_smr.vocab import AWAITING_RESPONSE_STATUSES, MENTIONS

router = APIRouter()


@router.get("/forecast", response_model=ForecastOut, tags=["prevision"])
def forecast(
    ctx: ReadCtx, site_id: int | None = None, horizon: int = Query(HORIZON_DAYS, ge=1, le=28)
) -> ForecastOut:
    sites = group_sites(ctx)
    if site_id is not None:
        sites = [s for s in sites if s.id == site_id]
        if not sites:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Site introuvable")
    today = ctx.clock.today()
    fc = build_forecast(ctx.session, ctx.group.id, sites, today, horizon)
    pools: list[PoolForecastOut] = []
    for site in sites:
        for pool in site.pools:
            pf = fc.pools.get((site.id, pool.mention))
            if pf is None:
                continue
            pools.append(
                PoolForecastOut(
                    site_id=site.id,
                    site_name=site.name,
                    mention=pool.mention,
                    beds_open=pool.beds_open,
                    beds_installed=pool.beds_installed,
                    occupied_now=pf.occupied_now,
                    days=[DayForecastOut(**d.__dict__) for d in pf.days],
                )
            )
    return ForecastOut(
        as_of=today,
        horizon=horizon,
        basis=ForecastBasis(
            method="Kaplan-Meier discret par mention + dates de sortie prévues",
            stays_used=sum(fc.model.n_stays.values()),
            completed_stays_used=sum(fc.model.n_completed.values()),
            low_data_mentions=fc.low_data_mentions,
            plan_slip_is_prior=True,
        ),
        pools=pools,
    )


@router.get("/dashboard", response_model=GroupDashboardOut, tags=["prevision"])
def dashboard(ctx: ReadCtx) -> GroupDashboardOut:
    today = ctx.clock.today()
    now = ctx.clock.now()
    sites = group_sites(ctx)
    fc = build_forecast(ctx.session, ctx.group.id, sites, today)

    open_reqs = list(
        ctx.session.scalars(
            select(AdmissionRequest).where(
                AdmissionRequest.group_id == ctx.group.id,
                AdmissionRequest.status.in_(AWAITING_RESPONSE_STATUSES),
            )
        )
    )
    if ctx.site_scope is not None:
        open_reqs = [r for r in open_reqs if r.site_id in (None, ctx.site_scope)]

    cards: list[SiteCardOut] = []
    day7 = min(6, HORIZON_DAYS - 1)
    for site in sites:
        installed = sum(p.beds_installed for p in site.pools)
        opened = sum(p.beds_open for p in site.pools)
        pfs = [
            fc.pools[(site.id, p.mention)] for p in site.pools if (site.id, p.mention) in fc.pools
        ]
        occupied = sum(pf.occupied_now for pf in pfs)
        waiting = [r for r in open_reqs if r.site_id == site.id]
        oldest = max(((now - r.received_at).total_seconds() / 3600 for r in waiting), default=None)
        cards.append(
            SiteCardOut(
                site_id=site.id,
                site_name=site.name,
                city=site.city,
                beds_installed=installed,
                beds_open=opened,
                occupied=occupied,
                occupancy_on_open=round(occupied / opened, 4) if opened else None,
                awaiting_response=len(waiting),
                oldest_waiting_hours=round(oldest, 1) if oldest is not None else None,
                discharges_next_7_days=round(
                    sum(pf.days[day7].cumulative_expected for pf in pfs), 1
                ),
                free_beds_in_7_days=round(sum(pf.days[day7].free_expected for pf in pfs), 1),
                reserved_next_7_days=sum(pf.days[day7].reserved for pf in pfs),
            )
        )

    daily: list[dict[str, float | str]] = []
    for k in range(HORIZON_DAYS):
        row: dict[str, float | str] = {"day": (today + timedelta(days=k)).isoformat()}
        for site in sites:
            row[site.name] = round(
                sum(
                    fc.pools[(site.id, p.mention)].days[k].free_expected
                    for p in site.pools
                    if (site.id, p.mention) in fc.pools
                ),
                1,
            )
        daily.append(row)

    since = now - timedelta(days=30)
    responded = ctx.session.execute(
        select(AdmissionRequest.received_at, AdmissionRequest.first_response_at).where(
            AdmissionRequest.group_id == ctx.group.id,
            AdmissionRequest.first_response_at.is_not(None),
            AdmissionRequest.first_response_at >= since,
        )
    ).all()
    hours = sorted((r - q).total_seconds() / 3600 for q, r in responded if r is not None)
    median_h = round(hours[len(hours) // 2], 1) if hours else None

    installed = sum(c.beds_installed for c in cards)
    opened = sum(c.beds_open for c in cards)
    occupied = sum(c.occupied for c in cards)
    return GroupDashboardOut(
        as_of=today,
        group_name=ctx.group.name,
        beds_installed=installed,
        beds_open=opened,
        occupied=occupied,
        occupancy_on_open=round(occupied / opened, 4) if opened else None,
        awaiting_response=len(open_reqs),
        responses_median_hours_30d=median_h,
        sites=cards,
        daily_free_beds=daily,
    )


def _local_bounds(ctx: Ctx, start: date, end: date) -> tuple[datetime, datetime]:
    zone = ctx.clock.zone
    return (
        datetime.combine(start, time.min, tzinfo=zone).astimezone(UTC),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC),
    )


def _capacity_inputs(
    ctx: Ctx, site_ids: list[int]
) -> tuple[list[CapacityPoint], list[PoolCapacity], dict[int, str]]:
    sites = [s for s in group_sites(ctx, include_inactive=True) if s.id in site_ids]
    current = [
        PoolCapacity(s.id, p.mention, p.beds_installed, p.beds_open) for s in sites for p in s.pools
    ]
    changes = [
        CapacityPoint(
            c.site_id, c.mention, c.effective_date, c.beds_installed, c.beds_open, c.reason
        )
        for c in ctx.session.scalars(
            select(CapacityChange).where(
                CapacityChange.group_id == ctx.group.id, CapacityChange.site_id.in_(site_ids)
            )
        )
    ]
    return changes, current, {s.id: s.name for s in sites}


def _capacity(
    ctx: Ctx, site_ids: list[int], start: date, end: date
) -> dict[date, tuple[int, int, dict[str, int]]]:
    changes, current, _ = _capacity_inputs(ctx, site_ids)
    return daily_capacity(changes, current, start, end)


HISTORY_BURN_IN_DAYS = 90


def _pool_series(
    ctx: Ctx, site_ids: list[int], records: list[StayRecord], history_start: date, end: date
) -> list[PoolSeries]:
    changes, current, names = _capacity_inputs(ctx, site_ids)
    cap = pool_capacity(changes, current, history_start, end)
    out: list[PoolSeries] = []
    for pool in current:
        key = (pool.site_id, pool.mention)
        stays = [r for r in records if (r.site_id, r.mention) == key]
        out.append(
            PoolSeries(
                key=f"{names[pool.site_id]} — {MENTIONS.get(pool.mention, pool.mention)}",
                occupied=daily_occupancy(stays, history_start, end),
                open_beds={d: v[1] for d, v in cap[key].items()},
            )
        )
    return out


def _occupancy_out(
    occ: dict[date, int], cap: dict[date, tuple[int, int, dict[str, int]]]
) -> OccupancyOut:
    return OccupancyOut(**summarise_occupancy(occ, cap).__dict__)


@router.get("/metrics/pilot", response_model=PilotMetricsOut, tags=["indicateurs"])
def pilot_metrics(
    ctx: ReadCtx,
    start: date | None = None,
    end: date | None = None,
    site_id: int | None = None,
) -> PilotMetricsOut:
    today = ctx.clock.today()
    end = end or today - timedelta(days=1)
    start = start or end - timedelta(days=27)
    if start > end:
        raise HTTPException(UNPROCESSABLE, "Période invalide")
    if (end - start).days > 731:
        raise HTTPException(UNPROCESSABLE, "Période limitée à 2 ans")
    if site_id is not None:
        get_site(ctx, site_id)
        if not ctx.can_see_site(site_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Site hors de votre périmètre")
        site_ids = [site_id]
    else:
        site_ids = [s.id for s in group_sites(ctx, include_inactive=True)]

    records = stay_records(ctx.session, ctx.group.id, site_ids)
    occ = daily_occupancy(records, start, end)
    cap = _capacity(ctx, site_ids, start, end)

    lo, hi = _local_bounds(ctx, start, end)
    req_query = select(AdmissionRequest).where(
        AdmissionRequest.group_id == ctx.group.id,
        AdmissionRequest.received_at >= lo,
        AdmissionRequest.received_at < hi,
    )
    if site_id is not None:
        req_query = req_query.where(AdmissionRequest.site_id == site_id)
    elif ctx.site_scope is not None:
        req_query = req_query.where(AdmissionRequest.site_id == ctx.site_scope)
    reqs = list(ctx.session.scalars(req_query))
    accorded_ids = (
        set(
            ctx.session.scalars(
                select(RequestEvent.request_id).where(
                    RequestEvent.request_id.in_([r.id for r in reqs]),
                    RequestEvent.to_status == "accord",
                )
            )
        )
        if reqs
        else set()
    )
    req_records = [
        RequestRecord(
            request_id=r.id,
            received_at=r.received_at,
            status=r.status,
            first_response_at=r.first_response_at,
            refusal_reason=r.refusal_reason,
            loss_reason=r.loss_reason,
            was_accorded=r.id in accorded_ids,
        )
        for r in reqs
    ]
    summary = summarise_requests(req_records)

    group = ctx.group
    baseline = BaselineOut(
        start=group.baseline_start, end=group.baseline_end, frozen_at=group.baseline_frozen_at
    )
    baseline_occ_out: OccupancyOut | None = None
    ns_out: NorthStarOut | None = None
    reason: str | None = None
    if group.baseline_start is None or group.baseline_end is None:
        reason = "Aucune période de référence définie."
    elif group.baseline_end >= start:
        reason = "La période analysée chevauche la période de référence."
    else:
        b_occ = daily_occupancy(records, group.baseline_start, group.baseline_end)
        b_cap = _capacity(ctx, site_ids, group.baseline_start, group.baseline_end)
        baseline_occ_out = _occupancy_out(b_occ, b_cap)
        # Stays admitted before the first imported month are missing, so early census is
        # under-counted: history starts after a burn-in of about two lengths of stay.
        first = min((r.admission_date for r in records), default=group.baseline_start)
        history_start = min(group.baseline_start, first + timedelta(days=HISTORY_BURN_IN_DAYS))
        series = _pool_series(ctx, site_ids, records, history_start, end)
        result = north_star(
            series,
            (group.baseline_start, group.baseline_end),
            (start, end),
            group.value_per_bed_day,
            group.success_fee_rate,
            history_start,
        )
        if result is None:
            reason = (
                "Aucune unité comparable : la capacité ouverte a changé partout "
                "entre la référence et la période."
            )
        else:
            ns_out = NorthStarOut(**result.__dict__)
            if group.baseline_frozen_at is None:
                reason = "Référence non gelée : résultat indicatif, non opposable."

    weekly: list[dict[str, float | str | None]] = []
    week_start = start
    while week_start <= end:
        week_end = min(end, week_start + timedelta(days=6))
        days = date_range(week_start, week_end)
        occupied = sum(occ[d] for d in days)
        opened = sum(cap[d][1] for d in days)
        wlo, whi = _local_bounds(ctx, week_start, week_end)
        week_reqs = [r for r in req_records if wlo <= r.received_at < whi]
        hours = sorted(
            (r.first_response_at - r.received_at).total_seconds() / 3600
            for r in week_reqs
            if r.first_response_at
        )
        weekly.append(
            {
                "week_start": week_start.isoformat(),
                "occupancy_on_open": round(occupied / opened, 4) if opened else None,
                "closed_beds": round(sum(cap[d][0] - cap[d][1] for d in days) / len(days), 1),
                "received": float(len(week_reqs)),
                "admitted": float(sum(1 for r in week_reqs if r.status == "admise")),
                "response_hours_median": round(hours[len(hours) // 2], 1) if hours else None,
            }
        )
        week_start = week_end + timedelta(days=1)

    return PilotMetricsOut(
        period_start=start,
        period_end=end,
        site_id=site_id,
        occupancy=_occupancy_out(occ, cap),
        requests=RequestsSummaryOut(**summary.__dict__),
        baseline=baseline,
        baseline_occupancy=baseline_occ_out,
        north_star=ns_out,
        north_star_unavailable_reason=reason,
        weekly=weekly,
    )


@router.get("/metrics/backtest", response_model=BacktestOut, tags=["indicateurs"])
def forecast_backtest(
    ctx: ReadCtx, site_id: int | None = None, weeks: int = Query(12, ge=2, le=52)
) -> BacktestOut:
    today = ctx.clock.today()
    if site_id is not None:
        get_site(ctx, site_id)
        if not ctx.can_see_site(site_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Site hors de votre périmètre")
    records = stay_records(ctx.session, ctx.group.id)
    if site_id is not None:
        # The LOS model is fitted on the group; the replay counts the site's discharges.
        target = [r for r in records if r.site_id == site_id]
    elif ctx.site_scope is not None:
        target = [r for r in records if r.site_id == ctx.site_scope]
    else:
        target = records
    horizon = 7
    as_of_dates = [today - timedelta(days=horizon + 7 * k) for k in range(weeks)][::-1]
    result = backtest(target, as_of_dates, today, horizon)
    return BacktestOut(
        horizon_days=result.horizon_days,
        points=[BacktestPointOut(**p.__dict__) for p in result.points],
        mae=result.mae,
        bias=result.bias,
        coverage_80=result.coverage_80,
        note=(
            "Rejeu à dates passées sans les dates de sortie prévues (historique non conservé) : "
            "mesure le modèle de durée de séjour seul. Couverture attendue de l'intervalle : 80 %."
        ),
    )


def _settings_out(ctx: Ctx) -> GroupSettingsOut:
    g = ctx.group
    return GroupSettingsOut(
        name=g.name,
        value_per_bed_day=g.value_per_bed_day,
        success_fee_rate=g.success_fee_rate,
        scoring_weights=weights_of(ctx),
        baseline=BaselineOut(
            start=g.baseline_start, end=g.baseline_end, frozen_at=g.baseline_frozen_at
        ),
    )


@router.get("/settings", response_model=GroupSettingsOut, tags=["parametres"])
def get_settings(ctx: ReadCtx) -> GroupSettingsOut:
    return _settings_out(ctx)


@router.put("/settings", response_model=GroupSettingsOut, tags=["parametres"])
def put_settings(body: GroupSettingsIn, ctx: AdminCtx) -> GroupSettingsOut:
    g = ctx.group
    contract_change = body.value_per_bed_day is not None or body.success_fee_rate is not None
    if contract_change and g.baseline_frozen_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Référence gelée : la valeur de la journée et le taux d'intéressement sont figés",
        )
    if body.value_per_bed_day is not None:
        g.value_per_bed_day = body.value_per_bed_day
    if body.success_fee_rate is not None:
        g.success_fee_rate = body.success_fee_rate
    if body.scoring_weights is not None:
        unknown = set(body.scoring_weights) - set(DEFAULT_WEIGHTS)
        if unknown or any(v < 0 for v in body.scoring_weights.values()):
            raise HTTPException(UNPROCESSABLE, "Pondérations invalides")
        g.scoring_weights_json = json.dumps(body.scoring_weights)
    ctx.audit("parametres.update", "group", g.id, json.dumps(body.model_dump(exclude_none=True)))
    ctx.session.commit()
    return _settings_out(ctx)


@router.put("/settings/baseline", response_model=GroupSettingsOut, tags=["parametres"])
def put_baseline(body: BaselineIn, ctx: AdminCtx) -> GroupSettingsOut:
    g = ctx.group
    if g.baseline_frozen_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Référence gelée : dégelez-la d'abord")
    if body.end < body.start:
        raise HTTPException(UNPROCESSABLE, "Fin avant le début")
    if body.end >= ctx.clock.today():
        raise HTTPException(UNPROCESSABLE, "La référence doit être passée")
    if (body.end - body.start).days < 27:
        raise HTTPException(UNPROCESSABLE, "Référence d'au moins 4 semaines")
    g.baseline_start, g.baseline_end = body.start, body.end
    ctx.audit("reference.update", "group", g.id, f"{body.start} → {body.end}")
    ctx.session.commit()
    return _settings_out(ctx)


@router.post("/settings/baseline/freeze", response_model=GroupSettingsOut, tags=["parametres"])
def freeze_baseline(ctx: AdminCtx) -> GroupSettingsOut:
    g = ctx.group
    if g.baseline_start is None or g.baseline_end is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Définissez la période de référence")
    if g.baseline_frozen_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Référence déjà gelée")
    g.baseline_frozen_at = ctx.clock.now()
    ctx.audit(
        "reference.freeze",
        "group",
        g.id,
        f"{g.baseline_start} → {g.baseline_end}, {g.value_per_bed_day} €/j, "
        f"intéressement {g.success_fee_rate:.0%}",
    )
    ctx.session.commit()
    return _settings_out(ctx)


class UnfreezeIn(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


@router.post("/settings/baseline/unfreeze", response_model=GroupSettingsOut, tags=["parametres"])
def unfreeze_baseline(body: UnfreezeIn, ctx: AdminCtx) -> GroupSettingsOut:
    g = ctx.group
    if g.baseline_frozen_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "La référence n'est pas gelée")
    g.baseline_frozen_at = None
    ctx.audit("reference.unfreeze", "group", g.id, body.reason)
    ctx.session.commit()
    return _settings_out(ctx)
