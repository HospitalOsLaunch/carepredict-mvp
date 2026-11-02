"""One forecast for a group at a date: series → models → Monte Carlo → rows to store.

``as_of`` is the forecast day J+0. The engine anchors everything at 00:00 that day: the
models see the days before ``as_of``, the patients present at 00:00 are the starting
census, and J+k values describe the end of day ``as_of + k``. A live run (``as_of`` =
today) and a backtest replay therefore use exactly the same definitions.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from services.admissions_smr.domain.ed import BOARDING_ARRIVED_BEFORE, BOARDING_HOUR
from services.admissions_smr.domain.forecast import (
    HazardModel,
    PlanHistory,
    StayRecord,
    discharge_cdf,
    estimate_plan_slip,
    fit_hazard,
    plan_known_at,
)
from services.admissions_smr.service import plan_history, reservations, stay_records
from services.admissions_smr.vocab import FORECAST_SCOPES
from services.forecast_engine import MODEL_VERSION
from services.forecast_engine.calendar import day_kinds
from services.forecast_engine.capacity import (
    DRAWS,
    SEED,
    IntDraws,
    UnitInputs,
    aggregate,
    common_shock_variance,
    gamma_factor,
    sample_counts,
    simulate_unit,
    summarise,
    tension_probabilities,
    weekday_retention,
)
from services.forecast_engine.conformal import ALPHA, GAMMA, WINDOW
from services.forecast_engine.data import History, Series
from services.forecast_engine.models import (
    CV_REFIT,
    CV_WINDOWS,
    HORIZON,
    SeriesForecast,
    forecast_series,
)

log = logging.getLogger("forecast_engine")

ED_ARRIVALS = "ed_arrivals"  # extra target: emergency department arrivals per site


@dataclass(frozen=True)
class ValueRow:
    scope: str
    scope_key: str
    target: str
    day: date
    mean: float
    q10: float
    q50: float
    q90: float
    p_tension: float | None = None
    p_critique: float | None = None
    site_id: int | None = None
    pool_id: int | None = None


@dataclass
class RunResult:
    as_of: date
    model_version: str
    params: dict[str, Any]
    metrics: dict[str, Any]
    values: list[ValueRow]
    forecasts: dict[str, SeriesForecast] = field(default_factory=dict)
    unit_draws: dict[int, IntDraws] = field(default_factory=dict)  # available beds


def truncated(values: Series, history: History, last_day: date) -> Series:
    return values[: history.index(last_day) + 1]


def scope_keys(history: History, site_id: int) -> dict[str, str]:
    """Aggregation keys of a site: itself, the group, its GHT and département."""
    site = history.sites[site_id]
    keys = {"site": f"site:{site_id}", "group": f"group:{history.group_id}"}
    if site.ght:
        keys["ght"] = site.ght
    if site.departement:
        keys["departement"] = site.departement
    return keys


def compute(
    session: Session,
    history: History,
    as_of: date,
    use_current_plans: bool,
    draws: int = DRAWS,
    seed: int = SEED,
    alpha: float = ALPHA,
    gamma: float = GAMMA,
    window: int = WINDOW,
    progress: Callable[[str], None] = log.info,
) -> RunResult:
    last_day = as_of - timedelta(days=1)
    days = [as_of + timedelta(days=k) for k in range(HORIZON)]
    beds = {p: u for p, u in history.units.items() if u.installed > 0}

    # 1. Count series and their models (one cross-validation for all of them).
    series: dict[str, Series] = {
        f"arrivals:{p}": truncated(history.unit_series["arrivals"][p], history, last_day)
        for p in beds
    }
    for name in (ED_ARRIVALS, "boarding_10h"):
        for site_id, counts in history.site_series[name].items():
            series[f"{name}:{site_id}"] = truncated(counts, history, last_day)
    progress(f"Modèles : {len(series)} séries jusqu'au {last_day:%d/%m/%Y}")
    forecasts = forecast_series(series, last_day, alpha, gamma, window)

    # 2. Discharge model of the admissions service (Kaplan-Meier, plans with slip).
    progress("Modèle de sorties (durées de séjour, glissement des dates prévues)")
    plans = plan_history(session, history.group_id)
    model, slip = discharge_model(session, history.group_id, as_of, plans)
    promised_requests = reservations(session, history.group_id) if use_current_plans else {}
    present = history.present_at_start(as_of)
    waiting = history.ed_waiting(history.midnight(as_of))
    profile = discharge_profile(history, beds, last_day)
    keep_by_weekday = weekday_retention(profile)
    retention = [keep_by_weekday[day.weekday()] for day in days]

    # 3. Monte Carlo per unit, with one common daily factor on arrivals.
    relative = [
        fc.residuals[1] / max(1.0, float(series[key][-CV_WINDOWS:].mean()))
        for key, fc in forecasts.items()
        if key.startswith("arrivals:") and 1 in fc.residuals
    ]
    shared_var = common_shock_variance(relative)
    rng = np.random.default_rng(seed)
    common = gamma_factor(shared_var, (draws, HORIZON), rng)
    progress(f"Monte Carlo : {len(beds)} unités × {draws} tirages")

    sims = {}
    for pool_id, unit in beds.items():
        records = [
            StayRecord(
                s.stay_id,
                s.site_id,
                s.mention,
                s.admission_date,
                None,
                s.planned_discharge_date
                if use_current_plans
                else plan_known_at(plans.get(s.stay_id, ()), as_of),
            )
            for s in present.get(pool_id, [])
        ]
        cdfs = np.array([discharge_cdf(r, as_of, HORIZON, model, slip) for r in records])
        newcomer = StayRecord(0, unit.site_id, unit.code, as_of)
        new_cdf = np.array(discharge_cdf(newcomer, as_of, HORIZON, model))
        due = promised_requests.get((unit.site_id, unit.code), {})
        promised = [waiting[pool_id] + sum(n for d, n in due.items() if d <= day) for day in days]
        capacity = [history.capacity_on(pool_id, day) for day in days]
        fc = forecasts[f"arrivals:{pool_id}"]
        sims[pool_id] = simulate_unit(
            UnitInputs(
                key=pool_id,
                installed=[c[0] for c in capacity],
                open_beds=[c[1] for c in capacity],
                occupied=len(records),
                discharge_cdfs=cdfs.reshape(len(records), HORIZON),
                new_stay_cdf=new_cdf,
                promised_cum=promised,
                arrivals_centre=fc.q50,
                arrivals_q10=fc.q10,
                arrivals_q90=fc.q90,
                discharge_retention=retention,
            ),
            rng,
            common,
            shared_var,
            draws,
        )

    # 4. Rows: unit scope, then sums by site, group, GHT and département.
    values: list[ValueRow] = []

    def add(
        scope: str,
        key: str,
        target: str,
        mean: Series,
        q10: Series,
        q50: Series,
        q90: Series,
        probs: tuple[Series, Series] | None = None,
        site_id: int | None = None,
        pool_id: int | None = None,
    ) -> None:
        for k, day in enumerate(days):
            values.append(
                ValueRow(
                    scope,
                    key,
                    target,
                    day,
                    round(float(mean[k]), 3),
                    round(float(q10[k]), 3),
                    round(float(q50[k]), 3),
                    round(float(q90[k]), 3),
                    None if probs is None else round(float(probs[0][k]), 4),
                    None if probs is None else round(float(probs[1][k]), 4),
                    site_id,
                    pool_id,
                )
            )

    def add_draws(
        scope: str,
        key: str,
        target: str,
        d: IntDraws,
        installed: list[int] | None = None,
        site_id: int | None = None,
        pool_id: int | None = None,
    ) -> None:
        s = summarise(d)
        probs = tension_probabilities(d, installed) if installed is not None else None
        add(scope, key, target, s.mean, s.q10, s.q50, s.q90, probs, site_id, pool_id)
        if probs is not None:
            p = probs[0]
            add(scope, key, "tension_prob", p, p, p, p, probs, site_id, pool_id)

    installed_by: dict[str, list[int]] = defaultdict(lambda: [0] * HORIZON)
    scope_of: dict[str, dict[int, str]] = {s: {} for s in FORECAST_SCOPES[1:]}
    for pool_id, unit in beds.items():
        sim = sims[pool_id]
        installed = [history.capacity_on(pool_id, day)[0] for day in days]
        fc = forecasts[f"arrivals:{pool_id}"]
        key = f"pool:{pool_id}"
        add("unit", key, "arrivals", fc.point, fc.q10, fc.q50, fc.q90, None, unit.site_id, pool_id)
        add_draws("unit", key, "discharges", sim.discharges, None, unit.site_id, pool_id)
        add_draws("unit", key, "available_beds", sim.available, installed, unit.site_id, pool_id)
        for scope, scope_key in scope_keys(history, unit.site_id).items():
            scope_of[scope][pool_id] = scope_key
            installed_by[scope_key] = [
                a + b for a, b in zip(installed_by[scope_key], installed, strict=True)
            ]

    site_of_key = {f"site:{s}": s for s in history.sites}
    for scope in FORECAST_SCOPES[1:]:
        for target, field_name in (
            ("arrivals", "arrivals"),
            ("discharges", "discharges"),
            ("available_beds", "available"),
        ):
            sums = aggregate({p: getattr(sims[p], field_name) for p in beds}, scope_of[scope])
            for key, d in sums.items():
                tension = installed_by[key] if target == "available_beds" else None
                add_draws(scope, key, target, d, tension, site_of_key.get(key))

    for name in (ED_ARRIVALS, "boarding_10h"):
        site_draws: dict[int, IntDraws] = {}
        for site_id in history.site_series[name]:
            fc = forecasts[f"{name}:{site_id}"]
            add("site", f"site:{site_id}", name, fc.point, fc.q10, fc.q50, fc.q90, None, site_id)
            site_draws[site_id] = sample_counts(fc.q50, fc.q10, fc.q90, rng, draws=draws)
        for scope in ("group", "ght", "departement"):
            keys = {s: scope_keys(history, s).get(scope) for s in site_draws}
            for key, d in aggregate(site_draws, {s: k for s, k in keys.items() if k}).items():
                add_draws(scope, key, name, d)

    metrics = run_metrics(history, forecasts, series, last_day, sims, shared_var)
    metrics["discharge_weekday_profile"] = [round(f, 3) for f in profile]
    params = {
        "as_of": as_of.isoformat(),
        "horizon_days": HORIZON,
        "alpha": alpha,
        "aci_gamma": gamma,
        "conformal_window": window,
        "cv_windows": CV_WINDOWS,
        "cv_refit_every": CV_REFIT,
        "draws": draws,
        "seed": seed,
        "boarding_definition": (
            f"présents aux urgences à {BOARDING_HOUR:%H:%M}, décision d'hospitalisation à "
            f"{BOARDING_HOUR:%H:%M} au plus tard, arrivés avant {BOARDING_ARRIVED_BEFORE:%H:%M}"
        ),
        "plans": "actuels" if use_current_plans else "connus à la date",
    }
    unit_draws = {p: s.available for p, s in sims.items()}
    return RunResult(as_of, MODEL_VERSION, params, metrics, values, forecasts, unit_draws)


def discharge_model(
    session: Session, group_id: int, as_of: date, plans: PlanHistory
) -> tuple[HazardModel, Mapping[int, float]]:
    """The hazards and plan slip of ``service.build_forecast``, without its per-pool work."""
    records = stay_records(session, group_id)
    model = fit_hazard(records, as_of, plans=plans or None)
    return model, estimate_plan_slip(records, plans, as_of).weights


PROFILE_WEEKS = 12
RECENT_DAYS = 28  # observed values kept with the run, for the charts


def discharge_profile(history: History, pools: Iterable[int], last_day: date) -> list[float]:
    """Mean discharges per weekday (Monday first) over the overall daily mean, all units."""
    stop = history.index(last_day) + 1
    start = max(0, stop - 7 * PROFILE_WEEKS)
    total = sum(history.unit_series["discharges"][p][start:stop] for p in pools)
    if isinstance(total, int) or stop - start < 14 or float(np.mean(total)) == 0:
        return [1.0] * 7
    weekdays = np.array(
        [(history.first_day + timedelta(days=i)).weekday() for i in range(start, stop)]
    )
    mean = float(np.mean(total))
    return [float(np.mean(total[weekdays == d])) / mean for d in range(7)]


def run_metrics(
    history: History,
    forecasts: dict[str, SeriesForecast],
    series: dict[str, Series],
    last_day: date,
    sims: dict[int, Any],
    shared_var: float,
) -> dict[str, Any]:
    """What the run used and how each model did in cross-validation."""
    per_series: dict[str, Any] = {}
    kinds = day_kinds(last_day - timedelta(days=CV_WINDOWS + HORIZON), last_day)
    for key, fc in forecasts.items():
        entry: dict[str, Any] = {
            "model": fc.model,
            "fallback": fc.fallback,
            "cv_mae": {m: round(v, 4) for m, v in fc.cv_mae.items()},
            "aci_alpha": [round(float(a), 4) for a in fc.alpha],
        }
        if 1 in fc.residuals:
            # Step-1 residual i targets the day after cutoff i; cutoffs end H days before.
            first_target = last_day - timedelta(days=HORIZON + len(fc.residuals[1]) - 2)
            by_kind: dict[str, list[float]] = defaultdict(list)
            for i, r in enumerate(fc.residuals[1]):
                by_kind[kinds.get(first_target + timedelta(days=i), "inconnu")].append(float(r))
            entry["mean_error_by_day_kind"] = {
                k: round(float(np.mean(v)), 3) for k, v in sorted(by_kind.items())
            }
        per_series[key] = entry
    chosen: dict[str, int] = defaultdict(int)
    for fc in forecasts.values():
        chosen[fc.model] += 1
    modes: dict[str, dict[str, int]] = {}
    for pool_id in sims:
        start = max(0, history.index(last_day) - 27)
        stop = history.index(last_day) + 1
        modes[f"pool:{pool_id}"] = {
            m: int(history.unit_series[f"arrivals_{m}"][pool_id][start:stop].sum())
            for m in ("urgences", "programme", "mutation", "transfert", "autre")
        }
    recent: dict[str, dict[str, float]] = {}
    for key, values in series.items():
        if key.startswith(("arrivals:", "boarding_10h:", f"{ED_ARRIVALS}:")):
            tail = values[-RECENT_DAYS:]
            first = last_day - timedelta(days=len(tail) - 1)
            recent[key] = {
                (first + timedelta(days=i)).isoformat(): float(v) for i, v in enumerate(tail)
            }
    return {
        "history": {"first_day": history.first_day.isoformat(), "last_day": last_day.isoformat()},
        "recent_observed": recent,
        "series": per_series,
        "models_chosen": dict(chosen),
        "fallback_series": sorted(k for k, fc in forecasts.items() if fc.fallback),
        "common_shock_variance": round(shared_var, 5),
        "arrival_modes_last_28_days": modes,
    }
