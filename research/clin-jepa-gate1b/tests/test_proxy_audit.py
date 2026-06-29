"""Tests that bite on the preregistered proxy audit statistics."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from loaders.proxy_audit import compute_proxy_audit, write_proxy_audit

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "runs" / "serialize" / "proxy_audit.json"


def test_checked_in_proxy_audit_contains_required_real_statistics() -> None:
    audit = json.loads(ARTIFACT.read_text(encoding="utf-8"))

    assert audit["source_rows"] > 0
    assert isinstance(audit["drg_rule_auprc_floor"], (int, float))
    assert 0.0 <= audit["drg_rule_auprc_floor"] <= 1.0
    assert 0.0 <= audit["top10_drg_positive_share"] <= 1.0
    assert audit["age_proxy"]["seventy_plus"]["count"] > 0
    assert audit["age_proxy"]["other_ages"]["count"] > 0


def test_proxy_audit_computes_age_gap_top_share_and_drg_rule_floor() -> None:
    frame = _canonical_fixture()

    audit = compute_proxy_audit(frame)

    assert audit["age_proxy"]["seventy_plus"]["aval_rate"] == 0.75
    assert audit["age_proxy"]["other_ages"]["aval_rate"] == 0.25
    assert audit["top10_drg_positive_share"] == 1.0
    assert audit["drg_rule"]["rate_threshold"] == 0.5
    assert audit["drg_rule"]["predicted_positive_count"] == 4
    assert audit["drg_rule_auprc_floor"] > audit["baseline_prevalence"]


def test_proxy_audit_writes_json_and_markdown_without_model_metrics(tmp_path: Path) -> None:
    source = tmp_path / "sparcs.csv"
    _raw_fixture().to_csv(source, index=False)

    audit = write_proxy_audit(source, tmp_path / "out")
    markdown = (tmp_path / "out" / "proxy_audit.md").read_text(encoding="utf-8")

    assert (tmp_path / "out" / "proxy_audit.json").exists()
    assert "pas une fuite technique" in markdown
    assert "hard-case" in markdown
    assert "drg_rule_auprc_floor" not in audit.get("model_metrics", {})


def _canonical_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "age_group": ["70 or Older"] * 4 + ["30-49"] * 4,
            "apr_drg": ["DRG HIGH"] * 4 + ["DRG LOW"] * 4,
            "ccsr_diagnosis": ["FAMILY HIGH"] * 4 + ["FAMILY LOW"] * 4,
            "target_disposition": [
                "aval_institu",
                "aval_institu",
                "aval_institu",
                "domicile",
                "aval_institu",
                "domicile",
                "domicile",
                "domicile",
            ],
        }
    )


def _raw_fixture() -> pd.DataFrame:
    rows = []
    canonical = _canonical_fixture()
    disposition = {
        "aval_institu": "Skilled Nursing Home",
        "domicile": "Home or Self Care",
    }
    for row in canonical.itertuples(index=False):
        rows.append(
            {
                "Age Group": row.age_group,
                "APR DRG Description": row.apr_drg,
                "CCSR Diagnosis Description": row.ccsr_diagnosis,
                "Patient Disposition": disposition[row.target_disposition],
            }
        )
    return pd.DataFrame(rows)
