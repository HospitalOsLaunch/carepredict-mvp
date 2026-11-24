from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from hospitalos.hybrid import flow_clock
from hospitalos.hybrid.flow_clock import CohortClock
from hospitalos.hybrid.models import Action, Bed, Discharge, Fact, FactEvent, Patient, State, Unit
from hospitalos.hybrid.multiday import assess_horizon, paired_future
from hospitalos.hybrid.outlook import Departures, UnitOutlook, check_feed
from hospitalos.hybrid.planning import PlanRequest, enumerate_actions, plan
from hospitalos.hybrid.scenarios import FutureArrival
from hospitalos.hybrid.scoring import score
from hospitalos.hybrid.simulation import Assumptions, Trajectory, Transition, simulate
from hospitalos.hybrid.synthetic_outlook import synthetic_outlook

D = datetime(2026, 3, 27, 8, 30, tzinfo=UTC)
UNIT = "medecine-polyvalente"
NO = Action(kind="no_op")


def state_at_d() -> State:
    admitted = D - timedelta(days=2)
    patient = Patient(
        id="p",
        status="admitted",
        bed_id="A",
        compatible_units=(UNIT,),
        medically_cleared=False,
        waiting_since=admitted - timedelta(hours=4),
    )
    state = State(
        hospital_id="fiction",
        at=D,
        fingerprint="public",
        units=(Unit(id=UNIT, staffed_beds=2, cleaning_teams=1),),
        patients=(patient,),
        beds=(
            Bed(id="A", unit_id=UNIT, state="occupied", occupant="p"),
            Bed(id="B", unit_id=UNIT, state="clean"),
        ),
        discharges=(
            Discharge(
                id="p",
                documents_ready=True,
                downstream_required=False,
                transport_required=False,
                escort_required=False,
            ),
        ),
    )
    return state.model_copy(
        update={"outlooks": (synthetic_outlook(state, UNIT, admission_times={"p": admitted}),)}
    )


def test_clock_is_conditional_and_clock_changes_do_not_move_the_local_discharge_window() -> None:
    z = ZoneInfo("Europe/Paris")
    for origin in (datetime(2026, 3, 29, 7, 39, tzinfo=z), datetime(2026, 10, 25, 7, 39, tzinfo=z)):
        origin = origin.astimezone(UTC)
        admission = origin - timedelta(days=1)
        for j in range(20):
            clock = CohortClock(origin, "H", UNIT, 41, j, ())
            t = clock.departure("p", admission)
            assert t is not None and t > 0
            assert (origin + timedelta(minutes=t)).astimezone(z).hour == 7
        assert clock.departure("outside_support", origin - timedelta(days=12)) is None


def test_short_and_long_are_one_path_and_never_authorize_an_action() -> None:
    state = state_at_d()
    paths = {}
    for minutes in (720, 1440, 10080):
        tape = paired_future(state, None, 41, 0, minutes, multiday=minutes > 1440)
        assert tape.cohort
        trace = simulate(
            state,
            NO,
            Assumptions(),
            seed=41,
            scenario=0,
            horizon_minutes=minutes,
            future=tape,
            multiday=minutes > 1440,
        )
        assert not score(state, trace, expected_future=tape).violations
        paths[minutes] = trace.events
    for minutes in (720, 1440):
        assert paths[minutes] == tuple(e for e in paths[10080] if e.minute <= minutes)
    events = paths[10080]
    projected = [e for e in events if e.kind == "forecast_depart"]
    assert any(e.patient_id == "p" for e in projected)
    assert any(e.patient_id != "p" for e in projected)
    assert not [a for a in enumerate_actions(state, 32)[0] if a.patient_id == "p"]
    assert state.patients[0].medically_cleared is False
    assert state.beds[0].occupant == "p"
    starts = {e.patient_id: e.minute for e in events if e.kind == "admit"}
    assert all(starts[e.patient_id] < e.minute for e in projected if e.patient_id != "p")


def test_scorer_rejects_omitted_or_forged_population_departure() -> None:
    state = state_at_d()
    tape = paired_future(state, None, 9, 0, 10080, multiday=True)
    assert tape.cohort
    omitted = score(state, Trajectory(10080, ()), expected_future=tape)
    assert "missing_forecast_departure" in omitted.violations
    early = Transition(0, "forecast_depart", "p", "A")
    assert (
        "invalid_forecast_departure"
        in score(state, Trajectory(1, (early,)), expected_future=tape).violations
    )
    untrusted = replace(tape, cohort=replace(tape.cohort, residents=(("p", D),)))
    with pytest.raises(ValueError, match="Unverified cohort"):
        score(state, Trajectory(1, ()), expected_future=untrusted)
    blocked = state.model_copy(
        update={"discharges": (state.discharges[0].model_copy(update={"escort_required": True}),)}
    )
    blocked_tape = paired_future(blocked, None, 9, 0, 1440, multiday=False)
    assert blocked_tape.cohort and not blocked_tape.cohort.residents


@pytest.mark.parametrize(
    "rejection", ["future_admission", "admission_clock_missing", "outage", "hospital_export"]
)
def test_partial_or_unqualified_sources_do_not_activate_population_clock(rejection: str) -> None:
    state = state_at_d()
    feeds = []
    for f in state.outlooks[0].feeds:
        if isinstance(f, Departures):
            if rejection in {"future_admission", "admission_clock_missing"}:
                date = D + timedelta(minutes=1) if rejection == "future_admission" else None
                f = f.model_copy(
                    update={"records": (f.records[0].model_copy(update={"admitted_at": date}),)}
                )
            elif rejection == "outage":
                f = f.model_copy(update={"status": "outage"})
            else:
                f = f.model_copy(update={"provenance": "hospital_export"})
        feeds.append(f)
    state = state.model_copy(update={"outlooks": (UnitOutlook(id=UNIT, feeds=tuple(feeds)),)})
    tape = paired_future(state, None, 41, 0, 720, multiday=False)
    assert tape.cohort is None and not any(isinstance(e, FutureArrival) for e in tape.events)
    assert not assess_horizon(state, UNIT, 3).qualified
    if rejection != "hospital_export":
        assert rejection in check_feed(state, UNIT, "departures", D + timedelta(hours=12)).reasons


def test_normal_planner_uses_facts_at_origin_and_old_receipts_keep_their_shape() -> None:
    state = state_at_d()
    facts: tuple[Fact, ...] = (
        *state.units,
        *state.beds,
        *state.patients,
        *state.discharges,
        *state.outlooks,
    )
    events = tuple(
        FactEvent(
            hospital_id=state.hospital_id,
            event_id=f.kind + ":" + f.id,
            source="syn",
            event_time=D,
            available_at=D,
            fact=f,
        )
        for f in facts
    )
    request = PlanRequest(
        hospital_id=state.hospital_id,
        at=D,
        unit_id=UNIT,
        events=events,
        expected_entities=tuple(e.event_id for e in events),
        scenarios=1,
        horizon_minutes=10080,
    )
    p = plan(request)
    assert p.horizon_minutes == 1440 and "synthetic_residence_projection" in p.warnings
    assert [w.minutes for w in p.shadow_flow] == [720, 1440]
    assert all(w.mean_occupied == 1 + w.mean_admissions - w.mean_departures for w in p.shadow_flow)
    legacy_outlook = flow_clock.reference_state(state).outlooks[0]
    reference = plan(
        request.model_copy(
            update={
                "events": (*events[:-1], events[-1].model_copy(update={"fact": legacy_outlook}))
            }
        )
    )
    assert (p.selected, p.bundle, p.windows, p.team_practice, p.candidates) == (
        reference.selected,
        reference.bundle,
        reference.windows,
        reference.team_practice,
        reference.candidates,
    )
    assert not reference.shadow_flow
    experimental = plan(request, research_cohort_ranking=True)
    assert p.plan_id != experimental.plan_id and "research_cohort_ranking" in experimental.warnings
    assert "cohort_ranking_unqualified" in p.horizons[0].reasons
    late = events[-1].model_copy(update={"available_at": D + timedelta(minutes=1)})
    delayed = request.model_copy(update={"events": (*events[:-1], late)})
    assert not flow_clock.available(delayed.state(), 720)
    old = next(f for f in synthetic_outlook(state, UNIT).feeds if isinstance(f, Departures))
    assert "cohort_profile" not in old.model_dump()
    assert "admitted_at" not in old.records[0].model_dump()
