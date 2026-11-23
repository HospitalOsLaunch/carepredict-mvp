"""Predeclared v2 decision experiment; the v1 scientific conclusion is inconclusive."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from .continuous import Array, copula_uniforms, isolated_gain, log_loss, quantiles
from .cusum import BatchFeedback, CusumSettings, DelayedCusum, calibrate_cusum
from .robustness_models import (
    LOADING,
    LOCK,
    TEST_START,
    WEIGHT_AVAILABLE,
    Experts,
    cohort,
    fit_experts,
    select_weight,
)
from .robustness_queue import (
    Context,
    action_scores,
    choose,
    context,
    event_oracle,
    guard,
    queue_cost,
)
from .robustness_report import summarize, table, validate_documented_conclusion, validate_report

TEST_SEEDS = tuple(range(20000, 20030))
STREAMS = ("stable", "reorganization", "announced_resource_shock", "unannounced_resource_shock")
CHANGE = 16
EPISODES = 48
SCENARIOS = 128
POLICIES = (
    "pooled_analytic",
    "oldest_cleared",
    "logistic",
    "boosting",
    "fixed_mixture",
    "guard_only",
    "alarm_only",
    "supervised_mixture",
    "independent_mixture",
)


@dataclass(frozen=True)
class Locked:
    experts: Experts
    alpha: float
    alarms: CusumSettings
    development: dict[str, Any]


def fit_locked() -> Locked:
    from .robustness_diagnostics import development_checks

    # No test seeds, outcomes or regimes are arguments to any fitting function.
    experts = fit_experts(cohort(1701, 1200, datetime(2026, 3, 1, tzinfo=UTC)))
    alpha, scores = select_weight(experts, cohort(1801, 128, datetime(2026, 8, 2, tzinfo=UTC)))
    alarms, operating = calibrate_cusum(experts, alpha)
    return Locked(
        experts,
        alpha,
        alarms,
        {
            "weight_scores": scores,
            "alarm_operating_point": operating,
            "development_checks": development_checks(experts, alpha, alarms),
        },
    )


def decisions(
    c: Context,
    prediction: dict[str, Array],
    alpha: float,
    monitor: DelayedCusum,
    seed: int,
    scenarios: int = SCENARIOS,
) -> dict[str, tuple[int, str]]:
    if c.at < monitor.settings.available_at or c.at < monitor.clock:
        raise ValueError("Decision precedes available strategy/feedback")
    u = copula_uniforms(seed, 3, scenarios, LOADING)
    independent = copula_uniforms(seed, 3, scenarios, 0)
    scores = {name: action_scores(c, quantiles(rates, u).T) for name, rates in prediction.items()}
    mix = quantiles(prediction["pooled"], u, prediction["boosting"], alpha).T
    mix_scores = action_scores(c, mix)
    separate = action_scores(
        c, quantiles(prediction["pooled"], independent, prediction["boosting"], alpha).T
    )
    # A deterministic analytic marginal rule, not an MC tie-breaking policy.
    gain = isolated_gain(prediction["pooled"], 360 - c.transport - c.cleaning)
    reference = 0 if c.announced_shock else 1 + int(np.argmax(gain[1:]))
    operational = 0 if c.announced_shock else 1 + int(np.argmax(c.clearance_age[1:]))
    fixed = choose(mix_scores)
    guarded, mode = guard(scores["pooled"], scores["boosting"], fixed, reference)
    alarm_action, alarm_mode = fixed, "recommend" if fixed else "no_change"
    if monitor.suspended_at is not None:
        alarm_action, alarm_mode = 0, "abstain_reference_alarm"
    elif monitor.fallback_at is not None:
        alarm_action, alarm_mode = reference, "fallback_relative_alarm"
    supervised = (
        (alarm_action, alarm_mode)
        if monitor.suspended_at or monitor.fallback_at
        else (guarded, mode)
    )
    result = {
        "pooled_analytic": (reference, "recommend" if reference else "no_change"),
        "oldest_cleared": (operational, "recommend" if operational else "no_change"),
        "logistic": (choose(scores["logistic"]), "fixed"),
        "boosting": (choose(scores["boosting"]), "fixed"),
        "fixed_mixture": (fixed, "fixed"),
        "guard_only": (guarded, mode),
        "alarm_only": (alarm_action, alarm_mode),
        "supervised_mixture": supervised,
        "independent_mixture": (choose(separate), "fixed"),
    }
    return result


def alarm_summary(at: datetime | None, stream: str) -> dict[str, Any]:
    change_at = TEST_START + timedelta(hours=2 * CHANGE)
    # Resource-only shocks do not change preparation labels in this protocol.
    # A preparation alarm there is false, even after the resource-change time.
    false = at is not None and (stream != "reorganization" or at < change_at + timedelta(hours=24))
    return {
        "at": at.isoformat() if at else None,
        "known_false_alarm": false,
        "delay_hours_after_change": (at - change_at).total_seconds() / 3600
        if at is not None and not false
        else None,
    }


def replay(
    locked: Locked, stream: str, seed: int, *, episodes: int = EPISODES, scenarios: int = SCENARIOS
) -> dict[str, Any]:
    if stream not in STREAMS or not 1 <= episodes <= EPISODES:
        raise ValueError("Invalid reserved replay")
    coefficients = np.repeat(
        np.where(np.arange(episodes) >= CHANGE, 1.5 if stream == "reorganization" else -2.0, -2.0),
        3,
    )
    data = cohort(seed, episodes, TEST_START, coefficient=coefficients)
    predicted = locked.experts.predict(data.features)
    ref_loss = log_loss(predicted["pooled"], data.time, data.observed).reshape(-1, 3).mean(axis=1)
    shadow_loss = (
        log_loss(predicted["pooled"], data.time, data.observed, predicted["boosting"], locked.alpha)
        .reshape(-1, 3)
        .mean(axis=1)
    )
    monitor = DelayedCusum(locked.alarms)
    rows: list[dict[str, Any]] = []
    for index in range(episodes):
        at = TEST_START + timedelta(hours=2 * index)
        if index >= 12:
            previous = index - 12
            monitor.observe(
                BatchFeedback(
                    f"{seed}:{previous}",
                    TEST_START + timedelta(hours=2 * previous),
                    at,
                    float(shadow_loss[previous] - ref_loss[previous]),
                    float(ref_loss[previous]),
                ),
                at,
            )
        shock = index >= CHANGE and stream.endswith("resource_shock")
        announced = shock and stream == "announced_resource_shock"
        features = data.features[3 * index : 3 * index + 3]
        c = context(seed, index, at, features, announced)
        forecasts = {name: p[3 * index : 3 * index + 3] for name, p in predicted.items()}
        # The decision interface has no truth, censoring, stream or future-loss argument.
        choices = decisions(c, forecasts, locked.alpha, monitor, seed * 100003 + index, scenarios)
        truth = data.truth[3 * index : 3 * index + 3]
        actual = np.stack([queue_cost(c, truth[None], a, shock)[0] for a in (0, 1, 2)])
        # Independent event integration checks every counterfactual, not just the chosen one.
        for a in (0, 1, 2):
            if not np.allclose(actual[a], event_oracle(c, truth, a, shock), atol=1e-8, rtol=0):
                raise AssertionError("Independent queue oracle disagreement")
        reference = actual[choices["logistic"][0], 0]
        oracle = float(actual[:, 0].min())
        for policy, (action, mode) in choices.items():
            alarm = monitor.suspended_at or monitor.fallback_at
            stage = (
                "guard_before_alarm"
                if policy in ("guard_only", "supervised_mixture")
                else "no_alarm_intervention"
            )
            if policy == "guard_only":
                stage = "guard_without_alarm"
            if policy in ("supervised_mixture", "alarm_only") and alarm:
                stage = (
                    "known_false_alarm"
                    if alarm_summary(alarm, stream)["known_false_alarm"]
                    else "alarm_after_changed_feedback_available"
                )
            value = actual[action]
            rows.append(
                {
                    "seed": seed,
                    "index": index,
                    "policy": policy,
                    "wait": float(value[0]),
                    "reference_wait": float(reference),
                    "delta_logistic": float(value[0] - reference),
                    "oracle_wait": oracle,
                    "staffing": float(value[1]),
                    "transport": float(value[2]),
                    "resource_regression": bool(np.any(value[1:] > actual[0, 1:] + 1e-8)),
                    "mode": mode,
                    "action": action,
                    "stage": stage,
                }
            )
    return {
        "stream": stream,
        "seed": seed,
        "rows": rows,
        "relative_alarm": alarm_summary(monitor.fallback_at, stream),
        "reference_alarm": alarm_summary(monitor.suspended_at, stream),
        "matured_batches": len(monitor.seen),
        "pending_batches": min(12, episodes),
    }


def run(locked: Locked) -> dict[str, Any]:
    from .robustness_diagnostics import reserved_forecast_diagnostics

    runs = [replay(locked, stream, seed) for stream in STREAMS for seed in TEST_SEEDS]
    full, post = {}, {}
    for stream in STREAMS:
        rows = [r for run in runs if run["stream"] == stream for r in run["rows"]]
        full[stream] = {
            p: summarize([r for r in rows if r["policy"] == p], inference=False) for p in POLICIES
        }
        if stream != "stable":
            post[stream] = {
                p: summarize(
                    [r for r in rows if r["policy"] == p and r["index"] >= CHANGE],
                    inference=stream == "reorganization" and p == "supervised_mixture",
                )
                for p in POLICIES
            }
    primary = post["reorganization"]["supervised_mixture"]
    ci = primary["paired_trajectory_ci95"]
    precise = (ci[1] - ci[0]) / 2 <= 10
    conclusion = (
        "synthetic_primary_improvement"
        if precise and ci[1] < 0
        else "synthetic_primary_regression"
        if precise and ci[0] > 0
        else "inconclusive"
    )
    settings = {
        "version": "DECISION_ROBUSTNESS_2",
        "seeds": TEST_SEEDS,
        "streams": STREAMS,
        "episodes": EPISODES,
        "scenarios": SCENARIOS,
        "alpha": locked.alpha,
        "experts": locked.experts.identity,
        "weight_available_at": WEIGHT_AVAILABLE.isoformat(),
        "settings_available_at": LOCK.isoformat(),
        "alarm": asdict(locked.alarms),
        "loading": LOADING,
    }
    report: dict[str, Any] = {
        "status": "synthetic_research_only",
        "settings": settings,
        "settings_hash": hashlib.sha256(
            json.dumps(settings, default=str, sort_keys=True).encode()
        ).hexdigest(),
        "development": locked.development,
        "primary_result": conclusion,
        "precision_target_met": precise,
        "deployment_conclusion": "research_only_no_promotion",
        "decision_episodes": len(STREAMS) * len(TEST_SEEDS) * EPISODES,
        "all_episodes": full,
        "post_change": post,
        "alarms": [{k: v for k, v in r.items() if k != "rows"} for r in runs],
        "limitations": [
            "conditional_on_one_model_fit_and_generator",
            "episodic_not_continuous_hospital",
            "action_independent_labels_assumed",
            "clairvoyant_oracle_not_attainable",
            "exploratory_secondary_comparisons",
            "no_clinical_validation",
        ],
    }
    report["markdown_table"] = table(report)
    report["forecast_diagnostics"] = reserved_forecast_diagnostics(locked.experts)
    validate_report(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate aggregate/table identities")
    args = parser.parse_args()
    locked = fit_locked()
    result = run(locked)
    if args.check:
        validate_report(result)
        validate_documented_conclusion(
            result, Path(__file__).resolve().parents[3] / "docs/operational/decision-v2-protocol.md"
        )
    print(json.dumps(result, default=str, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
