"""Sandbox-only transactional reservation and command lifecycle.

A local claim is not an atomic reservation in the hospital SI. Source/actor
strings and reconciliation attestations are not authenticated by this module.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Literal

from pydantic import field_validator

from hospitalos.operational.contract import Closed, Identifier, instant

from .live_models import Assessment, LiveSnapshot, PlanningOptions, SandboxCommand
from .live_store import LiveStore
from .models import Action, action_errors


class Reconciliation(Closed):
    command_id: Identifier
    outcome: Literal["completed", "not_executed"]
    source: Identifier
    observed_at: datetime
    evidence_ref: Identifier
    # Adapter/operator attests that new residual counts include this command's effects.
    resource_accounting_confirmed: Literal[True]

    @field_validator("observed_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)


def claims(action: Action, snapshot: LiveSnapshot) -> tuple[str, ...]:
    keys = [f"bed:{action.bed_id}"]
    if action.patient_id:
        keys.append(f"patient:{action.patient_id}")
    unit_id = snapshot.state.units[0].id
    if action.kind == "prioritize_cleaning":
        keys.append(f"cleaning:{unit_id}")
    elif action.kind == "reserve_bed":
        keys.append(f"staffed:{unit_id}")
    elif action.kind == "request_transport":
        discharge = next(d for d in snapshot.state.discharges if d.id == action.patient_id)
        keys.append(f"transport:{discharge.transport_pool_id}")
        if discharge.downstream_required:
            keys.append(f"downstream:{discharge.downstream_pool_id}")
    else:
        raise ValueError("No actionable claim")
    return tuple(sorted(keys))


class LiveWorkflow:
    def __init__(self, store: LiveStore) -> None:
        if store.policy.mode != "sandbox":
            raise ValueError("Shadow mode cannot create approvals, claims or commands")
        self.store = store

    def _record(self, key: str, status: str, now: datetime, actor: str, evidence: str) -> None:
        if not actor.strip() or not evidence.strip():
            raise ValueError("Actor and evidence are required")
        self.store.db.execute(
            "INSERT INTO live_transitions(proposal, status, at, actor, evidence) "
            "VALUES (?, ?, ?, ?, ?)",
            (key, status, now.isoformat(), actor, evidence),
        )

    def _current(self, key: str) -> tuple[Assessment, str]:
        row = self.store.db.execute("SELECT body FROM live_proposals WHERE id=?", (key,)).fetchone()
        last = self.store.db.execute(
            "SELECT status FROM live_transitions WHERE proposal=? ORDER BY sequence DESC LIMIT 1",
            (key,),
        ).fetchone()
        if row is None or last is None:
            raise ValueError("Unknown proposal")
        return Assessment.model_validate_json(row[0]), str(last[0])

    def propose(self, now: datetime, options: PlanningOptions | None = None) -> str:
        with self.store.transaction(now) as now:
            assessment = self.store._assess(now, options or PlanningOptions())
            if (
                assessment.gate_reasons
                or assessment.plan is None
                or assessment.plan.decision != "recommend"
            ):
                raise ValueError(f"No actionable recommendation: {assessment.gate_reasons}")
            key = uuid.uuid4().hex
            self.store.db.execute(
                "INSERT INTO live_proposals VALUES (?, ?)", (key, assessment.model_dump_json())
            )
            self._record(key, "proposed", now, "local_planner", "simulation_only")
            return key

    def _check(self, key: str, assessment: Assessment, now: datetime) -> LiveSnapshot:
        if now >= assessment.expires_at:
            raise ValueError("Proposal expired; replan")
        current = self.store._snapshot(now)
        if current.issues:
            raise ValueError(f"Live observation gate: {current.issues}")
        if current.semantic_fingerprint != assessment.snapshot.semantic_fingerprint:
            raise ValueError("Observed state or availability changed; replan")
        if self.store.db.execute(
            "SELECT 1 FROM live_holds WHERE proposal<>? LIMIT 1", (key,)
        ).fetchone():
            raise ValueError("Another local action is unresolved; replan after reconciliation")
        proposal = assessment.plan
        if proposal is None or action_errors(current.state, proposal.selected):
            raise ValueError("Action preconditions no longer hold")
        budgets = {r.key: r for r in current.resources}
        for resource in claims(proposal.selected, current):
            if resource in budgets:
                available = budgets[resource].observed_available
                if available is None or available < 1:
                    raise ValueError(f"Resource unavailable: {resource}")
        return current

    def approve(self, key: str, now: datetime, actor: str) -> None:
        with self.store.transaction(now) as now:
            assessment, status = self._current(key)
            if status != "proposed":
                raise ValueError("Proposal is not awaiting approval")
            snapshot = self._check(key, assessment, now)
            assert assessment.plan is not None
            expiry = min(
                assessment.expires_at, now + timedelta(seconds=self.store.policy.hold_ttl_seconds)
            )
            for resource in claims(assessment.plan.selected, snapshot):
                self.store.db.execute(
                    "INSERT INTO live_holds(proposal, resource, expires) VALUES (?, ?, ?)",
                    (key, resource, expiry.isoformat()),
                )
            self._record(key, "approved", now, actor, "local_sandbox_approval")

    def dispatch(self, key: str, now: datetime) -> SandboxCommand:
        with self.store.transaction(now) as now:
            assessment, status = self._current(key)
            if status != "approved":
                raise ValueError("Not approved or already dispatched; do not retry")
            snapshot = self._check(key, assessment, now)
            assert assessment.plan is not None
            expected = set(claims(assessment.plan.selected, snapshot))
            held = {
                str(r[0])
                for r in self.store.db.execute(
                    "SELECT resource FROM live_holds WHERE proposal=?", (key,)
                )
            }
            if held != expected:
                raise ValueError("Unsent local holds expired; create a new proposal")
            # Commit BEFORE returning; ambiguous delivery must be reconciled, never resent.
            self.store.db.execute("UPDATE live_holds SET sent=1 WHERE proposal=?", (key,))
            self._record(key, "sent", now, "local_sandbox_gateway", "no_external_execution")
            command = SandboxCommand(
                command_id=key,
                proposal_id=key,
                hospital_id=self.store.policy.hospital_id,
                action=assessment.plan.selected.model_dump(),
            )
        return command

    def acknowledge(self, key: str, now: datetime, actor: str, evidence: str) -> None:
        with self.store.transaction(now) as now:
            _assessment, status = self._current(key)
            if status != "sent":
                raise ValueError("Only a sent command can be acknowledged")
            self._record(key, "acknowledged", now, actor, evidence)

    def mark_unknown(self, key: str, now: datetime, actor: str, evidence: str) -> None:
        with self.store.transaction(now) as now:
            _assessment, status = self._current(key)
            if status not in {"sent", "acknowledged"}:
                raise ValueError("Only an unresolved dispatch can become unknown")
            self._record(key, "unknown", now, actor, evidence)

    def dismiss(self, key: str, now: datetime, actor: str, reason: str) -> None:
        with self.store.transaction(now) as now:
            _assessment, status = self._current(key)
            if status not in {"proposed", "approved"}:
                raise ValueError("Dispatched commands require reconciliation")
            self.store.db.execute("DELETE FROM live_holds WHERE proposal=?", (key,))
            self._record(key, "dismissed", now, actor, reason)

    def reconcile(self, evidence: Reconciliation, now: datetime, actor: str) -> None:
        with self.store.transaction(now) as now:
            key = evidence.command_id
            assessment, status = self._current(key)
            if status not in {"sent", "acknowledged", "unknown"}:
                raise ValueError("Command is not awaiting reconciliation")
            row = self.store.db.execute(
                "SELECT at FROM live_transitions WHERE proposal=? AND status='sent'", (key,)
            ).fetchone()
            assert row is not None and assessment.plan is not None
            sent = datetime.fromisoformat(row[0])
            if (
                evidence.source not in self.store.policy.sources
                or not sent < evidence.observed_at <= now
                or (now - evidence.observed_at).total_seconds()
                > self.store.policy.resource_ttl_seconds
            ):
                raise ValueError("Fresh command-bound reconciliation evidence is required")
            snapshot = self.store._snapshot(now)
            if snapshot.issues:
                raise ValueError(f"Reconciliation observation gate: {snapshot.issues}")
            action = assessment.plan.selected
            related = {f"bed:{action.bed_id}"}
            if action.patient_id:
                related.add(f"patient:{action.patient_id}")
            if action.kind == "request_transport":
                related.add(f"discharge:{action.patient_id}")
            for entity in related:
                facts = [e for e in snapshot.events if f"{e.fact.kind}:{e.fact.id}" == entity]
                if not facts or any(e.event_time <= sent for e in facts):
                    raise ValueError("Related facts must be observed after dispatch")
            for resource in snapshot.resources:
                # All capacities must reflect the post-command resource accounting.
                if any(o.observed_at <= sent for o in resource.observations):
                    raise ValueError("Resource confirmations must be observed after dispatch")
            bed = next(b for b in snapshot.state.beds if b.id == action.bed_id)
            patient = next((p for p in snapshot.state.patients if p.id == action.patient_id), None)
            completed = evidence.outcome == "completed"
            if action.kind == "prioritize_cleaning":
                consistent = bed.state == ("clean" if completed else "dirty")
            elif action.kind == "reserve_bed":
                consistent = (
                    (bed.reserved_for == action.patient_id or bed.occupant == action.patient_id)
                    if completed
                    else (
                        bed.state == "clean"
                        and bed.reserved_for is None
                        and patient is not None
                        and patient.status == "waiting"
                    )
                )
            else:
                discharge = next(d for d in snapshot.state.discharges if d.id == action.patient_id)
                consistent = (
                    (
                        patient is not None
                        and patient.status == "departed"
                        and bed.occupant != action.patient_id
                    )
                    if completed
                    else (
                        patient is not None
                        and patient.status == "admitted"
                        and patient.bed_id == bed.id
                        and bed.occupant == patient.id
                        and discharge.transport_requested is False
                    )
                )
            if not consistent:
                raise ValueError("Observed effect does not support the reconciliation outcome")
            self._record(key, evidence.outcome, now, actor, evidence.model_dump_json())
            self.store.db.execute("DELETE FROM live_holds WHERE proposal=?", (key,))

    def history(self, key: str) -> tuple[tuple[str, str, str, str], ...]:
        with self.store.lock:
            return tuple(
                self.store.db.execute(
                    "SELECT status, at, actor, evidence FROM live_transitions "
                    "WHERE proposal=? ORDER BY sequence",
                    (key,),
                )
            )
