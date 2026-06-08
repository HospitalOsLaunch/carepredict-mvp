"""Tests for the causal SIIPS trajectory model."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from data.synthetic.causal_model import (
    PatientTrajectory,
    aggregate_care_load_from_patients,
    compute_patient_siips_trajectory,
)
from data.synthetic.siips_generator import DEFAULT_SERVICES, _hour_index, generate_dataset


def _patient(
    *,
    service_id: str = "urg-001",
    admission_time: datetime = datetime(2024, 1, 1, tzinfo=UTC),
    los_hours: int = 72,
    surgery_hour: int | None = None,
) -> PatientTrajectory:
    return PatientTrajectory(
        patient_id=f"{service_id}-pat-test",
        encounter_id=f"{service_id}-enc-test",
        service_id=service_id,
        admission_time=admission_time,
        los_hours=los_hours,
        initial_siips=24.0,
        plateau_siips=14.0,
        pre_discharge_siips=8.0,
        noise_std=0.0,
        surgery_hour=surgery_hour,
    )


def test_patient_trajectory_shape() -> None:
    rng = np.random.default_rng(42)
    trajectory = compute_patient_siips_trajectory(_patient(los_hours=97), rng)

    assert trajectory.shape == (97,)
    assert np.all(trajectory >= 0.0)


def test_admission_increases_load() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    patient = _patient(admission_time=start + timedelta(hours=4), los_hours=48)
    rng = np.random.default_rng(42)

    care_load, patient_count = aggregate_care_load_from_patients(
        [patient],
        start=start,
        hours=12,
        rng=rng,
        autocorrelation=0.0,
    )

    assert care_load[3] == 0.0
    assert care_load[4] > care_load[3]
    assert patient_count[4] == 1


def test_discharge_decreases_load() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    patient = _patient(admission_time=start, los_hours=12)
    rng = np.random.default_rng(42)

    care_load, patient_count = aggregate_care_load_from_patients(
        [patient],
        start=start,
        hours=16,
        rng=rng,
        autocorrelation=0.0,
    )

    assert care_load[11] > 0.0
    assert care_load[12] == 0.0
    assert patient_count[12] == 0


def test_surgery_bonus_chir_only() -> None:
    rng_chir = np.random.default_rng(42)
    rng_urg = np.random.default_rng(42)
    chir = compute_patient_siips_trajectory(
        _patient(service_id="chir-001", surgery_hour=10),
        rng_chir,
        autocorrelation=0.0,
    )
    urg = compute_patient_siips_trajectory(
        _patient(service_id="urg-001", surgery_hour=10),
        rng_urg,
        autocorrelation=0.0,
    )

    assert chir[10] - urg[10] >= 7.5
    assert abs(chir[8] - urg[8]) < 0.01


def test_correlation_after_generation() -> None:
    service = next(item for item in DEFAULT_SERVICES if item.service_id == "urg-001")
    dataset = generate_dataset(months=18, services=[service], seed=42)
    start = min(record.measured_at for record in dataset.care_load)
    hours = len(dataset.care_load)
    discharges = np.zeros(hours, dtype=float)
    siips = np.asarray([record.siips_score for record in dataset.care_load], dtype=float)

    for discharge in dataset.discharges:
        index = _hour_index(discharge.discharge_time, start)
        if 0 <= index < hours:
            discharges[index] += 1.0

    event_hours = discharges > 0
    correlation = float(np.corrcoef(discharges[event_hours], siips[event_hours])[0, 1])

    assert len(dataset.admissions) >= 1_000
    assert -0.7 <= correlation <= -0.1
