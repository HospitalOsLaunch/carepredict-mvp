"""Isolated hospital sessions, durable command intents and autonomous fleet clock."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import uuid4

import structlog
from pydantic import Field, StrictBool, StrictInt, model_validator

from hospitalos.hybrid.live_models import LiveSnapshot, PlanningOptions, ShadowEpisode
from hospitalos.hybrid.models import action_errors
from hospitalos.hybrid.simulation import Assumptions
from hospitalos.operational.contract import Closed, Identifier
from hospitalos.simulator.engine import START, Frame

from .config import HospitalConfig, hospitals
from .engine import VirtualEngine
from .feed import VirtualFeed


class Decision(Closed):
    hospital_id: Identifier
    unit_id: Identifier | None = None
    run_id: Identifier
    request_id: Identifier
    revision: Annotated[StrictInt, Field(ge=0)]
    plan_id: Identifier
    snapshot_fingerprint: Identifier
    accept: StrictBool
    reason: Annotated[str, Field(max_length=300)] = ""

    @model_validator(mode="after")
    def refusal_reason(self) -> Self:
        if not self.accept and not self.reason.strip():
            raise ValueError("refusal_reason_required")
        return self


class DecisionRecord(Closed):
    request_id: str
    plan_id: str
    at: datetime
    second: float
    action: str
    bed_id: str | None
    patient_id: str | None
    accepted: bool
    reason: str
    actor: str = "Équipe de garde"
    status: Literal["accepted", "refusal_recorded", "executed", "refused", "failed"]
    outcome_at: datetime | None = None


class Activity(Closed):
    admissions: int = 0
    departures: int = 0
    arrivals: int = 0


class HospitalView(Closed):
    schema_version: Literal["HOSPITAL_WORKSPACE_1"] = "HOSPITAL_WORKSPACE_1"
    hospital_id: str
    hospital_name: str
    unit_id: str = "geriatrie"
    unit_name: str
    run_id: str
    revision: int
    now: datetime
    clock_rate: float
    synthetic: Literal[True] = True
    snapshot: LiveSnapshot
    episode: ShadowEpisode | None
    can_decide: bool
    decisions: tuple[DecisionRecord, ...]
    activity: Activity


class HospitalRuntime:
    def __init__(
        self,
        config: HospitalConfig,
        seed: int = 7,
        path: str = ":memory:",
        clock_rate: float = 12,
        *,
        epoch: datetime = START,
        warmup_seconds: float = 0,
        history_receiver: Callable[[Frame], None] | None = None,
        engine_type: type[VirtualEngine] = VirtualEngine,
        managed: bool = False,
    ) -> None:
        self.lock = threading.RLock()
        self.config, self.seed, self.clock_rate = config, seed, clock_rate
        self.history_receiver = history_receiver
        self.projection_from = max(0, warmup_seconds - 120)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, request TEXT NOT NULL, "
            "record TEXT NOT NULL, evidence TEXT NOT NULL);"
        )
        identity = json.dumps(
            {
                "engine": "VIRTUAL_ENGINE_1",
                "config": config.model_dump(),
                "seed": seed,
                **({"epoch": epoch.isoformat()} if epoch != START else {}),
                **({"mechanics": "WORKPLACE_1"} if managed else {}),
            },
            sort_keys=True,
        )
        old = self.db.execute("SELECT value FROM meta WHERE key='identity'").fetchone()
        if old and old[0] != identity:
            self.db.close()
            raise ValueError("virtual_state_configuration_changed_use_another_state_directory")
        run = self.db.execute("SELECT value FROM meta WHERE key='run'").fetchone()
        self.run_id = str(run[0]) if run else uuid4().hex
        saved = self.db.execute("SELECT value FROM meta WHERE key='second'").fetchone()
        target = max(
            float(saved[0]) if saved and not managed else config.delivery_seconds, warmup_seconds
        )
        self.revision = 0
        self.offered: ShadowEpisode | None = None
        self.assessed_second = -1000.0
        self.used: set[str] = set()
        self.records: dict[str, DecisionRecord] = {}
        self.observed_status: dict[str, str] = {}
        self.activity = Activity()
        self.feed = VirtualFeed(lambda: self.engine.now, config, epoch=epoch)
        self.engine = engine_type(config, seed, self._receive, epoch=epoch)
        self.replaying = True
        try:
            # Intents are replayed in original insertion order, including equal timestamps.
            for request_json, record_json in self.db.execute(
                "SELECT request, record FROM decisions WHERE ?=0 ORDER BY rowid", (int(managed),)
            ):
                request = Decision.model_validate_json(request_json)
                record = DecisionRecord.model_validate_json(record_json)
                self._advance_to(record.second)
                self.records[record.request_id] = record.model_copy(
                    update={
                        "status": "accepted" if record.accepted else "refusal_recorded",
                        "outcome_at": None,
                    }
                )
                self.used.add(record.plan_id)
                self.revision += 1
                self._dispatch(self.records[record.request_id])
                if request.run_id != self.run_id:
                    raise ValueError("virtual_corrupted_run_identity")
            self._advance_to(target)
        except Exception:
            self.feed.store.close()
            self.db.close()
            raise
        finally:
            self.replaying = False
        with self.db:
            self.db.executemany(
                "INSERT OR REPLACE INTO meta VALUES (?, ?)",
                (("identity", identity), ("run", self.run_id)),
            )
        self.checkpoint()

    def _advance_to(self, second: float) -> None:
        if second < self.engine.second:
            raise ValueError("virtual_corrupted_clock")
        while second > self.engine.second:
            self.engine.advance(min(86400, second - self.engine.second))

    def _receive(self, frame: Frame) -> None:
        if self.history_receiver is not None:
            self.history_receiver(frame)
        if self.engine.second < self.projection_from:
            return
        first = not self.observed_status
        counts = self.activity.model_dump()
        for patient in frame.patients:
            before = self.observed_status.get(patient.id)
            if not first:
                if before is None and patient.status == "waiting":
                    counts["arrivals"] += 1
                if before == "waiting" and patient.status == "admitted":
                    counts["admissions"] += 1
                if before == "admitted" and patient.status == "departed":
                    counts["departures"] += 1
            self.observed_status[patient.id] = patient.status
        self.feed.receive(frame)
        self.activity = Activity(**counts)

    def advance(self, seconds: float, *, plan: bool = True) -> None:
        with self.lock:
            self.engine.advance(seconds)
            if plan:
                self.assess()

    def assess(self, force: bool = False) -> None:
        with self.lock:
            if not force and self.engine.second - self.assessed_second < 60:
                return
            snapshot = self.feed.store.snapshot(self.engine.now)
            if self._valid(snapshot) and self.offered is not None:
                return
            self.assessed_second = self.engine.second
            if snapshot.issues:
                self.offered = None
                return
            # Independent planning assumptions: the current hospital's realized draws are hidden.
            self.offered = self.feed.store.record_shadow(
                self.engine.now,
                PlanningOptions(
                    horizon_minutes=120,
                    scenarios=8,
                    seed=7,
                    assumptions=Assumptions(cleaning_minutes=(15, 20, 25), load_multipliers=(1,)),
                ),
            )

    def _valid(self, snapshot: LiveSnapshot) -> bool:
        return bool(
            self.offered is not None
            and not snapshot.issues
            and self.engine.now < self.offered.assessment.expires_at
            and snapshot.semantic_fingerprint
            == self.offered.assessment.snapshot.semantic_fingerprint
        )

    def view(self) -> HospitalView:
        with self.lock:
            snapshot = self.feed.store.snapshot(self.engine.now)
            episode = self.offered if self._valid(snapshot) else None
            plan = episode.assessment.plan if episode else None
            return HospitalView(
                hospital_id=self.config.hospital_id,
                hospital_name=self.config.name,
                unit_id=self.config.unit_id,
                unit_name=self.config.unit_name,
                run_id=self.run_id,
                revision=self.revision,
                now=self.engine.now,
                clock_rate=self.clock_rate,
                snapshot=snapshot,
                episode=episode,
                can_decide=bool(
                    plan
                    and plan.decision == "recommend"
                    and plan.plan_id not in self.used
                    and plan.selected.kind in {"prioritize_cleaning", "reserve_bed"}
                ),
                decisions=tuple(self.records.values())[-50:],
                activity=self.activity,
            )

    def decide(self, request: Decision) -> HospitalView:
        with self.lock:
            if request.hospital_id != self.config.hospital_id or request.run_id != self.run_id:
                raise ValueError("hospital_or_run_mismatch")
            if request.unit_id is not None and request.unit_id != self.config.unit_id:
                raise ValueError("unit_mismatch")
            existing = self.db.execute(
                "SELECT request FROM decisions WHERE id=?", (request.request_id,)
            ).fetchone()
            if existing:
                if Decision.model_validate_json(existing[0]) != request:
                    raise ValueError("request_identity_conflict")
                return self.view()
            view = self.view()
            if request.revision != self.revision or not view.can_decide or view.episode is None:
                raise ValueError("proposal_changed_refresh_required")
            plan = view.episode.assessment.plan
            assert plan is not None
            if (
                request.plan_id != plan.plan_id
                or request.snapshot_fingerprint != view.snapshot.semantic_fingerprint
                or action_errors(view.snapshot.state, plan.selected)
            ):
                raise ValueError("proposal_state_mismatch")
            record = DecisionRecord(
                request_id=request.request_id,
                plan_id=plan.plan_id,
                at=self.engine.now,
                second=self.engine.second,
                action=plan.selected.kind,
                bed_id=plan.selected.bed_id,
                patient_id=plan.selected.patient_id,
                accepted=request.accept,
                reason=request.reason.strip(),
                status="accepted" if request.accept else "refusal_recorded",
            )
            # Persist intent and evidence before dispatch; restart replays it once.
            with self.db:
                self.db.execute(
                    "INSERT INTO decisions VALUES (?, ?, ?, ?)",
                    (
                        request.request_id,
                        request.model_dump_json(),
                        record.model_dump_json(),
                        view.episode.model_dump_json(),
                    ),
                )
                self.db.execute(
                    "INSERT OR REPLACE INTO meta VALUES ('second', ?)", (str(self.engine.second),)
                )
            self.records[record.request_id] = record
            self.revision += 1
            self.used.add(plan.plan_id)
            self._dispatch(record)
            return self.view()

    def _dispatch(self, record: DecisionRecord) -> None:
        def outcome(status: str) -> None:
            updated = DecisionRecord.model_validate(
                {
                    **self.records[record.request_id].model_dump(),
                    "status": status,
                    "outcome_at": self.engine.now,
                }
            )
            self.records[record.request_id] = updated
            # Outcome and clock persist together; replay reconstructs acknowledgements.

        self.engine.command(
            record.action, record.bed_id or "", record.patient_id, record.accepted, outcome
        )

    def checkpoint(self) -> None:
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO meta VALUES ('second', ?)", (str(self.engine.second),)
            )
            for record in self.records.values():
                self.db.execute(
                    "UPDATE decisions SET record=? WHERE id=?",
                    (record.model_dump_json(), record.request_id),
                )

    def close(self) -> None:
        with self.lock:
            self.checkpoint()
            self.feed.store.close()
            self.db.close()


class VirtualFleet:
    def __init__(
        self,
        state_dir: Path | None = None,
        seed: int = 7,
        clock_rate: float = 12,
        configs: tuple[HospitalConfig, ...] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.monotonic, self.clock_rate = monotonic, clock_rate
        self.errors: dict[str, str] = {}
        self.units: dict[str, HospitalRuntime] = {}
        self.file_lock = None
        if not 0 < clock_rate <= 60:
            raise ValueError("clock_rate_between_zero_and_60_required")
        selected = configs if configs is not None else hospitals()
        if not selected or len({c.hospital_id for c in selected}) != len(selected):
            raise ValueError("unique_hospital_ids_required")
        if state_dir is not None:
            import fcntl

            state_dir.mkdir(parents=True, exist_ok=True)
            self.file_lock = (state_dir / "runtime.lock").open("a")
            try:
                fcntl.flock(self.file_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                self.file_lock.close()
                raise ValueError("virtual_hospitals_already_running_stop_previous_demo") from error
        try:
            for config in selected:
                # Use a digest for paths, including custom developer configuration.
                import hashlib

                filename = hashlib.sha256(config.hospital_id.encode()).hexdigest()[:20] + ".sqlite"
                path = str(state_dir / filename) if state_dir is not None else ":memory:"
                self.units[config.hospital_id] = HospitalRuntime(config, seed, path, clock_rate)
        except Exception:
            for unit in self.units.values():
                unit.close()
            if self.file_lock:
                self.file_lock.close()
            raise

    def start(self) -> None:
        if self.thread is not None:
            return
        for unit in self.units.values():
            unit.assess(force=True)
        self.thread = threading.Thread(target=self._work, name="virtual-hospitals", daemon=True)
        self.thread.start()

    def _work(self) -> None:
        previous = self.monotonic()
        checkpoint_at = previous
        while not self.stop_event.wait(0.5):
            now = self.monotonic()
            elapsed = max(0, now - previous)
            # Laptop sleep and backend downtime pause the virtual world.
            if elapsed > 300:
                elapsed = 0
            previous = now
            for key, unit in self.units.items():
                if key in self.errors:
                    continue
                try:
                    unit.advance(elapsed * self.clock_rate)
                    if now - checkpoint_at >= 5:
                        unit.checkpoint()
                except Exception:
                    self.errors[key] = "virtual_hospital_unavailable"
                    structlog.get_logger().exception("virtual_hospital_failed", hospital=key)
            if now - checkpoint_at >= 5:
                checkpoint_at = now

    def get(self, hospital_id: str) -> HospitalRuntime:
        if hospital_id not in self.units:
            raise KeyError(hospital_id)
        if hospital_id in self.errors:
            raise RuntimeError(self.errors[hospital_id])
        return self.units[hospital_id]

    def close(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join()  # Owned thread completes before SQLite handles close.
        for unit in self.units.values():
            unit.close()
        if self.file_lock:
            self.file_lock.close()
