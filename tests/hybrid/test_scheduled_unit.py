from datetime import UTC, datetime, timedelta

import pytest

from hospitalos.hybrid.models import Action, Bed, FactEvent, Unit, bundle_errors
from hospitalos.hybrid.planning import PlanRequest, evaluate, plan
from hospitalos.hybrid.scenarios import FutureAssumptions, ResourceChange, sample_future
from hospitalos.hybrid.unit_schedule import UnitSchedule

D = datetime(2026, 11, 24, 8, 30, tzinfo=UTC)


def scheduled_request() -> PlanRequest:
    def at(minutes: int) -> datetime:
        return D + timedelta(minutes=minutes)

    schedule = UnitSchedule.model_validate(
        {
            "id": "med",
            "budget_minutes": 60,
            "offers": [
                {
                    "option": {
                        "option_id": "shift",
                        "skill": "IDE",
                        "start": at(30),
                        "end": at(90),
                        "source": "shared_unit",
                        "confirmation": "confirmed",
                        "lending_unit": "donor",
                        "lending_unit_minimum": 2,
                        "lending_unit_scheduled": 3,
                    },
                    "staff_id": "staff-x",
                    "staffed_places": 1,
                }
            ],
            "admissions": [
                {
                    "request": {
                        "request_id": "elective",
                        "requirements": ["oxygen"],
                        "expected_arrival": at(40),
                        "arrival_delay": {"support": [0], "weights": [1]},
                        "care": [],
                        "admission_task_minutes": 90,
                        "provenance": {
                            "source": "appointments",
                            "obs_id": "booking",
                            "event_time": D,
                            "available_at": D,
                        },
                    },
                    "window_start": at(30),
                    "window_end": at(80),
                }
            ],
        }
    )
    facts = (
        Unit(id="med", staffed_beds=0, cleaning_teams=1),
        Bed(id="bed", unit_id="med", state="clean", capabilities=("oxygen",)),
        schedule,
    )
    events = tuple(
        FactEvent(
            hospital_id="H", event_id=f.kind, source="demo", event_time=D, available_at=D, fact=f
        )
        for f in facts
    )
    change = ResourceChange(
        id="roster", minute=90, resource="staffed_beds", target_id="med", capacity=1
    )
    return PlanRequest(
        hospital_id="H",
        unit_id="med",
        at=D,
        expected_entities=tuple(f"{f.kind}:{f.id}" for f in facts),
        events=events,
        future=FutureAssumptions(declared_at=D, changes=(change,)),
        horizon_minutes=1440,
        max_bundle=2,
        scenarios=2,
    )


def test_joint_only_gain_preserves_demand_and_timed_coverage() -> None:
    req = scheduled_request()
    p = plan(req)
    assert p.schema_version == "HYBRID_UNIT_PLAN_1"
    assert {s.kind for s in p.bundle} == {"reinforce", "prepare_admission"}
    assert {c.mean_waiting_patient_minutes for c in p.candidates} == {90}
    assert p.bundle_evaluation and p.bundle_evaluation.mean_waiting_patient_minutes == 0
    assert p.bundle_marginal_minutes == (0, 90)
    assert [w.minutes for w in p.windows] == [720, 1440]
    assert all(w.saved_wait == 90 for w in p.windows)
    assert all(c.max_arrived == 1 for c in (*p.candidates, p.bundle_evaluation))
    assert p.service_status == "served_in_all_sampled_scenarios"


def test_end_of_staff_window_can_veto_a_faster_bundle() -> None:
    req = scheduled_request().model_copy(update={"future": None})
    p = plan(req)
    assert p.decision == "no_change"
    ev = evaluate(
        req.state(),
        (
            Action(kind="reinforce", slot_id="shift"),
            Action(kind="prepare_admission", slot_id="elective", bed_id="bed"),
        ),
        req,
    )
    assert ev.candidate.mean_staffed_pressure > 0


def test_conditional_staff_and_lender_floor_are_checked() -> None:
    state = scheduled_request().state()
    schedule = state.schedules[0]
    offer = schedule.offers[0]
    for patch in ({"confirmation": "requested"}, {"lending_unit_scheduled": 2}):
        changed = offer.model_copy(update={"option": offer.option.model_copy(update=patch)})
        new = state.model_copy(
            update={"schedules": (schedule.model_copy(update={"offers": (changed,)}),)}
        )
        assert bundle_errors(new, (Action(kind="reinforce", slot_id="shift"),))
    assert len(sample_future(state, None, 3, 7).events) == 1


def test_request_refuses_scope_switch() -> None:
    with pytest.raises(ValueError, match="single beneficiary"):
        PlanRequest.model_validate(scheduled_request().model_dump() | {"unit_id": "other"})


def test_sandbox_holds_every_step_in_one_transaction() -> None:
    from hospitalos.hybrid.live_models import (
        Availability,
        LivePolicy,
        ObservationBatch,
        PlanningOptions,
    )
    from hospitalos.hybrid.live_store import LiveStore
    from hospitalos.hybrid.live_workflow import LiveWorkflow

    req = scheduled_request()
    store = LiveStore(LivePolicy(hospital_id="H", unit_id="med", sources=("demo",), mode="sandbox"))
    try:
        batch = ObservationBatch(
            batch_id="first",
            hospital_id="H",
            source="demo",
            manifest_version=1,
            expected_entities=req.expected_entities,
            events=req.events,
            availability=(
                Availability(
                    resource="staffed",
                    target_id="med",
                    available=0,
                    source="demo",
                    observed_at=D,
                    evidence_ref="n",
                ),
                Availability(
                    resource="cleaning",
                    target_id="med",
                    available=1,
                    source="demo",
                    observed_at=D,
                    evidence_ref="b",
                ),
            ),
        )
        store.ingest(batch, D)
        flow = LiveWorkflow(store)
        proposal = flow.propose(D, PlanningOptions(horizon_minutes=80, scenarios=1, max_bundle=2))
        flow.approve(proposal, D, "reviewer")
        held = dict(store.db.execute("SELECT resource,quantity FROM live_holds"))
        assert held["booking:elective"] == held["bed:bed"] == held["offer:med:shift"] == 1
        assert any(k.startswith("staff:staff-x:") for k in held)
        assert {a["kind"] for a in flow.dispatch(proposal, D).actions} == {
            "reinforce",
            "prepare_admission",
        }
    finally:
        store.close()


def test_multiday_requires_server_qualification_and_complete_asof_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hospitalos.hybrid import multiday
    from hospitalos.hybrid.synthetic_outlook import synthetic_outlook

    req = scheduled_request().model_copy(update={"scenarios": 1, "horizon_minutes": 10080})

    def observed(days: int) -> PlanRequest:
        outlook = synthetic_outlook(req.state(), "med", days)
        event = FactEvent(
            hospital_id="H",
            event_id="outlook",
            source="syn-export",
            event_time=D,
            available_at=D,
            fact=outlook,
        )
        return req.model_copy(
            update={
                "events": (*req.events, event),
                "expected_entities": (*req.expected_entities, "unit_outlook:med"),
            }
        )

    insufficient = plan(observed(7))
    assert insufficient.horizon_minutes == 1440
    assert "qualification_missing" in insufficient.horizons[0].reasons
    # Isolate the positive engineering path from the actual scientific NO-GO.
    monkeypatch.setattr(multiday, "qualified_units", lambda: {"med": [3, 7]})
    assert plan(req).horizon_minutes == 1440
    three = plan(observed(3))
    assert three.horizon_minutes == 4320 and three.requested_horizon_minutes == 10080
    assert [w.minutes for w in three.windows] == [720, 1440, 4320]
    seven = plan(observed(7))
    assert seven.horizon_minutes == 10080
    assert [w.minutes for w in seven.windows] == [720, 1440, 4320, 10080]
    assert all(not c.violations for c in seven.candidates)
    assert any(c.max_arrived > 1 for c in seven.candidates)
    assert seven.plan_id != insufficient.plan_id


def test_action_and_booking_reach_day_three_on_the_same_tape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hospitalos.hybrid import multiday
    from hospitalos.hybrid.synthetic_outlook import synthetic_outlook
    from hospitalos.hybrid.unit_schedule import UnitSchedule

    req = scheduled_request()
    schedule = req.state().schedules[0]
    delta = timedelta(days=2)
    b = schedule.admissions[0]
    booking = b.model_copy(
        update={
            "window_start": b.window_start + delta,
            "window_end": b.window_end + delta,
            "request": b.request.model_copy(
                update={"expected_arrival": b.request.expected_arrival + delta}
            ),
        }
    )
    offer = schedule.offers[0]
    moved = offer.model_copy(
        update={
            "option": offer.option.model_copy(
                update={"start": offer.option.start + delta, "end": offer.option.end + delta}
            )
        }
    )
    schedule = schedule.model_copy(update={"admissions": (booking,), "offers": (moved,)})
    events = tuple(
        e.model_copy(update={"fact": schedule}) if isinstance(e.fact, UnitSchedule) else e
        for e in req.events
    )
    req = req.model_copy(update={"events": events, "scenarios": 1, "horizon_minutes": 4320})
    outlook = synthetic_outlook(req.state(), "med", 3)
    event = FactEvent(
        hospital_id="H",
        event_id="outlook",
        source="syn-export",
        event_time=D,
        available_at=D,
        fact=outlook,
    )
    req = req.model_copy(
        update={
            "events": (*events, event),
            "expected_entities": (*req.expected_entities, "unit_outlook:med"),
        }
    )
    monkeypatch.setattr(multiday, "qualified_units", lambda: {"med": [3]})
    p = plan(req)
    assert p.horizon_minutes == 4320
    assert {"reinforce", "prepare_admission"} <= {c.action.kind for c in p.candidates}
    assert all(c.max_arrived >= 1 and not c.violations for c in p.candidates)
    short = plan(req.model_copy(update={"horizon_minutes": 1440}))
    assert {c.action.kind for c in short.candidates} == {"no_op"}


def test_external_assignments_and_committed_staff_are_not_double_counted() -> None:
    from hospitalos.hybrid.outlook import ExternalShift, Roster
    from hospitalos.hybrid.scenarios import FutureTape, staffing_tape
    from hospitalos.hybrid.synthetic_outlook import synthetic_outlook

    state = scheduled_request().state()
    schedule = state.schedules[0]
    offer = schedule.offers[0]
    outlook = synthetic_outlook(state, schedule.id)
    roster = next(f for f in outlook.feeds if isinstance(f, Roster))
    outside = ExternalShift(
        unit_id="unrelated",
        staff_id=offer.staff_id,
        skill="IDE",
        start=offer.option.start,
        end=offer.option.end,
        status="confirmed",
    )
    roster = roster.model_copy(update={"external_shifts": (outside,)})
    state = state.model_copy(
        update={"outlooks": (outlook.model_copy(update={"feeds": (roster,)}),)}
    )
    assert "staff_already_assigned" in bundle_errors(
        state, (Action(kind="reinforce", slot_id="shift"),)
    )
    included = offer.model_copy(update={"committed": True, "included_in_baseline": True})
    state = state.model_copy(
        update={"schedules": (schedule.model_copy(update={"offers": (included,)}),)}
    )
    unchanged, tape = staffing_tape(state, FutureTape(state.at, ()), ())
    assert unchanged.units == state.units and not tape.events
