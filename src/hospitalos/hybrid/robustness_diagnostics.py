"""Prespecified diagnostics; none of these results tune a model or policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from sklearn.metrics import roc_auc_score  # type: ignore[import-untyped]

from .continuous import Array, copula_uniforms, log_loss, quantiles, survival
from .cusum import CusumSettings, DelayedCusum
from .robustness_models import LOCK, Experts, cohort
from .robustness_queue import action_scores, context


def development_checks(experts: Experts, alpha: float, settings: CusumSettings) -> dict[str, Any]:
    from .robustness_v2 import decisions

    # Only development seeds; these checks do not select a scenario count or loading.
    data = cohort(6101, 24, LOCK + timedelta(days=1))
    predicted = experts.predict(data.features)
    disagreements = {"32_vs_512": 0, "128_vs_512": 0}
    dependence: dict[str, list[float]] = {str(x): [] for x in (0.0, 0.6, 0.85)}
    for i in range(24):
        c = context(
            6101, i, data.origin + timedelta(hours=2 * i), data.features[3 * i : 3 * i + 3], False
        )
        forecasts = {k: v[3 * i : 3 * i + 3] for k, v in predicted.items()}
        choices = {
            n: decisions(c, forecasts, alpha, DelayedCusum(settings), 6101 * 100003 + i, n)[
                "supervised_mixture"
            ][0]
            for n in (32, 128, 512)
        }
        for n in (32, 128):
            disagreements[f"{n}_vs_512"] += int(choices[n] != choices[512])
        for loading in (0.0, 0.6, 0.85):
            ranks = copula_uniforms(6101 * 100003 + i, 3, 512, loading)
            sampled = quantiles(forecasts["pooled"], ranks, forecasts["boosting"], alpha).T
            dependence[str(loading)].append(float(action_scores(c, sampled)[0][1]))
    return {
        "episodes": 24,
        "scenario_action_disagreements": disagreements,
        "mean_predicted_objective_action1_by_loading": {
            k: float(np.mean(v)) for k, v in dependence.items()
        },
        "used_for_tuning": False,
    }


def diagnostic_ipcw(
    time: Array, observed: Array, prediction: Array, horizon: float
) -> float | None:
    """Marginal reverse KM, deliberately invalid under informative censoring.

    Published ONLY to quantify diagnostic bias against complete synthetic truth.
    """
    g = 1.0
    steps = []
    for t in sorted(set(time[~observed])):
        risk = int(np.sum(time >= t))
        failures = int(np.sum((time == t) & observed))
        censoring = int(np.sum((time == t) & ~observed))
        g *= 1 - censoring / (risk - failures)
        steps.append((t, g))
    gh = next((s for t, s in reversed(steps) if t <= horizon), 1.0)
    if gh < 0.1:
        return None
    total = 0.0
    for t, event, s in zip(time, observed, prediction, strict=True):
        if event and t <= horizon:
            gt = next((v for when, v in reversed(steps) if when < t), 1.0)
            if gt < 0.1:
                return None
            total += float(s**2 / gt)
        elif t > horizon:
            total += float((1 - s) ** 2 / gh)
    return total / len(time)


def reserved_forecast_diagnostics(experts: Experts) -> dict[str, Any]:
    # Separate reserved seeds; exploratory grid, not an optimized crossing estimate.
    origin = datetime(2027, 2, 1, tzinfo=UTC)
    results: list[dict[str, Any]] = []
    for coefficient in np.arange(-2.0, 2.01, 0.5):
        data = cohort(71001, 1000, origin, coefficient=float(coefficient))
        predicted = experts.predict(data.features)
        models: dict[str, Any] = {}
        for name, rates in predicted.items():
            s = survival(rates, np.full(len(rates), 240))
            y = data.truth > 240
            # Follow-up selectively stops early for the slowest synthetic cases.
            censor = np.where(y, 120.0, 480.0)
            followup, events = np.minimum(data.truth, censor), data.truth <= censor
            invalid = diagnostic_ipcw(followup, events, s, 240)
            oracle_brier = float(np.mean((y - s) ** 2))
            models[name] = {
                "censored_nll": float(np.mean(log_loss(rates, data.time, data.observed))),
                "oracle_auc_240": float(roc_auc_score(~y, 1 - s)),
                "oracle_brier_240": oracle_brier,
                "informative_censoring_diagnostic_only": {
                    "invalid_marginal_ipcw_brier": invalid,
                    "oracle_brier": oracle_brier,
                    "bias": invalid - oracle_brier if invalid is not None else None,
                    "valid_for_efficacy": False,
                },
            }
        results.append({"load_coefficient": float(coefficient), "models": models})
    crossing = next(
        (
            r["load_coefficient"]
            for r in results
            if r["models"]["boosting"]["censored_nll"] > r["models"]["pooled"]["censored_nll"]
        ),
        None,
    )
    return {
        "coefficient_grid": results,
        "first_sampled_coefficient_gbm_worse_than_pooled": crossing,
        "interpretation": "exploratory_grid_not_universal_threshold",
        "used_for_tuning": False,
    }
