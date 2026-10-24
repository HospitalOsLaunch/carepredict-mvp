"""Distribution arithmetic, delayed supervision and independent decision outcomes."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from hospitalos.hybrid.decision_benchmark import (
    SETTINGS_AVAILABLE,
    TEST_START,
    WEIGHT_AVAILABLE,
    BenchmarkModels,
    development_origin,
    fit_benchmark,
    policy_plans,
    request_with,
    run_stream,
    summarize_alarm,
)
from hospitalos.hybrid.decision_cases import CHANGE_INDEX, UNITS, actual_score, episode
from hospitalos.hybrid.decision_guard import (
    Feedback,
    MixtureSettings,
    Supervisor,
    curve_loss,
    guard_choice,
    mix_curve,
    mix_forecasts,
)
from hospitalos.hybrid.planning import enumerate_actions, plan
from hospitalos.hybrid.preparation import PreparationCurve, PreparationFeatures
from hospitalos.hybrid.survival import PreparationRecord, forecast_preparation


@pytest.fixture(scope="module")
def models() -> BenchmarkModels:
    return fit_benchmark()


def feedback(at: datetime, name: str = "p", ref: float = 0.9, candidate: float = 0.1) -> Feedback:
    r = PreparationRecord(
        episode_id=name,
        patient_id=name,
        hospital_id="fictional-hospital",
        unit_id=UNITS[0],
        origin=at,
        features_available_at=at,
        features=PreparationFeatures(
            occupied_per_staffed_bed=1,
            waiting_per_staffed_bed=1,
            hour_utc=at.hour,
            weekday_utc=at.weekday(),
        ),
        followed_minutes=30,
        event_observed=True,
        label_available_at=at + timedelta(hours=24),
    )
    return Feedback(
        r,
        PreparationCurve(patient_id=name, mass=(ref, 0, 0, 0, 0, 0), beyond_24h=1 - ref),
        PreparationCurve(
            patient_id=name, mass=(candidate, 0, 0, 0, 0, 0), beyond_24h=1 - candidate
        ),
    )


def short_settings(models: BenchmarkModels) -> MixtureSettings:
    return models.settings.model_copy(
        update={
            "alpha": 0.75,
            "min_feedback": 4,
            "feedback_window": 4,
            "paired_loss_limit": 0.1,
            "reference_loss_limit": 10.0,
        }
    )


def test_mixture_is_a_distribution_not_an_average_of_log_losses() -> None:
    f = feedback(TEST_START, ref=0.1, candidate=0.9)
    mix = mix_curve(f.reference, f.issued, 0.5)
    assert mix.mass[0] == pytest.approx(0.5)
    assert mix.beyond_24h == pytest.approx(0.5)
    assert curve_loss(mix, f.record) == pytest.approx(-math.log(0.5))
    assert curve_loss(mix, f.record) != pytest.approx(
        (curve_loss(f.reference, f.record) + curve_loss(f.issued, f.record)) / 2
    )
    assert mix_curve(f.reference, f.issued, 0) == f.reference
    assert mix_curve(f.reference, f.issued, 1) == f.issued


def test_weight_selection_alarm_calibration_and_test_have_followup_embargoes() -> None:
    assert development_origin(39) + timedelta(hours=24) <= WEIGHT_AVAILABLE
    assert development_origin(40) >= WEIGHT_AVAILABLE
    assert development_origin(59) + timedelta(hours=24) <= SETTINGS_AVAILABLE
    assert SETTINGS_AVAILABLE < TEST_START


def test_censored_loss_uses_only_survived_complete_intervals() -> None:
    f = feedback(TEST_START)
    curve = PreparationCurve(patient_id="p", mass=(0.2, 0.3, 0, 0, 0, 0), beyond_24h=0.5)
    r = f.record.model_copy(update={"event_observed": False, "followed_minutes": 45})
    assert curve_loss(curve, r) == pytest.approx(-math.log(0.8))
    assert curve_loss(curve, r.model_copy(update={"followed_minutes": 20})) == pytest.approx(0)
    assert curve_loss(curve, r.model_copy(update={"followed_minutes": 1440})) == pytest.approx(
        -math.log(0.5)
    )


@pytest.mark.parametrize("hours", [20, 24, 40])
def test_alarm_before_changed_feedback_is_not_credited_as_detection(hours: int) -> None:
    at = TEST_START + timedelta(hours=2 * CHANGE_INDEX + hours)
    alarm = summarize_alarm(at, "reorganization")
    assert alarm["false_alarm"] == (hours < 24)
    assert alarm["elapsed_since_change_hours"] == hours
    assert alarm["delay_hours"] == (hours if hours >= 24 else None)


def test_stable_alarm_is_false_and_has_no_detection_delay() -> None:
    alarm = summarize_alarm(TEST_START + timedelta(hours=80), "stable")
    assert alarm["false_alarm"]
    assert alarm["elapsed_since_change_hours"] is None and alarm["delay_hours"] is None
    assert not summarize_alarm(None, "stable")["false_alarm"]


@pytest.mark.parametrize(
    "fault", ["future_weight", "different_state", "patient_coverage", "invalid_weight"]
)
def test_mixture_rejects_incompatible_or_unavailable_inputs(
    models: BenchmarkModels, fault: str
) -> None:
    case = episode(TEST_START, 701, 0, "stable", scenarios=1)
    ref = forecast_preparation(models.reference, case.request.state())
    other = forecast_preparation(models.challenger, case.request.state())
    at = models.settings.available_at
    alpha = 0.5
    if fault == "future_weight":
        at = TEST_START + timedelta(seconds=1)
    elif fault == "different_state":
        other = other.model_copy(update={"state_fingerprint": "a" * 64})
    elif fault == "patient_coverage":
        other = other.model_copy(update={"curves": other.curves[:1]})
    else:
        alpha = 1.01
    with pytest.raises(ValueError):
        mix_forecasts(ref, other, alpha, at)


def test_future_feedback_cannot_change_state(models: BenchmarkModels) -> None:
    s = Supervisor(short_settings(models))
    f = feedback(TEST_START)
    with pytest.raises(ValueError, match="unavailable"):
        s.observe(f, TEST_START + timedelta(hours=23))
    assert s.seen == set() and s.history == []
    assert s.fallback_at is None
    assert s.alpha_at(TEST_START) == 0.75


def test_alarm_needs_minimum_matured_information_and_latches(models: BenchmarkModels) -> None:
    s = Supervisor(short_settings(models))
    for i in range(4):
        f = feedback(TEST_START + timedelta(minutes=i), name=f"patient-{i}")
        s.observe(f, f.record.label_available_at)
        assert (s.fallback_at is not None) == (i == 3)
    assert s.alpha_at(s.clock) == 0
    first = s.fallback_at
    for i in range(4, 8):
        f = feedback(TEST_START + timedelta(minutes=i), name=f"patient-{i}", ref=0.1, candidate=0.9)
        s.observe(f, f.record.label_available_at)
    assert s.fallback_at == first and s.alpha_at(s.clock) == 0


def test_repeated_patient_unknown_unit_and_clock_reversal_are_rejected(
    models: BenchmarkModels,
) -> None:
    s = Supervisor(short_settings(models))
    f = feedback(TEST_START)
    s.observe(f, f.record.label_available_at)
    with pytest.raises(ValueError, match="Duplicate"):
        s.observe(f, f.record.label_available_at)
    with pytest.raises(ValueError, match="scope"):
        s.observe(
            replace(f, record=f.record.model_copy(update={"unit_id": "unknown-unit"})), s.clock
        )
    with pytest.raises(ValueError, match="backwards"):
        s.alpha_at(TEST_START)


def test_uninformative_censoring_does_not_count_towards_alarm(models: BenchmarkModels) -> None:
    s = Supervisor(short_settings(models))
    for i in range(8):
        f = feedback(TEST_START, name=f"p-{i}")
        f = replace(
            f, record=f.record.model_copy(update={"followed_minutes": 1, "event_observed": False})
        )
        s.observe(f, f.record.label_available_at)
    assert len(s.seen) == 8 and s.history == [] and s.fallback_at is None


def test_reference_alarm_abstains_instead_of_calling_reference_safe(
    models: BenchmarkModels,
) -> None:
    settings = short_settings(models).model_copy(update={"reference_loss_limit": 1.0})
    m = replace(models, settings=settings)
    s = Supervisor(settings)
    for i in range(4):
        f = feedback(TEST_START - timedelta(days=1), name=f"p-{i}", ref=0.01, candidate=0.01)
        s.observe(f, TEST_START)
    case = episode(TEST_START, 701, 0, "stable", scenarios=2)
    _, choice = policy_plans(case.request, m, s)
    assert choice.mode == "abstain" and choice.action.kind == "no_op"
    assert s.suspended_at == TEST_START and s.fallback_at is None


def test_guard_rejects_mixture_with_wrong_weight_and_unpaired_simulation(
    models: BenchmarkModels,
) -> None:
    s = Supervisor(models.settings)
    case = episode(TEST_START, 701, 0, "stable", scenarios=2)
    plans, _ = policy_plans(case.request, models, s)
    ref, other = plans["reference"].preparation, plans["boosting"].preparation
    assert ref is not None and other is not None
    wrong_weight = 0.0 if models.settings.alpha != 0 else 1.0
    wrong = plan(
        request_with(
            case.request, mix_forecasts(ref, other, wrong_weight, models.settings.available_at)
        )
    )
    with pytest.raises(ValueError, match="weight"):
        guard_choice(plans["reference"], plans["boosting"], wrong, s)
    with pytest.raises(ValueError, match="paired"):
        guard_choice(
            plans["reference"],
            plans["boosting"].model_copy(update={"seed": 123456}),
            plans["fixed_mixture"],
            s,
        )


def test_latent_regime_and_unannounced_shock_are_absent_from_policy_input() -> None:
    index = CHANGE_INDEX + 1
    at = TEST_START + timedelta(hours=2 * index)
    stable = episode(at, 701, index, "stable", scenarios=1)
    reorganization = episode(at, 701, index, "reorganization", scenarios=1)
    shock = episode(at, 701, index, "operational_shock", scenarios=1)
    assert stable.request == reorganization.request == shock.request
    assert stable.hidden.future.events == ()
    assert shock.hidden.future.events


@pytest.mark.parametrize("ready", [30, 60, 120, 240, None])
@pytest.mark.parametrize("shock", [False, True])
def test_actual_simulation_matches_independent_oracle_with_resource_shocks(
    ready: int | None, shock: bool
) -> None:
    index = 20
    case = episode(
        TEST_START + timedelta(hours=2 * index),
        701,
        index,
        "operational_shock" if shock else "stable",
        scenarios=1,
    )
    actions, _ = enumerate_actions(case.request.state(), 32)
    assert len(actions) == 3
    assert actual_score(case, actions[0]).admitted == 0
    for action in actions[1:]:
        changed = replace(
            case,
            hidden=replace(
                case.hidden,
                completion=tuple(
                    (pid, ready if pid == action.patient_id else value)
                    for pid, value in case.hidden.completion
                ),
            ),
        )
        result = actual_score(changed, action)
        assert not result.violations
        assert result.pressure.transport_team_minutes == (45 if shock and ready == 30 else 0)
        assert result.admitted == int(ready is not None)


def test_no_feedback_before_24h_and_policies_use_identical_outcomes(
    models: BenchmarkModels,
) -> None:
    r = run_stream(models, "stable", 701, episodes=12, scenarios=2)
    assert r["matured_feedback"] == 0 and r["pending_feedback_at_end"] == 24
    assert r["shadow_alarm"]["at"] is None and r["reference_alarm"]["at"] is None
    rows = r["rows"]
    for index in range(12):
        paired = [x for x in rows if x["index"] == index]
        assert len(paired) == 4
        for a in paired:
            for b in paired:
                if a["action"] == b["action"]:
                    assert a["waiting_patient_minutes"] == b["waiting_patient_minutes"]
                    assert a["transport_team_minutes"] == b["transport_team_minutes"]


def test_future_feedback_changes_cannot_change_earlier_actions(
    models: BenchmarkModels, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hospitalos.hybrid import decision_benchmark as benchmark

    original = episode
    before = benchmark.run_stream(models, "stable", 809, episodes=4, scenarios=2)

    # Replace only hidden labels; context and realized trajectories stay fixed.
    from hospitalos.hybrid.decision_cases import DecisionEpisode, Stream

    def alter(
        at: datetime, seed: int, index: int, stream: Stream, *, scenarios: int = 32
    ) -> DecisionEpisode:
        case = original(at, seed, index, stream, scenarios=scenarios)
        return replace(
            case,
            hidden=replace(
                case.hidden,
                feedback=tuple(
                    r.model_copy(update={"event_observed": not r.event_observed})
                    for r in case.hidden.feedback
                ),
            ),
        )

    monkeypatch.setattr(benchmark, "episode", alter)
    after = benchmark.run_stream(models, "stable", 809, episodes=4, scenarios=2)
    assert before == after


def test_benchmark_experts_cover_two_units_and_strategy_is_time_gated(
    models: BenchmarkModels,
) -> None:
    assert {u for _, u in models.reference.sites_units} == set(UNITS)
    case = episode(models.settings.available_at - timedelta(hours=1), 701, 0, "stable", scenarios=1)
    with pytest.raises(ValueError, match="not available"):
        policy_plans(case.request, models, Supervisor(models.settings))
