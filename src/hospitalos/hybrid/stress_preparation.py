"""Frozen synthetic stress cases; never used to retune or select the learner.

Oracle outcomes exist only in these fixtures and are kept separate from features
and observed labels. They diagnose informative censoring without claiming IPCW
is valid when its assumptions are knowingly broken.
"""

from __future__ import annotations

import json
import math
import random
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from .learning_demo import train_demo
from .preparation import EDGES, PreparationFeatures
from .survival import CensoringDistribution, HazardModel, PreparationRecord, Selection, evaluate

Regime = Literal[
    "reference_new_seed",
    "slow_preparation",
    "changed_load_effect",
    "informative_censoring",
    "outside_load_support",
]
REGIMES: tuple[Regime, ...] = (
    "reference_new_seed",
    "slow_preparation",
    "changed_load_effect",
    "informative_censoring",
    "outside_load_support",
)
SEEDS = (101, 202, 303)


@dataclass(frozen=True)
class StressData:
    observed: tuple[PreparationRecord, ...]
    oracle: tuple[PreparationRecord, ...]
    independent_censoring: bool


def stress_data(regime: Regime, seed: int, count: int = 200) -> StressData:
    if regime not in REGIMES or count < 1:
        raise ValueError("Unknown regime or empty stress cohort")
    context, outcomes, censoring = (random.Random(seed + i) for i in range(3))
    observed, oracle = [], []
    for i in range(count):
        at = datetime(2026, 10, 2, tzinfo=UTC) + timedelta(minutes=context.randrange(7 * 1440))
        f = PreparationFeatures(
            occupied_per_staffed_bed=context.choice(
                (1.8, 2.1, 2.4) if regime == "outside_load_support" else (0.3, 0.6, 0.9, 1.2, 1.5)
            ),
            waiting_per_staffed_bed=context.choice((0.0, 0.5, 1.0, 1.5)),
            hour_utc=at.hour,
            weekday_utc=at.weekday(),
        )
        completion = 1441
        for index, edge in enumerate(EDGES):
            load_effect = 2.0 if regime == "changed_load_effect" else -2.0
            logit = (
                -0.8
                + 0.18 * index
                + load_effect * (f.occupied_per_staffed_bed - 0.8)
                - 0.7 * f.waiting_per_staffed_bed
                + 0.3 * math.sin(2 * math.pi * at.hour / 24)
            )
            if regime == "slow_preparation":
                logit -= 1.0
            if outcomes.random() < 1 / (1 + math.exp(-logit)):
                completion = edge
                break
        followup = censoring.choice((90, 180, 300, 600, 1440, 1440, 1440))
        if regime == "informative_censoring":
            # Deliberately future-dependent observation; forbidden as a feature.
            followup = 90 if completion > 120 else 1440
        truth = PreparationRecord(
            episode_id=f"stress-{regime}-{seed}-{i}",
            patient_id=f"stress-{regime}-{seed}-{i}",
            hospital_id="fictional-hospital",
            unit_id="medicine",
            origin=at,
            features_available_at=at,
            features=f,
            followed_minutes=min(completion, 1440),
            event_observed=completion <= 1440,
            label_available_at=at + timedelta(days=1),
        )
        oracle.append(truth)
        observed.append(
            PreparationRecord.model_validate(
                {
                    **truth.model_dump(),
                    "followed_minutes": min(completion, followup),
                    "event_observed": completion <= followup,
                }
            )
        )
    return StressData(tuple(observed), tuple(oracle), regime != "informative_censoring")


def supported(model: HazardModel, record: PreparationRecord) -> bool:
    return model.supports(record.features, record.hospital_id, record.unit_id)


def evaluate_stress(
    selection: Selection, regime: Regime, seed: int, count: int = 200
) -> dict[str, Any]:
    data = stress_data(regime, seed, count)
    # Serving support is checked before reporting performance; no extrapolation is hidden.
    eligible = tuple(
        i for i, r in enumerate(data.observed) if all(supported(m, r) for m in selection.candidates)
    )
    observed = tuple(data.observed[i] for i in eligible)
    truth = tuple(data.oracle[i] for i in eligible)
    scores = {}
    for m in selection.candidates:
        scores[m.name] = {
            "oracle_complete_followup": evaluate(m, truth, CensoringDistribution((), 1440))
            if truth
            else None,
            # Training-estimated G need not transfer to a new observation mechanism.
            "observed_training_ipcw": evaluate(m, observed, selection.censoring)
            if observed and data.independent_censoring
            else None,
        }
    return {
        "regime": regime,
        "seed": seed,
        "total": count,
        "supported": len(eligible),
        "abstained": count - len(eligible),
        "observed_censored": sum(not r.event_observed for r in data.observed),
        "ipcw_assumptions": "independent_same_observation_mechanism"
        if data.independent_censoring
        else "violated_scores_suppressed",
        "scores": scores,
    }


def stress_report(selection: Selection, *, count: int = 200) -> dict[str, Any]:
    cases = tuple(
        evaluate_stress(selection, regime, seed, count) for regime in REGIMES for seed in SEEDS
    )
    summaries = {}
    for regime in REGIMES:
        group = tuple(c for c in cases if c["regime"] == regime)
        means = {}
        for m in selection.candidates:
            values = [
                c["scores"][m.name]["oracle_complete_followup"]["interval_nll_per_record"]
                for c in group
                if c["supported"]
            ]
            means[m.name] = statistics.mean(values) if values else None
        regressions = sum(
            c["supported"] > 0
            and c["scores"][selection.selected.name]["oracle_complete_followup"][
                "interval_nll_per_record"
            ]
            > c["scores"]["pooled_hazard"]["oracle_complete_followup"]["interval_nll_per_record"]
            for c in group
        )
        summaries[regime] = {
            "total": sum(c["total"] for c in group),
            "supported": sum(c["supported"] for c in group),
            "oracle_nll_mean_across_seeds": means,
            "selected_worse_than_pooled_seeds": regressions,
            "ipcw_assumptions": group[0]["ipcw_assumptions"],
        }
    return {
        "status": "synthetic_stress_diagnostic_only",
        "selected_model_id": selection.selected.model_id,
        "selected_model": selection.selected.name,
        "retuning_performed": False,
        "seeds": SEEDS,
        "summary": summaries,
        "verdict": "not_robust_to_all_reserved_regimes"
        if any(v["selected_worse_than_pooled_seeds"] for v in summaries.values())
        else "no_regression_observed_on_this_synthetic_suite",
        "real_validation": "not_performed",
        "cases": cases,
    }


def main() -> None:
    selection, _ = train_demo()
    report = stress_report(selection)
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))


if __name__ == "__main__":
    main()
