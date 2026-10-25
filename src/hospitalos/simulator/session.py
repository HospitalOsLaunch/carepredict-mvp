"""Single-process local demo session. All writes target an owned simulated world."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field, StrictBool, StrictInt

from hospitalos.hybrid.live_models import LiveSnapshot, PlanningOptions, ShadowEpisode
from hospitalos.hybrid.models import action_errors
from hospitalos.hybrid.simulation import Assumptions
from hospitalos.operational.contract import Closed, Identifier

from .engine import LIMIT, HospitalSimulation
from .evaluation import Evaluation, evaluate
from .feed import DeclaredFeed


class RunRequest(Closed):
    run_id: Identifier
    request_id: Identifier
    revision: Annotated[StrictInt, Field(ge=0)]


class ControlRequest(RunRequest):
    operation: Literal["advance", "play", "pause", "disconnect", "reconnect", "finish", "reset"]
    seconds: Annotated[StrictInt, Field(ge=1, le=3600)] = 300
    speed: Literal[1, 60] = 60


class DecisionRequest(RunRequest):
    plan_id: Identifier
    snapshot_fingerprint: Identifier
    accept: StrictBool


class CommandReceipt(Closed):
    request_id: str
    plan_id: str
    at: datetime
    status: Literal["accepted", "refusal_recorded", "executed", "refused", "failed"]
    outcome_at: datetime | None = None
    processing_seconds: int = 30
    effect_scope: Literal["simulator_only"] = "simulator_only"


class DemoView(Closed):
    schema_version: Literal["DYNAMIC_DEMO_1"] = "DYNAMIC_DEMO_1"
    mode: Literal["simulation_sandbox"] = "simulation_sandbox"
    run_id: str
    revision: int
    unit_name: str = "Court séjour gériatrique"
    now: datetime
    speed: int
    completed: bool
    feed_enabled: bool
    snapshot: LiveSnapshot
    episode: ShadowEpisode | None
    can_apply: bool
    commands: tuple[CommandReceipt, ...]
    evaluation: Evaluation | None = None


class DemoSession:
    def __init__(self, seed: int = 7, monotonic: Callable[[], float] = time.monotonic) -> None:
        self.lock = threading.RLock()
        self.seed, self.monotonic = seed, monotonic
        self._initialize()

    def _initialize(self) -> None:
        self.run_id = uuid4().hex
        self.revision = 0
        self.speed = 0
        self.completed = False
        self.last_wall = self.monotonic()
        self.offered: ShadowEpisode | None = None
        self.used_plans: set[str] = set()
        self.requests: dict[str, str] = {}
        self.commands: dict[str, CommandReceipt] = {}
        self.feed = DeclaredFeed(lambda: self.engine.now)
        self.engine = HospitalSimulation(self.seed, self.feed.receive)
        self.engine.advance(30)  # Initial observed export arrives, no action or task is executed.

    def close(self) -> None:
        with self.lock:
            self.feed.store.close()

    def _sync(self) -> None:
        wall = self.monotonic()
        if self.speed and not self.completed:
            seconds = min(max(0, wall - self.last_wall) * self.speed, LIMIT - self.engine.second)
            self.engine.advance(seconds)
            if self.engine.second >= LIMIT:
                self.speed, self.completed = 0, True
        self.last_wall = wall

    def _view(self) -> DemoView:
        snapshot = self.feed.store.snapshot(self.engine.now)
        offered = self.offered
        valid = (
            offered is not None
            and not snapshot.issues
            and offered.assessment.snapshot.semantic_fingerprint == snapshot.semantic_fingerprint
            and self.engine.now < offered.assessment.expires_at
        )
        episode = offered if valid else None
        plan = episode.assessment.plan if episode else None
        can_apply = bool(
            not self.completed
            and plan is not None
            and plan.decision == "recommend"
            and plan.selected.kind in {"prioritize_cleaning", "reserve_bed"}
            and plan.plan_id not in self.used_plans
        )
        return DemoView(
            run_id=self.run_id,
            revision=self.revision,
            now=self.engine.now,
            speed=self.speed,
            completed=self.completed,
            feed_enabled=self.engine.feed_enabled,
            snapshot=snapshot,
            episode=episode,
            can_apply=can_apply,
            commands=tuple(self.commands.values()),
            evaluation=evaluate(self.engine.journal, self.engine.second)
            if self.completed
            else None,
        )

    def view(self) -> DemoView:
        with self.lock:
            self._sync()
            return self._view()

    def assess(self, options: PlanningOptions | None = None) -> ShadowEpisode:
        with self.lock:
            self._sync()
            if self.completed:
                raise ValueError("run_completed")
            if options is None:
                options = PlanningOptions(
                    horizon_minutes=120,
                    scenarios=16,
                    assumptions=Assumptions(cleaning_minutes=(15, 20, 25), load_multipliers=(1,)),
                )
            self.offered = self.feed.store.record_shadow(self.engine.now, options)
            return self.offered

    def _check_request(self, request: RunRequest) -> bool:
        if request.run_id != self.run_id:
            raise ValueError("run_replaced_refresh_required")
        content = json.dumps(request.model_dump(mode="json"), sort_keys=True)
        previous = self.requests.get(request.request_id)
        if previous is not None:
            if previous != content:
                raise ValueError("request_identity_conflict")
            return False
        if request.revision != self.revision:
            raise ValueError("revision_changed_refresh_required")
        return True

    def _remember(self, request: RunRequest) -> None:
        self.requests[request.request_id] = json.dumps(
            request.model_dump(mode="json"), sort_keys=True
        )
        self.revision += 1

    def control(self, request: ControlRequest) -> DemoView:
        with self.lock:
            self._sync()
            if not self._check_request(request):
                return self._view()
            if request.operation == "reset":
                self.feed.store.close()
                self._initialize()
                return self._view()
            if self.completed:
                raise ValueError("run_completed")
            if request.operation == "advance":
                if self.speed:
                    raise ValueError("pause_before_stepping")
                self.engine.advance(min(request.seconds, LIMIT - self.engine.second))
            elif request.operation == "play":
                self.speed = request.speed
            elif request.operation == "pause":
                self.speed = 0
            elif request.operation in {"disconnect", "reconnect"}:
                self.engine.feed_enabled = request.operation == "reconnect"
            elif request.operation == "finish":
                self.speed, self.completed = 0, True
            if self.engine.second >= LIMIT:
                self.speed, self.completed = 0, True
            self._remember(request)
            return self._view()

    def decide(self, request: DecisionRequest) -> DemoView:
        with self.lock:
            self._sync()
            if not self._check_request(request):
                return self._view()
            view = self._view()
            if not view.can_apply or view.episode is None:
                raise ValueError("proposal_expired_changed_or_consumed")
            plan = view.episode.assessment.plan
            assert plan is not None
            if (
                plan.plan_id != request.plan_id
                or view.snapshot.semantic_fingerprint != request.snapshot_fingerprint
            ):
                raise ValueError("proposal_state_mismatch")
            errors = action_errors(view.snapshot.state, plan.selected)
            if errors:
                raise ValueError("action_preconditions_changed")
            self.commands[request.request_id] = CommandReceipt(
                request_id=request.request_id,
                plan_id=plan.plan_id,
                at=self.engine.now,
                status="accepted" if request.accept else "refusal_recorded",
            )

            def outcome(status: str) -> None:
                self.commands[request.request_id] = CommandReceipt.model_validate(
                    {
                        **self.commands[request.request_id].model_dump(),
                        "status": status,
                        "outcome_at": self.engine.now,
                    }
                )

            self.engine.command(
                plan.selected.kind,
                plan.selected.bed_id or "",
                plan.selected.patient_id,
                request.accept,
                outcome,
            )
            self.used_plans.add(plan.plan_id)
            self._remember(request)
            return self._view()
