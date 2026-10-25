"""Adversarial tests of information boundaries, resource mechanics and approval."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from pydantic import ValidationError

from hospitalos.hybrid.demo import demo_request
from hospitalos.hybrid.journal import Journal
from hospitalos.hybrid.models import (
    Action,
    Bed,
    Discharge,
    Fact,
    FactEvent,
    Patient,
    ResourcePool,
    Unit,
    action_errors,
)
from hospitalos.hybrid.planning import PlanRequest, plan
from hospitalos.hybrid.scoring import score
from hospitalos.hybrid.simulation import Assumptions, Trajectory, Transition, draw, simulate
from hospitalos.hybrid.workflow import Workflow


def replace_facts(request: PlanRequest, *facts: Fact) -> PlanRequest:
    replacements = {f"{f.kind}:{f.id}": f for f in facts}
    events = tuple(
        event.model_copy(
            update={"fact": replacements.pop(f"{event.fact.kind}:{event.fact.id}", event.fact)}
        )
        for event in request.events
    )
    events += tuple(
        FactEvent(
            hospital_id=request.hospital_id,
            event_id=f"test:{key}",
            source="fictional_feed",
            event_time=request.at,
            available_at=request.at,
            fact=fact,
        )
        for key, fact in replacements.items()
    )
    return request.model_copy(
        update={
            "events": events,
            "expected_entities": tuple(sorted({f"{e.fact.kind}:{e.fact.id}" for e in events})),
        }
    )


class ObservationsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.request = demo_request()

    def test_future_revision_does_not_change_past_state(self) -> None:
        original = self.request.events[0]
        correction = original.model_copy(
            update={
                "version": 2,
                "available_at": self.request.at + timedelta(minutes=10),
                "fact": Unit(id="medicine", staffed_beds=0, cleaning_teams=1),
            }
        )
        revised = self.request.model_copy(update={"events": self.request.events + (correction,)})
        self.assertEqual(self.request.state(), revised.state())
        later = revised.model_copy(update={"at": correction.available_at}).state()
        self.assertEqual(later.units[0].staffed_beds, 0)
        self.assertNotEqual(later.fingerprint, self.request.state().fingerprint)

    def test_input_order_and_exact_duplicates_do_not_change_result(self) -> None:
        changed = self.request.model_copy(
            update={"events": tuple(reversed(self.request.events)) + (self.request.events[0],)}
        )
        self.assertEqual(plan(self.request), plan(changed))

    def test_missing_late_source_abstains(self) -> None:
        late = self.request.events[0].model_copy(
            update={"available_at": self.request.at + timedelta(minutes=1)}
        )
        request = self.request.model_copy(update={"events": (late,) + self.request.events[1:]})
        self.assertEqual(plan(request).decision, "abstain")
        self.assertIn("missing:unit:medicine", plan(request).reasons)

    def test_stale_state_abstains(self) -> None:
        request = self.request.model_copy(update={"at": self.request.at + timedelta(minutes=61)})
        self.assertEqual(plan(request).decision, "abstain")
        self.assertEqual(plan(request).candidates, ())

    def test_conflicting_sources_require_reconciliation(self) -> None:
        other = self.request.events[0].model_copy(
            update={
                "source": "second_source",
                "event_id": "other",
                "fact": Unit(id="medicine", staffed_beds=1, cleaning_teams=1),
            }
        )
        request = self.request.model_copy(update={"events": self.request.events + (other,)})
        self.assertIn("conflicting_sources:unit:medicine", plan(request).reasons)

    def test_unknown_is_not_zero(self) -> None:
        request = replace_facts(
            self.request, Unit(id="medicine", staffed_beds=None, cleaning_teams=1)
        )
        self.assertEqual(plan(request).decision, "abstain")

    def test_naive_times_and_impossible_clocks_rejected(self) -> None:
        event = self.request.events[0].model_dump()
        event["event_time"] = self.request.at.replace(tzinfo=None)
        with self.assertRaises(ValidationError):
            FactEvent.model_validate(event)
        event = self.request.events[0].model_dump()
        event["available_at"] = self.request.at - timedelta(seconds=1)
        with self.assertRaises(ValidationError):
            FactEvent.model_validate(event)

    def test_identity_and_version_conflicts_are_rejected(self) -> None:
        original = self.request.events[0]
        other = original.model_copy(
            update={"fact": Unit(id="medicine", staffed_beds=1, cleaning_teams=1)}
        )
        bad = self.request.model_copy(update={"events": self.request.events + (other,)})
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            bad.state()
        other = original.model_copy(update={"version": 2, "source": "changed"})
        bad = self.request.model_copy(update={"events": self.request.events + (other,)})
        with self.assertRaisesRegex(ValueError, "identity"):
            bad.state()

    def test_missing_manifest_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            PlanRequest.model_validate({**self.request.model_dump(), "expected_entities": []})

    def test_journal_persists_and_rejects_conflicting_append(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "facts.sqlite")
            journal = Journal(path)
            event = self.request.events[0]
            self.assertTrue(journal.append(event))
            self.assertFalse(journal.append(event))
            with self.assertRaises(ValueError):
                journal.append(event.model_copy(update={"source": "other"}))
            journal.close()
            journal = Journal(path)
            self.assertEqual(journal.read(self.request.hospital_id), (event,))
            self.assertEqual(journal.read("other_hospital"), ())
            journal.close()


class MechanicsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.request = demo_request()

    def test_priority_changes_order_not_duration(self) -> None:
        assumptions = Assumptions(cleaning_minutes=(60,), load_multipliers=(1,))
        state = self.request.state()
        baseline = simulate(state, Action(kind="no_op"), assumptions, seed=0, scenario=0)
        priority = simulate(
            state,
            Action(kind="prioritize_cleaning", bed_id="bed-z"),
            assumptions,
            seed=0,
            scenario=0,
        )
        self.assertEqual(score(state, baseline).waiting_patient_minutes, 120)
        self.assertEqual(score(state, priority).waiting_patient_minutes, 60)
        for trajectory in (baseline, priority):
            starts = {e.bed_id: e.minute for e in trajectory.events if e.kind == "clean_start"}
            ends = {e.bed_id: e.minute for e in trajectory.events if e.kind == "clean_end"}
            self.assertEqual(
                {key: ends[key] - starts[key] for key in starts}, {"bed-a": 60, "bed-z": 60}
            )
            self.assertEqual(score(state, trajectory).violations, ())

    def test_no_implicit_discharge_and_conservation_across_scenarios(self) -> None:
        at = self.request.at
        request = replace_facts(
            self.request,
            Bed(id="bed-a", unit_id="medicine", state="occupied", occupant="inpatient"),
            Patient(
                id="inpatient",
                status="admitted",
                bed_id="bed-a",
                compatible_units=("medicine",),
                waiting_since=at - timedelta(days=1),
                medically_cleared=None,
                downstream_confirmed=True,
            ),
        )
        state = request.state()
        for seed in range(5):
            for scenario in range(8):
                trace = simulate(
                    state, Action(kind="no_op"), request.assumptions, seed=seed, scenario=scenario
                )
                self.assertFalse(any(e.kind == "depart" for e in trace.events))
                self.assertEqual(score(state, trace).violations, ())

    def test_departure_requires_both_confirmations(self) -> None:
        for downstream in (False, None, True):
            request = replace_facts(
                self.request,
                Discharge(
                    id="inpatient",
                    documents_ready=True,
                    escort_required=False,
                    downstream_required=True,
                    downstream_pool_id="smr",
                    transport_required=False,
                ),
                ResourcePool(id="smr", resource="downstream", unit_ids=("medicine",), available=1),
                Bed(id="bed-a", unit_id="medicine", state="occupied", occupant="inpatient"),
                Patient(
                    id="inpatient",
                    status="admitted",
                    bed_id="bed-a",
                    compatible_units=("medicine",),
                    waiting_since=self.request.at,
                    medically_cleared=True,
                    downstream_confirmed=downstream,
                ),
            )
            state = request.state()
            trace = simulate(state, Action(kind="no_op"), request.assumptions, seed=1, scenario=1)
            self.assertEqual(any(e.kind == "depart" for e in trace.events), downstream is True)
            self.assertEqual(score(state, trace).violations, ())

    def test_observed_overload_is_preserved_and_blocks_admission(self) -> None:
        request = replace_facts(
            self.request,
            Unit(id="medicine", staffed_beds=0, cleaning_teams=1),
            Bed(id="bed-a", unit_id="medicine", state="occupied", occupant="inpatient"),
            Patient(
                id="inpatient",
                status="admitted",
                bed_id="bed-a",
                compatible_units=("medicine",),
                waiting_since=self.request.at,
            ),
        )
        state = request.state()
        self.assertIn("observed_overload:medicine", state.warnings)
        self.assertEqual(len([b for b in state.beds if b.occupant]), 1)
        trace = simulate(state, Action(kind="no_op"), request.assumptions, seed=1, scenario=1)
        result = score(state, trace)
        self.assertEqual(result.admitted, 0)
        self.assertEqual(result.violations, ())

    def test_incompatible_reservation_rejected(self) -> None:
        request = replace_facts(self.request, Bed(id="bed-a", unit_id="medicine", state="clean"))
        errors = action_errors(
            request.state(), Action(kind="reserve_bed", bed_id="bed-a", patient_id="fictional-p1")
        )
        self.assertTrue(errors)

    def test_reservation_honoured_and_duplicate_rejected(self) -> None:
        request = replace_facts(
            self.request,
            Bed(id="bed-z", unit_id="medicine", state="clean", capabilities=("oxygen",)),
        )
        action = Action(kind="reserve_bed", bed_id="bed-z", patient_id="fictional-p1")
        trace = simulate(request.state(), action, request.assumptions, seed=1, scenario=1)
        self.assertEqual(score(request.state(), trace).violations, ())
        self.assertEqual(score(request.state(), trace).admitted, 1)
        reserved = replace_facts(
            request,
            Bed(
                id="bed-z",
                unit_id="medicine",
                state="clean",
                capabilities=("oxygen",),
                reserved_for="fictional-p1",
            ),
        )
        self.assertTrue(action_errors(reserved.state(), action))

    def test_zero_cleaners_do_not_produce_clean_beds(self) -> None:
        request = replace_facts(self.request, Unit(id="medicine", staffed_beds=2, cleaning_teams=0))
        trace = simulate(
            request.state(), Action(kind="no_op"), request.assumptions, seed=1, scenario=1
        )
        self.assertEqual(trace.events, ())
        self.assertEqual(score(request.state(), trace).waiting_patient_minutes, 1440)

    def test_scorer_detects_impossible_admission(self) -> None:
        forged = Trajectory(60, (Transition(0, "admit", "fictional-p1", "bed-a"),))
        self.assertIn("invalid_admission", score(self.request.state(), forged).violations)

    def test_exogenous_draw_is_stable_without_call_order(self) -> None:
        before = draw((10, 20, 30), 5, 9, "clean", "bed-z")
        for index in range(100):
            draw((10, 20, 30), 5, index, "clean", "other")
        self.assertEqual(before, draw((10, 20, 30), 5, 9, "clean", "bed-z"))


class PlanningAndWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.request = demo_request()

    def test_demo_recommends_compatible_bed_cleaning(self) -> None:
        result = plan(self.request)
        self.assertEqual(result.decision, "recommend")
        self.assertEqual(result.selected, Action(kind="prioritize_cleaning", bed_id="bed-z"))
        self.assertTrue(all(not candidate.violations for candidate in result.candidates))
        self.assertEqual(result.evidence, "simulation_under_declared_assumptions")

    def test_candidate_budget_explicit_and_no_op_always_kept(self) -> None:
        result = plan(self.request.model_copy(update={"max_candidates": 2}))
        self.assertTrue(result.candidates_truncated)
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(result.candidates[0].action.kind, "no_op")

    def test_unneeded_actions_do_not_win_ties(self) -> None:
        request = replace_facts(
            self.request,
            Bed(id="bed-z", unit_id="medicine", state="clean", capabilities=("oxygen",)),
        )
        self.assertEqual(plan(request).decision, "no_change")

    def test_end_to_end_unknown_outcome_cannot_be_replayed(self) -> None:
        proposal = plan(self.request)
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "workflow.sqlite")
            workflow = Workflow(path)
            workflow.propose(proposal)
            workflow.propose(proposal)
            self.assertEqual(len(workflow.history(proposal.plan_id)), 1)
            with self.assertRaises(ValueError):
                workflow.dispatch(proposal.plan_id, self.request.state(), self.request.at)
            workflow.approve(
                proposal.plan_id, self.request.state(), self.request.at, "demo_reviewer"
            )
            command = json.loads(
                workflow.dispatch(proposal.plan_id, self.request.state(), self.request.at)
            )
            self.assertFalse(command["external_execution"])
            workflow.outcome(
                proposal.plan_id, self.request.at, "demo_operator", "unknown", "timeout_test"
            )
            workflow.close()
            workflow = Workflow(path)
            with self.assertRaises(ValueError):
                workflow.dispatch(proposal.plan_id, self.request.state(), self.request.at)
            workflow.outcome(
                proposal.plan_id, self.request.at, "demo_operator", "confirmed", "sandbox_readback"
            )
            self.assertEqual(
                [row[0] for row in workflow.history(proposal.plan_id)],
                ["proposed", "approved", "sent", "unknown", "confirmed"],
            )
            workflow.close()

    def test_changed_state_invalidates_approval(self) -> None:
        workflow = Workflow()
        proposal = plan(self.request)
        workflow.propose(proposal)
        changed = replace_facts(self.request, Unit(id="medicine", staffed_beds=2, cleaning_teams=0))
        with self.assertRaisesRegex(ValueError, "changed"):
            workflow.approve(proposal.plan_id, changed.state(), self.request.at, "operator")
        workflow.close()

    def test_expiration_and_stale_recheck_block_dispatch(self) -> None:
        workflow = Workflow()
        proposal = plan(self.request)
        workflow.propose(proposal)
        workflow.approve(proposal.plan_id, self.request.state(), self.request.at, "operator")
        later = self.request.model_copy(update={"at": self.request.at + timedelta(minutes=15)})
        with self.assertRaisesRegex(ValueError, "expired"):
            workflow.dispatch(proposal.plan_id, later.state(), later.at)
        with self.assertRaisesRegex(ValueError, "fresh"):
            workflow.dispatch(proposal.plan_id, self.request.state(), later.at)
        workflow.close()

    def test_refusal_is_terminal_and_requires_reason(self) -> None:
        workflow = Workflow()
        proposal = plan(self.request)
        workflow.propose(proposal)
        workflow.dismiss(proposal.plan_id, self.request.at, "operator", "local_constraint")
        with self.assertRaises(ValueError):
            workflow.approve(proposal.plan_id, self.request.state(), self.request.at, "operator")
        workflow.close()


if __name__ == "__main__":
    unittest.main()
