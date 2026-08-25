"""Tests for Validator v2 — the eight NO-GO defects + delegated checks (HOS-006)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from services.validation.validator import (
    CorruptFileError,
    Decision,
    UsageError,
    load_records,
    main,
    validate_batch,
)

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "validator"
_PARIS = ZoneInfo("Europe/Paris")


def _run(name: str, **kwargs):  # type: ignore[no-untyped-def]
    records, domain = load_records(_FIXTURES / name, None)
    return validate_batch(records, domain, run_id="test", **kwargs)


def test_valid_batch_is_go() -> None:
    report = _run("valid.json")
    assert report.decision is Decision.GO
    assert report.exit_code == 0
    assert report.findings == []


def test_defect1_corrupt_file_no_go_no_crash() -> None:
    with pytest.raises(CorruptFileError):
        load_records(_FIXTURES / "defect1_corrupt.json", "care_load")
    assert main(["--input", str(_FIXTURES / "defect1_corrupt.json"), "--domain", "care_load"]) == 20


@pytest.mark.parametrize(
    ("fixture", "expected_code"),
    [
        ("defect2_schema.json", "missing_required"),
        ("defect3_types.json", "type_mismatch"),
        ("defect4_values.json", "out_of_range"),
        ("defect5_timestamps.json", "temporal_order"),
        ("defect6_duplicates.json", "duplicate_record"),
        ("defect8_categories.json", "enum_violation"),
        ("defect_conflict.json", "conflicting_restatement"),
    ],
)
def test_defect_yields_no_go_with_code(fixture: str, expected_code: str) -> None:
    report = _run(fixture)
    assert report.decision is Decision.NO_GO
    assert report.exit_code == 20
    assert any(f.code == expected_code for f in report.findings)


def test_defect7_missingness_is_restrict() -> None:
    report = _run("defect7_missingness.json")
    assert report.decision is Decision.RESTRICT
    assert any(f.code == "missingness" for f in report.findings)


def test_lag_degeneracy_is_restrict() -> None:
    report = _run("defect_lag_degeneracy.json")
    assert report.decision is Decision.RESTRICT
    assert any(f.code == "lag_degeneracy" for f in report.findings)


def test_legitimate_restatement_not_flagged() -> None:
    report = _run("restatement_ok.json")
    codes = {f.code for f in report.findings}
    assert "duplicate_record" not in codes
    assert "conflicting_restatement" not in codes
    assert report.decision is Decision.GO


def test_empty_extraction_is_no_go() -> None:
    report = validate_batch([], "care_load", run_id="t")
    assert report.decision is Decision.NO_GO
    assert any(f.code == "empty_extraction" for f in report.findings)


def test_history_span_below_minimum_is_restrict() -> None:
    report = _run("valid.json", min_history_days=90)
    assert report.decision is Decision.RESTRICT
    assert any(f.code == "history_span" for f in report.findings)


def test_future_timestamp_detected_against_reference() -> None:
    records, domain = load_records(_FIXTURES / "valid.json", None)
    past_reference = datetime(2026, 8, 11, 8, 30, tzinfo=_PARIS)  # before the 09:00 record
    report = validate_batch(records, domain, run_id="t", reference_time=past_reference)
    assert report.decision is Decision.NO_GO
    assert any(f.code == "timestamp_future" for f in report.findings)


def test_naive_reference_time_rejected() -> None:
    records, domain = load_records(_FIXTURES / "valid.json", None)
    naive = datetime(2026, 8, 11, 8, 30)  # tz-naive
    with pytest.raises(ValueError, match="tz-aware"):
        validate_batch(records, domain, run_id="t", reference_time=naive)


def test_determinism_same_input_same_report() -> None:
    first = _run("defect_conflict.json").to_dict()
    second = _run("defect_conflict.json").to_dict()
    assert first == second
    findings = _run("defect_conflict.json").findings
    assert findings == sorted(findings)


def test_no_sensitive_value_echoed() -> None:
    report = _run("defect3_types.json")
    blob = json.dumps(report.to_dict())
    assert "vingt-quatre" not in blob


def test_report_carries_provenance_and_summary() -> None:
    d = _run("valid.json").to_dict()
    assert d["schema_version"] == "1.0.0"
    assert d["run_id"] == "test"
    assert d["domain"] == "care_load"
    assert d["record_count"] == 2
    assert set(d["summary"]) == {"errors", "warnings", "findings"}


def test_cli_valid_go(tmp_path: Path) -> None:
    out = tmp_path / "r.json"
    code = main(["--input", str(_FIXTURES / "valid.json"), "--json", str(out)])
    assert code == 0
    assert json.loads(out.read_text())["decision"] == "GO"


def test_cli_malformed_now_is_usage_error() -> None:
    assert main(["--input", str(_FIXTURES / "valid.json"), "--now", "not-a-date"]) == 1


def test_cli_missing_domain_is_usage_error(tmp_path: Path) -> None:
    f = tmp_path / "list.json"
    f.write_text("[]", encoding="utf-8")
    with pytest.raises(UsageError):
        load_records(f, None)
    assert main(["--input", str(f)]) == 1
