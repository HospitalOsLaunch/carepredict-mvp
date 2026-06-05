"""Synthetic SIIPS-like data generator scaffold."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path


def write_seed(output: Path) -> None:
    """Write a tiny deterministic seed file until step 2 adds full generation."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "hospital_id",
                "service_id",
                "measured_at",
                "siips_score",
                "aas_score",
                "patient_count",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "hospital_id": "hosp-001",
                "service_id": "urg-001",
                "measured_at": datetime.now(tz=timezone.utc).isoformat(),
                "siips_score": "42.0",
                "aas_score": "18.5",
                "patient_count": "24",
            }
        )


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/generated/siips.csv"))
    args = parser.parse_args()
    write_seed(args.output)


if __name__ == "__main__":
    main()
