"""Backtest protocol: gate rules, origins and the regime-shift window (T-1)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from services.forecast_engine.backtest import (
    HORIZONS,
    ORIGINS,
    SHIFT_DAYS,
    _gates,
    protocol_origins,
    regime_shift,
)
from services.forecast_engine.data import History, SiteRef, UnitRef


def report(
    ratios: list[float | None] | None = None,
    cov_arrivals: float | None = 0.8,
    cov_beds: float | None = 0.8,
    static: float | None = 0.66,
    aci: float | None = 0.79,
    boarding: float | None = 0.9,
) -> dict[str, Any]:
    by_k = {str(k): {"mae_ratio": r} for k, r in zip(HORIZONS, ratios or [0.8] * 7, strict=True)}
    return {
        "arrivals": {"by_horizon": by_k, "pooled": {"coverage_80": cov_arrivals}},
        "available_beds": {"pooled": {"coverage_80": cov_beds}},
        "regime_shift": {"static": {"pooled": static}, "aci": {"pooled": aci}},
        "boarding_10h": {} if boarding is None else {"pooled": {"mae_ratio": boarding}},
    }


@pytest.mark.parametrize(
    ("aci", "verdict"),
    [
        (0.75, "réussi"),  # |0.75 − 0.8| is 0.05000000000000004 in floats: still inside
        (0.85, "réussi"),
        (0.758, "réussi"),
        (0.7499, "échoué"),
        (0.8501, "échoué"),
        (None, "non concluant"),
    ],
)
def test_gate_c_tolerance_is_inclusive(aci: float | None, verdict: str) -> None:
    assert _gates(report(aci=aci))["c_regime_shift"] == verdict


@pytest.mark.parametrize(
    ("static", "verdict"),
    [(0.7499, "réussi"), (0.75, "non concluant"), (0.9, "non concluant"), (None, "non concluant")],
)
def test_gate_c_needs_the_frozen_interval_to_break(static: float | None, verdict: str) -> None:
    assert _gates(report(static=static))["c_regime_shift"] == verdict


@pytest.mark.parametrize(
    ("arrivals", "beds", "verdict"),
    [
        (0.75, 0.85, "réussi"),
        (0.8, 0.8, "réussi"),
        (0.7499, 0.8, "échoué"),
        (0.8, 0.8501, "échoué"),
        (0.8, 0.918, "échoué"),  # the published (b) failure: beds over-cover
        (None, 0.8, "échoué"),
    ],
)
def test_gate_b_coverage_bounds_are_inclusive(
    arrivals: float | None, beds: float | None, verdict: str
) -> None:
    assert _gates(report(cov_arrivals=arrivals, cov_beds=beds))["b_coverage_80"] == verdict


@pytest.mark.parametrize(
    ("ratios", "verdict"),
    [
        ([0.8] * 7, "réussi"),
        ([0.8] * 6 + [1.0], "échoué"),  # strictly below 1 at every horizon
        ([0.8] * 6 + [None], "échoué"),
    ],
)
def test_gate_a_every_horizon_beats_the_reference(ratios: list[float | None], verdict: str) -> None:
    assert _gates(report(ratios=ratios))["a_arrivals_mae_ratio"] == verdict


@pytest.mark.parametrize(
    ("boarding", "verdict"), [(0.87, "réussi"), (1.0, "échoué"), (None, "non évaluable")]
)
def test_gate_d_boarding(boarding: float | None, verdict: str) -> None:
    assert _gates(report(boarding=boarding))["d_boarding_mae_ratio"] == verdict


def test_protocol_origins_are_weekly_and_end_a_week_before_the_last_day() -> None:
    origins = protocol_origins(date(2026, 10, 24))

    assert len(origins) == ORIGINS == 21
    assert origins[-1] == date(2026, 10, 17)
    assert origins[0] == date(2026, 10, 17) - timedelta(weeks=20)
    assert {(b - a).days for a, b in zip(origins, origins[1:], strict=False)} == {7}
    # J+7 of the last origin is the last full day: every target is observed.
    assert origins[-1] + timedelta(days=max(HORIZONS)) == date(2026, 10, 24)


def test_regime_shift_scores_every_day_of_the_window_at_every_horizon() -> None:
    first, last = date(2026, 1, 1), date(2026, 9, 30)
    n = (last - first).days + 1
    rng = np.random.default_rng(3)
    weekly = np.array([1.2, 1.1, 1.0, 1.0, 1.0, 0.7, 0.6])
    arrivals = rng.poisson(5 * weekly[[(first + timedelta(days=i)).weekday() for i in range(n)]])
    history = History(
        1,
        ZoneInfo("Europe/Paris"),
        first,
        last,
        {1: SiteRef(1, "Site", None, None)},
        {1: UnitRef(1, 1, "medecine_polyvalente", "Médecine", 20, 20)},
        [],
        [],
        {},
        unit_series={"arrivals": {1: arrivals.astype(float)}},
        site_series={"ed_arrivals": {}},
    )
    start = last - timedelta(days=48)

    shift = regime_shift(history, start)

    assert shift["window"] == [start.isoformat(), (start + timedelta(SHIFT_DAYS - 1)).isoformat()]
    assert shift["series"] == ["arrivals:1"]
    assert shift["n"] == SHIFT_DAYS * len(HORIZONS)
    for kind in ("static", "aci"):
        pooled = shift[kind]["pooled"]
        assert pooled is not None and 0 <= pooled <= 1
    # Arrivals × 1.5: the interval frozen before the shift under-covers.
    assert shift["static"]["pooled"] < 0.75
