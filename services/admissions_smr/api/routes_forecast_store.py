"""Read the forecasts stored by services/forecast_engine (owner: forecast-engine).

The API never computes them (no numpy, pandas or statsforecast here): it serves the
latest successful run of the group, with its freshness, the model of each series and the
headline of the latest backtest. No run yet is an empty answer, not an error.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from services.admissions_smr.api.deps import UNPROCESSABLE, ReadCtx
from services.admissions_smr.models import BedPool, ForecastRun, ForecastValue, Site
from services.admissions_smr.schemas_liscop import (
    BacktestHeadlineOut,
    ForecastDayOut,
    ForecastRunOut,
    ForecastSeriesOut,
    LiscopForecastOut,
    ObservedPointOut,
)
from services.admissions_smr.vocab import (
    FORECAST_SCOPES,
    FORECAST_STALE_AFTER_HOURS,
    FORECAST_TARGETS,
    SYNTHETIC_GROUPS,
)

router = APIRouter()

# Series names used by the engine in metrics_json, per stored target.
SERIES_OF_TARGET = {
    "arrivals": "arrivals",
    "boarding_10h": "boarding_10h",
    "ed_arrivals": "ed_arrivals",
}
NOTES = [
    "Disponibles attendus = lits ouverts − patients présents à 0 h − admissions promises "
    "+ sorties prévues − arrivées non programmées prévues ; fourchette à 80 % (q10-q90).",
    "Probabilité de tension : part des 2 000 scénarios où les lits disponibles passent sous "
    "20 % des lits installés (légende LISCOP) ; critique : aucun lit disponible.",
    "Agrégats (établissement, GHT, département) : somme des scénarios des unités, avec un "
    "facteur commun journalier sur les arrivées (épidémies, jour de semaine).",
]


def _json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


@router.get("/forecast/liscop", response_model=LiscopForecastOut, tags=["prevision"])
def liscop_forecast(
    ctx: ReadCtx,
    scope: str = "unit",
    target: Annotated[list[str] | None, Query()] = None,
) -> LiscopForecastOut:
    if scope not in FORECAST_SCOPES:
        raise HTTPException(UNPROCESSABLE, f"Portée inconnue : {scope}")
    targets = target or list(FORECAST_TARGETS)
    unknown = sorted(set(targets) - set(FORECAST_TARGETS))
    if unknown:
        raise HTTPException(UNPROCESSABLE, f"Cible inconnue : {', '.join(unknown)}")
    now = ctx.clock.now()
    synthetic = ctx.group.name in SYNTHETIC_GROUPS
    runs = select(ForecastRun).where(ForecastRun.group_id == ctx.group.id)
    latest = ctx.session.scalars(
        runs.where(ForecastRun.status == "ok")
        .order_by(ForecastRun.created_at.desc(), ForecastRun.id.desc())
        .limit(1)
    ).first()
    failure = ctx.session.scalars(
        runs.where(ForecastRun.status == "failed").order_by(ForecastRun.created_at.desc()).limit(1)
    ).first()
    backtest = ctx.session.scalars(
        runs.where(ForecastRun.status == "backtest")
        .order_by(ForecastRun.created_at.desc())
        .limit(1)
    ).first()
    out = LiscopForecastOut(
        scope=scope,
        targets=targets,
        run=None,
        last_failure_at=failure.created_at
        if failure and (latest is None or failure.created_at > latest.created_at)
        else None,
        restricted_to_site=ctx.site_scope,
        synthetic=synthetic,
        series=[],
        backtest=_backtest(backtest) if backtest else None,
        notes=NOTES,
    )
    if latest is None:
        return out

    metrics = _json(latest.metrics_json)
    age = max(0.0, (now - latest.created_at).total_seconds() / 3600)
    out.run = ForecastRunOut(
        id=latest.id,
        as_of=latest.as_of,
        created_at=latest.created_at,
        model_version=latest.model_version,
        horizon_days=latest.horizon_days,
        age_hours=round(age, 1),
        stale=latest.as_of != ctx.clock.today() or age > FORECAST_STALE_AFTER_HOURS,
        models_chosen={str(k): int(v) for k, v in metrics.get("models_chosen", {}).items()},
        fallback_series=len(metrics.get("fallback_series", [])),
        common_shock_variance=_float(metrics.get("common_shock_variance")),
    )

    query = select(ForecastValue).where(
        ForecastValue.run_id == latest.id,
        ForecastValue.scope == scope,
        ForecastValue.target.in_(targets),
    )
    if ctx.site_scope is not None:  # a site-scoped user sees its own site only
        query = query.where(ForecastValue.site_id == ctx.site_scope)
    rows = ctx.session.scalars(query.order_by(ForecastValue.day)).all()
    sites = {
        s.id: s for s in ctx.session.scalars(select(Site).where(Site.group_id == ctx.group.id))
    }
    pools = {
        p.id: p for p in ctx.session.scalars(select(BedPool).where(BedPool.site_id.in_(sites)))
    }
    grouped: dict[tuple[str, str], list[ForecastValue]] = defaultdict(list)
    for row in rows:
        grouped[(row.scope_key, row.target)].append(row)
    series_metrics = metrics.get("series", {})
    recent_all = metrics.get("recent_observed", {})
    for (key, tgt), values in grouped.items():
        first = values[0]
        engine_key = _engine_key(tgt, first)
        info = series_metrics.get(engine_key, {}) if engine_key else {}
        out.series.append(
            ForecastSeriesOut(
                scope=scope,
                scope_key=key,
                label=_label(scope, key, first, sites, pools, ctx.group.name),
                site_id=first.site_id,
                pool_id=first.pool_id,
                target=tgt,
                beds_installed=_installed(scope, key, first, sites, pools),
                model=info.get("model"),
                fallback=info.get("fallback"),
                values=[
                    ForecastDayOut(
                        day=v.day,
                        horizon=f"J+{(v.day - latest.as_of).days}",
                        mean=v.mean,
                        q10=v.q10,
                        q50=v.q50,
                        q90=v.q90,
                        p_tension=v.p_tension,
                        p_critique=v.p_critique,
                    )
                    for v in values
                ],
                recent=[
                    ObservedPointOut(day=date.fromisoformat(d), value=float(x))
                    for d, x in (recent_all.get(engine_key, {}) if engine_key else {}).items()
                ],
            )
        )
    out.series.sort(key=lambda s: (s.target, s.site_id or 0, s.label))
    return out


def _engine_key(target: str, row: ForecastValue) -> str | None:
    name = SERIES_OF_TARGET.get(target)
    if name is None:
        return None
    if row.scope == "unit" and row.pool_id is not None:
        return f"{name}:{row.pool_id}"
    if row.scope == "site" and row.site_id is not None and name != "arrivals":
        return f"{name}:{row.site_id}"
    return None


def _label(
    scope: str,
    key: str,
    row: ForecastValue,
    sites: dict[int, Site],
    pools: dict[int, BedPool],
    group_name: str,
) -> str:
    if scope == "unit" and row.pool_id in pools:
        pool = pools[row.pool_id]
        return pool.label or pool.mention
    if scope == "site" and row.site_id in sites:
        return sites[row.site_id].name
    if scope == "group":
        return group_name
    if scope == "departement":
        return f"Département {key}"
    return key


def _installed(
    scope: str, key: str, row: ForecastValue, sites: dict[int, Site], pools: dict[int, BedPool]
) -> int | None:
    if scope == "unit" and row.pool_id in pools:
        return pools[row.pool_id].beds_installed
    if scope not in ("site", "group", "ght", "departement"):
        return None

    def member(site: Site) -> bool:
        if scope == "site":
            return site.id == row.site_id
        if scope == "ght":
            return site.ght == key
        if scope == "departement":
            return site.departement == key
        return True

    return sum(p.beds_installed for p in pools.values() if member(sites[p.site_id]))


def _backtest(run: ForecastRun) -> BacktestHeadlineOut | None:
    m = _json(run.metrics_json)
    gates = m.get("gates")
    if not isinstance(gates, dict):
        return None
    created: datetime = run.created_at
    return BacktestHeadlineOut(
        created_at=created,
        last_full_day=run.as_of,
        origins=int(m.get("origins", 0)),
        gates={str(k): str(v) for k, v in gates.items()},
        arrivals_mae_ratio=_float(m.get("arrivals_mae_ratio")),
        arrivals_coverage_80=_float(m.get("arrivals_coverage_80")),
        beds_coverage_80=_float(m.get("beds_coverage_80")),
        beds_coverage_80_randomised=_float(m.get("beds_coverage_80_randomised")),
        boarding_mae_ratio=_float(m.get("boarding_mae_ratio")),
    )
