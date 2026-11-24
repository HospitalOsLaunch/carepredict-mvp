"""Combinations of immediate actions (« action combinée »): evaluated together, step by step."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "web" / "dev"))

import demo_unit  # type: ignore[import-not-found]  # noqa: E402

from hospitalos.hybrid.models import Action, bundle_errors  # noqa: E402
from hospitalos.hybrid.planning import evaluate, plan  # noqa: E402
from hospitalos.hybrid.simulation import simulate  # noqa: E402

T412 = Action(kind="request_transport", bed_id="L02", patient_id="P-0412")
T388 = Action(kind="request_transport", bed_id="L06", patient_id="P-0388")


def test_one_action_and_a_one_step_bundle_simulate_identically() -> None:
    request = demo_unit.nominal()
    state = request.state()
    kwargs = {"seed": request.seed, "scenario": 3, "horizon_minutes": request.horizon_minutes}
    alone = simulate(state, T412, request.assumptions, **kwargs)
    bundled = simulate(state, (T412,), request.assumptions, **kwargs)
    assert alone == bundled


def test_conflicting_steps_are_rejected() -> None:
    state = demo_unit.peak().state()
    r1 = Action(kind="reserve_bed", bed_id="L08", patient_id="U-1043")
    r2 = Action(kind="reserve_bed", bed_id="L08", patient_id="U-1047")
    assert bundle_errors(state, (T412, T388)) == ()
    assert bundle_errors(state, (r1, r2)) == ("bundle_bed_reserved_twice",)
    assert bundle_errors(state, (T412, T412)) == ("bundle_duplicate_action",)
    with pytest.raises(ValueError, match="bundle_bed_reserved_twice"):
        simulate(state, (r1, r2), demo_unit.ASSUMPTIONS, seed=7, scenario=0)


def test_default_requests_keep_their_one_action_plan_and_id() -> None:
    request = demo_unit.nominal()
    assert request.max_bundle == 1
    single = plan(request)
    assert single.bundle == () and single.bundle_evaluation is None
    # The id ignores max_bundle at its default: historical plans keep their identity.
    assert plan(request).plan_id == single.plan_id
    assert plan(request.model_copy(update={"max_bundle": 3})).plan_id != single.plan_id


def test_two_ready_departures_are_requested_together_when_it_matters() -> None:
    request = demo_unit.peak().model_copy(update={"max_bundle": 3})
    proposal = plan(request)
    assert proposal.decision == "recommend"
    assert proposal.bundle == (T412, T388)
    assert proposal.selected == proposal.bundle[0]
    assert len(proposal.bundle_marginal_minutes) == 2
    assert all(m > 0 for m in proposal.bundle_marginal_minutes)
    best_single = min(c.objective for c in proposal.candidates)
    joint = proposal.bundle_evaluation
    assert joint is not None and joint.objective < best_single
    # The joint evaluation is reproducible on the same paired scenarios.
    again = evaluate(request.state(), proposal.bundle, request).candidate
    assert again.objective == pytest.approx(joint.objective)
    # Marginals (mean waiting) add up: doing nothing → step 1 → step 1 + step 2.
    baseline = next(c for c in proposal.candidates if c.action.kind == "no_op")
    assert baseline.mean_waiting_patient_minutes - sum(
        proposal.bundle_marginal_minutes
    ) == pytest.approx(joint.mean_waiting_patient_minutes)


def test_no_combination_without_a_material_joint_gain() -> None:
    proposal = plan(demo_unit.nominal().model_copy(update={"max_bundle": 3}))
    assert proposal.decision == "recommend"
    assert proposal.bundle == ()
