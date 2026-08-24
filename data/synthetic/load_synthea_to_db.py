"""Load Synthea CSV exports into canonical TimescaleDB tables."""

from __future__ import annotations

import argparse
import csv
import logging
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

LOGGER = logging.getLogger("carepredict.synthea_loader")
SOURCE_SYSTEM = "synthea"


@dataclass(frozen=True, slots=True)
class ServiceRow:
    """Canonical service row."""

    service_id: str
    hospital_id: str
    service_name: str
    specialty: str
    bed_count: int
    patient_profile: str


@dataclass(frozen=True, slots=True)
class SyntheaAdmission:
    """Canonical admission parsed from Synthea encounters."""

    patient_id: str
    encounter_id: str
    hospital_id: str
    service_id: str
    admission_time: datetime
    admission_type: str
    source_system: str


@dataclass(frozen=True, slots=True)
class SyntheaDischarge:
    """Canonical discharge parsed from Synthea encounters."""

    patient_id: str
    encounter_id: str
    hospital_id: str
    service_id: str
    discharge_time: datetime
    discharge_disposition: str
    source_system: str


@dataclass(frozen=True, slots=True)
class SyntheaDataset:
    """Parsed Synthea rows ready for insertion."""

    services: list[ServiceRow]
    admissions: list[SyntheaAdmission]
    discharges: list[SyntheaDischarge]


SERVICES: tuple[ServiceRow, ...] = (
    ServiceRow("card-001", "hosp-001", "Cardiologie", "cardiology", 34, "medical_high_acuity"),
    ServiceRow("urg-001", "hosp-001", "Urgences", "emergency", 42, "acute_unscheduled"),
    ServiceRow("med-001", "hosp-001", "Médecine", "internal_medicine", 38, "medical_mixed"),
    ServiceRow("chir-001", "hosp-001", "Chirurgie", "surgery", 32, "scheduled_surgical"),
    ServiceRow("ped-001", "hosp-001", "Pédiatrie", "pediatrics", 28, "pediatric_winter_sensitive"),
)


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


def find_csv(root: Path, name: str) -> Path | None:
    """Find a Synthea CSV by file name under the output root."""
    direct_candidates = [
        root / name,
        root / "csv" / name,
        root / "output" / "csv" / name,
    ]
    for candidate in direct_candidates:
        if candidate.exists():
            return candidate
    matches = sorted(root.rglob(name)) if root.exists() else []
    return matches[0] if matches else None


def parse_datetime(value: str) -> datetime:
    """Parse Synthea date/datetime values into UTC timestamps."""
    text = value.strip()
    if not text:
        raise ValueError("Synthea datetime is empty")
    normalized = text.replace("Z", "+00:00")
    if "T" not in normalized and len(normalized) == 10:
        parsed = datetime.fromisoformat(normalized + "T00:00:00+00:00")
    else:
        parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def service_for_encounter(row: dict[str, str], index: int) -> ServiceRow:
    """Map Synthea encounter metadata to one of the five pilot services."""
    encounter_class = row.get("ENCOUNTERCLASS", row.get("encounterclass", "")).lower()
    description = row.get("DESCRIPTION", row.get("description", "")).lower()
    reason = row.get("REASONDESCRIPTION", row.get("reasondescription", "")).lower()
    text = f"{encounter_class} {description} {reason}"
    if "emergency" in text or "urgent" in text:
        return SERVICES[1]
    if "card" in text or "heart" in text:
        return SERVICES[0]
    if "surg" in text or "procedure" in text:
        return SERVICES[3]
    if "child" in text or "pediatric" in text:
        return SERVICES[4]
    return SERVICES[index % len(SERVICES)]


def admission_type_for_encounter(row: dict[str, str]) -> str:
    """Derive canonical admission type from Synthea encounter class."""
    value = row.get("ENCOUNTERCLASS", row.get("encounterclass", "ambulatory")).lower()
    if "emergency" in value:
        return "emergency"
    if "inpatient" in value:
        return "scheduled"
    if "urgent" in value:
        return "urgent"
    return value or "scheduled"


def discharge_disposition(row: dict[str, str]) -> str:
    """Assign a canonical discharge disposition."""
    description = row.get("DESCRIPTION", row.get("description", "")).lower()
    if "death" in description:
        return "deceased"
    if "transfer" in description:
        return "transfer"
    return "home"


def load_synthea_csv(root: Path, limit: int | None = None) -> SyntheaDataset:
    """Parse Synthea encounters into admissions and discharges."""
    encounters_path = find_csv(root, "encounters.csv")
    if encounters_path is None:
        LOGGER.info("Synthea encounters.csv non disponible, skip")
        return SyntheaDataset(services=list(SERVICES), admissions=[], discharges=[])

    admissions: list[SyntheaAdmission] = []
    discharges: list[SyntheaDischarge] = []
    with encounters_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            if limit is not None and index >= limit:
                break
            patient_id = row.get("PATIENT", row.get("patient", f"synthea-patient-{index}"))
            encounter_id = row.get("Id", row.get("ID", row.get("id", f"synthea-encounter-{index}")))
            start_value = row.get("START", row.get("start", ""))
            stop_value = row.get("STOP", row.get("stop", ""))
            if not start_value.strip():
                continue
            service = service_for_encounter(row, index)
            admissions.append(
                SyntheaAdmission(
                    patient_id=f"synthea-{patient_id}",
                    encounter_id=f"synthea-{encounter_id}",
                    hospital_id=service.hospital_id,
                    service_id=service.service_id,
                    admission_time=parse_datetime(start_value),
                    admission_type=admission_type_for_encounter(row),
                    source_system=SOURCE_SYSTEM,
                )
            )
            if stop_value.strip():
                discharges.append(
                    SyntheaDischarge(
                        patient_id=f"synthea-{patient_id}",
                        encounter_id=f"synthea-{encounter_id}",
                        hospital_id=service.hospital_id,
                        service_id=service.service_id,
                        discharge_time=parse_datetime(stop_value),
                        discharge_disposition=discharge_disposition(row),
                        source_system=SOURCE_SYSTEM,
                    )
                )
    return SyntheaDataset(services=list(SERVICES), admissions=admissions, discharges=discharges)


def insert_dataset(dataset: SyntheaDataset) -> None:
    """Insert Synthea canonical rows transactionally."""
    psycopg2 = _psycopg2()
    with psycopg2.connect(**db_config_from_env()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM canonical.admissions WHERE source_system = %s", (SOURCE_SYSTEM,)
            )
            cursor.execute(
                "DELETE FROM canonical.discharges WHERE source_system = %s", (SOURCE_SYSTEM,)
            )
            insert_services(cursor, dataset.services)
            insert_admissions(cursor, dataset.admissions)
            insert_discharges(cursor, dataset.discharges)
        connection.commit()


def insert_services(cursor: object, services: Sequence[ServiceRow]) -> None:
    """Upsert the five pilot services."""
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


def insert_admissions(cursor: object, rows: Sequence[SyntheaAdmission]) -> None:
    """Bulk insert Synthea admissions."""
    if not rows:
        return
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
        page_size=5000,
    )


def insert_discharges(cursor: object, rows: Sequence[SyntheaDischarge]) -> None:
    """Bulk insert Synthea discharges."""
    if not rows:
        return
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
        page_size=5000,
    )


def configure_logging() -> None:
    """Configure CLI logging."""
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
    """Load generated Synthea CSV into TimescaleDB canonical tables."""
    parser = argparse.ArgumentParser(description="Load Synthea CSV exports to TimescaleDB")
    parser.add_argument("--input", type=Path, default=Path("data/generated/synthea"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-db", action="store_true")
    args = parser.parse_args()

    configure_logging()
    dataset = load_synthea_csv(args.input, limit=args.limit)
    if not args.skip_db:
        insert_dataset(dataset)
    LOGGER.info(
        "Synthea ingestion complete services=%s admissions=%s discharges=%s",
        len(dataset.services),
        len(dataset.admissions),
        len(dataset.discharges),
    )


if __name__ == "__main__":
    main()
