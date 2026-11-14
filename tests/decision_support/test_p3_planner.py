"""P3 — automatic planner, abstention, bounded search, review, manual mode on the same engine."""

from __future__ import annotations

import json
import re
from datetime import timedelta

import pytest

from hospitalos.decision_support.contracts import (
    LockedDischarge,
    LockedReinforcement,
    ScenarioLocks,
)
from hospitalos.decision_support.export import SeedReuseError, evaluate_out_of_sample
from hospitalos.decision_support.planner import (
    IdempotencyConflict,
    ReviewStore,
    Settings,
    _config,
    recommend,
    review,
    simulate,
)
from hospitalos.decision_support.snapshot import snapshot_from_fixture

from .conftest import FX, locks_of, snapshot_with


def _ev(rec, pid):
    return next(e for e in rec.bundle.evaluations if e.plan.plan_id == pid)


def test_t15_auto_mode_without_user_scenario(auto, settings):
    assert auto.mode == "auto" and auto.locks is None
    assert auto.status == "RECOMMENDATION_READY"
    primary, baseline = _ev(auto, auto.primary_plan_id), _ev(auto, auto.baseline_plan_id)
    assert baseline.plan.is_baseline and not primary.plan.is_baseline
    tolerance = settings.objective["tiers"][1]["equivalence_tolerance"]
    assert (
        primary.metrics.uncovered_care_minutes < baseline.metrics.uncovered_care_minutes - tolerance
    )
    assert auto.bundle.search.complete and auto.bundle.search.evaluated <= 16
    assert auto.reasons and auto.conditions and auto.uncertainties
    assert (auto.scientific_status, auto.clinical_validation, auto.g2) == (
        "PROTOTYPE_UNVALIDATED",
        False,
        "NO-GO",
    )
    for e in auto.bundle.evaluations:  # every plan respects the auto bounds
        assert sum(a.type == "coordinate_discharge" for a in e.plan.actions) <= 2
        assert sum(a.type == "reinforcement" for a in e.plan.actions) <= 2


def test_selection_follows_objective_order(auto, settings):
    """The chosen plan is the lexicographic optimum of the evaluated set (recomputed here)."""
    tol = settings.objective["tiers"][1]["equivalence_tolerance"]
    evs = [e for e in auto.bundle.evaluations if e.admissible]
    best = min(e.metrics.uncovered_care_minutes for e in evs)
    eligible = [e for e in evs if e.metrics.uncovered_care_minutes <= best + tol]
    expected = min(
        eligible,
        key=lambda e: (
            e.metrics.reinforcement_hours,
            e.metrics.interventions,
            e.metrics.uncovered_care_minutes,
        ),
    )
    assert auto.primary_plan_id == expected.plan.plan_id
    if auto.alternative_plan_id:
        alt, prim = _ev(auto, auto.alternative_plan_id), _ev(auto, auto.primary_plan_id)
        assert {a.action_id for a in alt.plan.actions} != {a.action_id for a in prim.plan.actions}


def test_t16_no_action_preferred(settings):
    r = recommend(snapshot_from_fixture(FX / "no_action.json"), settings)
    assert r.status == "NO_ACTION_PREFERRED"
    assert r.primary_plan_id == r.baseline_plan_id
    assert _ev(r, r.primary_plan_id).plan.actions == ()
    assert len(r.bundle.evaluations) > 1  # actions were searched, none forced


def test_t17_insufficient_or_contradictory_data(settings):
    r = recommend(snapshot_from_fixture(FX / "insufficient_data.json"), settings)
    assert r.status == "INSUFFICIENT_DATA" and r.bundle is None and not r.approvable
    assert any(d.startswith("roster_unknown:IDE") for d in r.diagnostics)
    twice = snapshot_with(
        "nominal_auto.json",
        [
            {
                "obs_id": "o-stay-S04-moved",
                "kind": "stay",
                "subject": "S04",
                "event_time": "2026-11-16T18:00:00+00:00",
                "available_at": "2026-11-16T18:05:00+00:00",
                "source": "synthetic_feed",
                "value": {"bed_id": "L03", "present": True},
            }
        ],
    )
    r = recommend(twice, settings)
    assert r.status == "INSUFFICIENT_DATA"
    assert any(d.startswith("bed_claimed_twice:L03") for d in r.diagnostics)


def test_t24_search_bound_reported_without_optimum_claim(nominal, settings):
    r = recommend(nominal, settings, max_plans=5)
    assert r.bundle.search.complete is False
    assert (r.bundle.search.evaluated, r.bundle.search.enumerated) == (5, 12)
    assert any("no optimum claimed" in x for x in r.reasons)
    text = json.dumps(r.model_dump(mode="json")["reasons"])
    assert not re.search(r"\boptimal\b|\bglobal optimum\b", text)


def test_t25_peak_and_time_above_threshold_visible(auto, settings):
    threshold = settings.score["threshold"]
    found = False
    for e in auto.bundle.evaluations:
        scores = [p.pressure_score for p in e.trajectory]
        assert e.metrics.peak_pressure == max(scores)
        assert e.metrics.hours_above_threshold is not None
        if scores[-1] < threshold <= max(scores):
            found = True
            assert e.metrics.peak_pressure_hour < len(scores) - 1
    assert found  # a plan low at T but with an earlier peak is reported as such


def test_t26_unconfigured_score_is_not_invented(nominal, settings):
    s = Settings(settings.profile, settings.objective, None)
    r = recommend(nominal, s)
    assert r.bundle.score["score_status"] == "UNCONFIGURED"
    for e in r.bundle.evaluations:
        assert e.metrics.peak_pressure is None
        assert all(p.pressure_score is None for p in e.trajectory)
    assert r.primary_plan_id is not None  # decisions do not depend on the summary score


def test_t23_selection_and_evaluation_seeds_separated(nominal, auto, settings):
    assert auto.bundle.seed_role == "selection_in_sample"
    out = evaluate_out_of_sample(nominal, auto, settings)
    assert "not_real_world" in out["label"]
    assert not set(out["selection_seeds"]) & set(out["evaluation_seeds"])
    reuse = {**settings.profile, "forecast": {"selection_seeds": [101], "evaluation_seeds": [101]}}
    with pytest.raises(SeedReuseError):
        evaluate_out_of_sample(nominal, auto, Settings(reuse, settings.objective, settings.score))


def test_t10_t27_review_idempotent_and_invalidated_by_new_information(nominal, auto):
    store = ReviewStore()
    now = auto.created_at + timedelta(minutes=5)
    first = review(auto, "approve", nominal, now, "req-1", store)
    second = review(auto, "approve", nominal, now, "req-1", store)
    assert first.outcome == "APPROVED_IN_DEMO" and not first.replayed
    # same key + same content: historical receipt unchanged, current validity re-evaluated
    assert second.replayed and second.current_validity == "still_valid"
    assert second.model_dump(exclude={"replayed", "current_validity"}) == first.model_dump(
        exclude={"replayed", "current_validity"}
    )
    with pytest.raises(IdempotencyConflict):  # same key + other content: explicit conflict
        review(auto, "reject", nominal, now, "req-1", store)
    assert first.external_command_sent is False
    assert first.lifecycle["execution"] == "not_executed_no_external_system"
    assert len(store.ledger.by_key) == len(first.reservations)
    expired = review(auto, "approve", nominal, auto.valid_until, "req-2", ReviewStore())
    assert expired.outcome == "INVALIDATED" and expired.recompute_required
    revoked = snapshot_with(
        "nominal_auto.json",
        [
            {
                "obs_id": "o-auth-S01-revoked",
                "kind": "medical_authorization",
                "subject": "S01",
                "event_time": "2026-11-16T18:55:00+00:00",
                "available_at": "2026-11-16T18:58:00+00:00",
                "source": "synthetic_feed",
                "value": {"status": "revoked", "by_role": "medecin"},
            }
        ],
    )
    result = review(auto, "approve", revoked, now, "req-3", ReviewStore())
    assert result.outcome == "INVALIDATED" and result.recompute_required
    assert "S01:medical_authorization_revoked" in result.reasons  # T05 at re-examination
    fresh = recommend(revoked)  # explicit recomputation, new identity
    assert fresh.recommendation_id != auto.recommendation_id
    assert all("S01" not in {a.target for a in e.plan.actions} for e in fresh.bundle.evaluations)


def test_t09_concurrent_approvals_do_not_double_book(nominal, auto):
    store = ReviewStore()
    now = auto.created_at + timedelta(minutes=1)
    review(auto, "approve", nominal, now, "cadre-A", store)
    clone = auto.model_copy(update={"recommendation_id": "reco-other"})
    other = review(clone, "approve", nominal, now, "cadre-B", store)
    assert other.outcome == "APPROVED_IN_DEMO"  # same idempotency keys per action: deduplicated
    assert all(r.endswith("duplicate_ignored") for r in other.reservations)


def test_t18_locked_x1_x2_identical_in_all_complements(manual):
    assert manual.mode == "manual" and manual.status in {
        "RECOMMENDATION_READY",
        "NO_ACTION_PREFERRED",
    }
    locked = _ev(manual, manual.locked_plan_id)
    lock_ids = [a.action_id for a in locked.plan.actions]
    assert len(lock_ids) == 2
    starts = {a.target: a.window_start.isoformat() for a in locked.plan.actions}
    assert starts == {"S01": "2026-11-17T09:00:00+00:00", "S02": "2026-11-17T15:00:00+00:00"}
    for e in manual.bundle.evaluations:
        if e.plan.is_baseline:
            continue
        kept = [a for a in e.plan.actions if a.origin == "manual_lock"]
        assert [a.model_dump() for a in kept] == [a.model_dump() for a in locked.plan.actions]
        assert not {a.target for a in e.plan.actions if a.origin == "auto"} & {"S01", "S02"}


def test_t19_extension_t_changes_only_after_departure_hour(nominal, settings):
    base = locks_of("scenario_x1x2.json").model_dump(mode="json")
    trajectories, totals = {}, {}
    for t in range(0, 7):
        locks = json.loads(json.dumps(base))
        locks["locks"][1]["extension_hours"] = t
        locks["search_complements"] = False
        r = simulate(nominal, ScenarioLocks.model_validate(locks), settings)
        e = _ev(r, r.locked_plan_id)
        trajectories[t] = e.trajectory
        totals[t] = e.metrics.uncovered_in_unit_minutes
    departure_index = {t: 16 + t for t in trajectories}  # 12:00 Paris = index 16 (as_of 20:00)
    for t in range(0, 6):
        a, b = trajectories[t], trajectories[t + 1]
        diff = [i for i, (p, q) in enumerate(zip(a, b, strict=True)) if p != q]
        assert diff and min(diff) >= departure_index[t]  # nothing changes before X2 leaves
        assert (
            a[departure_index[t]].demand_minutes["IDE"]
            != b[departure_index[t]].demand_minutes["IDE"]
        )
    assert len(set(totals.values())) > 1  # a threshold is crossed somewhere in 0..6
    # no monotonicity is imposed: totals may stay equal or move either way between t values


def test_t20_same_plan_auto_and_manual_same_forecast(nominal, auto, settings):
    primary = _ev(auto, auto.primary_plan_id)
    config = _config(settings, nominal.as_of, 24)
    as_manual = primary.plan.model_copy(update={"mode": "manual"})
    e = settings.backend.forecast(nominal, as_manual, config)
    assert e.metrics == primary.metrics
    assert e.trajectory == primary.trajectory
    locks = ScenarioLocks(
        locks=tuple(
            LockedDischarge(stay_id=a.target, at=a.window_start, basis="validated_instruction")
            if a.type == "coordinate_discharge"
            else LockedReinforcement(option_id=a.target, include=True)
            for a in primary.plan.actions
        ),
        search_complements=False,
    )
    r = simulate(nominal, locks, settings)
    assert _ev(r, r.locked_plan_id).metrics.model_dump(
        exclude={"interventions"}
    ) == primary.metrics.model_dump(exclude={"interventions"})


def test_t06_hypothesis_is_simulated_but_never_approvable(nominal, settings):
    r = simulate(nominal, locks_of("scenario_hypothesis.json"), settings)
    assert r.status == "HYPOTHETICAL_ONLY" and r.approvable is False
    locked = _ev(r, r.locked_plan_id)
    assert locked.admissible and locked.plan.actions[0].basis == "hypothesis_only"
    result = review(r, "approve", nominal, r.created_at, "hyp-1", ReviewStore())
    assert result.outcome == "REFUSED" and "not_approvable:HYPOTHETICAL_ONLY" in result.reasons
    downgraded = simulate(
        nominal,
        ScenarioLocks(
            locks=(
                LockedDischarge(
                    stay_id="S04",
                    at=nominal.as_of + timedelta(hours=18),
                    basis="validated_instruction",
                ),
            )
        ),
        settings,
    )
    assert downgraded.status == "HYPOTHETICAL_ONLY"
    assert any("treated as hypothesis_only" in d for d in downgraded.diagnostics)


def test_impossible_and_contradictory_scenarios(nominal, settings):
    impossible = simulate(nominal, locks_of("scenario_impossible.json"), settings)
    assert impossible.status == "INFEASIBLE" and not impossible.approvable
    assert any(d.startswith("locked_transport_unavailable:S01") for d in impossible.diagnostics)
    contradictory = simulate(nominal, locks_of("scenario_contradictory.json"), settings)
    assert contradictory.status == "INFEASIBLE"
    assert contradictory.diagnostics[0].startswith("contradictory_locks:S02")
