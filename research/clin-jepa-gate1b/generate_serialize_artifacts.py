#!/usr/bin/env python3
"""Generate preregistered, inspectable Gate 1-B serialization artifacts."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from loaders.serialize import serialize_fluent, serialize_structured, serialized_field_names
from loaders.sparcs_adapter import (
    COLUMN_CANDIDATES,
    FORBIDDEN_CANONICAL_FEATURES,
    LEAK_PRONE_COLUMNS,
    load_canonical,
    read_extract,
)

SEED = 42
SAMPLES_PER_CLASS = 5
SAMPLE_CLASSES = ("aval_institu", "domicile")
TARGET_COLUMNS_EXCLUDED = (
    "Patient Disposition",
    "patient_disposition",
    "disposition_raw",
    "target_disposition",
    "aval_institu",
    "target",
    "label",
    "mapped_class",
)


def generate_serialize_artifacts(input_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Write both fixed styles for the same balanced, deterministic ten stays."""
    raw = read_extract(input_path)
    canonical = load_canonical(input_path, include_apr=False)
    disposition_column = _required_disposition_column(raw.columns)
    selected_indices = _balanced_indices(canonical["target_disposition"].astype(str).to_numpy())

    structured_lines: list[str] = []
    fluent_lines: list[str] = []
    records: list[dict[str, Any]] = []
    for line_index, source_index in enumerate(selected_indices):
        row = canonical.iloc[source_index].to_dict()
        patient_disposition = str(raw.iloc[source_index][disposition_column]).strip()
        row["Patient Disposition"] = patient_disposition
        structured_lines.append(serialize_structured(row))
        fluent_lines.append(serialize_fluent(row))
        records.append(
            {
                "line_index": line_index,
                "source_row": int(source_index),
                "stay_id": int(row["stay_id"]),
                "target_class": str(row["target_disposition"]),
                "patient_disposition": patient_disposition,
            }
        )

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _write_lines(output / "sample_structured.txt", structured_lines)
    _write_lines(output / "sample_fluent.txt", fluent_lines)
    manifest = _build_manifest(records)
    (output / "serialize_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def _balanced_indices(targets: np.ndarray) -> list[int]:
    rng = np.random.default_rng(SEED)
    selected: list[int] = []
    for target_class in SAMPLE_CLASSES:
        candidates = np.flatnonzero(targets == target_class)
        if len(candidates) < SAMPLES_PER_CLASS:
            raise ValueError(
                f"need at least {SAMPLES_PER_CLASS} rows for {target_class}; found {len(candidates)}"
            )
        selected.extend(rng.choice(candidates, size=SAMPLES_PER_CLASS, replace=False).tolist())
    rng.shuffle(selected)
    return [int(index) for index in selected]


def _build_manifest(records: list[dict[str, Any]]) -> dict[str, Any]:
    class_counts = Counter(record["target_class"] for record in records)
    effective_blacklist = sorted(set(LEAK_PRONE_COLUMNS) | FORBIDDEN_CANONICAL_FEATURES)
    return {
        "primary_style": "structured",
        "ablation_style": "fluent",
        "decision_locked_before_results": True,
        "apr_default": "excluded",
        "target_columns_excluded": list(TARGET_COLUMNS_EXCLUDED),
        "temporal_assumption": {
            "prediction_time": "admission_or_early_stay",
            "drg_and_diagnosis_group": (
                "included_by_preregistration_but_temporal_availability_must_be_audited_"
                "before_interpreting_product_feasibility"
            ),
            "apr_fields": "excluded_by_default_due_to_possible_post_stay_coding",
        },
        "leak_blacklist": effective_blacklist,
        "serialized_fields": {
            "no_apr": list(serialized_field_names(include_apr=False)),
        },
        "sample_audit": {
            "seed": SEED,
            "samples_per_class": SAMPLES_PER_CLASS,
            "class_counts": dict(sorted(class_counts.items())),
            "records": records,
        },
    }


def _required_disposition_column(columns: Any) -> str:
    for candidate in COLUMN_CANDIDATES["disposition_raw"]:
        if candidate in columns:
            return candidate
    raise ValueError("Patient Disposition column is missing from sample source")


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate fixed Gate 1-B serialization samples")
    parser.add_argument("--input", required=True, help="Real SPARCS CSV/Parquet extract")
    parser.add_argument("--out", default="runs/serialize")
    args = parser.parse_args()
    manifest = generate_serialize_artifacts(args.input, args.out)
    print(f"primary_style={manifest['primary_style']}")
    print(f"ablation_style={manifest['ablation_style']}")
    print(f"sample_counts={manifest['sample_audit']['class_counts']}")
    print(f"artifacts={args.out}")


if __name__ == "__main__":
    main()
