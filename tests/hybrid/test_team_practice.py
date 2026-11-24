"""Gain against an explicit team practice (review of PR #50, 24 Nov 2026).

The historical comparison is « nobody makes the gesture within the window »: the gain then
grows by one patient-hour per hour of window and per blocked patient. The team-practice
counterfactual replays the same gestures made by the team after a delay.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hospitalos.hybrid.models import Action
from hospitalos.hybrid.planning import PlanRequest, evaluate, plan

FIXTURES = Path(__file__).resolve().parents[2] / "web/src/fixtures"


def nominal(*, planned: bool = False) -> tuple[PlanRequest, Action, dict[str, Any]]:
    """The published request asks for 7 days; the plan falls back to the qualified 24 hours."""
    data = json.loads((FIXTURES / "scenario-nominal.json").read_text())
    published = data["plan"]
    request = PlanRequest.model_validate(data["request"])
    if not planned:
        request = request.model_copy(update={"horizon_minutes": published["horizon_minutes"]})
    return request, Action.model_validate(published["selected"]), published


def test_no_delay_is_acting_now() -> None:
    request, selected, _ = nominal()
    state = request.state()
    now = evaluate(state, (selected,), request).candidate
    zero = evaluate(state, (selected,), request, late={selected.key: 0}).candidate
    assert zero == now


# Independent replay published with the review (transport.json): same patient, same 32 draws,
# 24-hour window, the team's request after the delay.
REVIEW = {
    (30, False): 494.53125,
    (30, True): 478.59375,
    (60, False): 511.875,
    (60, True): 480.0,
    (120, False): 565.3125,
    (120, True): 497.34375,
}


@pytest.mark.parametrize(("delay", "started"), sorted(REVIEW))
def test_reproduces_the_review_replay(delay: int, started: bool) -> None:
    request, selected, _ = nominal()
    state = request.state()
    late = evaluate(
        state, (selected,), request, late={selected.key: delay}, preparation_started=started
    ).candidate
    assert not late.violations
    assert late.mean_waiting_patient_minutes == pytest.approx(REVIEW[delay, started])


def test_never_grows_with_the_window_but_the_practice_gain_does_not() -> None:
    request, selected, published = nominal()
    windows = {w["minutes"]: w["saved_wait"] for w in published["windows"]}
    # Against « never », 12 more hours add exactly one blocked patient-hour per hour.
    assert windows[1440] - windows[720] == pytest.approx(720)
    state = request.state()
    gains = []
    for minutes in (720, 1440):
        clipped = request.model_copy(update={"horizon_minutes": minutes})
        now = evaluate(state, (selected,), clipped).candidate.mean_waiting_patient_minutes
        team = evaluate(
            state, (selected,), clipped, late={selected.key: 60}, preparation_started=True
        ).candidate.mean_waiting_patient_minutes
        gains.append(team - now)
    assert gains[1] - gains[0] < 1


def test_plan_states_the_practice_on_a_bounded_window() -> None:
    request, selected, published = nominal(planned=True)
    result = plan(request)
    assert result.plan_id == published["plan_id"]
    practice = result.team_practice
    assert practice is not None and practice.supported
    assert practice.window_minutes == 720
    window = next(w for w in result.windows if w.minutes == 720)
    assert practice.never_saved_wait == pytest.approx(window.saved_wait)
    assert len(practice.cases) == 6
    assert all(0 <= c.saved_wait < practice.never_saved_wait for c in practice.cases)
    # Preparation already under way and a team acting within the hour: cleaning L11 does as
    # well or better than the transport (near tie), as in the review.
    leaders = {(c.delay_minutes, c.preparation): c.leader for c in practice.cases}
    assert leaders[60, "already_started"].key == "prioritize_cleaning:L11:"
    assert leaders[60, "after_request"] == selected
    assert sum(practice.step_saved_wait) == pytest.approx(practice.never_saved_wait)


def test_retries_when_transport_is_cut() -> None:
    data = json.loads((FIXTURES / "scenario-perturbations.json").read_text())
    request = PlanRequest.model_validate(data["request"])
    result = plan(request)
    assert result.team_practice is not None
    for case in result.team_practice.cases:
        # The team's late request is made once transport is back: never worse than « never ».
        assert case.saved_wait < result.team_practice.never_saved_wait


def test_reinforcement_has_no_delay_replay() -> None:
    data = json.loads((FIXTURES / "scenario-garde.json").read_text())
    result = plan(PlanRequest.model_validate(data["request"]))
    assert result.team_practice is not None
    assert not result.team_practice.supported and not result.team_practice.cases
    state = PlanRequest.model_validate(data["request"]).state()
    with pytest.raises(ValueError, match="can be delayed"):
        evaluate(
            state,
            result.bundle,
            PlanRequest.model_validate(data["request"]),
            late={a.key: 30 for a in result.bundle},
        )
