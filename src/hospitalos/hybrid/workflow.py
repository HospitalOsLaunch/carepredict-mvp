"""Durable approval workflow for sandbox commands; no hospital write adapter.

The sent state is persisted BEFORE returning a command. A crash after persistence
must be reconciled, never blindly retried. Exactly-once external execution is not
claimed. Actor strings here are audit metadata, not authenticated identities.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Literal

from hospitalos.operational.contract import instant

from .models import State, action_errors
from .planning import Plan


class Workflow:
    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS transitions (sequence INTEGER PRIMARY KEY, "
            "proposal TEXT NOT NULL, status TEXT NOT NULL, at TEXT NOT NULL, "
            "actor TEXT NOT NULL, evidence TEXT NOT NULL)"
        )

    def propose(self, proposal: Plan) -> None:
        if proposal.decision != "recommend":
            raise ValueError("Only an actionable recommendation can enter approval")
        with self.db:
            old = self.db.execute(
                "SELECT body FROM proposals WHERE id=?", (proposal.plan_id,)
            ).fetchone()
            if old:
                if old[0] != proposal.model_dump_json():
                    raise ValueError("Conflicting proposal")
                return
            self.db.execute(
                "INSERT INTO proposals VALUES (?, ?)",
                (proposal.plan_id, proposal.model_dump_json()),
            )
            self._record(
                proposal.plan_id, "proposed", proposal.created_at, "planner", "simulation_only"
            )

    def _record(self, key: str, status: str, at: datetime, actor: str, evidence: str) -> None:
        if not actor.strip():
            raise ValueError("Actor is required")
        self.db.execute(
            "INSERT INTO transitions (proposal, status, at, actor, evidence) "
            "VALUES (?, ?, ?, ?, ?)",
            (key, status, instant(at).isoformat(), actor, evidence),
        )

    def _current(self, key: str, at: datetime) -> tuple[Plan, str]:
        row = self.db.execute("SELECT body FROM proposals WHERE id=?", (key,)).fetchone()
        if row is None:
            raise ValueError("Unknown proposal")
        last = self.db.execute(
            "SELECT status, at FROM transitions WHERE proposal=? ORDER BY sequence DESC LIMIT 1",
            (key,),
        ).fetchone()
        if last is None or instant(at) < datetime.fromisoformat(last[1]):
            raise ValueError("Workflow time must be monotonic")
        return Plan.model_validate_json(row[0]), str(last[0])

    @staticmethod
    def _recheck(proposal: Plan, state: State, now: datetime) -> None:
        now = instant(now)
        if state.at != now:
            raise ValueError("Reconstruct a fresh state at the operation time")
        if now >= proposal.expires_at:
            raise ValueError("Proposal expired")
        if (
            state.hospital_id != proposal.hospital_id
            or state.fingerprint != proposal.state_fingerprint
        ):
            raise ValueError("Observed state changed; replan")
        errors = action_errors(state, proposal.selected)
        if errors:
            raise ValueError(f"Preconditions failed: {errors}")

    def approve(self, key: str, state: State, now: datetime, actor: str) -> None:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            proposal, status = self._current(key, now)
            if status != "proposed":
                raise ValueError("Proposal is not awaiting approval")
            self._recheck(proposal, state, now)
            self._record(key, "approved", now, actor, "human_approval")

    def dismiss(self, key: str, now: datetime, actor: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("A rejection/cancellation reason is required")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            _proposal, status = self._current(key, now)
            if status not in {"proposed", "approved"}:
                raise ValueError("An already sent action requires reconciliation")
            self._record(key, "dismissed", now, actor, reason)

    def dispatch(self, key: str, state: State, now: datetime) -> str:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            proposal, status = self._current(key, now)
            if status != "approved":
                raise ValueError("Not approved or already dispatched; do not retry")
            self._recheck(proposal, state, now)
            self._record(key, "sent", now, "sandbox_gateway", "no_external_side_effect")
        return json.dumps(
            {
                "mode": "sandbox_only",
                "command_id": key,
                "hospital_id": proposal.hospital_id,
                "action": proposal.selected.model_dump(),
                "external_execution": False,
            }
        )

    def outcome(
        self,
        key: str,
        now: datetime,
        actor: str,
        status: Literal["confirmed", "failed", "unknown"],
        evidence: str,
    ) -> None:
        if status not in {"confirmed", "failed", "unknown"} or not evidence.strip():
            raise ValueError("Outcome and evidence are required")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            _proposal, old = self._current(key, now)
            if old != "sent" and not (old == "unknown" and status in {"confirmed", "failed"}):
                raise ValueError("Invalid outcome transition")
            self._record(key, status, now, actor, evidence)

    def history(self, key: str) -> tuple[tuple[str, str, str, str], ...]:
        return tuple(
            self.db.execute(
                "SELECT status, at, actor, evidence FROM transitions "
                "WHERE proposal=? ORDER BY sequence",
                (key,),
            )
        )

    def close(self) -> None:
        self.db.close()
