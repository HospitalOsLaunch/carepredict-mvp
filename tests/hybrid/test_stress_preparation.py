"""Stress protocol checks, not assertions that a model must outperform its baseline."""

from __future__ import annotations

from typing import Any

import pytest

from hospitalos.hybrid.learning_demo import train_demo
from hospitalos.hybrid.stress_preparation import (
    REGIMES,
    Regime,
    evaluate_stress,
    stress_data,
    stress_report,
)
from hospitalos.hybrid.survival import Selection


@pytest.fixture(scope="module")
def selection() -> Selection:
    return train_demo()[0]


@pytest.mark.parametrize("regime", REGIMES)
def test_oracle_is_separate_from_observed_followup_and_features(regime: Regime) -> None:
    data = stress_data(regime, 101, 40)
    assert data == stress_data(regime, 101, 40)
    for observed, truth in zip(data.observed, data.oracle, strict=True):
        assert observed.features == truth.features
        assert observed.followed_minutes <= truth.followed_minutes
        if observed.event_observed:
            assert truth.event_observed
            assert observed.followed_minutes == truth.followed_minutes


def test_informative_censoring_changes_observation_only() -> None:
    reference = stress_data("reference_new_seed", 202, 200)
    informative = stress_data("informative_censoring", 202, 200)
    assert [(r.features, r.followed_minutes, r.event_observed) for r in reference.oracle] == [
        (r.features, r.followed_minutes, r.event_observed) for r in informative.oracle
    ]
    assert [r.followed_minutes for r in reference.observed] != [
        r.followed_minutes for r in informative.observed
    ]
    assert informative.independent_censoring is False


def test_ipcw_is_suppressed_when_assumptions_are_intentionally_broken(selection: Selection) -> None:
    result = evaluate_stress(selection, "informative_censoring", 101, 40)
    assert result["ipcw_assumptions"] == "violated_scores_suppressed"
    for model in result["scores"].values():
        assert model["observed_training_ipcw"] is None
        assert model["oracle_complete_followup"] is not None


def test_unsupported_loads_are_counted_as_abstentions(selection: Selection) -> None:
    result = evaluate_stress(selection, "outside_load_support", 101, 40)
    assert result["supported"] == 0
    assert result["abstained"] == result["total"] == 40
    assert all(s["oracle_complete_followup"] is None for s in result["scores"].values())


def test_stress_evaluation_never_retunes_and_verdict_tracks_actual_regressions(
    selection: Selection,
) -> None:
    before = selection.selected.hazards(
        (stress_data("reference_new_seed", 101, 1).observed[0].features,)
    )
    identity = selection.selected.model_id
    report: dict[str, Any] = stress_report(selection, count=40)
    after = selection.selected.hazards(
        (stress_data("reference_new_seed", 101, 1).observed[0].features,)
    )
    assert before == after
    assert identity == report["selected_model_id"]
    assert report["retuning_performed"] is False
    assert len(report["cases"]) == 15
    assert sum(c["total"] for c in report["cases"]) == 600
    regressed = any(v["selected_worse_than_pooled_seeds"] for v in report["summary"].values())
    assert (report["verdict"] == "not_robust_to_all_reserved_regimes") == regressed
