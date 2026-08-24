"""Causal SIIPS patient trajectories for synthetic care-load generation.

The coefficients and phase profiles are calibrated from public SIIPS material:
Club des Utilisateurs SIIPS, "Guide SIIPS 2016"; AP-HP Cochin oncology,
hematology and visceral surgery SIIPS grids, 2012; Centre Hospitalier Emile
Roux Le Puy, geriatric SSR SIIPS grid, 2013. The module intentionally exposes
pure functions so the synthetic generator can inject causal intervention
signals without coupling the model to TimescaleDB or the CLI.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import numpy.typing as npt

ADMISSION_RATES_PER_DAY: dict[str, float] = {
    "urg-001": 35.0,
    "med-001": 8.0,
    "chir-001": 6.0,
    "rea-001": 1.5,
    "ssr-001": 1.2,
}

CAUSAL_EVENT_EFFECTS: dict[str, float] = {
    "admission_siips_bonus": 120.0,
    "discharge_siips_relief": 40.0,
}

SIIPS_SERVICE_PROFILES: dict[str, dict[str, float | tuple[float, float]]] = {
    "urg-001": {
        "admission_initial_siips": (18.0, 24.0),
        "plateau_siips": (10.0, 14.0),
        "pre_discharge_siips": (6.0, 10.0),
        "mean_los_hours": 18.0,
        "std_los_hours": 12.0,
        "noise_std": 2.5,
    },
    "med-001": {
        "admission_initial_siips": (12.0, 18.0),
        "plateau_siips": (10.0, 16.0),
        "pre_discharge_siips": (8.0, 12.0),
        "mean_los_hours": 168.0,
        "std_los_hours": 72.0,
        "noise_std": 2.0,
    },
    "chir-001": {
        "admission_initial_siips": (8.0, 12.0),
        "peak_post_op_siips": (24.0, 30.0),
        "plateau_siips": (12.0, 18.0),
        "pre_discharge_siips": (6.0, 10.0),
        "mean_los_hours": 144.0,
        "std_los_hours": 48.0,
        "noise_std": 2.5,
    },
    "rea-001": {
        "admission_initial_siips": (75.0, 110.0),
        "plateau_siips": (60.0, 90.0),
        "pre_discharge_siips": (30.0, 50.0),
        "mean_los_hours": 96.0,
        "std_los_hours": 72.0,
        "noise_std": 8.0,
    },
    "ssr-001": {
        "admission_initial_siips": (30.0, 40.0),
        "plateau_siips": (25.0, 35.0),
        "pre_discharge_siips": (15.0, 25.0),
        "mean_los_hours": 504.0,
        "std_los_hours": 240.0,
        "noise_std": 4.0,
    },
}


@dataclass(frozen=True, slots=True)
class PatientTrajectory:
    """A synthetic stay with SIIPS phase levels and optional surgery timing."""

    patient_id: str
    encounter_id: str
    service_id: str
    admission_time: datetime
    los_hours: int
    initial_siips: float
    plateau_siips: float
    pre_discharge_siips: float
    noise_std: float
    surgery_hour: int | None = None


def sample_phase_siips(
    profile: Mapping[str, float | tuple[float, float]],
    phase: str,
    rng: np.random.Generator,
) -> float:
    """Sample a patient SIIPS level for one clinical phase."""
    value = profile[phase]
    if isinstance(value, tuple):
        return float(rng.uniform(value[0], value[1]))
    return float(value)


def sample_los_hours(
    profile: Mapping[str, float | tuple[float, float]],
    rng: np.random.Generator,
) -> int:
    """Sample a truncated length of stay from the SIIPS service profile."""
    mean = _scalar_profile_value(profile, "mean_los_hours")
    std = _scalar_profile_value(profile, "std_los_hours")
    sampled = float(rng.normal(mean, std))
    return int(np.clip(round(sampled), 24, 3.0 * mean))


def build_patient_trajectory(
    *,
    patient_id: str,
    encounter_id: str,
    service_id: str,
    admission_time: datetime,
    rng: np.random.Generator,
) -> PatientTrajectory:
    """Create a deterministic patient trajectory definition from a service profile."""
    profile = SIIPS_SERVICE_PROFILES[service_id]
    surgery_hour = None
    if service_id == "chir-001":
        surgery_hour = int(rng.integers(8, 30))
        plateau = sample_phase_siips(profile, "peak_post_op_siips", rng)
    else:
        plateau = sample_phase_siips(profile, "plateau_siips", rng)
    return PatientTrajectory(
        patient_id=patient_id,
        encounter_id=encounter_id,
        service_id=service_id,
        admission_time=admission_time,
        los_hours=sample_los_hours(profile, rng),
        initial_siips=sample_phase_siips(profile, "admission_initial_siips", rng),
        plateau_siips=plateau,
        pre_discharge_siips=sample_phase_siips(profile, "pre_discharge_siips", rng),
        noise_std=_scalar_profile_value(profile, "noise_std"),
        surgery_hour=surgery_hour,
    )


def _scalar_profile_value(
    profile: Mapping[str, float | tuple[float, float]], key: str
) -> float:
    """Read a profile field that is contractually scalar."""
    value = profile[key]
    if isinstance(value, tuple):
        raise TypeError(f"Profile field {key!r} must be scalar")
    return float(value)


def compute_patient_siips_trajectory(
    patient: PatientTrajectory,
    rng: np.random.Generator,
    *,
    autocorrelation: float = 0.78,
) -> npt.NDArray[np.float64]:
    """Compute the hourly SIIPS trajectory for one admitted patient.

    The trajectory follows an admission peak, a plateau, and a discharge
    preparation phase with six-hour linear transitions. For surgical patients,
    a post-operative technical-care bonus is added after the scheduled surgery.
    """
    if patient.los_hours <= 0:
        raise ValueError("los_hours must be strictly positive")
    if not 0.0 <= autocorrelation < 1.0:
        raise ValueError("autocorrelation must be in [0, 1)")

    targets = np.zeros(patient.los_hours, dtype=float)
    for hour in range(patient.los_hours):
        base = _phase_target(patient, hour)
        targets[hour] = base + _surgery_bonus(patient, hour)

    trajectory = np.zeros(patient.los_hours, dtype=float)
    previous = targets[0]
    innovation_weight = 1.0 - autocorrelation
    for hour, target in enumerate(targets):
        noisy_target = target + float(rng.normal(0.0, patient.noise_std))
        value = autocorrelation * previous + innovation_weight * noisy_target
        trajectory[hour] = max(0.0, value)
        previous = trajectory[hour]
    return trajectory.astype(np.float64)


def aggregate_care_load_from_patients(
    patients: list[PatientTrajectory],
    *,
    start: datetime,
    hours: int,
    rng: np.random.Generator,
    autocorrelation: float = 0.78,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.int_]]:
    """Aggregate patient trajectories into hourly service SIIPS and census arrays."""
    if hours <= 0:
        raise ValueError("hours must be strictly positive")

    care_load = np.zeros(hours, dtype=float)
    patient_count = np.zeros(hours, dtype=int)
    for patient in patients:
        start_index = int((patient.admission_time - start).total_seconds() // 3600)
        if start_index >= hours:
            continue
        trajectory = compute_patient_siips_trajectory(
            patient,
            rng,
            autocorrelation=autocorrelation,
        )
        source_start = max(0, -start_index)
        target_start = max(0, start_index)
        available = len(trajectory) - source_start
        target_end = min(hours, target_start + available)
        if target_end <= target_start:
            continue
        source_end = source_start + (target_end - target_start)
        care_load[target_start:target_end] += trajectory[source_start:source_end]
        patient_count[target_start:target_end] += 1
    return care_load.astype(np.float64), patient_count.astype(int)


def _phase_target(patient: PatientTrajectory, hour: int) -> float:
    initial_end = 24
    discharge_start = max(24, patient.los_hours - 24)
    if hour < initial_end:
        return _linear_blend(
            patient.initial_siips,
            patient.plateau_siips,
            center=initial_end,
            hour=hour,
        )
    if hour >= discharge_start:
        return _linear_blend(
            patient.plateau_siips,
            patient.pre_discharge_siips,
            center=discharge_start,
            hour=hour,
        )
    return patient.plateau_siips


def _linear_blend(start_value: float, end_value: float, *, center: int, hour: int) -> float:
    transition_start = center - 3
    transition_end = center + 3
    if hour <= transition_start:
        return start_value
    if hour >= transition_end:
        return end_value
    fraction = (hour - transition_start) / max(transition_end - transition_start, 1)
    return start_value + fraction * (end_value - start_value)


def _surgery_bonus(patient: PatientTrajectory, hour: int) -> float:
    if patient.service_id != "chir-001" or patient.surgery_hour is None:
        return 0.0
    if hour < patient.surgery_hour:
        return 0.0
    if hour < patient.surgery_hour + 24:
        return 8.0
    return float(8.0 * np.exp(-float(hour - patient.surgery_hour - 24) / 36.0))
