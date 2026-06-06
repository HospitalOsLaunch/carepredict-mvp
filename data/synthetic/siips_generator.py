"""Generate realistic SIIPS-like synthetic care-load data and load TimescaleDB."""

from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence
from uuid import uuid4

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True, slots=True)
class ServiceProfile:
    """Static hospital service characteristics used by the generator."""

    service_id: str
    hospital_id: str
    service_name: str
    specialty: str
    bed_count: int
    patient_profile: str
    baseline_patients: int
    daily_admission_rate: float
    acuity_factor: float
    nurse_day_ratio: float
    aide_day_ratio: float


@dataclass(frozen=True, slots=True)
class AdmissionRecord:
    """Synthetic admission row for canonical.admissions."""

    patient_id: str
    encounter_id: str
    hospital_id: str
    service_id: str
    admission_time: datetime
    admission_type: str
    source_system: str


@dataclass(frozen=True, slots=True)
class DischargeRecord:
    """Synthetic discharge row for canonical.discharges."""

    patient_id: str
    encounter_id: str
    hospital_id: str
    service_id: str
    discharge_time: datetime
    discharge_disposition: str
    source_system: str


@dataclass(frozen=True, slots=True)
class StaffingRecord:
    """Synthetic hourly staffing row for canonical.staffing."""

    hospital_id: str
    service_id: str
    shift_start: datetime
    shift_end: datetime
    nurse_count: float
    aide_count: float
    overtime_hours: float
    avg_seniority_months: float
    source_system: str


@dataclass(frozen=True, slots=True)
class CareLoadRecord:
    """Synthetic hourly care-load row for canonical.care_load."""

    hospital_id: str
    service_id: str
    measured_at: datetime
    siips_score: float
    aas_score: float
    patient_count: int
    source_system: str


@dataclass(frozen=True, slots=True)
class SyntheticDataset:
    """Full synthetic dataset ready for optional CSV export and DB load."""

    services: list[ServiceProfile]
    admissions: list[AdmissionRecord]
    discharges: list[DischargeRecord]
    staffing: list[StaffingRecord]
    care_load: list[CareLoadRecord]


DEFAULT_SERVICES: tuple[ServiceProfile, ...] = (
    ServiceProfile(
        service_id="card-001",
        hospital_id="hosp-001",
        service_name="Cardiologie",
        specialty="cardiology",
        bed_count=34,
        patient_profile="medical_high_acuity",
        baseline_patients=25,
        daily_admission_rate=5.5,
        acuity_factor=1.28,
        nurse_day_ratio=7.0,
        aide_day_ratio=10.0,
    ),
    ServiceProfile(
        service_id="urg-001",
        hospital_id="hosp-001",
        service_name="Urgences",
        specialty="emergency",
        bed_count=42,
        patient_profile="acute_unscheduled",
        baseline_patients=31,
        daily_admission_rate=19.0,
        acuity_factor=1.42,
        nurse_day_ratio=5.8,
        aide_day_ratio=8.0,
    ),
    ServiceProfile(
        service_id="med-001",
        hospital_id="hosp-001",
        service_name="Médecine",
        specialty="internal_medicine",
        bed_count=38,
        patient_profile="medical_mixed",
        baseline_patients=29,
        daily_admission_rate=7.5,
        acuity_factor=1.18,
        nurse_day_ratio=7.5,
        aide_day_ratio=9.5,
    ),
    ServiceProfile(
        service_id="chir-001",
        hospital_id="hosp-001",
        service_name="Chirurgie",
        specialty="surgery",
        bed_count=32,
        patient_profile="scheduled_surgical",
        baseline_patients=23,
        daily_admission_rate=6.8,
        acuity_factor=1.22,
        nurse_day_ratio=6.8,
        aide_day_ratio=9.0,
    ),
    ServiceProfile(
        service_id="ped-001",
        hospital_id="hosp-001",
        service_name="Pédiatrie",
        specialty="pediatrics",
        bed_count=28,
        patient_profile="pediatric_winter_sensitive",
        baseline_patients=18,
        daily_admission_rate=4.5,
        acuity_factor=1.12,
        nurse_day_ratio=6.5,
        aide_day_ratio=10.5,
    ),
)

SOURCE_SYSTEM = "synthetic_siips"


def db_config_from_env() -> dict[str, str | int]:
    """Build psycopg2 connection parameters from .env-compatible variables."""
    return {
        "host": os.getenv("TIMESCALE_HOST", os.getenv("POSTGRES_HOST", "localhost")),
        "port": int(os.getenv("TIMESCALE_PORT", os.getenv("POSTGRES_PORT", "5432"))),
        "dbname": os.getenv("TIMESCALE_DB", os.getenv("POSTGRES_DB", "carepredict")),
        "user": os.getenv("TIMESCALE_USER", os.getenv("POSTGRES_USER", "carepredict")),
        "password": os.getenv(
            "TIMESCALE_PASSWORD",
            os.getenv("POSTGRES_PASSWORD", "carepredict_dev_password"),
        ),
    }


def months_to_days(months: int) -> int:
    """Convert calendar months to a deterministic day count; 24 months -> 730 days."""
    if months <= 0:
        raise ValueError("months must be strictly positive")
    return int(round(months * 365.0 / 12.0))


def selected_services(service_names: Sequence[str] | None) -> list[ServiceProfile]:
    """Return requested services, preserving the default deterministic order."""
    if not service_names:
        return list(DEFAULT_SERVICES)
    normalized = {name.strip().lower() for name in service_names if name.strip()}
    services = [
        service
        for service in DEFAULT_SERVICES
        if service.service_name.lower() in normalized or service.service_id.lower() in normalized
    ]
    if not services:
        raise ValueError("No matching services selected")
    return services


def generate_dataset(
    *,
    months: int = 24,
    services: Sequence[ServiceProfile] | None = None,
    seed: int = 20260606,
    start: datetime = datetime(2024, 1, 1, tzinfo=UTC),
) -> SyntheticDataset:
    """Generate admissions, discharges, staffing and hourly care load."""
    rng = np.random.default_rng(seed)
    service_profiles = list(services or DEFAULT_SERVICES)
    days = months_to_days(months)
    hours = days * 24
    admissions: list[AdmissionRecord] = []
    discharges: list[DischargeRecord] = []
    staffing: list[StaffingRecord] = []
    care_load: list[CareLoadRecord] = []

    for service_index, service in enumerate(service_profiles):
        generated = _generate_service_dataset(
            service=service,
            start=start,
            days=days,
            hours=hours,
            rng=rng,
            service_index=service_index,
        )
        admissions.extend(generated.admissions)
        discharges.extend(generated.discharges)
        staffing.extend(generated.staffing)
        care_load.extend(generated.care_load)

    return SyntheticDataset(
        services=service_profiles,
        admissions=admissions,
        discharges=discharges,
        staffing=staffing,
        care_load=care_load,
    )


def _generate_service_dataset(
    *,
    service: ServiceProfile,
    start: datetime,
    days: int,
    hours: int,
    rng: np.random.Generator,
    service_index: int,
) -> SyntheticDataset:
    admissions = _generate_admissions(service, start, days, rng, service_index)
    discharges = _generate_discharges(service, admissions, start, hours, rng)
    occupancy = _occupancy_curve(service, admissions, discharges, start, hours)
    admissions_hourly = _event_counts_by_hour(admissions, start, hours, "admission_time")
    discharges_hourly = _event_counts_by_hour(discharges, start, hours, "discharge_time")

    staffing: list[StaffingRecord] = []
    care_load: list[CareLoadRecord] = []
    for hour_index in range(hours):
        measured_at = start + timedelta(hours=hour_index)
        patient_count = int(occupancy[hour_index])
        staffing_record = _staffing_for_hour(service, measured_at, patient_count, rng)
        load = _siips_for_hour(
            service=service,
            measured_at=measured_at,
            patient_count=patient_count,
            staffing=staffing_record,
            admissions_last_6h=float(admissions_hourly[max(0, hour_index - 5) : hour_index + 1].sum()),
            discharges_last_6h=float(discharges_hourly[max(0, hour_index - 5) : hour_index + 1].sum()),
            rng=rng,
        )
        staffing.append(staffing_record)
        care_load.append(load)

    return SyntheticDataset(
        services=[service],
        admissions=admissions,
        discharges=discharges,
        staffing=staffing,
        care_load=care_load,
    )


def _generate_admissions(
    service: ServiceProfile,
    start: datetime,
    days: int,
    rng: np.random.Generator,
    service_index: int,
) -> list[AdmissionRecord]:
    admissions: list[AdmissionRecord] = []
    patient_counter = service_index * 1_000_000
    for day_index in range(days):
        day = start + timedelta(days=day_index)
        rate = service.daily_admission_rate * _weekly_multiplier(day) * _winter_multiplier(day, service)
        daily_count = int(rng.poisson(rate))
        for _ in range(daily_count):
            hour = _sample_admission_hour(service, rng)
            minute = int(rng.integers(0, 60))
            admission_time = day + timedelta(hours=hour, minutes=minute)
            patient_counter += 1
            encounter_id = f"{service.service_id}-enc-{patient_counter}"
            admissions.append(
                AdmissionRecord(
                    patient_id=f"{service.service_id}-pat-{patient_counter}",
                    encounter_id=encounter_id,
                    hospital_id=service.hospital_id,
                    service_id=service.service_id,
                    admission_time=admission_time,
                    admission_type=_admission_type(service, rng),
                    source_system=SOURCE_SYSTEM,
                )
            )
    return admissions


def _generate_discharges(
    service: ServiceProfile,
    admissions: Sequence[AdmissionRecord],
    start: datetime,
    hours: int,
    rng: np.random.Generator,
) -> list[DischargeRecord]:
    end = start + timedelta(hours=hours)
    discharges: list[DischargeRecord] = []
    for admission in admissions:
        los_hours = _length_of_stay_hours(service, rng)
        discharge_time = admission.admission_time + timedelta(hours=los_hours)
        if discharge_time >= end:
            continue
        discharges.append(
            DischargeRecord(
                patient_id=admission.patient_id,
                encounter_id=admission.encounter_id,
                hospital_id=admission.hospital_id,
                service_id=admission.service_id,
                discharge_time=discharge_time,
                discharge_disposition=_discharge_disposition(rng),
                source_system=SOURCE_SYSTEM,
            )
        )
    return discharges


def _occupancy_curve(
    service: ServiceProfile,
    admissions: Sequence[AdmissionRecord],
    discharges: Sequence[DischargeRecord],
    start: datetime,
    hours: int,
) -> npt.NDArray[np.int_]:
    delta = np.zeros(hours, dtype=int)
    for admission in admissions:
        index = _hour_index(admission.admission_time, start)
        if 0 <= index < hours:
            delta[index] += 1
    for discharge in discharges:
        index = _hour_index(discharge.discharge_time, start)
        if 0 <= index < hours:
            delta[index] -= 1
    raw = service.baseline_patients + np.cumsum(delta)
    return np.clip(raw, 1, int(service.bed_count * 1.25)).astype(int)


def _event_counts_by_hour(
    records: Sequence[AdmissionRecord] | Sequence[DischargeRecord],
    start: datetime,
    hours: int,
    attribute: str,
) -> npt.NDArray[np.int_]:
    counts = np.zeros(hours, dtype=int)
    for record in records:
        event_time = getattr(record, attribute)
        index = _hour_index(event_time, start)
        if 0 <= index < hours:
            counts[index] += 1
    return counts


def _staffing_for_hour(
    service: ServiceProfile,
    measured_at: datetime,
    patient_count: int,
    rng: np.random.Generator,
) -> StaffingRecord:
    shift_name = _shift_name(measured_at.hour)
    if shift_name == "day":
        nurse_ratio = service.nurse_day_ratio
        aide_ratio = service.aide_day_ratio
        seniority_center = 72.0
    elif shift_name == "evening":
        nurse_ratio = service.nurse_day_ratio * 1.18
        aide_ratio = service.aide_day_ratio * 1.12
        seniority_center = 66.0
    else:
        nurse_ratio = service.nurse_day_ratio * 1.55
        aide_ratio = service.aide_day_ratio * 1.35
        seniority_center = 60.0

    weekday_pressure = 0.95 if measured_at.weekday() in (0, 1) else 1.0
    winter_pressure = 0.92 if measured_at.month in (12, 1, 2) else 1.0
    nurse_count = max(1.0, round(patient_count / nurse_ratio * weekday_pressure * winter_pressure, 2))
    aide_count = max(1.0, round(patient_count / aide_ratio * weekday_pressure, 2))
    expected_nurses = patient_count / service.nurse_day_ratio
    staffing_gap = max(0.0, expected_nurses - nurse_count)
    overtime_hours = round(float(staffing_gap * rng.uniform(0.25, 0.9)), 2)
    avg_seniority = round(float(rng.normal(seniority_center, 14.0)), 2)
    return StaffingRecord(
        hospital_id=service.hospital_id,
        service_id=service.service_id,
        shift_start=measured_at,
        shift_end=measured_at + timedelta(hours=1),
        nurse_count=nurse_count,
        aide_count=aide_count,
        overtime_hours=overtime_hours,
        avg_seniority_months=max(6.0, avg_seniority),
        source_system=SOURCE_SYSTEM,
    )


def _siips_for_hour(
    *,
    service: ServiceProfile,
    measured_at: datetime,
    patient_count: int,
    staffing: StaffingRecord,
    admissions_last_6h: float,
    discharges_last_6h: float,
    rng: np.random.Generator,
) -> CareLoadRecord:
    daily = _daily_cycle(measured_at.hour)
    weekly = 3.8 if measured_at.weekday() in (0, 1) else 0.0
    seasonal = _winter_pressure(measured_at, service)
    staffing_pressure = max(0.0, patient_count / max(staffing.nurse_count, 1.0) - service.nurse_day_ratio)
    flow_pressure = admissions_last_6h * 0.55 + discharges_last_6h * 0.25
    noise = float(rng.normal(0.0, 2.2))
    siips = (
        18.0
        + patient_count * service.acuity_factor
        + daily
        + weekly
        + seasonal
        + staffing_pressure * 1.6
        + flow_pressure
        + noise
    )
    aas = siips * 0.42 + patient_count * 0.12 + float(rng.normal(0.0, 0.8))
    return CareLoadRecord(
        hospital_id=service.hospital_id,
        service_id=service.service_id,
        measured_at=measured_at,
        siips_score=round(max(0.0, siips), 2),
        aas_score=round(max(0.0, aas), 2),
        patient_count=patient_count,
        source_system=SOURCE_SYSTEM,
    )


def _daily_cycle(hour: int) -> float:
    morning_peak = 7.5 if 8 <= hour <= 11 else 0.0
    afternoon_peak = 4.8 if 14 <= hour <= 16 else 0.0
    night_relief = -3.4 if 0 <= hour <= 5 else 0.0
    handover = 1.2 if hour in (7, 13, 21) else 0.0
    return morning_peak + afternoon_peak + night_relief + handover


def _weekly_multiplier(day: datetime) -> float:
    if day.weekday() == 0:
        return 1.18
    if day.weekday() == 1:
        return 1.12
    if day.weekday() in (5, 6):
        return 0.82
    return 1.0


def _winter_multiplier(day: datetime, service: ServiceProfile) -> float:
    if day.month in (12, 1, 2):
        return 1.28 if service.specialty in {"emergency", "pediatrics"} else 1.12
    if day.month in (7, 8):
        return 0.9
    return 1.0


def _winter_pressure(measured_at: datetime, service: ServiceProfile) -> float:
    if measured_at.month not in (12, 1, 2):
        return -1.5 if measured_at.month in (7, 8) else 0.0
    if service.specialty in {"emergency", "pediatrics"}:
        return 7.0
    return 3.0


def _sample_admission_hour(service: ServiceProfile, rng: np.random.Generator) -> int:
    if service.specialty == "surgery":
        hours = np.array([7, 8, 9, 10, 13, 14, 15, 16])
        weights = np.array([0.08, 0.18, 0.2, 0.14, 0.08, 0.12, 0.12, 0.08])
    elif service.specialty == "emergency":
        hours = np.arange(24)
        weights = np.array([0.025, 0.02, 0.018, 0.018, 0.02, 0.025, 0.035, 0.045, 0.055, 0.06, 0.06, 0.055, 0.05, 0.05, 0.055, 0.06, 0.065, 0.065, 0.06, 0.055, 0.05, 0.045, 0.035, 0.03])
        weights = weights / weights.sum()
    else:
        hours = np.array([8, 9, 10, 11, 14, 15, 16, 17])
        weights = np.array([0.13, 0.18, 0.18, 0.12, 0.1, 0.11, 0.1, 0.08])
    return int(rng.choice(hours, p=weights))


def _admission_type(service: ServiceProfile, rng: np.random.Generator) -> str:
    if service.specialty in {"surgery", "cardiology"}:
        return str(rng.choice(["scheduled", "urgent"], p=[0.68, 0.32]))
    if service.specialty == "emergency":
        return str(rng.choice(["emergency", "transfer"], p=[0.86, 0.14]))
    return str(rng.choice(["scheduled", "urgent", "transfer"], p=[0.38, 0.5, 0.12]))


def _length_of_stay_hours(service: ServiceProfile, rng: np.random.Generator) -> int:
    if service.specialty == "emergency":
        value = rng.gamma(shape=1.8, scale=14.0)
    elif service.specialty == "surgery":
        value = rng.gamma(shape=2.6, scale=28.0)
    elif service.specialty == "pediatrics":
        value = rng.gamma(shape=2.1, scale=24.0)
    else:
        value = rng.gamma(shape=2.8, scale=34.0)
    return int(np.clip(value, 6, 24 * 14))


def _discharge_disposition(rng: np.random.Generator) -> str:
    return str(rng.choice(["home", "rehab", "transfer", "deceased"], p=[0.78, 0.12, 0.08, 0.02]))


def _shift_name(hour: int) -> str:
    if 7 <= hour < 14:
        return "day"
    if 14 <= hour < 21:
        return "evening"
    return "night"


def _hour_index(value: datetime, start: datetime) -> int:
    return int((value - start).total_seconds() // 3600)


def write_care_load_csv(path: Path, records: Sequence[CareLoadRecord]) -> None:
    """Optionally export generated care-load rows to CSV for inspection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "hospital_id",
                "service_id",
                "measured_at",
                "siips_score",
                "aas_score",
                "patient_count",
                "source_system",
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "hospital_id": record.hospital_id,
                    "service_id": record.service_id,
                    "measured_at": record.measured_at.isoformat(),
                    "siips_score": record.siips_score,
                    "aas_score": record.aas_score,
                    "patient_count": record.patient_count,
                    "source_system": record.source_system,
                }
            )


def load_dataset_to_db(dataset: SyntheticDataset) -> None:
    """Load the generated dataset into TimescaleDB with transactional bulk inserts."""
    config = db_config_from_env()
    psycopg2 = _psycopg2()
    with psycopg2.connect(**config) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM canonical.admissions WHERE source_system = %s", (SOURCE_SYSTEM,))
            cursor.execute("DELETE FROM canonical.discharges WHERE source_system = %s", (SOURCE_SYSTEM,))
            cursor.execute("DELETE FROM canonical.staffing WHERE source_system = %s", (SOURCE_SYSTEM,))
            cursor.execute("DELETE FROM canonical.care_load WHERE source_system = %s", (SOURCE_SYSTEM,))
            _insert_services(cursor, dataset.services)
            _insert_admissions(cursor, dataset.admissions)
            _insert_discharges(cursor, dataset.discharges)
            _insert_staffing(cursor, dataset.staffing)
            _insert_care_load(cursor, dataset.care_load)
        connection.commit()


def _insert_services(cursor: object, services: Sequence[ServiceProfile]) -> None:
    query = """
        INSERT INTO canonical.services
            (service_id, hospital_id, service_name, specialty, bed_count, patient_profile)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (service_id) DO UPDATE SET
            hospital_id = EXCLUDED.hospital_id,
            service_name = EXCLUDED.service_name,
            specialty = EXCLUDED.specialty,
            bed_count = EXCLUDED.bed_count,
            patient_profile = EXCLUDED.patient_profile
    """
    _execute_batch(
        cursor,
        query,
        [
            (
                service.service_id,
                service.hospital_id,
                service.service_name,
                service.specialty,
                service.bed_count,
                service.patient_profile,
            )
            for service in services
        ],
        page_size=100,
    )


def _insert_admissions(cursor: object, admissions: Sequence[AdmissionRecord]) -> None:
    query = """
        INSERT INTO canonical.admissions
            (event_id, patient_id, encounter_id, hospital_id, service_id,
             admission_time, admission_type, source_system)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    _execute_batch(
        cursor,
        query,
        [
            (
                str(uuid4()),
                record.patient_id,
                record.encounter_id,
                record.hospital_id,
                record.service_id,
                record.admission_time,
                record.admission_type,
                record.source_system,
            )
            for record in admissions
        ],
        page_size=5000,
    )


def _insert_discharges(cursor: object, discharges: Sequence[DischargeRecord]) -> None:
    query = """
        INSERT INTO canonical.discharges
            (event_id, patient_id, encounter_id, hospital_id, service_id,
             discharge_time, discharge_disposition, source_system)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    _execute_batch(
        cursor,
        query,
        [
            (
                str(uuid4()),
                record.patient_id,
                record.encounter_id,
                record.hospital_id,
                record.service_id,
                record.discharge_time,
                record.discharge_disposition,
                record.source_system,
            )
            for record in discharges
        ],
        page_size=5000,
    )


def _insert_staffing(cursor: object, staffing: Sequence[StaffingRecord]) -> None:
    query = """
        INSERT INTO canonical.staffing
            (event_id, hospital_id, service_id, shift_start, shift_end, nurse_count,
             aide_count, overtime_hours, avg_seniority_months, source_system)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    _execute_batch(
        cursor,
        query,
        [
            (
                str(uuid4()),
                record.hospital_id,
                record.service_id,
                record.shift_start,
                record.shift_end,
                record.nurse_count,
                record.aide_count,
                record.overtime_hours,
                record.avg_seniority_months,
                record.source_system,
            )
            for record in staffing
        ],
        page_size=5000,
    )


def _insert_care_load(cursor: object, care_load: Sequence[CareLoadRecord]) -> None:
    query = """
        INSERT INTO canonical.care_load
            (event_id, hospital_id, service_id, measured_at, siips_score,
             aas_score, patient_count, source_system)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    _execute_batch(
        cursor,
        query,
        [
            (
                str(uuid4()),
                record.hospital_id,
                record.service_id,
                record.measured_at,
                record.siips_score,
                record.aas_score,
                record.patient_count,
                record.source_system,
            )
            for record in care_load
        ],
        page_size=5000,
    )


def _psycopg2() -> object:
    import psycopg2

    return psycopg2


def _execute_batch(
    cursor: object,
    query: str,
    argslist: Iterable[tuple[object, ...]],
    *,
    page_size: int,
) -> None:
    from psycopg2.extras import execute_batch

    execute_batch(cursor, query, list(argslist), page_size=page_size)


def _parse_services(values: str | None) -> list[str] | None:
    if values is None or not values.strip():
        return None
    return [value.strip() for value in values.split(",")]


def _summary(dataset: SyntheticDataset) -> str:
    return (
        f"services={len(dataset.services)} "
        f"admissions={len(dataset.admissions)} "
        f"discharges={len(dataset.discharges)} "
        f"staffing={len(dataset.staffing)} "
        f"care_load={len(dataset.care_load)}"
    )


def main() -> None:
    """CLI entrypoint for synthetic SIIPS generation and DB loading."""
    parser = argparse.ArgumentParser(description="Generate SIIPS-like synthetic data")
    parser.add_argument("--output", type=Path, default=Path("data/generated/siips.csv"))
    parser.add_argument("--months", type=int, default=int(os.getenv("SYNTHETIC_MONTHS", "24")))
    parser.add_argument("--services", type=str, default=None)
    parser.add_argument("--seed", type=int, default=20260606)
    parser.add_argument("--skip-db", action="store_true")
    args = parser.parse_args()

    services = selected_services(_parse_services(args.services))
    dataset = generate_dataset(months=args.months, services=services, seed=args.seed)
    write_care_load_csv(args.output, dataset.care_load)
    if not args.skip_db:
        load_dataset_to_db(dataset)
    print(f"SIIPS synthetic generation complete: {_summary(dataset)}")


if __name__ == "__main__":
    main()
