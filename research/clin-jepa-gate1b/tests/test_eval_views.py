"""Blocking tests for proxy-controlled hard-case evaluation views."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from loaders.eval_views import BLOCKING_WARNING, THRESHOLDS, build_eval_views

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "runs" / "serialize"


def _read(name: str) -> dict:
    return json.loads((ARTIFACT_DIR / name).read_text(encoding="utf-8"))


def test_checked_in_indexes_have_both_classes_and_required_metric_guards() -> None:
    stratified = _read("hard_case_stratified_index.json")
    matched = _read("hard_case_matched_index.json")

    for payload in (stratified, matched):
        assert payload["class_counts_after"]["aval_institu"] > 0
        assert payload["class_counts_after"]["non_aval"] > 0
        assert "loss_rate_positive" in payload
        assert payload["stay_ids"]
    assert stratified["auprc_comparable_to_natural_floor"] is True
    assert "recomputed on this view" in stratified["comparability_note"]
    assert isinstance(stratified["observed_prevalence_shift"], float)
    assert matched["baselines_must_be_recomputed_on_this_prevalence"] is True


def test_threshold_sweep_and_selection_rule_are_frozen() -> None:
    sweep = _read("threshold_sweep.json")
    rows = sweep["thresholds"]

    assert {row["min_per_class"] for row in rows} == set(THRESHOLDS)
    assert all("loss_rate_positive" in row for row in rows)
    passing = [
        row["min_per_class"] for row in rows if row["loss_rate_positive"] <= 0.50
    ]
    expected = min(passing) if passing else 5
    assert sweep["min_per_class_selected"] == expected
    assert (sweep["blocking_warning"] is not None) is (not passing)


def test_eval_preregistration_locks_roles_and_prevalence_comparability() -> None:
    prereg = _read("eval_preregistration.json")

    assert prereg["primary_lift_view"] == "hard_case_stratified"
    assert prereg["confound_control_view"] == "hard_case_matched"
    assert prereg["view_roles"]["full_structured"] == "upper_bound_only"
    assert prereg["view_roles"]["no_drg_structured"] == "lower_bound_only"
    assert prereg["decision_locked_before_encoding"] is True
    assert "recompute ALL baselines" in prereg["matched_metric_rule"]
    assert "eligibility filtering" in prereg["stratified_metric_caveat"]


def test_index_artifacts_do_not_serialize_leak_prone_source_fields() -> None:
    forbidden = (
        "patient disposition",
        "length_of_stay",
        "total_charges",
        "total_costs",
        "apr_severity",
        "apr_risk_mortality",
    )
    for name in ("hard_case_stratified_index.json", "hard_case_matched_index.json"):
        text = (ARTIFACT_DIR / name).read_text(encoding="utf-8").lower()
        assert not any(token in text for token in forbidden)


def test_all_thresholds_over_loss_limit_emit_blocking_warning() -> None:
    canonical = _destructive_fixture()

    with pytest.warns(RuntimeWarning, match="stop and review"):
        payloads = build_eval_views(
            canonical,
            baseline_prevalence=0.5,
            drg_rule_floor=0.5,
        )

    sweep = payloads["threshold_sweep"]
    assert all(row["loss_rate_positive"] > 0.50 for row in sweep["thresholds"])
    assert sweep["min_per_class_selected"] == 5
    assert sweep["blocking_warning"] == BLOCKING_WARNING


def test_matched_index_is_deterministic_at_seed_42() -> None:
    canonical = _balanced_fixture()

    first = build_eval_views(canonical, baseline_prevalence=0.5, drg_rule_floor=0.5)
    second = build_eval_views(canonical, baseline_prevalence=0.5, drg_rule_floor=0.5)

    assert first["hard_case_matched_index"]["seed"] == 42
    assert (
        first["hard_case_matched_index"]["stay_ids"]
        == second["hard_case_matched_index"]["stay_ids"]
    )


def _destructive_fixture() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    stay_id = 0
    for _ in range(20):
        rows.append(_row(stay_id, "70 or Older", "POSITIVE ONLY", "aval_institu"))
        stay_id += 1
    for label in (["aval_institu"] * 5 + ["domicile"] * 5):
        rows.append(_row(stay_id, "50-69", "SMALL ELIGIBLE", label))
        stay_id += 1
    return pd.DataFrame(rows)


def _balanced_fixture() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    stay_id = 0
    for family in ("CARDIAC", "NEURO"):
        for label in (["aval_institu"] * 20 + ["domicile"] * 80):
            rows.append(_row(stay_id, "70 or Older", family, label))
            stay_id += 1
    return pd.DataFrame(rows)


def _row(stay_id: int, age: str, family: str, target: str) -> dict[str, object]:
    return {
        "stay_id": stay_id,
        "age_group": age,
        "ccsr_diagnosis": family,
        "target_disposition": target,
    }
