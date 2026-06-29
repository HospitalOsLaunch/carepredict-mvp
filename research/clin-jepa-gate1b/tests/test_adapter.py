"""Tests that lock SPARCS mapping, leakage, and class-audit behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from loaders.sparcs_adapter import (
    APR_FEATURES,
    DISPOSITION_MAP,
    MajorDispositionUnmappedError,
    class_distribution_from_counts,
    disposition_value_counts,
    feature_audit,
    load_canonical,
    mapping_audit_from_counts,
    tabular_features,
    write_audit_artifacts,
)


def _row(disposition: str, *, los: str = "7") -> dict[str, str]:
    return {
        "Age Group": "70 or Older",
        "Gender": "F",
        "Race": "White",
        "Ethnicity": "Not Span/Hispanic",
        "APR DRG Description": "HIP JOINT REPLACEMENT",
        "APR Severity of Illness Description": "Major",
        "APR Risk of Mortality": "Moderate",
        "APR Medical Surgical Description": "Surgical",
        "CCSR Diagnosis Description": "OSTEOARTHRITIS",
        "Type of Admission": "Emergency",
        "Emergency Department Indicator": "Y",
        "Health Service Area": "New York City",
        "Payment Typology 1": "Medicare",
        "Length of Stay": los,
        "Total Charges": "123456.78",
        "Total Costs": "45678.90",
        "Patient Disposition": disposition,
    }


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_adapter_maps_three_classes_and_keeps_los_out_of_features(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path / "sparcs.csv",
        [
            _row("Home or Self Care", los="2"),
            _row("Skilled Nursing Home", los="11"),
            _row("Expired", los="5"),
        ],
    )

    canonical = load_canonical(path)

    assert set(canonical["target_disposition"]) == {"domicile", "aval_institu", "autre"}
    assert canonical["length_of_stay"].tolist() == [2, 11, 5]
    assert "length_of_stay" not in canonical.attrs["tabular_features"]
    assert "total_charges" not in canonical.attrs["tabular_features"]


def test_material_unmapped_disposition_fails_at_half_percent() -> None:
    raw = pd.DataFrame(
        {"Patient Disposition": ["Home or Self Care"] * 199 + ["Mystery Facility"]}
    )
    counts = disposition_value_counts(raw)

    with pytest.warns(UserWarning, match="UNMAPPED"):
        audit = mapping_audit_from_counts(counts)

    assert audit["unmapped_count"] == 1
    assert audit["unmapped_rate"] == pytest.approx(0.005)
    assert audit["decision"] == "FAIL"
    with pytest.raises(MajorDispositionUnmappedError, match="Mystery Facility"):
        from loaders.sparcs_adapter import assert_material_dispositions_mapped

        assert_material_dispositions_mapped(audit)


def test_minor_unknown_is_listed_and_never_silently_mapped_to_other(tmp_path: Path) -> None:
    rows = [_row("Home or Self Care") for _ in range(999)] + [_row("Tiny Unknown")]
    path = _write_csv(tmp_path / "minor_unknown.csv", rows)
    counts = disposition_value_counts(pd.DataFrame(rows))

    with pytest.warns(UserWarning, match="Tiny Unknown"):
        audit = mapping_audit_from_counts(counts)
    with pytest.warns(UserWarning, match="Tiny Unknown"):
        canonical = load_canonical(path)

    assert audit["decision"] == "PASS"
    assert audit["unmapped_values"][0]["patient_disposition"] == "Tiny Unknown"
    assert pd.isna(canonical["target_disposition"].iloc[-1])


def test_apr_fields_are_excluded_by_default_and_flag_gated() -> None:
    no_apr = tabular_features()
    with_apr = tabular_features(include_apr=True)

    assert set(APR_FEATURES).isdisjoint(no_apr)
    assert set(APR_FEATURES).issubset(with_apr)
    assert len(with_apr) == len(no_apr) + len(APR_FEATURES)


def test_feature_audit_logs_leak_prone_columns_and_both_configs(caplog: pytest.LogCaptureFixture) -> None:
    raw = pd.DataFrame([_row("Home or Self Care")])

    with caplog.at_level("WARNING"):
        audit = feature_audit(raw)

    excluded = {item["source_column"] for item in audit["excluded_source_columns"]}
    assert {"Length of Stay", "Total Charges", "Total Costs", "Patient Disposition"}.issubset(
        excluded
    )
    assert audit["active_configuration"] == "no_apr"
    assert set(APR_FEATURES).isdisjoint(audit["active_features"])
    assert set(APR_FEATURES).issubset(audit["configurations"]["with_apr"])
    assert "excluded leak-prone columns" in caplog.text


def test_class_distribution_reports_prevalence_and_rare_positive_warning() -> None:
    raw = pd.DataFrame(
        {"Patient Disposition": ["Home or Self Care"] * 99 + ["Skilled Nursing Home"]}
    )
    counts = disposition_value_counts(raw)

    with pytest.warns(RuntimeWarning, match="positive class too rare"):
        distribution = class_distribution_from_counts(counts)

    assert distribution["class_counts"]["aval_institu"] == 1
    assert distribution["aval_institu_rate"] == pytest.approx(0.01)
    assert distribution["baseline_auprc_prevalence"] == pytest.approx(0.01)


def test_step1_artifacts_exclude_predictive_metrics_and_bootstrap(tmp_path: Path) -> None:
    source = _write_csv(
        tmp_path / "sparcs.csv",
        [
            _row("Home or Self Care"),
            _row("Skilled Nursing Home"),
            _row("Expired"),
        ],
    )
    output = tmp_path / "runs"

    result = write_audit_artifacts(
        source_path=source,
        disposition_path=None,
        output_dir=output,
    )

    expected = {
        "disposition_value_counts.csv",
        "disposition_audit.md",
        "mapping_audit.json",
        "class_distribution.json",
        "feature_audit.json",
        "summary.md",
    }
    assert {path.name for path in output.iterdir()} == expected
    assert not list(output.glob("metrics_*.json"))
    assert "bootstrap" not in result
    feature_payload = json.loads((output / "feature_audit.json").read_text())
    assert feature_payload["active_configuration"] == "no_apr"
    assert "deferred to Step 5" in (output / "summary.md").read_text()


def test_all_observed_2024_dispositions_are_explicitly_mapped() -> None:
    observed = {
        "Home or Self Care",
        "Home w/ Home Health Services",
        "Skilled Nursing Home",
        "Left Against Medical Advice",
        "Expired",
        "Short-term Hospital",
        "Inpatient Rehabilitation Facility",
        "Hospice - Home",
        "Psychiatric Hospital or Unit of Hosp",
        "Hospice - Medical Facility",
        "Facility w/ Custodial/Supportive Care",
        "Another Type Not Listed",
        "Court/Law Enforcement",
        "Medicare Cert Long Term Care Hospital",
        "Medicaid Cert Nursing Facility",
        "Cancer Center or Childrens Hospital",
        "Hosp Basd Medicare Approved Swing Bed",
        "Federal Health Care Facility",
        "Critical Access Hospital",
    }
    assert observed == set(DISPOSITION_MAP)
