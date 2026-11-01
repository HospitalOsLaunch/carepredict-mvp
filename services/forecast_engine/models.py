"""Daily count forecasts with Nixtla statsforecast, chosen per series by rolling-origin CV.

Candidates (statsforecast 2.1, https://nixtlaverse.nixtla.io/statsforecast/):
``SeasonalNaive(7)`` (the reference), ``AutoETS(season_length=7)``,
``AutoTheta(season_length=7)`` and ``MSTL`` (weekly + yearly seasonality when the series
covers two years, weekly only otherwise) with an ``AutoETS(model="ZZN")`` trend.

Selection: ``StatsForecast.cross_validation`` with h = 8 (J+0 to J+7 from the last full
day), one origin per day over the last 56 days, models refitted every 7 origins (the
``forward`` method carries them in between). The candidate with the lowest MAE over all
windows and horizons wins; when none beats ``SeasonalNaive`` the reference is kept and
the series is flagged ``fallback``.

Intervals: split conformal per horizon on the signed CV residuals of the chosen model,
adapted online by ACI (see ``conformal.py``). The point forecast is clipped at 0; the
interval bounds too.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from statsforecast import StatsForecast
from statsforecast.models import MSTL, AutoETS, AutoTheta, SeasonalNaive

from services.forecast_engine.conformal import ALPHA, GAMMA, WINDOW, adaptive_conformal
from services.forecast_engine.data import Series

HORIZON = 8  # J+0 .. J+7, counted from the day after the last full day
CV_WINDOWS = 56
CV_REFIT = 7
SEASON = 7
REFERENCE = "SeasonalNaive"
MIN_DAYS = CV_WINDOWS + HORIZON + 4 * SEASON  # below, the reference is used without CV


def candidates(n_days: int) -> list[Any]:
    seasons: int | list[int] = [SEASON, 365] if n_days >= 2 * 365 else SEASON
    return [
        SeasonalNaive(season_length=SEASON),
        AutoETS(season_length=SEASON),
        AutoTheta(season_length=SEASON),
        MSTL(season_length=seasons, trend_forecaster=AutoETS(model="ZZN")),
    ]


@dataclass(frozen=True)
class SeriesForecast:
    """Forecast of one series for the HORIZON days after its last day."""

    model: str
    fallback: bool  # no candidate beat the seasonal naive reference
    cv_mae: dict[str, float]  # per candidate, all windows and horizons
    days: list[date]
    point: Series  # model forecast, clipped at 0
    reference: Series  # seasonal naive forecast, for the record
    q10: Series
    q50: Series
    q90: Series
    alpha: Series  # ACI level used at each horizon
    residuals: dict[int, Series]  # step -> signed CV residuals of the chosen model, by cutoff


def long_frame(series: dict[str, Series], last_day: date) -> Any:
    frames = []
    for key, values in series.items():
        days = pd.date_range(end=pd.Timestamp(last_day), periods=len(values), freq="D")
        frames.append(pd.DataFrame({"unique_id": key, "ds": days, "y": values.astype(float)}))
    return pd.concat(frames, ignore_index=True)


def cross_validate(series: dict[str, Series], last_day: date, n_windows: int = CV_WINDOWS) -> Any:
    """Rolling-origin forecasts of every candidate (one row per series, cutoff and day)."""
    n_days = min(len(v) for v in series.values())
    sf = StatsForecast(models=candidates(n_days), freq="D", fallback_model=SeasonalNaive(SEASON))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # constant series in statsmodels' acf
        return sf.cross_validation(
            h=HORIZON,
            df=long_frame(series, last_day),
            n_windows=n_windows,
            step_size=1,
            refit=CV_REFIT,
        )


def model_names(frame: Any) -> list[str]:
    return [c for c in frame.columns if c not in ("unique_id", "ds", "cutoff", "y")]


def forecast_series(
    series: dict[str, Series],
    last_day: date,
    alpha: float = ALPHA,
    gamma: float = GAMMA,
    window: int = WINDOW,
) -> dict[str, SeriesForecast]:
    """Select a model per series, forecast J+0..J+7 and attach adaptive conformal bounds."""
    if not series:
        return {}
    days = [last_day + timedelta(days=k) for k in range(1, HORIZON + 1)]
    long_enough = {k: v for k, v in series.items() if len(v) >= MIN_DAYS}
    out = {k: _reference_only(v, days) for k, v in series.items() if k not in long_enough}
    if not long_enough:
        return out
    n_days = min(len(v) for v in long_enough.values())
    cv = cross_validate(long_enough, last_day)
    sf = StatsForecast(models=candidates(n_days), freq="D", fallback_model=SeasonalNaive(SEASON))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        fc = sf.forecast(h=HORIZON, df=long_frame(long_enough, last_day))
    names = model_names(cv)
    for key in long_enough:
        rows = cv[cv["unique_id"] == key].sort_values(["cutoff", "ds"])
        y = rows["y"].to_numpy(float)
        mae = {
            m: float(np.mean(np.abs(y - np.clip(rows[m].to_numpy(float), 0, None)))) for m in names
        }
        best = min(names, key=lambda m: mae[m])
        fallback = mae[best] >= mae[REFERENCE]
        chosen = REFERENCE if fallback else best
        point = np.clip(fc.loc[fc["unique_id"] == key, chosen].to_numpy(float), 0, None)
        reference = np.clip(fc.loc[fc["unique_id"] == key, REFERENCE].to_numpy(float), 0, None)
        steps = ((rows["ds"] - rows["cutoff"]).dt.days).to_numpy(int)
        residuals = y - np.clip(rows[chosen].to_numpy(float), 0, None)
        by_step = {s: residuals[steps == s] for s in range(1, HORIZON + 1)}  # cutoff order
        q10, q50, q90, levels = (np.zeros(HORIZON) for _ in range(4))
        for s in range(1, HORIZON + 1):
            trace = adaptive_conformal(by_step[s], alpha, gamma, window, lag=s)
            lo, hi = trace.next_offsets
            mid = float(np.median(by_step[s][-window:]))
            q10[s - 1], q50[s - 1], q90[s - 1] = (point[s - 1] + v for v in (lo, mid, hi))
            levels[s - 1] = trace.next_alpha
        q10, q50, q90 = (np.clip(q, 0, None) for q in (q10, q50, q90))
        out[key] = SeriesForecast(
            chosen, fallback, mae, days, point, reference, q10, q50, q90, levels, by_step
        )
    return out


def _reference_only(values: Series, days: list[date]) -> SeriesForecast:
    """Too short to cross-validate: repeat the last week, no calibrated interval."""
    last_week = values[-SEASON:] if len(values) else np.zeros(SEASON)
    point = np.array([last_week[k % len(last_week)] for k in range(HORIZON)], dtype=float)
    return SeriesForecast(
        REFERENCE, True, {}, days, point, point, point, point, point, np.full(HORIZON, ALPHA), {}
    )
