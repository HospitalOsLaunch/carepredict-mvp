"""Sequential episodic decision benchmark with delayed shadow feedback.

Research only: separate development and test cohorts, two fictional units,
one action per episode, fixed learned experts, no continuous hospital replay.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .decision_cases import CHANGE_INDEX, UNITS, Stream, actual_score, episode
from .decision_guard import (
    Feedback,
    GuardedChoice,
    MixtureSettings,
    Supervisor,
    curve_loss,
    guard_choice,
    mix_curve,
    mix_forecasts,
)
from .learning_demo import protocol, synthetic_records
from .models import Action
from .planning import Plan, PlanRequest, enumerate_actions, plan
from .preparation import PreparationForecasts
from .survival import HazardModel, forecast_preparation, partition, select_model

DEVELOPMENT_START = datetime(2026, 10, 8, tzinfo=UTC)
WEIGHT_AVAILABLE = datetime(2026, 10, 12, 8, tzinfo=UTC)
SETTINGS_AVAILABLE = datetime(2026, 10, 15, tzinfo=UTC)
TEST_START = datetime(2026, 10, 18, tzinfo=UTC)
TEST_SEEDS = (1109, 1223, 1301)
TEST_STREAMS: tuple[Stream, ...] = ("stable", "reorganization", "operational_shock")
ALPHAS = (0.0, 0.25, 0.5, 0.75, 1.0)


def development_origin(index: int) -> datetime:
    if not 0 <= index < 60:
        raise ValueError("Development index outside locked windows")
    return DEVELOPMENT_START + timedelta(hours=2 * index + (24 if index >= 40 else 0))


@dataclass(frozen=True)
class BenchmarkModels:
    reference: HazardModel
    challenger: HazardModel
    settings: MixtureSettings
    development_scores: dict[str, float]


def fit_benchmark() -> BenchmarkModels:
    # Separate research fit covering both named units, not silent expansion of the
    # previous one-unit learner's serving scope. No previous stress/test rows reused.
    split = protocol()
    records = tuple(
        r.model_copy(update={"unit_id": UNITS[i % 2]})
        for i, r in enumerate(synthetic_records(split, counts=(600, 200, 200, 1), seed=20261025))
    )
    data = partition(records, split)
    selection = select_model(data.train, data.calibration, data.validation, split)
    reference = next(m for m in selection.candidates if m.name == "pooled_hazard")
    challenger = next(m for m in selection.candidates if m.name == "gbm_hazard")
    losses: dict[float, list[float]] = {alpha: [] for alpha in ALPHAS}
    for index in range(60):
        case = episode(development_origin(index), 503, index, "development", scenarios=1)
        ref = forecast_preparation(reference, case.request.state())
        boost = forecast_preparation(challenger, case.request.state())
        ref_curves = {c.patient_id: c for c in ref.curves}
        boost_curves = {c.patient_id: c for c in boost.curves}
        for r in case.hidden.feedback:
            if index < 40 and r.label_available_at > WEIGHT_AVAILABLE:
                raise ValueError("Weight selection read labels past its lock")
            if index >= 40 and r.origin < WEIGHT_AVAILABLE:
                raise ValueError("Alarm calibration predates the selected weight")
            if r.label_available_at > SETTINGS_AVAILABLE:
                raise ValueError("Development labels unavailable at settings lock")
            for alpha in ALPHAS:
                losses[alpha].append(
                    curve_loss(
                        mix_curve(ref_curves[r.patient_id], boost_curves[r.patient_id], alpha), r
                    )
                )
    # First 40 episodes choose the weight; last 20 calibrate alarm thresholds.
    # Both periods precede settings lock and are disjoint from reserved replays.
    alpha = min(ALPHAS, key=lambda a: (statistics.mean(losses[a][:80]), a))
    differences = [a - b for a, b in zip(losses[alpha][80:], losses[0.0][80:], strict=True)]

    def rolling_quantile(values: list[float], q: float) -> float:
        means = sorted(statistics.mean(values[i - 24 : i]) for i in range(24, len(values) + 1))
        return means[min(len(means) - 1, math.ceil(q * len(means)) - 1)]

    settings = MixtureSettings(
        hospital_id="fictional-hospital",
        unit_ids=UNITS,
        reference_model_id=reference.model_id,
        challenger_model_id=challenger.model_id,
        alpha=alpha,
        available_at=SETTINGS_AVAILABLE,
        min_feedback=24,
        feedback_window=24,
        paired_loss_limit=max(0.05, rolling_quantile(differences, 0.95) + 0.05),
        reference_loss_limit=rolling_quantile(losses[0.0][80:], 0.99) + 0.25,
        regret_budget_patient_minutes=30,
    )
    return BenchmarkModels(
        reference,
        challenger,
        settings,
        {str(a): statistics.mean(v[:80]) for a, v in losses.items()},
    )


def request_with(request: PlanRequest, forecasts: PreparationForecasts) -> PlanRequest:
    return PlanRequest.model_validate({**request.model_dump(), "preparation": forecasts})


def policy_plans(
    request: PlanRequest, models: BenchmarkModels, supervisor: Supervisor
) -> tuple[dict[str, Plan], GuardedChoice]:
    if request.at < models.settings.available_at:
        raise ValueError("Strategy not available at decision origin")
    state = request.state()
    reference = forecast_preparation(models.reference, state)
    challenger = forecast_preparation(models.challenger, state)
    fixed = mix_forecasts(
        reference, challenger, models.settings.alpha, models.settings.available_at
    )
    plans = {
        "reference": plan(request_with(request, reference)),
        "boosting": plan(request_with(request, challenger)),
        "fixed_mixture": plan(request_with(request, fixed)),
    }
    alpha = supervisor.alpha_at(request.at)
    if supervisor.fallback_at is None:
        supervised = plans["fixed_mixture"]
    else:
        supervised = plan(
            request_with(
                request, mix_forecasts(reference, challenger, alpha, supervisor.fallback_at)
            )
        )
    choice = guard_choice(plans["reference"], plans["boosting"], supervised, supervisor)
    return plans, choice


def run_stream(
    models: BenchmarkModels, stream: Stream, seed: int, *, episodes: int = 48, scenarios: int = 32
) -> dict[str, Any]:
    if stream not in TEST_STREAMS or not 1 <= episodes <= 48:
        raise ValueError("Reserved replay requires a test stream and 1..48 episodes")
    supervisor = Supervisor(models.settings)
    pending: list[Feedback] = []
    rows = []
    for index in range(episodes):
        at = TEST_START + timedelta(hours=2 * index)
        matured = sorted(
            (f for f in pending if f.record.label_available_at <= at),
            key=lambda f: (f.record.label_available_at, f.record.patient_id),
        )
        pending = [f for f in pending if f.record.label_available_at > at]
        for feedback in matured:
            supervisor.observe(feedback, at)
        case = episode(at, seed, index, stream, scenarios=scenarios)
        # Policies receive observed context only. Hidden outcomes are used after choice.
        plans, supervised = policy_plans(case.request, models, supervisor)
        choices = {
            name: GuardedChoice(
                p.selected,
                "abstain"
                if p.decision == "abstain"
                else "no_change"
                if p.selected.kind == "no_op"
                else "recommend",
                "fixed_policy",
                0.0
                if name == "reference"
                else 1.0
                if name == "boosting"
                else models.settings.alpha,
            )
            for name, p in plans.items()
        }
        choices["supervised_mixture"] = supervised
        actions, _ = enumerate_actions(case.request.state(), 32)
        realized = {a.key: actual_score(case, a) for a in actions}
        no_op = realized[Action(kind="no_op").key]
        clairvoyant = min(s.waiting_patient_minutes for s in realized.values())
        reference_result = realized[choices["reference"].action.key]
        for name, choice in choices.items():
            result = realized[choice.action.key]
            rows.append(
                {
                    "stream": stream,
                    "seed": seed,
                    "index": index,
                    "phase": "after_change"
                    if stream != "stable" and index >= CHANGE_INDEX
                    else "before_change",
                    "policy": name,
                    "action": choice.action.key,
                    "waiting_patient_minutes": result.waiting_patient_minutes,
                    "gain_vs_noop": no_op.waiting_patient_minutes - result.waiting_patient_minutes,
                    "delta_vs_reference": result.waiting_patient_minutes
                    - reference_result.waiting_patient_minutes,
                    "regret_vs_clairvoyant": result.waiting_patient_minutes - clairvoyant,
                    "pressure_regression": any(
                        a > b
                        for a, b in zip(
                            result.pressure.components(), no_op.pressure.components(), strict=True
                        )
                    ),
                    "staffed_patient_minutes": result.pressure.staffed_patient_minutes,
                    "transport_team_minutes": result.pressure.transport_team_minutes,
                    "violations": result.violations,
                    "mode": choice.mode,
                    "reason": choice.reason,
                    "no_action": choice.action.kind == "no_op",
                    "candidate_alpha": choice.alpha,
                    "served_alpha": None
                    if choice.mode == "abstain"
                    else 0.0
                    if choice.mode == "fallback_reference"
                    else choice.alpha,
                }
            )
        ref_bundle = plans["reference"].preparation
        shadow_bundle = plans["fixed_mixture"].preparation
        assert ref_bundle is not None and shadow_bundle is not None
        ref_curves = {c.patient_id: c for c in ref_bundle.curves}
        shadow_curves = {c.patient_id: c for c in shadow_bundle.curves}
        pending.extend(
            Feedback(r, ref_curves[r.patient_id], shadow_curves[r.patient_id])
            for r in case.hidden.feedback
        )
    return {
        "stream": stream,
        "seed": seed,
        "shadow_alarm": summarize_alarm(supervisor.fallback_at, stream),
        "reference_alarm": summarize_alarm(supervisor.suspended_at, stream),
        "matured_feedback": len(supervisor.seen),
        "pending_feedback_at_end": len(pending),
        "rows": rows,
    }


def summarize_alarm(at: datetime | None, stream: Stream) -> dict[str, Any]:
    change_at = TEST_START + timedelta(hours=2 * CHANGE_INDEX)
    # A post-change alarm can still use exclusively pre-change outcomes: labels
    # arrive after 24 hours. Do not credit such an alarm as drift detection.
    first_changed_feedback = change_at + timedelta(hours=24)
    false_alarm = at is not None and (stream == "stable" or at < first_changed_feedback)
    elapsed = (
        (at - change_at).total_seconds() / 3600
        if at is not None and stream != "stable" and at >= change_at
        else None
    )
    return {
        "at": at.isoformat() if at else None,
        "false_alarm": false_alarm,
        "elapsed_since_change_hours": elapsed,
        "delay_hours": elapsed if not false_alarm else None,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def mean(key: str) -> float:
        return float(statistics.mean(r[key] for r in rows))

    regret = sorted((r["regret_vs_clairvoyant"] for r in rows), reverse=True)
    return {
        "episodes": len(rows),
        "mean_waiting_patient_minutes": mean("waiting_patient_minutes"),
        "mean_gain_vs_noop": mean("gain_vs_noop"),
        "mean_delta_vs_reference": mean("delta_vs_reference"),
        "worse_than_reference_rate": statistics.mean(r["delta_vs_reference"] > 0 for r in rows),
        "mean_regret_vs_clairvoyant": statistics.mean(regret),
        "worst_decile_regret": statistics.mean(regret[: max(1, math.ceil(len(regret) / 10))]),
        "pressure_regression_rate": mean("pressure_regression"),
        "mean_staffed_patient_minutes": mean("staffed_patient_minutes"),
        "mean_transport_team_minutes": mean("transport_team_minutes"),
        "abstention_rate": statistics.mean(r["mode"] == "abstain" for r in rows),
        "fallback_rate": statistics.mean(r["mode"] == "fallback_reference" for r in rows),
        "no_action_rate": mean("no_action"),
        "mechanics_violations": sum(len(r["violations"]) for r in rows),
    }


def run_benchmark(*, episodes: int = 48, scenarios: int = 32) -> dict[str, Any]:
    models = fit_benchmark()
    runs = [
        run_stream(models, stream, seed, episodes=episodes, scenarios=scenarios)
        for stream in TEST_STREAMS
        for seed in TEST_SEEDS
    ]
    rows = [row for run in runs for row in run["rows"]]
    summary = {
        stream: {
            policy: summarize([r for r in rows if r["stream"] == stream and r["policy"] == policy])
            for policy in ("reference", "boosting", "fixed_mixture", "supervised_mixture")
        }
        for stream in TEST_STREAMS
    }
    post = {
        stream: {
            policy: summarize(
                [
                    r
                    for r in rows
                    if r["stream"] == stream
                    and r["policy"] == policy
                    and r["phase"] == "after_change"
                ]
            )
            for policy in ("reference", "boosting", "fixed_mixture", "supervised_mixture")
        }
        for stream in TEST_STREAMS
        if any(r["stream"] == stream and r["phase"] == "after_change" for r in rows)
    }
    return {
        "status": "synthetic_sequential_episodic_research_only",
        "settings": models.settings.model_dump(mode="json"),
        "development_censored_nll": models.development_scores,
        "weight_development_records": 80,
        "alarm_calibration_records": 40,
        "weight_available_at": WEIGHT_AVAILABLE.isoformat(),
        "decision_episodes": episodes * len(TEST_STREAMS) * len(TEST_SEEDS),
        "planning_scenarios": scenarios,
        "horizon_minutes": 360,
        "feedback_delay_hours": 24,
        "change_index": CHANGE_INDEX,
        "summary": summary,
        "after_change": post,
        "decision_findings": {
            "scientific_conclusion": "inconclusive_three_seeds_non_discriminating_reference",
            "supervised_mean_wait_worse_than_reference_after_change": [
                stream
                for stream, policies in post.items()
                if policies["supervised_mixture"]["mean_delta_vs_reference"] > 0
            ],
            "supervised_resource_regressions_observed": [
                stream
                for stream, policies in summary.items()
                if policies["supervised_mixture"]["pressure_regression_rate"] > 0
            ],
            "deployment_conclusion": "research_only_no_promotion",
        },
        "per_seed": [
            {
                **{k: v for k, v in run.items() if k != "rows"},
                "policies": {
                    p: summarize([r for r in run["rows"] if r["policy"] == p])
                    for p in ("reference", "boosting", "fixed_mixture", "supervised_mixture")
                },
            }
            for run in runs
        ],
        "limitations": [
            "independent_episodes_not_continuous_hospital",
            "preparation_feedback_for_both_patients_assumed_action_independent",
            "empirical_alarm_thresholds_no_false_alarm_guarantee",
            "unannounced_resource_shocks_not_visible_to_any_policy",
            "clairvoyant_oracle_is_not_deployable",
            "no_real_data_or_clinical_effect_established",
        ],
    }


def main() -> None:
    print(json.dumps(run_benchmark(), indent=2))


if __name__ == "__main__":
    main()
