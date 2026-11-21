"""Compare operational plans on one immutable four-hour synthetic census and driver tape.

Named cases are labels on whole persons already represented in the initial stock. A common
ordinary appointment is used unless the plan requests earlier coordination. Background
patients continue to flow through the released hourly kernel. Input data must already reflect
any reported absence. A replacement is a separately confirmed worker restoring that post.
"""

from __future__ import annotations

import ctypes
import hashlib
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from .physics import HERE, ModelUnavailable, verified

Direction = Literal["discharge", "admission"]
Mode = Literal[
    "discharge",
    "admission",
    "replacement",
    "redeploy",
    "ide",
    "as",
    "loan",
    "transport",
    "cleaning",
    "smr",
    "bed",
]
MODES: tuple[Mode, ...] = (
    "discharge",
    "admission",
    "replacement",
    "redeploy",
    "ide",
    "as",
    "loan",
    "transport",
    "cleaning",
    "smr",
    "bed",
)
UNITS = {
    "discharge": "patient",
    "admission": "patient",
    "replacement": "minutes IDE",
    "redeploy": "minutes AS",
    "ide": "minutes IDE",
    "as": "minutes AS",
    "loan": "minutes IDE",
    "transport": "transport patient-équivalent",
    "cleaning": "lit nettoyé",
    "smr": "place SMR",
    "bed": "lit équipé",
}
FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int32]
Inputs = Mapping[str, NDArray[Any]]


@dataclass(frozen=True)
class JointCase:
    id: str
    direction: Direction
    ward: int
    available_hour: int = 12
    scheduled_hour: int = 15


@dataclass(frozen=True)
class JointAction:
    id: str
    mode: Mode
    ward: int
    donor: int = -1
    patient_id: str | None = None
    start_hour: int = 12
    end_hour: int = 16


@dataclass(frozen=True)
class JointResult:
    stocks: FloatArray
    capacities: FloatArray
    metrics: FloatArray
    transport_used: FloatArray
    beds_cleaned: FloatArray
    beds_opened: FloatArray
    occupied_beds: FloatArray
    clean_beds: FloatArray
    staff_minutes: FloatArray
    requested: dict[str, float]
    realized: dict[str, float]
    case_realized: dict[str, float]
    case_hour: dict[str, int | None]
    case_present: dict[str, bool]


@lru_cache(maxsize=1)
def joint_kernel_sha256() -> str:
    """Bind the additional operational rules to a plan or a study receipt."""
    return hashlib.sha256((HERE / "joint_kernel.cpp").read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _native(kernel_sha: str, joint_sha: str) -> Any:
    original = verified(HERE / "flow_kernel.cpp", kernel_sha)
    extension = verified(HERE / "joint_kernel.cpp", joint_sha)
    compiler = shutil.which("c++")
    if compiler is None:
        raise ModelUnavailable("Le simulateur conjoint requiert un compilateur C++17.")
    with tempfile.TemporaryDirectory(prefix="hospitalos-joint-") as directory:
        library = Path(directory) / "joint.so"
        try:
            subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-O3",
                    "-shared",
                    "-fPIC",
                    str(extension),
                    str(original),
                    "-o",
                    str(library),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            call = ctypes.CDLL(str(library)).joint28
        except (OSError, subprocess.SubprocessError) as exc:
            raise ModelUnavailable("Le simulateur conjoint n’a pas pu démarrer.") from exc
    call.argtypes = [ctypes.c_int] * 3 + [ctypes.c_void_p] * 14
    call.restype = None
    return call


def _integer(value: int) -> bool:
    return isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_))


def _id(value: str) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) <= 128


def _inputs(
    data: Inputs,
    initial: NDArray[Any],
    drivers: NDArray[Any],
) -> tuple[FloatArray, IntArray, FloatArray, FloatArray, IntArray]:
    beds = np.ascontiguousarray(data["beds"], dtype=np.float64)
    route = np.asarray(data["route"])
    schedules = np.asarray(data["schedules"])
    state = np.ascontiguousarray(initial, dtype=np.float64)
    tape = np.ascontiguousarray(drivers, dtype=np.float64)
    if beds.ndim != 1 or not 4 <= len(beds) <= 8 or (beds <= 0).any():
        raise ValueError("Invalid physical capacity")
    width = len(beds)
    if (
        not np.isfinite(beds).all()
        or route.shape != (width,)
        or not np.issubdtype(route.dtype, np.integer)
        or ((route < 0) | (route >= width)).any()
        or state.shape != (width, 5)
        or not np.isfinite(state).all()
        or (state < -1e-8).any()
        or (state[:, 1:].sum(axis=1) > beds + 1e-7).any()
        or tape.shape != (4, width, 17)
        or not np.isfinite(tape).all()
        or (tape < 0).any()
        or (tape[..., 1] > 1).any()
        or (tape[..., 2] + tape[..., 3] > 1 + 1e-12).any()
        or (tape[..., 11] > 1).any()
        or schedules.ndim != 4
        or not len(schedules)
        or schedules.shape[1:] != (1, 4, 3)
        or not np.issubdtype(schedules.dtype, np.integer)
    ):
        raise ValueError("Invalid common census, hourly tape, routing, or morning plan")
    first = schedules[0, 0]
    for slot, (kind, target, donor) in enumerate(first):
        if kind == 0:
            continue
        if (
            kind not in ((1, 2, 6), (3,), (4,), (5,))[slot]
            or not 0 <= target < width
            or (kind == 6 and (not 0 <= donor < width or donor == target))
            or (kind != 6 and donor != -1)
        ):
            raise ValueError("Invalid committed assignment")
    return (
        beds,
        np.ascontiguousarray(route, dtype=np.int32),
        state,
        tape,
        np.ascontiguousarray(first, dtype=np.int32),
    )


def _cases(known: Sequence[JointCase], wards: int) -> tuple[list[JointCase], IntArray]:
    for c in known:
        if (
            not _id(c.id)
            or c.direction not in ("discharge", "admission")
            or not _integer(c.ward)
            or not 0 <= c.ward < wards
            or not _integer(c.available_hour)
            or not _integer(c.scheduled_hour)
            or not 12 <= c.available_hour <= c.scheduled_hour <= 16
        ):
            raise ValueError("Unknown case, ward or appointment window")
    if len({c.id for c in known}) != len(known):
        raise ValueError("A named case can appear only once")
    ordered = sorted(known, key=lambda c: (c.scheduled_hour, c.id))
    rows = [(MODES.index(c.direction), c.ward, c.available_hour, c.scheduled_hour) for c in ordered]
    return ordered, np.asarray(rows, dtype=np.int32).reshape(-1, 4)


def _action(
    action: JointAction,
    cases: dict[str, tuple[int, JointCase]],
    wards: int,
) -> tuple[tuple[int, ...], tuple[str, int]]:
    if (
        not _id(action.id)
        or action.mode not in MODES
        or not _integer(action.ward)
        or not 0 <= action.ward < wards
        or not _integer(action.donor)
        or not _integer(action.start_hour)
        or not _integer(action.end_hour)
        or not 12 <= action.start_hour < action.end_hour <= 16
    ):
        raise ValueError("Invalid action, target or time")
    idx = -1
    if action.mode in ("discharge", "admission"):
        found = cases.get(action.patient_id or action.id)
        if found is None or (found[1].direction, found[1].ward) != (action.mode, action.ward):
            raise ValueError("The named patient, ward and requested action must agree")
        idx = found[0]
    elif action.patient_id is not None:
        raise ValueError("Resource offers cannot claim a patient identity")
    if action.mode in ("redeploy", "loan"):
        if not 0 <= action.donor < wards or action.donor == action.ward:
            raise ValueError("A reassignment needs a distinct physical donor")
    elif action.donor != -1:
        raise ValueError("This action cannot use a donor")
    if action.mode == "bed" and (action.start_hour, action.end_hour) != (12, 16):
        raise ValueError("An equipped reserve bed stays open throughout the four-hour plan")
    exclusive = idx if idx >= 0 else action.ward if action.mode == "bed" else -1
    return (
        (
            MODES.index(action.mode),
            action.ward,
            action.donor,
            idx,
            action.start_hour,
            action.end_hour,
        ),
        (action.mode, exclusive),
    )


def simulate_batch(
    data: Inputs,
    initial: NDArray[Any],
    drivers: NDArray[Any],
    plans: Sequence[Sequence[JointAction]],
    kernel: str,
    *,
    known_cases: Sequence[JointCase] = (),
) -> list[JointResult]:
    """Evaluate alternative compositions in one native call, using one common exogenous tape.

    Staff deliveries are minutes. Transport and cleaning count patient-equivalent trips and
    washed beds. Realised named cases are always zero or one. All ward indices are zero-based.
    """
    beds, route, state, tape, morning = _inputs(data, initial, drivers)
    ordered, case_rows = _cases(known_cases, len(beds))
    case_index = {c.id: (i, c) for i, c in enumerate(ordered)}
    if not plans:
        return []
    rows: list[tuple[int, ...]] = []
    offsets = [0]
    encoded: dict[JointAction, tuple[tuple[int, ...], tuple[str, int]]] = {}
    for plan in plans:
        if len({a.id for a in plan}) != len(plan):
            raise ValueError("Repeated action ID in the same plan")
        used: set[tuple[str, int]] = set()
        for a in plan:
            if a not in encoded:
                encoded[a] = _action(a, case_index, len(beds))
            row, key = encoded[a]
            if key in used:
                raise ValueError("A patient or a declared singular resource is booked twice")
            used.add(key)
            rows.append(row)
        offsets.append(len(rows))
    cuts = np.asarray(offsets, dtype=np.int32)
    packed = np.asarray(rows, dtype=np.int32).reshape(-1, 6)
    shape = (len(plans), len(beds))
    final = np.zeros((*shape, 5), dtype=np.float64)
    metrics = np.zeros((*shape, 14), dtype=np.float64)
    resources = np.zeros((*shape, 5), dtype=np.float64)
    delivered = np.zeros(len(rows), dtype=np.float64)
    requested = np.zeros(len(rows), dtype=np.float64)
    hours = np.zeros((len(plans), len(ordered)), dtype=np.int32)
    arrays = (
        beds,
        route,
        state,
        tape,
        morning,
        case_rows,
        cuts,
        packed,
        final,
        metrics,
        resources,
        delivered,
        requested,
        hours,
    )
    _native(kernel, joint_kernel_sha256())(
        len(beds), len(plans), len(ordered), *(a.ctypes.data for a in arrays)
    )
    # Audit the queue, the occupied beds and the soiled beds separately in each unit.
    expected_queue = state[:, 0] + metrics[..., 10] - metrics[..., 4] - metrics[..., 7]
    occupancy = final[..., 1] + final[..., 2] + final[..., 4]
    departures = metrics[..., 5] + metrics[..., 6] + metrics[..., 9]
    expected_occupancy = (
        state[:, 1] + state[:, 2] + state[:, 4] + metrics[..., 4] + metrics[..., 8] - departures
    )
    expected_dirty = state[:, 3] + departures - resources[..., 1]
    if (
        not np.isfinite(final).all()
        or not np.isfinite(metrics).all()
        or not np.isfinite(resources).all()
        or (final < -1e-7).any()
        or (final[..., 1:].sum(axis=-1) > resources[..., 4] + 1e-7).any()
        or (delivered > requested + 1e-7).any()
        or not np.allclose(final[..., 0], expected_queue, atol=1e-7, rtol=1e-10)
        or not np.allclose(occupancy, expected_occupancy, atol=1e-7, rtol=1e-10)
        or not np.allclose(final[..., 3], expected_dirty, atol=1e-7, rtol=1e-10)
    ):
        raise ModelUnavailable("Le plan conjoint a produit un état physique incohérent.")
    out = []
    for p, plan in enumerate(plans):
        start = offsets[p]
        activity = resources[p]
        available = np.maximum(0.0, activity[:, 4] - occupancy[p] - final[p, :, 3])
        out.append(
            JointResult(
                stocks=final[p],
                capacities=activity[:, 4],
                metrics=metrics[p],
                transport_used=activity[:, 0],
                beds_cleaned=activity[:, 1],
                beds_opened=activity[:, 4] - beds,
                occupied_beds=occupancy[p],
                clean_beds=available,
                staff_minutes=activity[:, 2:4],
                requested={a.id: float(requested[start + i]) for i, a in enumerate(plan)},
                realized={a.id: float(delivered[start + i]) for i, a in enumerate(plan)},
                case_realized={c.id: float(hours[p, i] >= 0) for i, c in enumerate(ordered)},
                case_hour={
                    c.id: int(hours[p, i]) if hours[p, i] >= 0 else None
                    for i, c in enumerate(ordered)
                },
                case_present={c.id: bool(hours[p, i] != -2) for i, c in enumerate(ordered)},
            )
        )
    return out


def simulate_joint(
    data: Inputs,
    initial: NDArray[Any],
    drivers: NDArray[Any],
    actions: Sequence[JointAction],
    kernel: str,
    *,
    known_cases: Sequence[JointCase] = (),
) -> JointResult:
    return simulate_batch(data, initial, drivers, [actions], kernel, known_cases=known_cases)[0]
