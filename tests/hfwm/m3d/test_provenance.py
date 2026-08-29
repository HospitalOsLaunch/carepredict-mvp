"""M3D.1 provenance, partner translation, and no-execution gates."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from hfwm.m3d.contracts import validate_external_claims_ledger
from hfwm.m3d.release import load_scope

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs/research/hfwm"
LEDGER_PATH = DOCS / "HFWM_R0_M3_EXTERNAL_CLAIMS_LEDGER.yaml"
PARTNER_PATH = DOCS / "HFWM_R0_M3_PARTNER_DATA_REQUEST.md"
AMENDMENT_PATH = DOCS / "HFWM_R0_M3D1_AMENDMENT.md"
EPISODE_SPEC_PATH = DOCS / "HFWM_R0_M3_EPISODE_SPEC.yaml"
M2_RESULTS_PATH = ROOT / "artifacts/hfwm-r0/bakeoff-m2b/results.json"
MANIFEST_PATH = ROOT / "artifacts/hfwm-r0/m3d/manifest.json"


def _yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_agora_git_trace_reflects_recorded_history_and_is_removed_from_partner_package() -> None:
    history = subprocess.run(
        ["git", "log", "--all", "--reverse", "-SAGORA", "--format=%H", "--"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    commits = [line for line in history.stdout.splitlines() if line]
    # The first tracked occurrence is recorded by the release-freeze commit.
    # This proves repository provenance only; it does not prove editorial origin.
    assert commits
    assert commits[0] == "6cd4819ef342a2382213b5f51b0f4dde634fe7fa"
    assert "AGORA" not in PARTNER_PATH.read_text(encoding="utf-8").upper()
    amendment = AMENDMENT_PATH.read_text(encoding="utf-8")
    assert "première occurrence enregistrée" in amendment
    ledger = _yaml(LEDGER_PATH)
    original = ledger["claims"]["AGORA_HISTORICAL_PORTAL"]
    assert original["source_status"] == "UNSUPPORTED_REMOVE"
    assert original["supports_claim"] is False
    assert "non vérifié à ce stade" in original["claim_text"]
    current = ledger["claims"]["AGORA_CURRENT_PDF_ARTICLE_9"]
    assert current["attests_asserted_role"] is True
    assert current["external_exposure"] == "INTERNAL_PROVENANCE_ONLY"


def test_all_release_claim_files_are_covered_by_claims_ledger() -> None:
    ledger = _yaml(LEDGER_PATH)
    validate_external_claims_ledger(ledger)
    files = ledger["files_audited"]
    assert len(files) == 33
    assert len({entry["file"] for entry in files}) == 33
    assert all((ROOT / entry["file"]).is_file() for entry in files)
    scope = load_scope(DOCS / "HFWM_R0_M3D1_RELEASE_SCOPE.yaml")
    audited_paths = {entry["file"] for entry in files}
    for entry in scope["files"]:
        if entry["classification"] in {
            "EXTERNAL_CLAIM_SURFACE",
            "EXECUTABLE_EXTERNAL_CONTRACT",
        }:
            assert entry["path"] in audited_paths


def test_unsupported_external_claim_cannot_be_exposed() -> None:
    ledger = _yaml(LEDGER_PATH)
    broken = copy.deepcopy(ledger)
    broken["claims"]["UNSUPPORTED_WEEKLY_COMMITTEE"][
        "external_exposure"
    ] = "EXTERNAL_PARTNER_DOCUMENT"
    with pytest.raises(ValueError, match="unsupported claim exposed"):
        validate_external_claims_ledger(broken)


def test_official_source_must_attest_asserted_role_not_only_contain_term() -> None:
    ledger = _yaml(LEDGER_PATH)
    broken = copy.deepcopy(ledger)
    broken["claims"]["HCL_GOVERNANCE_CSE"]["attests_asserted_role"] = False
    with pytest.raises(ValueError, match="does not attest asserted role"):
        validate_external_claims_ledger(broken)


def test_partner_request_uses_calendar_scope_and_conservative_attrition() -> None:
    partner = PARTNER_PATH.read_text(encoding="utf-8")
    assert "continuous_history_months_minimum: 28" in partner
    assert "continuous_history_months_preferred: 36" in partner
    assert "hospital_sites_target: up_to_12_subject_to_comparable_unit_availability" in partner
    assert "hospital_sites_minimum_subject_to_blinded_recalculation: 8" in partner
    assert "site_count_semantics: FEASIBILITY_TARGET_NOT_INSTITUTION_WIDE_REQUIREMENT" in partner
    assert "comparable_unit_family: PARTNER_TO_CONFIRM" in partner
    assert "units_per_site: 4" in partner
    assert (
        "temporal_granularity: candidate_granularity_subject_to_partner_disclosure_and_"
        "feasibility_review"
    ) in partner
    assert "candidate_aggregation_granularity: 6_hours_reconstructed_by_executable_spec" in partner
    assert "8 sites = `feasibility_floor`" in partner
    assert "60 %" in partner
    assert "nombre d'épisodes" not in partner.lower()
    assert "Comité Scientifique et Éthique de la recherche sur les données de santé" in partner
    assert "CSE-EDS" in partner
    assert "Comité Social d'Établissement" in partner
    assert "article 111" in partner
    assert "Aucun mouvement pseudonymisé n'est demandé" in partner
    amendment = AMENDMENT_PATH.read_text(encoding="utf-8")
    assert "COUNT: P(FAIL)=4,55 %, UCB95=4,692 % ≤ 5 %" in amendment
    assert "RATE: P(FAIL)=4,48 %, UCB95=4,622 % ≤ 5 %" in amendment
    assert "HOLD_NO_ADVANCE" in amendment
    assert "NO_GO_M3_INSUFFICIENT_EFFECTIVE_SAMPLE_SIZE" in amendment
    for required in (
        "dernière migration majeure du SIH",
        "dernier changement de DPI",
        "dernier changement de gestion des lits",
        "modification des conventions de census",
        "ruptures de codage",
        "périodes de double run",
    ):
        assert required in partner


def test_internal_conversion_uses_actual_episode_spec_and_60pct_loss() -> None:
    episode = _yaml(EPISODE_SPEC_PATH)["episode_window"]
    assert episode["context_duration"] == "336_hours"
    assert episode["maximum_rollout_horizon"] == "24_hours"
    assert episode["full_episode_span"] == "360_hours"
    assert episode["independent_episode_stride"] == "360_hours"
    assert episode["temporal_block_duration"] == "30_days"
    raw_required = 8 * 4 * 28 * 2
    eligible_after_attrition = round(raw_required * 0.40)
    assert raw_required == 1792
    assert eligible_after_attrition == 717
    assert eligible_after_attrition >= 640


def test_m2_deterministic_arms_are_not_counted_as_seed_replications() -> None:
    results = json.loads(M2_RESULTS_PATH.read_text(encoding="utf-8"))
    by_arm: dict[str, list[dict[str, Any]]] = {}
    for run in results["raw_runs"]:
        by_arm.setdefault(run["arm_id"], []).append(run)
    assert len(by_arm) == 4
    for runs in by_arm.values():
        assert {run["seed"] for run in runs} == {1729, 2718, 3141}
        assert len({run["prediction_hash"] for run in runs}) == 1
        assert len({run["repeat_prediction_hash"] for run in runs}) == 1
    audit = (DOCS / "HFWM_R0_M3_SEED_REACHABILITY_AUDIT.md").read_text(encoding="utf-8")
    assert "ONE_FIT_PER_CONFIGURATION" in audit
    assert "poids n'ont pas été persistés" in audit
    assert "douze lignes M2" in audit
    assert "fundraising_evidence_allowed: false" in audit
    assert "weights_hash` est un hard fail" in audit
    ticket = (DOCS / "HFWM_R0_M2_SEED_AUDIT_TICKET.md").read_text(encoding="utf-8")
    assert "training_replay_authorized: true" in ticket
    assert "blocks_partner_document_review: false" in ticket


def test_m3d1_does_not_authorize_execution_or_claim_partner_data() -> None:
    for path in (
        DOCS / "HFWM_R0_M3_DATA_CONTRACT.yaml",
        DOCS / "HFWM_R0_M3_EPISODE_SPEC.yaml",
        DOCS / "HFWM_R0_M3F_HOLDOUT_POLICY.yaml",
    ):
        text = path.read_text(encoding="utf-8")
        assert "training_authorized: false" in text or "m3l_authorized: false" in text
    # Commit A is validated before the Commit-B attestation manifest exists.
    # When this test runs against B, enforce the manifest's no-execution gates.
    if MANIFEST_PATH.is_file():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        assert manifest["training_executed"] is False
        assert manifest["partner_data_consumed"] is False
        assert manifest["m3l_authorized"] is False
        assert manifest["m3f_authorized"] is False
