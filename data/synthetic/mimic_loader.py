"""Load MIMIC-IV demo admissions/discharges into canonical TimescaleDB tables."""

from __future__ import annotations

import csv
import gzip
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO
from uuid import uuid4

LOGGER = logging.getLogger("carepredict.mimic_loader")
SOURCE_SYSTEM = "mimic_iv_demo"
DEFAULT_MIMIC_DIR = Path("data/mimic_demo")
SERVICE_IDS = ("urg-001", "card-001", "med-001", "chir-001", "ped-001")


@dataclass(frozen=True, slots=True)
class MimicAdmission:
    """Canonical admission parsed from MIMIC-IV demo."""

    patient_id: str
    encounter_id: str
    hospital_id: str
    service_id: str
    admission_time: datetime
    admission_type: str
    source_system: str


@dataclass(frozen=True, slots=True)
class MimicDischarge:
    """Canonical discharge parsed from MIMIC-IV demo."""

    patient_id: str
    encounter_id: str
    hospital_id: str
    service_id: str
    discharge_time: datetime
    discharge_disposition: str
    source_system: str


@dataclass(frozen=True, slots=True)
class MimicDataset:
    """Parsed MIMIC dataset ready for insertion."""

    admissions: list[MimicAdmission]
    discharges: list[MimicDischarge]


def db_config_from_env() -> dict[str, str | int]:
    """Build psycopg2 connection parameters from environment variables."""
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


def mimic_demo_available(path: Path = DEFAULT_MIMIC_DIR) -> bool:
    """Return whether MIMIC-IV demo files are available locally."""
    return find_admissions_file(path) is not None


def find_admissions_file(path: Path) -> Path | None:
    """Find a MIMIC admissions CSV, supporting compressed files."""
    candidates = [
        path / "hosp" / "admissions.csv.gz",
        path / "hosp" / "admissions.csv",
        path / "admissions.csv.gz",
        path / "admissions.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    matches = sorted(path.rglob("admissions.csv*")) if path.exists() else []
    return matches[0] if matches else None


def open_text(path: Path) -> TextIO:
    """Open plain or gzipped CSV as text."""
    if path.suffix == ".gz":
        return gzip.open(path, mode="rt", encoding="utf-8", newline="")
    return path.open(mode="r", encoding="utf-8", newline="")


def parse_mimic_datetime(value: str) -> datetime:
    """Parse MIMIC datetime strings as UTC timestamps."""
    text = value.strip()
    if not text:
        raise ValueError("MIMIC datetime is empty")
    parsed = datetime.fromisoformat(text.replace(" ", "T"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def service_for_row(index: int, admission_type: str) -> str:
    """Assign MIMIC demo rows across the five pilot services."""
    lower = admission_type.lower()
    if "emergency" in lower or "urgent" in lower:
        return "urg-001"
    return SERVICE_IDS[index % len(SERVICE_IDS)]


def disposition(value: str) -> str:
    """Normalize MIMIC discharge location into canonical disposition."""
    lower = value.lower()
    if "home" in lower:
        return "home"
    if "rehab" in lower:
        return "rehab"
    if "expired" in lower or "dead" in lower:
        return "deceased"
    if "transfer" in lower:
        return "transfer"
    return "other"


def load_mimic_demo(path: Path = DEFAULT_MIMIC_DIR, limit: int = 100) -> MimicDataset:
    """Parse up to ``limit`` MIMIC admissions and discharges."""
    admissions_file = find_admissions_file(path)
    if admissions_file is None:
        LOGGER.info("MIMIC-IV demo non disponible, skip")
        return MimicDataset(admissions=[], discharges=[])

    admissions: list[MimicAdmission] = []
    discharges: list[MimicDischarge] = []
    with open_text(admissions_file) as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            if index >= limit:
                break
            subject_id = row.get("subject_id", f"subject-{index}")
            hadm_id = row.get("hadm_id", f"hadm-{index}")
            admission_type = row.get("admission_type", "unknown").lower().replace(" ", "_")
            service_id = service_for_row(index, admission_type)
            admission_time = parse_mimic_datetime(row.get("admittime", ""))
            discharge_raw = row.get("dischtime", "")
            admissions.append(
                MimicAdmission(
                    patient_id=f"mimic-{subject_id}",
                    encounter_id=f"mimic-{hadm_id}",
                    hospital_id="hosp-001",
                    service_id=service_id,
                    admission_time=admission_time,
                    admission_type=admission_type or "unknown",
                    source_system=SOURCE_SYSTEM,
                )
            )
            if discharge_raw.strip():
                discharges.append(
                    MimicDischarge(
                        patient_id=f"mimic-{subject_id}",
                        encounter_id=f"mimic-{hadm_id}",
                        hospital_id="hosp-001",
                        service_id=service_id,
                        discharge_time=parse_mimic_datetime(discharge_raw),
                        discharge_disposition=disposition(row.get("discharge_location", "")),
                        source_system=SOURCE_SYSTEM,
                    )
                )
    return MimicDataset(admissions=admissions, discharges=discharges)


def insert_mimic_dataset(dataset: MimicDataset) -> None:
    """Insert parsed MIMIC rows in one transaction."""
    if not dataset.admissions and not dataset.discharges:
        return
    psycopg2 = _psycopg2()
    with psycopg2.connect(**db_config_from_env()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM canonical.admissions WHERE source_system = %s", (SOURCE_SYSTEM,)
            )
            cursor.execute(
                "DELETE FROM canonical.discharges WHERE source_system = %s", (SOURCE_SYSTEM,)
            )
            insert_admissions(cursor, dataset.admissions)
            insert_discharges(cursor, dataset.discharges)
        connection.commit()


def insert_admissions(cursor: object, rows: Iterable[MimicAdmission]) -> None:
    """Bulk insert MIMIC admissions."""
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
                row.patient_id,
                row.encounter_id,
                row.hospital_id,
                row.service_id,
                row.admission_time,
                row.admission_type,
                row.source_system,
            )
            for row in rows
        ],
        page_size=1000,
    )


def insert_discharges(cursor: object, rows: Iterable[MimicDischarge]) -> None:
    """Bulk insert MIMIC discharges."""
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
                row.patient_id,
                row.encounter_id,
                row.hospital_id,
                row.service_id,
                row.discharge_time,
                row.discharge_disposition,
                row.source_system,
            )
            for row in rows
        ],
        page_size=1000,
    )


def configure_logging() -> None:
    """Configure concise structured-ish logging for CLI use."""
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s %(message)s")


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


def main() -> None:
    """Load MIMIC-IV demo when available and skip cleanly otherwise."""
    configure_logging()
    dataset = load_mimic_demo(DEFAULT_MIMIC_DIR, limit=100)
    insert_mimic_dataset(dataset)
    LOGGER.info(
        "MIMIC-IV demo ingestion complete admissions=%s discharges=%s",
        len(dataset.admissions),
        len(dataset.discharges),
    )


if __name__ == "__main__":
    main()
