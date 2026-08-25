"""Tests for the Nantes preflight GO/RESTRICT/NO-GO (HOS-003)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.connectors.schemas.canonical_schema import load_canonical_schema
from services.validation.preflight import (
    Coverage,
    Decision,
    MappingEntry,
    MappingTemplate,
    PreflightConfigError,
    _match_forbidden,
    load_template,
    main,
    run_preflight,
    validate_template_against_schema,
)

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "nantes"


def _columns(name: str) -> list[str]:
    with (_FIXTURES / name).open("r", encoding="utf-8") as handle:
        return list(json.load(handle)["columns"])


def _run(name: str):  # type: ignore[no-untyped-def]
    return run_preflight(_columns(name), run_id="test", template=load_template())


def test_go_full_conforming_extraction() -> None:
    report = _run("columns_go.json")
    assert report.decision is Decision.GO
    assert report.exit_code == 0
    assert not report.forbidden_columns
    assert not report.unknown_columns
    required = [f for f in report.fields if f.requirement == "required"]
    assert all(f.coverage is Coverage.MAPPED for f in required)


def test_restrict_unknown_and_forecast_only() -> None:
    report = _run("columns_restrict.json")
    assert report.decision is Decision.RESTRICT
    assert report.exit_code == 10
    assert "code_pmsi" in report.unknown_columns
    # staffing + capacity absent -> forecast-only reason present.
    assert any("forecast-only" in r for r in report.reasons)


def test_nogo_forbidden_columns() -> None:
    report = _run("columns_nogo_forbidden.json")
    assert report.decision is Decision.NO_GO
    assert report.exit_code == 20
    assert "Nom_Patient" in report.forbidden_columns
    assert "commentaire_libre" in report.forbidden_columns


def test_nogo_required_missing() -> None:
    report = _run("columns_nogo_missing.json")
    assert report.decision is Decision.NO_GO
    assert report.exit_code == 20
    missing = [f.canonical for f in report.fields if f.coverage is Coverage.MISSING]
    assert "identity.service_id" in missing


def test_forbidden_catches_date_of_birth_with_filler() -> None:
    # Regression: substring matching missed 'date_de_naissance'. Token matching catches it.
    report = _run("columns_leak_dob.json")
    assert report.decision is Decision.NO_GO
    assert "date_de_naissance" in report.forbidden_columns


def test_legitimate_soins_columns_not_blocked() -> None:
    # Regression: substring matching wrongly blocked 'charge_soins' / 'nombre_lits' ('ins'/'nom').
    report = _run("columns_clean_soins.json")
    assert not report.forbidden_columns
    assert report.decision is not Decision.NO_GO
    for legit in ("charge_soins", "nb_soins_realises", "nombre_lits", "denomination_uf"):
        assert legit in report.unknown_columns


@pytest.mark.parametrize(
    ("column", "blocked"),
    [
        ("Nom_Patient", True),
        ("commentaire_libre", True),
        ("ADRÉSSE_Patient", True),
        ("date_de_naissance", True),
        ("numero_securite_sociale", True),
        ("code_postal", True),
        ("ville_residence", True),
        ("charge_soins", False),
        ("nombre_presents", False),
        ("denomination_uf", False),
        ("score_autonomie", False),
        ("code_pmsi", False),
    ],
)
def test_forbidden_token_matching(column: str, blocked: bool) -> None:
    template = load_template()
    assert _match_forbidden(column, template.forbidden_patterns) is blocked


def test_determinism() -> None:
    first = _run("columns_restrict.json").to_dict()
    second = _run("columns_restrict.json").to_dict()
    assert first == second


def test_report_exposes_five_coverage_categories() -> None:
    report = _run("columns_nogo_forbidden.json")
    cov = report.to_dict()["coverage"]
    assert set(cov) == {"mapped", "derived", "missing", "unknown", "forbidden"}


def test_provenance_stamped() -> None:
    d = _run("columns_go.json").to_dict()
    assert d["run_id"] == "test"
    assert d["schema_version"] == "1.0.0"
    assert d["template_version"] == "1.0.0"


def test_contract_requests_no_nominative_data() -> None:
    template = load_template()
    for entry in template.entries:
        assert not _match_forbidden(entry.source, template.forbidden_patterns), entry.source


def test_template_targets_validated_against_schema() -> None:
    spec = load_canonical_schema()
    # Real template passes.
    validate_template_against_schema(load_template(), spec)
    # A typo'd canonical target fails fail-closed.
    bad = MappingTemplate(
        schema_ref="canonical@1.0.0",
        version="1.0.0",
        entries=(MappingEntry("identiy.hospital_id", "x", "required"),),
        forbidden_patterns=(),
    )
    with pytest.raises(PreflightConfigError):
        validate_template_against_schema(bad, spec)


def test_derived_coverage_path() -> None:
    # DERIVED coverage exercised via a synthetic template with a derivable field.
    template = MappingTemplate(
        schema_ref="canonical@1.0.0",
        version="1.0.0",
        entries=(
            MappingEntry("flow.admissions", "a", "optional"),
            MappingEntry("flow.discharges", "d", "optional"),
            MappingEntry("flow.occupancy", "occ", "optional", derivable_from=("a", "d")),
        ),
        forbidden_patterns=(),
    )
    report = run_preflight(["a", "d"], run_id="t", template=template)
    occ = next(f for f in report.fields if f.canonical == "flow.occupancy")
    assert occ.coverage is Coverage.DERIVED


def test_cli_exit_codes(tmp_path: Path) -> None:
    assert main(["--columns", str(_FIXTURES / "columns_go.json")]) == 0
    assert main(["--columns", str(_FIXTURES / "columns_restrict.json")]) == 10
    assert main(["--columns", str(_FIXTURES / "columns_nogo_forbidden.json")]) == 20
    out = tmp_path / "report.json"
    main(["--columns", str(_FIXTURES / "columns_go.json"), "--json", str(out)])
    payload = json.loads(out.read_text())
    assert payload["decision"] == "GO"
    assert payload["exit_code"] == 0


def test_cli_usage_error_on_bad_manifest(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert main(["--columns", str(bad)]) == 1
