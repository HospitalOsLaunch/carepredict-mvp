"""One multi-unit hospital, continuous UTC timeline, Paris presentation, durable history."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from .clinical import ClinicalEngine
from .config import HospitalConfig
from .history import History
from .operations import Operations
from .runtime import HospitalRuntime


def campus_units() -> tuple[HospitalConfig, ...]:
    return tuple(
        HospitalConfig(
            hospital_id="H1",
            name="Hôpital Saint-Clair · virtuel",
            unit_id=unit_id,
            unit_name=name,
            beds=beds,
            staffed_beds=beds,
            initially_occupied=beds - 4,
            oxygen_beds=tuple(range(2, beds + 1, 3)),
            cleaning_teams=teams,
            interarrival_seconds=arrivals,
            cleaning_seconds=cleaning,
        )
        for unit_id, name, beds, teams, arrivals, cleaning in (
            ("geriatrie", "Gériatrie", 18, 1, (2400, 3000, 3600), (900, 1200, 1500)),
            ("medecine", "Médecine polyvalente", 24, 2, (1500, 1800, 2100), (900, 1200, 1500)),
            ("pneumologie", "Pneumologie", 15, 1, (2400, 3000, 3600), (1200, 1500, 1800)),
            ("chirurgie", "Chirurgie", 21, 2, (1800, 2400, 3000), (900, 1200, 1500)),
        )
    )


class CampusFleet:
    def __init__(
        self, state_dir: Path, seed: int = 7, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        import fcntl

        self.clock = clock or (lambda: datetime.now(UTC))
        self.lock = threading.RLock()
        self.ops: Operations | None = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.errors: dict[str, str] = {}
        self.units: dict[str, HospitalRuntime] = {}
        self.histories: dict[str, History] = {}
        state_dir.mkdir(parents=True, exist_ok=True)
        self.file_lock = (state_dir / "runtime.lock").open("a")
        try:
            fcntl.flock(self.file_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.file_lock.close()
            raise ValueError("hospital_already_running") from error
        try:
            manifest_path = state_dir / "hospital.json"
            configs = campus_units()
            identity = {
                "version": "WORKPLACE_1",
                "seed": seed,
                "configs": [c.model_dump(mode="json") for c in configs],
            }
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text())
                if manifest["identity"] != identity:
                    raise ValueError("hospital_configuration_changed_use_another_state_directory")
                self.epoch = datetime.fromisoformat(manifest["epoch"])
            else:
                self.epoch = self.clock().astimezone(UTC).replace(
                    minute=0, second=0, microsecond=0
                ) - timedelta(days=28)
                temporary = manifest_path.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps({"identity": identity, "epoch": self.epoch.isoformat()})
                )
                temporary.replace(manifest_path)
            target = max(0, (self.clock() - self.epoch).total_seconds())
            self.ops = Operations(self, str(state_dir / "operations.sqlite"))
            commands = self.ops.commands()
            bootstrap = commands[0][0] if commands else target
            for index, config in enumerate(configs):
                key = config.unit_id
                name = hashlib.sha256(key.encode()).hexdigest()[:16]
                history = History(str(state_dir / f"{name}-history.sqlite"), config.beds)
                self.histories[key] = history
                self.units[key] = HospitalRuntime(
                    config,
                    seed + index,
                    str(state_dir / f"{name}.sqlite"),
                    1,
                    epoch=self.epoch,
                    warmup_seconds=bootstrap,
                    engine_type=ClinicalEngine,
                    managed=True,
                    history_receiver=history.receive,
                )
            for second, request, payload in commands:
                self._advance_all(second)
                self.ops.apply(request, payload, second)
            self._advance_all(target)
            for history in self.histories.values():
                history.fit()
        except Exception:
            self.close()
            raise

    def get(self, unit_id: str) -> HospitalRuntime:
        if unit_id in self.errors:
            raise RuntimeError("unit_feed_unavailable")
        return self.units[unit_id]

    def start(self) -> None:
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self._work, name="hospital-paris", daemon=True)
        self.thread.start()

    @property
    def second(self) -> float:
        return min(unit.engine.second for unit in self.units.values())

    @property
    def now(self) -> datetime:
        return self.epoch + timedelta(seconds=self.second)

    def _advance_all(self, target: float) -> None:
        if target < self.second:
            raise ValueError("clock_cannot_rewind")
        while self.second < target:
            boundary = (int(self.second) // 60 + 1) * 60
            step = min(target, boundary)
            for unit in self.units.values():
                with unit.lock:
                    unit.projection_from = max(0, target - 120)
                    unit._advance_to(step)
            if step == boundary and self.ops:
                self.ops.tick(self.epoch + timedelta(seconds=step))

    def sync(self, *, plan: bool = True) -> None:
        with self.lock:
            if self.errors:
                return
            target = max(self.second, (self.clock() - self.epoch).total_seconds())
            try:
                self._advance_all(target)
                for unit in self.units.values():
                    if plan:
                        unit.assess()
                    unit.checkpoint()
            except Exception:
                self.errors.update(dict.fromkeys(self.units, "hospital_runtime_unavailable"))
                structlog.get_logger().exception("hospital_runtime_failed")
                raise

    def _work(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.sync()
            except Exception:
                return
            self.stop_event.wait(1)

    def overview(self) -> dict[str, Any]:
        with self.lock:
            return self._overview()

    def _overview(self) -> dict[str, Any]:
        units: list[dict[str, Any]] = []
        for key, unit in self.units.items():
            with unit.lock:
                snapshot = unit.view().snapshot
                beds = snapshot.state.beds
                units.append(
                    {
                        "id": key,
                        "name": unit.config.unit_name,
                        "available": key not in self.errors,
                        "capacity": snapshot.state.units[0].staffed_beds,
                        "occupied": sum(b.state == "occupied" for b in beds),
                        "waiting": sum(p.status == "waiting" for p in snapshot.state.patients),
                        "observed_at": (
                            unit.engine.observed.observed_at
                            if unit.engine.observed
                            else snapshot.state.at
                        ).isoformat(),
                    }
                )
        return {
            "hospital_id": "H1",
            "name": "Hôpital Saint-Clair · virtuel",
            "timezone": "Europe/Paris",
            "now": self.clock().isoformat(),
            "synthetic": True,
            "units": units,
        }

    def close(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join()
        for unit in self.units.values():
            unit.close()
        for history in self.histories.values():
            history.close()
        if self.ops:
            self.ops.close()
        self.file_lock.close()
