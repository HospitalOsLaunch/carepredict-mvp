"""Open-cohort mechanics: independent future ledger, shocks, exposure and no foresight."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from pydantic import ValidationError

from hospitalos.hybrid.demo import future_request, pathway_request
from hospitalos.hybrid.models import (
    Action,
    Bed,
    Discharge,
    Fact,
    FactEvent,
    Patient,
    ResourcePool,
    Unit,
)
from hospitalos.hybrid.planning import PlanRequest, enumerate_actions, plan
from hospitalos.hybrid.scenarios import (
    ArrivalBatch,
    BedAdmissions,
    Change,
    FutureAssumptions,
    FutureTape,
    ResourceChange,
    sample_future,
)
from hospitalos.hybrid.scoring import Score, score
from hospitalos.hybrid.simulation import Assumptions, Trajectory, Transition, simulate


def fixture(*facts: Fact) -> PlanRequest:
    base = pathway_request()
    return base.model_copy(
        update={
            "events": tuple(
                FactEvent(
                    hospital_id=base.hospital_id,
                    event_id=f"fixture:{f.kind}:{f.id}",
                    source="fixture",
                    event_time=base.at,
                    available_at=base.at,
                    fact=f,
                )
                for f in facts
            ),
            "expected_entities": tuple(f"{f.kind}:{f.id}" for f in facts),
            "assumptions": Assumptions(
                cleaning_minutes=(60,),
                departure_minutes=(30,),
                transport_minutes=(45,),
                transport_return_minutes=(30,),
                load_multipliers=(1,),
            ),
        }
    )


def futures(
    request: PlanRequest,
    *,
    arrivals: tuple[ArrivalBatch, ...] = (),
    changes: tuple[Change, ...] = (),
) -> PlanRequest:
    return request.model_copy(
        update={
            "future": FutureAssumptions(declared_at=request.at, arrivals=arrivals, changes=changes)
        }
    )


def batch(minute: int, count: int = 1) -> ArrivalBatch:
    return ArrivalBatch(
        id="wave", minute_options=(minute,), count_options=(count,), compatible_units=("medicine",)
    )


def execute(
    request: PlanRequest, action: Action | None = None, scenario: int = 0
) -> tuple[Trajectory, Score, FutureTape]:
    state = request.state()
    tape = sample_future(state, request.future, request.seed, scenario)
    trace = simulate(
        state,
        action or Action(kind="no_op"),
        request.assumptions,
        seed=request.seed,
        scenario=scenario,
        horizon_minutes=request.horizon_minutes,
        future=tape,
    )
    return trace, score(state, trace, expected_future=tape), tape


def empty_unit(state: str = "clean", cleaners: int = 1) -> PlanRequest:
    return fixture(
        Unit(id="medicine", staffed_beds=2, cleaning_teams=cleaners),
        Bed.model_validate({"id": "bed", "unit_id": "medicine", "state": state}),
    )


def test_arrival_waiting_cost_starts_at_arrival_not_at_origin() -> None:
    request = futures(empty_unit("dirty"), arrivals=(batch(30),))
    trace, result, _ = execute(request)
    assert [(e.kind, e.minute) for e in trace.events] == [
        ("clean_start", 0),
        ("arrival", 30),
        ("clean_end", 60),
        ("admit", 60),
    ]
    assert result.waiting_patient_minutes == 30
    assert (result.arrived, result.admitted, result.waiting_at_end) == (1, 1, 0)
    assert result.violations == ()


def test_arrival_at_completion_time_is_seen_before_allocation() -> None:
    request = futures(empty_unit("dirty"), arrivals=(batch(60),))
    trace, result, _ = execute(request)
    assert [e.kind for e in trace.events if e.minute == 60] == ["arrival", "clean_end", "admit"]
    assert result.waiting_patient_minutes == 0
    assert result.violations == ()


def test_arrivals_after_horizon_and_zero_counts_do_not_enter_cohort() -> None:
    for arrival in (batch(200), batch(20, count=0)):
        request = futures(empty_unit(), arrivals=(arrival,)).model_copy(
            update={"horizon_minutes": 100}
        )
        trace, result, _ = execute(request)
        assert not any(e.kind == "arrival" for e in trace.events)
        assert result.arrived == 0
        assert result.violations == ()


def test_closure_at_arrival_time_blocks_admission_until_reopening() -> None:
    request = futures(
        empty_unit(),
        arrivals=(batch(30),),
        changes=(
            BedAdmissions(id="close", minute=30, bed_id="bed", admissions_open=False),
            BedAdmissions(id="open", minute=90, bed_id="bed", admissions_open=True),
        ),
    )
    trace, result, _ = execute(request)
    assert next(e.minute for e in trace.events if e.kind == "admit") == 90
    assert result.waiting_patient_minutes == 60
    assert result.violations == ()


def test_initially_closed_bed_requires_cleaning_on_reopening() -> None:
    request = futures(
        empty_unit("closed"),
        arrivals=(batch(20),),
        changes=(BedAdmissions(id="open", minute=10, bed_id="bed", admissions_open=True),),
    )
    trace, result, _ = execute(request)
    assert [
        (e.kind, e.minute) for e in trace.events if e.kind in {"clean_start", "clean_end", "admit"}
    ] == [("clean_start", 10), ("clean_end", 70), ("admit", 70)]
    assert result.waiting_patient_minutes == 50
    assert result.violations == ()


def test_occupied_bed_closure_preserves_patient_and_records_staff_shortfall() -> None:
    at = pathway_request().at
    request = fixture(
        Unit(id="medicine", staffed_beds=1, cleaning_teams=1),
        Bed(id="bed", unit_id="medicine", state="occupied", occupant="resident"),
        Patient(
            id="resident",
            status="admitted",
            bed_id="bed",
            compatible_units=("medicine",),
            waiting_since=at,
        ),
    )
    request = futures(
        request,
        arrivals=(batch(60),),
        changes=(
            BedAdmissions(id="close", minute=40, bed_id="bed", admissions_open=False),
            ResourceChange(
                id="staff-drop",
                minute=50,
                resource="staffed_beds",
                target_id="medicine",
                capacity=0,
            ),
        ),
    ).model_copy(update={"horizon_minutes": 100})
    trace, result, _ = execute(request)
    assert not any(e.kind in {"depart", "admit"} for e in trace.events)
    assert result.pressure.staffed_patient_minutes == 50
    assert result.waiting_at_end == 1
    assert result.violations == ()


def test_cleaning_drop_finishes_existing_work_and_blocks_new_start() -> None:
    request = fixture(
        Unit(id="medicine", staffed_beds=2, cleaning_teams=1),
        Bed(id="a", unit_id="medicine", state="dirty"),
        Bed(id="b", unit_id="medicine", state="dirty"),
    )
    request = futures(
        request,
        changes=(
            ResourceChange(
                id="off", minute=20, resource="cleaning_teams", target_id="medicine", capacity=0
            ),
            ResourceChange(
                id="on", minute=100, resource="cleaning_teams", target_id="medicine", capacity=1
            ),
        ),
    )
    trace, result, _ = execute(request)
    assert [(e.bed_id, e.minute) for e in trace.events if e.kind == "clean_start"] == [
        ("a", 0),
        ("b", 100),
    ]
    assert result.pressure.cleaning_team_minutes == 40
    assert result.violations == ()


def test_confirmed_transport_waits_for_capacity_that_was_zero_at_D() -> None:
    request = pathway_request()
    facts = tuple(
        e.fact.model_copy(update={"transport_requested": True})
        if isinstance(e.fact, Discharge)
        else e.fact.model_copy(update={"available": 0})
        if isinstance(e.fact, ResourcePool) and e.fact.resource == "transport"
        else e.fact
        for e in request.events
    )
    request = futures(
        fixture(*facts),
        changes=(
            ResourceChange(
                id="available", minute=100, resource="transport", target_id="transport", capacity=1
            ),
        ),
    )
    trace, result, _ = execute(request)
    assert next(e.minute for e in trace.events if e.kind == "transport_start") == 100
    assert result.violations == ()


def test_future_capacity_does_not_authorize_a_request_at_D() -> None:
    request = pathway_request()
    facts = tuple(
        e.fact.model_copy(update={"available": 0})
        if isinstance(e.fact, ResourcePool) and e.fact.resource == "transport"
        else e.fact
        for e in request.events
    )
    request = futures(
        fixture(*facts),
        changes=(
            ResourceChange(
                id="available", minute=100, resource="transport", target_id="transport", capacity=1
            ),
        ),
    )
    assert not any(a.kind == "request_transport" for a in enumerate_actions(request.state(), 32)[0])
    assert not any(e.kind == "depart" for e in execute(request)[0].events)
    forged = Trajectory(
        360, (Transition(0, "request_transport", "outgoing", "bed-1", "transport"),)
    )
    assert "invalid_transport_request" in score(request.state(), forged).violations


def test_staffed_capacity_recovery_resumes_waiting_queue() -> None:
    request = fixture(
        Unit(id="medicine", staffed_beds=0, cleaning_teams=1),
        Bed(id="bed", unit_id="medicine", state="clean"),
    )
    request = futures(
        request,
        arrivals=(batch(20),),
        changes=(
            ResourceChange(
                id="staff", minute=80, resource="staffed_beds", target_id="medicine", capacity=1
            ),
        ),
    )
    trace, result, _ = execute(request)
    assert next(e.minute for e in trace.events if e.kind == "admit") == 80
    assert result.waiting_patient_minutes == 60
    assert result.violations == ()


def test_close_cancels_observed_unusable_reservation_without_losing_patient() -> None:
    at = pathway_request().at
    request = fixture(
        Unit(id="medicine", staffed_beds=0, cleaning_teams=1),
        Bed(id="a", unit_id="medicine", state="clean", reserved_for="waiting"),
        Bed(id="b", unit_id="medicine", state="clean"),
        Patient(id="waiting", status="waiting", compatible_units=("medicine",), waiting_since=at),
    )
    request = futures(
        request,
        changes=(
            BedAdmissions(id="close", minute=10, bed_id="a", admissions_open=False),
            ResourceChange(
                id="staff", minute=20, resource="staffed_beds", target_id="medicine", capacity=1
            ),
        ),
    )
    trace, result, _ = execute(request)
    assert [
        (e.kind, e.bed_id) for e in trace.events if e.kind in {"reservation_cancel", "admit"}
    ] == [("reservation_cancel", "a"), ("admit", "b")]
    assert result.cancelled_reservations == 1
    assert result.violations == ()


def test_aval_capacity_update_does_not_recreate_consumed_place() -> None:
    request = pathway_request()
    facts = [e.fact for e in request.events]
    facts = [
        f.model_copy(update={"transport_requested": True}) if isinstance(f, Discharge) else f
        for f in facts
    ]
    facts += [
        Bed(id="bed-2", unit_id="medicine", state="occupied", occupant="outgoing-2"),
        Patient(
            id="outgoing-2",
            status="admitted",
            bed_id="bed-2",
            compatible_units=("medicine",),
            waiting_since=request.at,
            medically_cleared=True,
            downstream_confirmed=True,
        ),
        request.state()
        .discharges[0]
        .model_copy(update={"id": "outgoing-2", "transport_requested": True}),
    ]
    request = futures(
        fixture(*facts),
        changes=(
            ResourceChange(id="off", minute=45, resource="downstream", target_id="smr", capacity=0),
            ResourceChange(
                id="same-one-place", minute=100, resource="downstream", target_id="smr", capacity=1
            ),
        ),
    )
    trace, result, _ = execute(request)
    assert len([e for e in trace.events if e.kind == "depart"]) == 1
    assert result.pressure.downstream_place_minutes == 55
    assert result.violations == ()


def test_pressure_regression_excludes_a_faster_but_more_exposed_action() -> None:
    request = futures(
        pathway_request(),
        changes=(
            ResourceChange(
                id="transport-off",
                minute=45,
                resource="transport",
                target_id="transport",
                capacity=0,
            ),
            ResourceChange(
                id="transport-on",
                minute=120,
                resource="transport",
                target_id="transport",
                capacity=1,
            ),
        ),
    )
    result = plan(request)
    action = next(c for c in result.candidates if c.action.kind == "request_transport")
    baseline = result.candidates[0]
    assert action.mean_waiting_patient_minutes < baseline.mean_waiting_patient_minutes
    assert action.mean_transport_pressure == 60
    assert action.pressure_regression_scenarios == request.scenarios
    assert result.selected.kind == "no_op"
    assert result.reasons == ("simulated_improvement_rejected_due_to_resource_pressure",)


def test_pairing_uses_same_external_events_and_never_mutates_observed_state() -> None:
    request = future_request()
    before = request.state()
    action = Action(kind="request_transport", patient_id="outgoing", bed_id="bed-1")
    for scenario in range(12):
        reference, _, tape0 = execute(request, scenario=scenario)
        selected, result, tape1 = execute(request, action, scenario=scenario)
        assert tape0 == tape1
        assert [e for e in reference.events if e.external_id] == [
            e for e in selected.events if e.external_id
        ]
        assert result.violations == ()
    assert request.state() == before


def test_future_arrivals_cannot_be_targets_of_immediate_actions() -> None:
    request = futures(empty_unit("dirty"), arrivals=(batch(30),))
    result = plan(request)
    assert all(c.action.patient_id is None for c in result.candidates)
    assert result.candidates[0].max_arrived == 1


def test_future_observation_does_not_change_plan_or_fingerprint() -> None:
    request = future_request()
    late = FactEvent(
        hospital_id=request.hospital_id,
        event_id="late",
        source="observation",
        event_time=request.at + timedelta(minutes=10),
        available_at=request.at + timedelta(minutes=10),
        fact=Unit(id="medicine", staffed_beds=0, cleaning_teams=0),
    )
    changed = request.model_copy(update={"events": request.events + (late,)})
    assert plan(changed) == plan(request)


@pytest.mark.parametrize("mode", ["missing", "duplicate", "wrong_identity", "wrong_time"])
def test_scorer_audits_external_ledger_not_just_generated_log(mode: str) -> None:
    request = futures(empty_unit(), arrivals=(batch(30),))
    trace, _, tape = execute(request)
    event = next(e for e in trace.events if e.kind == "arrival")
    if mode == "missing":
        events = tuple(e for e in trace.events if e.kind != "arrival")
    elif mode == "duplicate":
        events = (event,) + trace.events
    elif mode == "wrong_identity":
        events = tuple(replace(e, patient_id="invented") if e == event else e for e in trace.events)
    else:
        events = tuple(replace(e, minute=29) if e == event else e for e in trace.events)
    assert score(request.state(), replace(trace, events=events), expected_future=tape).violations
    assert score(
        request.state(), trace
    ).violations  # no expected ledger: no invented arrivals accepted


def test_scorer_rejects_admission_before_same_time_closure() -> None:
    request = futures(
        empty_unit(),
        arrivals=(batch(30),),
        changes=(BedAdmissions(id="close", minute=30, bed_id="bed", admissions_open=False),),
    )
    trace, _, tape = execute(request)
    arrival = next(e for e in trace.events if e.kind == "arrival")
    closure = next(e for e in trace.events if e.kind == "bed_admissions")
    forged = Trajectory(360, (arrival, Transition(30, "admit", arrival.patient_id, "bed"), closure))
    assert (
        "external_event_missing_or_late"
        in score(request.state(), forged, expected_future=tape).violations
    )


def test_scorer_rejects_starting_cleaning_during_shutdown() -> None:
    request = futures(
        empty_unit("dirty", cleaners=0),
        changes=(
            ResourceChange(
                id="off", minute=20, resource="cleaning_teams", target_id="medicine", capacity=0
            ),
        ),
    )
    trace, _, tape = execute(request)
    forged = replace(trace, events=trace.events + (Transition(21, "clean_start", None, "bed"),))
    assert "cleaner_capacity" in score(request.state(), forged, expected_future=tape).violations


def test_future_contract_rejects_ambiguity_and_excessive_budget() -> None:
    at = pathway_request().at
    same = ResourceChange(
        id="one", minute=30, resource="staffed_beds", target_id="medicine", capacity=1
    )
    with pytest.raises(ValidationError):
        FutureAssumptions(
            declared_at=at, changes=(same, same.model_copy(update={"id": "two", "capacity": 0}))
        )
    with pytest.raises(ValidationError):
        FutureAssumptions(
            declared_at=at,
            arrivals=tuple(batch(30, 20).model_copy(update={"id": f"b-{i}"}) for i in range(11)),
        )
    with pytest.raises(ValidationError):
        ArrivalBatch(
            id="bad", minute_options=(0,), count_options=(1,), compatible_units=("medicine",)
        )


def test_sampler_is_stable_under_declaration_order_and_scenario_calls() -> None:
    request = future_request()
    assert request.future is not None
    original = sample_future(request.state(), request.future, 7, 4)
    reordered = request.future.model_copy(
        update={"changes": tuple(reversed(request.future.changes))}
    )
    for scenario in range(20):
        sample_future(request.state(), reordered, 7, scenario)
    assert sample_future(request.state(), reordered, 7, 4) == original


def test_hypothesis_changes_plan_identity_without_changing_observed_state() -> None:
    request = future_request()
    other = request.model_copy(update={"future": None})
    assert request.state() == other.state()
    assert plan(request).plan_id != plan(other).plan_id


def test_future_origin_and_unknown_scope_rejected_even_with_zero_arrivals() -> None:
    request = empty_unit()
    invalid = futures(
        request, arrivals=(batch(30, 0).model_copy(update={"compatible_units": ("unknown",)}),)
    )
    with pytest.raises(ValueError):
        plan(invalid)
    bad = FutureAssumptions(declared_at=request.at + timedelta(seconds=1))
    with pytest.raises(ValidationError):
        PlanRequest.model_validate({**request.model_dump(), "future": bad.model_dump()})
    with pytest.raises(ValueError):
        plan(request.model_copy(update={"future": bad}))


def test_combined_future_stress_matrix_has_no_invented_resource_or_patient() -> None:
    request = future_request().model_copy(update={"assumptions": Assumptions()})
    action = Action(kind="request_transport", patient_id="outgoing", bed_id="bed-1")
    for seed in range(4):
        changed = request.model_copy(update={"seed": seed})
        for scenario in range(16):
            for candidate in (Action(kind="no_op"), action):
                _, result, _ = execute(changed, candidate, scenario)
                assert result.violations == ()
                assert 1 <= result.arrived <= 3


def test_combined_demo_matches_hand_computed_admission_time() -> None:
    request = future_request()
    proposal = plan(request)
    trace, result, _ = execute(request, proposal.selected)
    assert proposal.selected.kind == "request_transport"
    assert next(e.minute for e in trace.events if e.kind == "transport_start") == 120
    assert next(e.minute for e in trace.events if e.kind == "clean_start") == 210
    assert next(e.minute for e in trace.events if e.kind == "admit") == 300
    assert result.waiting_patient_minutes == 300 + result.arrived * 180
    assert result.violations == ()
