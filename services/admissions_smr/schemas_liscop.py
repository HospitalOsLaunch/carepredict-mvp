"""HTTP contracts (Pydantic v2) of the LISCOP modules.

Each agent appends its own models under its own section only (see docs/liscop/PLAN.md),
so parallel branches merge without conflicts. Reuse ``Strict`` from ``schemas`` for inputs.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

# --- beds-ed ---

# --- movement-ingest ---

# --- forecast-engine ---


class ForecastDayOut(BaseModel):
    day: date
    horizon: str  # "J+0" .. "J+7"
    mean: float
    q10: float
    q50: float
    q90: float
    p_tension: float | None = None
    p_critique: float | None = None


class ObservedPointOut(BaseModel):
    day: date
    value: float


class ForecastSeriesOut(BaseModel):
    scope: str
    scope_key: str
    label: str
    site_id: int | None = None
    pool_id: int | None = None
    target: str
    beds_installed: int | None = None
    model: str | None = None  # model chosen for this series (arrivals, boarding)
    fallback: bool | None = None  # no candidate beat the seasonal naive reference
    values: list[ForecastDayOut]
    recent: list[ObservedPointOut] = Field(default_factory=list)


class ForecastRunOut(BaseModel):
    id: int
    as_of: date
    created_at: datetime
    model_version: str
    horizon_days: int
    age_hours: float
    stale: bool  # not computed for today, or more than 26 hours old
    models_chosen: dict[str, int]
    fallback_series: int
    common_shock_variance: float | None = None


class BacktestHeadlineOut(BaseModel):
    created_at: datetime
    last_full_day: date
    origins: int
    gates: dict[str, str]
    arrivals_mae_ratio: float | None = None
    arrivals_coverage_80: float | None = None
    beds_coverage_80: float | None = None
    beds_coverage_80_randomised: float | None = None
    boarding_mae_ratio: float | None = None


class LiscopForecastOut(BaseModel):
    scope: str
    targets: list[str]
    run: ForecastRunOut | None
    last_failure_at: datetime | None = None
    restricted_to_site: int | None = None
    synthetic: bool
    series: list[ForecastSeriesOut]
    backtest: BacktestHeadlineOut | None = None
    notes: list[str]


# --- ror-oru-export ---
