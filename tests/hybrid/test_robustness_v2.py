"""Independent distribution, queue, clock, alarm and inference checks for v2."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from scipy.special import ndtri  # type: ignore[import-untyped]

from hospitalos.hybrid.continuous import (
    GRID,
    copula_uniforms,
    isolated_gain,
    log_loss,
    quantiles,
)
from hospitalos.hybrid.cusum import (
    BatchFeedback,
    CusumSettings,
    DelayedCusum,
    run_lengths,
    summarize_lengths,
)
from hospitalos.hybrid.decision_cases import episode
from hospitalos.hybrid.decision_guard import mix_curve
from hospitalos.hybrid.planning import PlanRequest, plan
from hospitalos.hybrid.preparation import PreparationCurve, PreparationForecasts, preparation_draw
from hospitalos.hybrid.robustness_diagnostics import diagnostic_ipcw
from hospitalos.hybrid.robustness_models import (
    LOCK,
    TEST_START,
    Experts,
    calendar,
    cohort,
    fit_experts,
    select_weight,
)
from hospitalos.hybrid.robustness_queue import (
    Context,
    action_scores,
    context,
    event_oracle,
    queue_cost,
)
from hospitalos.hybrid.robustness_report import (
    paired_interval,
    table,
    validate_documented_conclusion,
    validate_report,
)
from hospitalos.hybrid.robustness_v2 import Locked, alarm_summary, decisions, replay


@pytest.fixture(scope="module")
def experts() -> Experts:
    return fit_experts(cohort(1701, 1200, datetime(2026, 3, 1, tzinfo=UTC)))


def test_continuous_inverse_and_censoring_are_not_upper_edge_rounding() -> None:
    rates = np.full((1, len(GRID)), 0.01)
    u = np.array([[1 - math.exp(-3.3)]])
    assert quantiles(rates, u)[0, 0] == pytest.approx(330)
    assert log_loss(rates, np.array([330]), np.array([False]))[0] == pytest.approx(3.3)
    assert log_loss(rates, np.array([330]), np.array([True]))[0] == pytest.approx(
        3.3 - math.log(0.01)
    )
    assert math.isinf(quantiles(np.zeros_like(rates), np.array([[0.5]]))[0, 0])


def test_continuous_mixture_preserves_density_and_quantile() -> None:
    a, b = np.full((1, len(GRID)), 0.01), np.full((1, len(GRID)), 0.02)
    density = 0.25 * 0.01 * math.exp(-1) + 0.75 * 0.02 * math.exp(-2)
    assert log_loss(a, np.array([100]), np.array([True]), b, 0.75)[0] == pytest.approx(
        -math.log(density)
    )
    rank = 1 - 0.25 * math.exp(-1) - 0.75 * math.exp(-2)
    assert quantiles(a, np.array([[rank]]), b, 0.75)[0, 0] == pytest.approx(100, abs=1e-4)


def test_gaussian_copula_preserves_marginals_and_shared_loading() -> None:
    u = copula_uniforms(5101, 3, 20000, 0.6)
    assert np.allclose(u.mean(axis=1), 0.5, atol=0.01)
    assert np.allclose((u < 0.2).mean(axis=1), 0.2, atol=0.01)
    assert np.corrcoef(ndtri(u))[0, 1] == pytest.approx(0.36, abs=0.025)
    assert np.array_equal(copula_uniforms(5, 3, 32, 1)[0], copula_uniforms(5, 3, 32, 1)[1])


def test_analytic_rule_matches_closed_form_integral() -> None:
    rates = np.full((2, len(GRID)), 0.01)
    horizon = np.array([200, 300])
    expected = horizon - (1 - np.exp(-0.01 * horizon)) / 0.01
    assert np.allclose(isolated_gain(rates, horizon), expected)


def test_local_calendar_does_not_shift_wall_clock_on_dst_change() -> None:
    before = datetime(2026, 10, 24, 6, tzinfo=UTC)
    after = datetime(2026, 10, 25, 7, tzinfo=UTC)
    assert np.allclose(calendar(before)[:2], calendar(after)[:2])


def test_training_and_weight_selection_refuse_future_labels(experts: Experts) -> None:
    data = cohort(5103, 3, TEST_START)
    with pytest.raises(ValueError, match="Future"):
        fit_experts(data)
    with pytest.raises(ValueError, match="boundary"):
        select_weight(experts, data)
    assert np.any(data.truth[np.isfinite(data.truth)] % 30 != 0)
    assert len(np.unique(data.features[:, 0])) == len(data.features)


def test_future_duplicate_and_nonfinite_feedback_do_not_mutate_monitor() -> None:
    s = DelayedCusum(CusumSettings((0, 0), (1, 1), 0.1))
    f = BatchFeedback("p", TEST_START, TEST_START + timedelta(hours=24), 1, 0)
    with pytest.raises(ValueError, match="Unavailable"):
        s.observe(f, TEST_START)
    assert not s.seen and s.fallback_at is None
    s.observe(f, f.available_at)
    assert s.fallback_at == f.available_at and s.suspended_at is None
    with pytest.raises(ValueError, match="Duplicate"):
        s.observe(f, f.available_at)
    s.observe(replace(f, episode_id="q", paired_loss=-100), f.available_at)
    assert s.fallback_at == f.available_at


def test_joint_cusum_run_length_and_right_censoring() -> None:
    settings = CusumSettings((0, 0), (1, 1), 1.5)
    values = np.array(
        [[[1.0, 0], [1, 0], [1, 0]], [[0, 1], [0, 1], [0, 1]], [[0, 0], [0, 0], [0, 0]]]
    )
    lengths = run_lengths(values, settings)
    assert lengths.tolist() == [2, 2, 4]
    result = summarize_lengths(lengths, 3)
    assert result["restricted_mean_run_length"] == pytest.approx(7 / 3)
    assert result["right_censored_fraction"] == pytest.approx(1 / 3)
    assert result["arl_exact"] is None


def test_resource_only_change_cannot_validate_a_preparation_alarm() -> None:
    at = TEST_START + timedelta(hours=80)
    assert alarm_summary(at, "unannounced_resource_shock")["known_false_alarm"]
    assert alarm_summary(at, "announced_resource_shock")["known_false_alarm"]
    assert not alarm_summary(at, "reorganization")["known_false_alarm"]


@pytest.mark.parametrize("shock", [False, True])
@pytest.mark.parametrize("action", [0, 1, 2])
def test_queue_counterfactuals_match_independent_integrated_oracle(
    shock: bool, action: int
) -> None:
    c = context(5109, 1, TEST_START, np.zeros((3, 5)), shock)
    for times in (
        np.array([30.0, 40, 50]),
        np.array([100.0, 30, 300]),
        np.array([np.inf, 100, np.inf]),
        np.array([90.0, 90, 90]),
    ):
        assert np.allclose(
            queue_cost(c, times[None], action, shock)[0],
            event_oracle(c, times, action, shock),
            atol=1e-8,
        )


def test_concurrent_transport_has_hand_calculated_wait() -> None:
    c = Context(
        TEST_START, np.zeros((3, 5)), np.full(3, 45.0), np.full(3, 30.0), np.zeros(3), 3, False
    )
    ready = np.array([[30.0, 40, 50]])
    assert queue_cost(c, ready, 0, False)[0, 0] == 825
    assert queue_cost(c, ready, 1, False)[0, 0] == 645
    assert queue_cost(c, ready, 1, True)[0].tolist() == [720, 345, 15]


def test_dependence_changes_tail_with_multiple_active_departures() -> None:
    c = Context(
        TEST_START, np.zeros((3, 5)), np.full(3, 45.0), np.full(3, 30.0), np.zeros(3), 3, False
    )
    rates = np.full((3, len(GRID)), 0.01)
    a = action_scores(c, quantiles(rates, copula_uniforms(5131, 3, 10000, 0)).T)[0]
    b = action_scores(c, quantiles(rates, copula_uniforms(5131, 3, 10000, 0.85)).T)[0]
    assert not np.allclose(a[1:], b[1:], atol=1)


def test_v2_json_forecast_roundtrip_and_legacy_mixture_rejection() -> None:
    rates = np.full(len(GRID), 0.01)
    s = np.exp(-rates * GRID)
    curve = PreparationCurve(
        patient_id="p",
        mass=tuple(np.r_[1, s[:-1]] - s),
        beyond_24h=float(s[-1]),
        edges=tuple(int(t) for t in GRID),
        interpolation="constant_hazard",
    )
    assert curve.quantile(1 - math.exp(-3.3)) in (330, 331)
    with pytest.raises(ValueError, match="Legacy"):
        mix_curve(curve, curve, 0.5)
    assert preparation_draw(curve, 1, 0, shared_loading=1, hospital_id="h") == preparation_draw(
        curve.model_copy(update={"patient_id": "q"}), 1, 0, shared_loading=1, hospital_id="h"
    )
    case = episode(TEST_START, 701, 0, "stable", scenarios=2)
    ids = [d.id for d in case.request.state().discharges]
    bundle = PreparationForecasts(
        schema_version="PREPARATION_FORECAST_2",
        model_id="a" * 64,
        hospital_id=case.request.hospital_id,
        state_fingerprint=case.request.state().fingerprint,
        origin=TEST_START,
        model_available_at=LOCK,
        shared_loading=0.6,
        curves=tuple(curve.model_copy(update={"patient_id": p}) for p in ids),
    )
    request = PlanRequest.model_validate(
        {**case.request.model_dump(), "preparation": bundle.model_dump()}
    )
    assert PlanRequest.model_validate_json(request.model_dump_json()) == request
    assert plan(request).schema_version == "HYBRID_PLAN_5"
    with pytest.raises(ValueError, match="schema v2"):
        PreparationForecasts.model_validate(
            {**bundle.model_dump(), "schema_version": "PREPARATION_FORECAST_1"}
        )


def test_inference_requires_trajectories_and_report_table_is_verified() -> None:
    with pytest.raises(ValueError, match="30"):
        paired_interval(np.array([1, 2, 3]))
    assert paired_interval(np.full(30, -2)) == [-2, -2]
    report: dict[str, Any] = {
        "deployment_conclusion": "research_only_no_promotion",
        "all_episodes": {},
        "post_change": {},
    }
    report["markdown_table"] = table(report)
    validate_report(report)
    report["markdown_table"] += "invented"
    with pytest.raises(AssertionError, match="table"):
        validate_report(report)


def test_documented_conclusion_is_recomputed_not_an_unchecked_claim(tmp_path: Path) -> None:
    path = tmp_path / "protocol.md"
    path.write_text("<!-- decision-v2-primary: inconclusive -->")
    validate_documented_conclusion({"primary_result": "inconclusive"}, path)
    with pytest.raises(AssertionError, match="Documented"):
        validate_documented_conclusion({"primary_result": "synthetic_primary_improvement"}, path)


def test_replay_has_no_feedback_before_24h_and_no_future_truth_input(experts: Experts) -> None:
    locked = Locked(experts, 0.5, CusumSettings((0, 5), (1, 1), 10), {})
    r = replay(locked, "stable", 5201, episodes=12, scenarios=8)
    assert r["matured_batches"] == 0 and r["pending_batches"] == 12
    f = cohort(5202, 1, TEST_START).features
    c = context(5202, 0, TEST_START, f, False)
    monitor = DelayedCusum(locked.alarms)
    a = decisions(c, experts.predict(f), 0.5, monitor, 1, 8)
    # Counterfactual observation timestamps gate the strategy independently of truth.
    with pytest.raises(ValueError, match="precedes"):
        decisions(
            replace(c, at=LOCK - timedelta(seconds=1)), experts.predict(f), 0.5, monitor, 1, 8
        )
    assert a == decisions(c, experts.predict(f), 0.5, monitor, 1, 8)


def test_future_labels_cannot_change_past_decisions(
    experts: Experts, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hospitalos.hybrid import robustness_v2 as benchmark

    locked = Locked(experts, 0.5, CusumSettings((0, 5), (1, 1), 10), {})
    before = replay(locked, "stable", 5211, episodes=12, scenarios=8)

    def changed(*args: Any, **kwargs: Any) -> Any:
        data = cohort(*args, **kwargs)
        return replace(
            data,
            time=np.full(len(data.time), 30.0),
            observed=np.ones(len(data.observed), dtype=bool),
        )

    monkeypatch.setattr(benchmark, "cohort", changed)
    assert replay(locked, "stable", 5211, episodes=12, scenarios=8) == before


def test_ipcw_diagnostic_matches_complete_truth_without_censoring() -> None:
    times = np.array([100.0, 300.0])
    event = np.array([True, True])
    predicted = np.array([0.25, 0.8])
    assert diagnostic_ipcw(times, event, predicted, 240) == pytest.approx((0.25**2 + 0.2**2) / 2)


def test_api_continuous_curve_matches_unrounded_research_distribution() -> None:
    rates = np.full((1, len(GRID)), 0.01)
    edge_survival = np.exp(-0.01 * GRID)
    curve = PreparationCurve(
        patient_id="p",
        mass=tuple(np.r_[1, edge_survival[:-1]] - edge_survival),
        beyond_24h=float(edge_survival[-1]),
        edges=tuple(int(t) for t in GRID),
        interpolation="constant_hazard",
    )
    ranks = np.array([[0.1, 0.5, 0.8, 0.99]])
    exact = quantiles(rates, ranks)[0]
    rounded = [curve.quantile(float(u)) for u in ranks[0]]
    assert all(v is not None and 0 <= v - t < 1.000001 for v, t in zip(rounded, exact, strict=True))
