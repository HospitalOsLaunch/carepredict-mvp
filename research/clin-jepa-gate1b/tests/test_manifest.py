"""Tests for preregistered serialization artifacts and balanced samples."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from generate_serialize_artifacts import generate_serialize_artifacts
from loaders.sparcs_adapter import FORBIDDEN_CANONICAL_FEATURES, LEAK_PRONE_COLUMNS

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "runs" / "serialize"


def _manifest(path: Path = ARTIFACT_DIR) -> dict:
    return json.loads((path / "serialize_manifest.json").read_text(encoding="utf-8"))


def _sample_lines(name: str, path: Path = ARTIFACT_DIR) -> list[str]:
    return [line for line in (path / name).read_text(encoding="utf-8").splitlines() if line]


def test_manifest_locks_primary_style_and_temporal_assumptions() -> None:
    manifest = _manifest()

    assert manifest["primary_style"] == "structured"
    assert manifest["ablation_style"] == "fluent"
    assert manifest["decision_locked_before_results"] is True
    assert manifest["apr_default"] == "excluded"
    assert "Patient Disposition" in manifest["target_columns_excluded"]
    assert manifest["temporal_assumption"]["drg_and_diagnosis_group"]


def test_manifest_blacklist_matches_effective_source_of_truth() -> None:
    expected = sorted(set(LEAK_PRONE_COLUMNS) | FORBIDDEN_CANONICAL_FEATURES)

    assert _manifest()["leak_blacklist"] == expected


def test_checked_in_samples_are_same_ten_balanced_stays() -> None:
    manifest = _manifest()
    structured = _sample_lines("sample_structured.txt")
    fluent = _sample_lines("sample_fluent.txt")
    records = manifest["sample_audit"]["records"]

    assert len(structured) == len(fluent) == len(records) == 10
    assert manifest["sample_audit"]["seed"] == 42
    assert manifest["sample_audit"]["class_counts"] == {
        "aval_institu": 5,
        "domicile": 5,
    }
    assert [record["line_index"] for record in records] == list(range(10))


def test_checked_in_samples_exclude_target_by_exact_provenance() -> None:
    manifest = _manifest()
    structured = _sample_lines("sample_structured.txt")
    fluent = _sample_lines("sample_fluent.txt")

    for record, structured_text, fluent_text in zip(
        manifest["sample_audit"]["records"], structured, fluent, strict=True
    ):
        disposition = record["patient_disposition"]
        assert disposition not in structured_text
        assert disposition not in fluent_text


def test_generator_is_byte_deterministic_and_balanced(tmp_path: Path) -> None:
    rows = []
    for index in range(12):
        rows.append(_row("Skilled Nursing Home", index))
        rows.append(_row("Home or Self Care", index + 100))
    source = tmp_path / "sparcs.csv"
    pd.DataFrame(rows).to_csv(source, index=False)
    first = tmp_path / "first"
    second = tmp_path / "second"

    generate_serialize_artifacts(source, first)
    generate_serialize_artifacts(source, second)

    for filename in ("sample_structured.txt", "sample_fluent.txt", "serialize_manifest.json"):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    assert _manifest(first)["sample_audit"]["class_counts"] == {
        "aval_institu": 5,
        "domicile": 5,
    }


def _row(disposition: str, marker: int) -> dict[str, object]:
    return {
        "Age Group": "70 or Older",
        "Gender": "F",
        "APR DRG Description": f"DRG {marker}",
        "APR Severity of Illness Description": "Major",
        "APR Risk of Mortality": "Moderate",
        "APR Medical Surgical Description": "Medical",
        "CCSR Diagnosis Description": f"Clinical category {marker}",
        "Type of Admission": "Emergency",
        "Emergency Department Indicator": "Y",
        "Health Service Area": "New York City",
        "Payment Typology 1": "Medicare",
        "Length of Stay": "9",
        "Total Charges": "999999",
        "Patient Disposition": disposition,
    }
