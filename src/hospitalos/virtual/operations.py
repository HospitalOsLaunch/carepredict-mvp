"""Hospital-wide command ledger and accountable, observation-confirmed work.

All identities here are explicitly fictional demo identities. Role checks are
server-side business checks, not authentication of a real hospital professional.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

from pydantic import Field, StrictBool, StrictInt, field_validator

from hospitalos.operational.contract import Closed, Identifier, instant
from hospitalos.simulator.engine import PhysicalPatient

from .clinical import CarePatient, ClinicalEngine
from .runtime import DecisionRecord

if TYPE_CHECKING:
    from .campus import CampusFleet


class Operation(Closed):
    request_id: Identifier
    revision: Annotated[StrictInt, Field(ge=0)]
    actor_id: Identifier
    kind: Literal[
        "place",
        "accept",
        "reject",
        "cancel",
        "remind",
        "assign",
        "capacity",
        "close_bed",
        "reopen_bed",
        "protect",
        "release_hold",
        "documents",
        "transport",
        "downstream",
        "cleaning",
        "plan_decision",
    ]
    unit_id: Identifier
    patient_id: Identifier | None = None
    target_unit: Identifier | None = None
    bed_id: Identifier | None = None
    task_id: Identifier | None = None
    owner_id: Identifier | None = None
    capacity: Annotated[StrictInt, Field(ge=0, le=40)] | None = None
    until: datetime | None = None
    reason: Annotated[str, Field(max_length=300)] = ""
    tokens: dict[str, str]
    plan_id: Identifier | None = None
    accept_plan: StrictBool = True

    @field_validator("until")
    @classmethod
    def utc_until(cls, value: datetime | None) -> datetime | None:
        return instant(value) if value is not None else None


class Operations:
    def __init__(self, fleet: CampusFleet, path: str) -> None:
        self.fleet = fleet
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS commands (seq INTEGER PRIMARY KEY, "
            "id TEXT UNIQUE, second REAL, request TEXT, payload TEXT, evidence TEXT)"
        )
        self.tasks: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.revision = 0

    def engine(self, unit_id: str) -> ClinicalEngine:
        return cast(ClinicalEngine, self.fleet.get(unit_id).engine)

    def staff(self) -> list[dict[str, str]]:
        return [
            {
                "id": "bm-camille",
                "name": "Camille · bed manager virtuel",
                "role": "bed_manager",
                "unit_id": "",
            },
            {
                "id": "bm-alex",
                "name": "Alex · bed manager virtuel",
                "role": "bed_manager",
                "unit_id": "",
            },
            *[
                {
                    "id": f"cadre-{key}",
                    "name": f"Cadre {u.config.unit_name} · virtuel",
                    "role": "cadre",
                    "unit_id": key,
                }
                for key, u in self.fleet.units.items()
            ],
            *[
                {
                    "id": f"service-{service}",
                    "name": f"Équipe {name} · virtuelle",
                    "role": "service",
                    "unit_id": "",
                }
                for service, name in (
                    ("documents", "documents"),
                    ("transport", "transport"),
                    ("downstream", "aval"),
                    ("cleaning", "hôtelière"),
                )
            ],
        ]

    def actor(self, identifier: str) -> dict[str, str]:
        return next((s for s in self.staff() if s["id"] == identifier), {})

    def commands(self) -> list[tuple[float, Operation, dict[str, Any]]]:
        return [
            (float(second), Operation.model_validate_json(request), json.loads(payload))
            for second, request, payload in self.db.execute(
                "SELECT second, request, payload FROM commands ORDER BY seq"
            )
        ]

    def current_tokens(self) -> dict[str, str]:
        return {
            key: unit.view().snapshot.semantic_fingerprint for key, unit in self.fleet.units.items()
        }

    def submit(self, request: Operation) -> dict[str, Any]:
        with self.fleet.lock:
            previous = self.db.execute(
                "SELECT request FROM commands WHERE id=?", (request.request_id,)
            ).fetchone()
            if previous:
                if Operation.model_validate_json(previous[0]) != request:
                    raise ValueError("request_identity_conflict")
                return self.view()
            self.fleet.sync(plan=False)
            if request.revision != self.revision:
                raise ValueError("workspace_changed_refresh_required")
            actor = self.actor(request.actor_id)
            if not actor or request.unit_id not in self.fleet.units:
                raise ValueError("unknown_actor_or_unit")
            if request.until and not self.fleet.now < request.until <= self.fleet.now + timedelta(
                hours=72
            ):
                raise ValueError("expiry_must_be_within_next_72_hours")
            payload = self.validate(request, actor)
            second = self.fleet.second
            evidence = {
                key: self.fleet.units[key].view().snapshot.model_dump(mode="json")
                for key in {request.unit_id, request.target_unit}
                if key in self.fleet.units
            }
            # One durable event before any physical effect. Replay starts before the first event.
            with self.db:
                self.db.execute(
                    "INSERT INTO commands (id, second, request, payload, evidence) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        request.request_id,
                        second,
                        request.model_dump_json(),
                        json.dumps(payload),
                        json.dumps(evidence),
                    ),
                )
            try:
                self.apply(request, payload, second)
            except Exception:
                self.fleet.errors.update(
                    dict.fromkeys(self.fleet.units, "hospital_command_replay_required")
                )
                raise
            return self.view()

    def _fresh(self, request: Operation, keys: set[str]) -> None:
        for key in keys:
            unit = self.fleet.get(key)
            snapshot = unit.view().snapshot
            if snapshot.issues or request.tokens.get(key) != snapshot.semantic_fingerprint:
                raise ValueError("observation_changed_refresh_required")

    def validate(self, r: Operation, actor: dict[str, str]) -> dict[str, Any]:
        engine = self.engine(r.unit_id)
        if r.kind in {"accept", "reject", "cancel", "remind", "assign"}:
            task = self.tasks.get(r.task_id or "")
            if not task or task["unit_id"] != r.unit_id:
                raise ValueError("task_not_in_unit")
            if task["status"] in {"completed", "rejected", "cancelled", "failed"}:
                raise ValueError("task_already_closed")
            if r.kind in {"accept", "reject"} and r.actor_id != task["owner_id"]:
                raise ValueError("recipient_acceptance_required")
            if r.kind not in {"accept", "reject"} and not (
                actor["role"] == "bed_manager"
                or actor["unit_id"] == r.unit_id
                or r.actor_id == task["owner_id"]
            ):
                raise ValueError("task_role_forbidden")
            if r.kind == "cancel" and task["status"] != "requested":
                raise ValueError("cannot_cancel_work_in_progress")
            if r.kind in {"reject", "cancel", "remind", "assign"} and not r.reason.strip():
                raise ValueError("reason_required")
            if r.kind == "assign":
                owner = self.actor(r.owner_id or "")
                if not owner or (
                    task["kind"] == "place" and owner["id"] != f"cadre-{task['target_unit']}"
                ):
                    raise ValueError("invalid_recipient")
                if task["kind"] != "place" and owner["id"] not in {
                    f"service-{task['kind']}",
                    f"cadre-{r.unit_id}",
                }:
                    raise ValueError("invalid_recipient")
            if r.kind == "accept":
                if task["status"] != "requested":
                    raise ValueError("task_already_accepted")
                if task["kind"] == "place":
                    self._fresh(r, {r.unit_id, task["target_unit"]})
                    self._placement(
                        task["unit_id"], task["target_unit"], task["patient_id"], task["bed_id"]
                    )
                else:
                    self._fresh(r, {r.unit_id})
            return {}
        if actor["role"] not in {"bed_manager", "cadre"}:
            raise ValueError("operator_role_required")
        if actor["role"] == "cadre" and actor["unit_id"] != r.unit_id:
            raise ValueError("unit_role_forbidden")
        self._fresh(r, {r.unit_id} | ({r.target_unit} if r.target_unit else set()))
        if r.kind in {"capacity", "close_bed", "reopen_bed"}:
            if actor["role"] != "cadre" or actor["unit_id"] != r.unit_id or not r.reason.strip():
                raise ValueError("unit_manager_and_reason_required")
            if r.kind == "capacity":
                if r.capacity is None or r.capacity > engine.config.beds or r.until is None:
                    raise ValueError("invalid_capacity")
            else:
                bed = engine.beds.get(r.bed_id or "")
                if bed is None:
                    raise ValueError("unknown_bed")
                if r.kind == "close_bed" and (
                    bed.occupant or bed.reserved_for or bed.id in engine.holds or r.until is None
                ):
                    raise ValueError("bed_committed_or_missing_expiry")
            return {}
        if r.kind == "place":
            if not r.target_unit or not r.patient_id or not r.bed_id:
                raise ValueError("placement_arguments_required")
            self._placement(r.unit_id, r.target_unit, r.patient_id, r.bed_id)
            if any(
                t["kind"] == "place"
                and t["patient_id"] == r.patient_id
                and t["status"] not in {"completed", "rejected", "cancelled", "failed"}
                for t in self.tasks.values()
            ):
                raise ValueError("placement_already_requested")
            return {}
        if r.kind in {"protect", "release_hold"}:
            if not r.reason.strip() or not r.bed_id or r.bed_id not in engine.beds:
                raise ValueError("bed_and_reason_required")
            if r.kind == "protect":
                scheduled = next(
                    (
                        a
                        for a in engine.schedule(
                            self.fleet.now, self.fleet.now + timedelta(hours=48)
                        )
                        if a["id"] == r.patient_id
                    ),
                    None,
                )
                bed = engine.beds[r.bed_id]
                if (
                    not scheduled
                    or bed.occupant
                    or bed.reserved_for
                    or not bed.opened
                    or bed.hygiene != "ready"
                    or bed.id in engine.holds
                ):
                    raise ValueError("admission_or_bed_unavailable")
                if scheduled["oxygen"] and not bed.oxygen:
                    raise ValueError("incompatible_bed")
                committed = sum(
                    b.occupant is not None or b.reserved_for is not None or b.id in engine.holds
                    for b in engine.beds.values()
                )
                if committed >= engine.staffed_capacity:
                    raise ValueError("no_staffed_capacity")
                if r.patient_id in engine.holds.values():
                    raise ValueError("admission_already_protected")
            elif r.bed_id not in engine.holds:
                raise ValueError("no_hold")
            return {}
        if r.kind == "plan_decision":
            view = self.fleet.units[r.unit_id].view()
            plan = view.episode.assessment.plan if view.episode else None
            if (
                not view.can_decide
                or not plan
                or r.plan_id != plan.plan_id
                or (not r.accept_plan and not r.reason.strip())
            ):
                raise ValueError("proposal_changed_refresh_required")
            return {
                "action": plan.selected.model_dump(),
                "plan_id": plan.plan_id,
                "run_id": view.run_id,
            }
        if r.kind == "cleaning":
            bed = engine.beds.get(r.bed_id or "")
            if not bed or bed.occupant or not bed.opened or bed.hygiene == "ready":
                raise ValueError("cleaning_not_required")
        else:
            patient = engine.patients.get(r.patient_id or "")
            if (
                not isinstance(patient, CarePatient)
                or patient.status != "admitted"
                or not patient.discharge_planned
            ):
                raise ValueError("discharge_not_in_preparation")
            if r.kind in {"transport", "downstream"} and not getattr(patient, f"{r.kind}_required"):
                raise ValueError("service_not_required")
            if getattr(patient, f"{r.kind}_ready"):
                raise ValueError("service_already_confirmed")
        if any(
            t["kind"] == r.kind
            and t["unit_id"] == r.unit_id
            and t["patient_id"] == r.patient_id
            and t["bed_id"] == r.bed_id
            and t["status"] not in {"completed", "rejected", "cancelled", "failed"}
            for t in self.tasks.values()
        ):
            raise ValueError("task_already_open")
        return {}

    def _placement(self, source: str, target: str, patient_id: str, bed_id: str) -> None:
        a, b = self.engine(source), self.engine(target)
        patient, bed = a.patients.get(patient_id), b.beds.get(bed_id)
        if not patient or patient.status != "waiting" or not bed:
            raise ValueError("patient_or_bed_changed")
        if not b.compatible(patient, bed):
            raise ValueError("incompatible_bed")
        protected = next((key for key, owner in b.holds.items() if owner == patient_id), None)
        if protected is not None and bed_id != protected:
            raise ValueError("use_or_release_protected_bed")
        if any(
            x.reserved_for == patient_id
            for unit in self.fleet.units.values()
            for x in unit.engine.beds.values()
        ):
            raise ValueError("patient_already_reserved")
        committed = sum(
            x.occupant is not None
            or x.reserved_for is not None
            or (x.id in b.holds and b.holds[x.id] != patient_id)
            for x in b.beds.values()
        )
        if (
            not bed.opened
            or bed.hygiene != "ready"
            or bed.occupant
            or bed.reserved_for
            or b.held_for_other(bed_id, patient_id)
            or committed >= b.staffed_capacity
        ):
            raise ValueError("bed_or_capacity_unavailable")

    def _event(
        self, task: dict[str, Any], status: str, actor: str, at: datetime, note: str = ""
    ) -> None:
        task["status"] = status
        task["events"].append(
            {"at": at.isoformat(), "actor": actor, "status": status, "note": note}
        )
        if status in {"completed", "failed", "rejected", "cancelled"}:
            unit = self.fleet.units[task["unit_id"]]
            record = unit.records.get(task["id"])
            if record:
                unit.records[task["id"]] = record.model_copy(
                    update={
                        "status": "executed" if status == "completed" else "failed",
                        "outcome_at": at,
                    }
                )
                unit.revision += 1

    def apply(self, r: Operation, payload: dict[str, Any], second: float) -> None:
        at = self.fleet.epoch + timedelta(seconds=second)
        engine = self.engine(r.unit_id)
        self.revision += 1
        self.events.append(
            {
                "id": r.request_id,
                "at": at.isoformat(),
                "actor_id": r.actor_id,
                "kind": r.kind,
                "unit_id": r.unit_id,
                "reason": r.reason,
                "capacity": r.capacity,
                "until": r.until.isoformat() if r.until else None,
                "bed_id": r.bed_id,
                "patient_id": r.patient_id,
            }
        )
        if r.kind in {"accept", "reject", "cancel", "remind", "assign"}:
            task = self.tasks[r.task_id or ""]
            if r.kind == "accept":
                self._start(task, r.actor_id, at)
            elif r.kind in {"reject", "cancel"}:
                if task["kind"] == "place":
                    self.engine(task["unit_id"]).pending_placements.discard(task["patient_id"])
                self._event(
                    task,
                    "rejected" if r.kind == "reject" else "cancelled",
                    r.actor_id,
                    at,
                    r.reason,
                )
            elif r.kind == "remind":
                task["reminders"] += 1
                self._event(task, task["status"], r.actor_id, at, f"Relance : {r.reason}")
            else:
                task["owner_id"] = r.owner_id
                self._event(task, task["status"], r.actor_id, at, f"Transmission : {r.reason}")
            return
        if r.kind == "capacity":
            assert r.capacity is not None and r.until is not None
            engine.set_capacity(r.capacity, r.until, r.reason)
            return
        if r.kind == "close_bed":
            assert r.bed_id and r.until
            engine.close_bed(r.bed_id, r.until, r.reason)
            return
        if r.kind == "reopen_bed":
            assert r.bed_id
            engine.reopen_bed(r.bed_id)
            return
        if r.kind in {"protect", "release_hold"}:
            assert r.bed_id
            if r.kind == "protect":
                assert r.patient_id
                engine.holds[r.bed_id] = r.patient_id
            else:
                engine.holds.pop(r.bed_id, None)
            return
        if r.kind == "plan_decision":
            unit = self.fleet.units[r.unit_id]
            action = payload["action"]
            record = DecisionRecord(
                request_id=r.request_id,
                plan_id=payload["plan_id"],
                at=at,
                second=second,
                action=action["kind"],
                bed_id=action["bed_id"],
                patient_id=action["patient_id"],
                accepted=r.accept_plan,
                reason=r.reason,
                actor=self.actor(r.actor_id)["name"],
                status="accepted" if r.accept_plan else "refusal_recorded",
            )
            unit.records[r.request_id] = record
            unit.used.add(record.plan_id)
            unit.revision += 1
            if not r.accept_plan:
                unit._dispatch(record)
                return
            if action["kind"] == "reserve_bed":
                r = r.model_copy(
                    update={
                        "kind": "place",
                        "target_unit": r.unit_id,
                        "patient_id": action["patient_id"],
                        "bed_id": action["bed_id"],
                    }
                )
            else:
                r = r.model_copy(update={"kind": "cleaning", "bed_id": action["bed_id"]})
        owner = f"cadre-{r.target_unit}" if r.kind == "place" else f"service-{r.kind}"
        task = {
            "id": r.request_id,
            "kind": r.kind,
            "unit_id": r.unit_id,
            "target_unit": r.target_unit,
            "patient_id": r.patient_id,
            "bed_id": r.bed_id,
            "owner_id": owner,
            "requested_by": r.actor_id,
            "created_at": at.isoformat(),
            "due_at": (
                r.until or at + timedelta(minutes=30 if r.kind == "place" else 90)
            ).isoformat(),
            "status": "requested",
            "events": [],
            "reminders": 0,
        }
        if r.kind == "place":
            engine.pending_placements.add(r.patient_id or "")
        self.tasks[r.request_id] = task
        self._event(task, "requested", r.actor_id, at, r.reason)

    def _start(self, task: dict[str, Any], actor: str, at: datetime) -> None:
        unit_id = task["unit_id"]
        engine = self.engine(unit_id)
        try:
            if task["kind"] == "place":
                destination = self.engine(task["target_unit"])
                self._placement(unit_id, task["target_unit"], task["patient_id"], task["bed_id"])
                patient = engine.patients[task["patient_id"]]
                if engine is not destination:
                    del engine.patients[patient.id]
                    destination.patients[patient.id] = patient
                if not destination._reserve(patient.id, task["bed_id"], coordinated=True):
                    if engine is not destination:
                        engine.patients[patient.id] = destination.patients.pop(patient.id)
                    raise ValueError("placement_failed")
                engine.pending_placements.discard(patient.id)
                if engine is not destination:
                    engine._record("transferred_out", patient.id)
                    destination._record("transferred_in", patient.id)
            elif task["kind"] == "cleaning":
                bed = engine.beds[task["bed_id"]]
                if not bed.opened or bed.occupant:
                    raise ValueError("cleaning_preconditions_changed")
                if bed.hygiene == "dirty" and bed.id not in engine.priorities:
                    engine.priorities.append(bed.id)
            else:
                service_patient = engine.patients.get(task["patient_id"])
                if (
                    not isinstance(service_patient, CarePatient)
                    or service_patient.status != "admitted"
                ):
                    raise ValueError("patient_no_longer_admitted")
                engine.request_service(service_patient.id, task["kind"])
            self._event(task, "in_progress", actor, at, "Demande acceptée par le destinataire")
        except (KeyError, ValueError) as error:
            engine.pending_placements.discard(task["patient_id"] or "")
            self._event(task, "failed", actor, at, str(error))

    def tick(self, at: datetime) -> None:
        for task in self.tasks.values():
            if (
                task["status"] == "requested"
                and task["kind"] == "place"
                and at > datetime.fromisoformat(task["due_at"])
            ):
                self.engine(task["unit_id"]).pending_placements.discard(task["patient_id"])
                self._event(
                    task,
                    "failed",
                    "systeme-virtuel",
                    at,
                    "Accord non reçu avant l’échéance ; patient remis en file",
                )
            if (
                task["status"] == "requested"
                and task["kind"] != "place"
                and task["owner_id"].startswith("service-")
                and at >= datetime.fromisoformat(task["created_at"]) + timedelta(seconds=60)
            ):
                self._start(task, task["owner_id"], at)
            if task["status"] != "in_progress":
                continue
            unit = self.fleet.units[
                task["target_unit"] if task["kind"] == "place" else task["unit_id"]
            ]
            frame = unit.engine.observed
            if frame is None:
                continue
            patient = next((p for p in frame.patients if p.id == task["patient_id"]), None)
            bed = next((b for b in frame.beds if b.id == task["bed_id"]), None)
            complete = (
                task["kind"] == "place"
                and patient is not None
                and patient.status == "admitted"
                and patient.bed == task["bed_id"]
            )
            if task["kind"] == "cleaning":
                complete = bed is not None and bed.hygiene == "ready"
            if task["kind"] in {"documents", "transport", "downstream"}:
                complete = isinstance(patient, CarePatient) and bool(
                    getattr(patient, f"{task['kind']}_ready")
                )
            if complete:
                self._event(
                    task,
                    "completed",
                    "observation-si",
                    at,
                    f"Résultat observé à {frame.observed_at.isoformat()}",
                )
            elif (
                task["kind"] == "place"
                and bed
                and not bed.reserved_for
                and (not patient or patient.status != "admitted")
                and at >= datetime.fromisoformat(task["events"][-1]["at"]) + timedelta(minutes=3)
            ):
                self._event(
                    task,
                    "failed",
                    "observation-si",
                    at,
                    "Installation non confirmée ; revoir la capacité",
                )

    def options(self, unit_id: str, patient: PhysicalPatient) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        for target, runtime in self.fleet.units.items():
            snapshot = runtime.view().snapshot
            committed = sum(
                b.occupant is not None
                or b.reserved_for is not None
                or (
                    b.id in self.engine(target).holds
                    and self.engine(target).holds[b.id] != patient.id
                )
                for b in snapshot.state.beds
            )
            capacity = snapshot.state.units[0].staffed_beds or 0
            for bed in snapshot.state.beds:
                reasons: list[str] = []
                if not isinstance(patient, CarePatient) or target not in patient.compatible_units:
                    reasons.append("Unité non déclarée compatible")
                if patient.oxygen and "oxygen" not in bed.capabilities:
                    reasons.append("Oxygène requis")
                if (
                    isinstance(patient, CarePatient)
                    and patient.isolation
                    and "isolation" not in bed.capabilities
                ):
                    reasons.append("Chambre d’isolement requise")
                holds = self.engine(target).holds
                own_hold = holds.get(bed.id) == patient.id
                if (
                    bed.state != "clean" and not (own_hold and bed.state == "closed")
                ) or bed.reserved_for:
                    reasons.append("Lit occupé, fermé, à nettoyer ou protégé")
                if patient.id in holds.values() and not own_hold:
                    reasons.append("Utiliser ou lever le lit déjà protégé pour ce patient")
                if committed >= capacity:
                    reasons.append("Capacité du poste atteinte")
                if snapshot.issues or target in self.fleet.errors:
                    reasons.append("Observation indisponible ou périmée")
                options.append(
                    {
                        "unit_id": target,
                        "bed_id": bed.id,
                        "eligible": not reasons,
                        "reasons": reasons,
                    }
                )
        return sorted(options, key=lambda o: (not o["eligible"], o["unit_id"], o["bed_id"]))

    def view(self) -> dict[str, Any]:
        patients: list[dict[str, Any]] = []
        latest: dict[str, tuple[datetime, str]] = {}
        for unit_key, runtime in self.fleet.units.items():
            frame = runtime.engine.observed
            if frame:
                for p in frame.patients:
                    if p.id not in latest or frame.observed_at > latest[p.id][0]:
                        latest[p.id] = (frame.observed_at, unit_key)
        discharges: list[dict[str, Any]] = []
        admissions: list[dict[str, Any]] = []
        constraints: list[dict[str, Any]] = []
        forecasts: list[dict[str, Any]] = []
        for key in self.fleet.units:
            engine = self.engine(key)
            frame = engine.observed
            if frame:
                for patient in frame.patients:
                    if patient.status == "waiting" and latest[patient.id][1] == key:
                        patients.append(
                            {
                                "id": patient.id,
                                "unit_id": key,
                                "waiting_since": (
                                    engine.epoch + timedelta(seconds=patient.since)
                                ).isoformat(),
                                "oxygen": patient.oxygen,
                                "isolation": getattr(patient, "isolation", False),
                                "programmed": getattr(patient, "programmed", False),
                                "options": self.options(key, patient),
                            }
                        )
                    if (
                        isinstance(patient, CarePatient)
                        and patient.status == "admitted"
                        and patient.discharge_planned
                    ):
                        discharges.append(
                            {
                                "id": patient.id,
                                "unit_id": key,
                                "phase": "authorized"
                                if patient.cleared
                                else "awaiting_authorization",
                                "documents_ready": patient.documents_ready,
                                "transport_required": patient.transport_required,
                                "transport_ready": patient.transport_ready,
                                "downstream_required": patient.downstream_required,
                                "downstream_ready": patient.downstream_ready,
                                "observed_at": frame.observed_at.isoformat(),
                            }
                        )
            for entry in engine.schedule(self.fleet.now, self.fleet.now + timedelta(hours=48)):
                entry["protected_bed"] = next(
                    (bed for bed, patient in engine.holds.items() if patient == entry["id"]), None
                )
                admissions.append(entry)
            constraints.append(
                {
                    "unit_id": key,
                    "capacity": engine.staffed_capacity,
                    "physical_beds": engine.config.beds,
                    "reason": engine.capacity_reason,
                    "until": engine.capacity_until.isoformat() if engine.capacity_until else None,
                    "closed_beds": [
                        {"bed_id": bed, "until": value[1].isoformat(), "reason": value[2]}
                        for bed, value in engine.closures.items()
                    ],
                    "holds": [
                        {"bed_id": bed, "patient_id": patient}
                        for bed, patient in engine.holds.items()
                    ],
                }
            )
            if self.fleet.histories[key].model:
                history = self.fleet.histories[key].summary()
                forecasts.append(
                    {
                        "unit_id": key,
                        "capacity": engine.staffed_capacity,
                        "forecasts": history.get("shift_forecasts", []),
                        "planned_next_shift": sum(
                            a["unit_id"] == key
                            and datetime.fromisoformat(a["at"])
                            <= self.fleet.now + timedelta(hours=8)
                            for a in admissions
                        ),
                        "discharges_to_prepare": sum(d["unit_id"] == key for d in discharges),
                    }
                )
        tasks = [
            {
                **t,
                "overdue": t["status"] in {"requested", "in_progress"}
                and self.fleet.now > datetime.fromisoformat(t["due_at"]),
            }
            for t in self.tasks.values()
        ]
        return {
            "schema_version": "WORKPLACE_1",
            "hospital_id": "H1",
            "now": self.fleet.now.isoformat(),
            "revision": self.revision,
            "tokens": self.current_tokens(),
            "staff": self.staff(),
            "patients": sorted(patients, key=lambda p: p["waiting_since"]),
            "discharges": discharges,
            "admissions": sorted(admissions, key=lambda a: a["at"]),
            "constraints": constraints,
            "tasks": tasks[-500:],
            "events": self.events[-500:],
            "forecasts": forecasts,
        }

    def close(self) -> None:
        self.db.close()
