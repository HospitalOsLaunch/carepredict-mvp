"""Reproduce lot 07 development diagnostics; never materialize reserved test worlds."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from hospitalos.synthetic.cohort import freeze
from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.engine import simulate
from hospitalos.synthetic.generate import export_result, source_hashes
from hospitalos.synthetic.registry import CohortPlan

VARIANTS = {
    "arrivals": ("shared_bursts_v1", "appointments_v1"),
    "discharges": ("daily_rounds_v1", "rolling_v1"),
    "staffing": ("persistent_absence_v1", "shared_float_v1"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    raw = json.loads((root / "configs/synthetic/hospital_two_poles.json").read_text())
    records = []
    cases = [("reference", {})] + [
        (variant, {axis: variant}) for axis, variants in VARIANTS.items() for variant in variants
    ]
    for name, dynamics in cases:
        configured = HospitalConfig.model_validate(
            {
                **raw,
                "partition": "development",
                "hospital_id": f"H_DEV_{name}",
                "dynamics": dynamics,
            }
        )
        result = simulate(configured)
        destination = args.output / name
        manifest = export_result(configured, result, destination)
        for relative, expected in manifest["files_sha256"].items():
            assert hashlib.sha256((destination / relative).read_bytes()).hexdigest() == expected
        rows = pd.read_csv(destination / "truth/hospital_hourly.csv")
        record = {
            "case": name,
            "dynamics": configured.dynamics.model_dump(),
            "config_sha256": configured.fingerprint,
            "incoming_patients_including_warmup": result.simulation.x.N,
            "mean_occupied_beds": float(rows.lits_occupes.mean()),
            "mean_ed_waiting": float(rows.attente_urgences_nb.mean()),
            "mean_staff_present": float(rows.soignants_presents.mean()),
            "discharges": int(rows.sorties_h.sum()),
            "checks": manifest["checks"],
            "files_verified": len(manifest["files_sha256"]),
            "manifest_sha256": hashlib.sha256(
                (destination / "manifest.json").read_bytes()
            ).hexdigest(),
        }
        records.append(record)
        del result
        print(json.dumps(record), flush=True)
    registries = {}
    for axis in VARIANTS:
        plan = CohortPlan.model_validate_json(
            (root / f"configs/synthetic/cohort_{axis}_v1.json").read_text()
        )
        registry = freeze(plan, args.output / f"registry_{axis}")
        registries[axis] = {"sha256": registry.fingerprint, **registry.summary()}
    report = {
        "status": "complete",
        "synthetic_only": True,
        "test_access": {"opened": False},
        "purpose": "development diagnostics; not a generalization benchmark or causal comparison",
        "days_per_case": raw["days"],
        "warmup_days": raw["warmup_days"],
        "source_sha256": source_hashes(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cases": records,
        "reserved_registries": registries,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
