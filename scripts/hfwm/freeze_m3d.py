"""Freeze M3D pre-data evidence without training or partner-data access."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from hfwm.m3d.contracts import (
    assert_fixture_only,
    generate_assumed_questions,
    replayability_decision,
    score_replayability,
    validate_external_claims_ledger,
)
from hfwm.m3d.power import run_power_plan
from hfwm.m3d.release import (
    enumerate_release_scope,
    git_tree_sha,
    load_scope,
    validate_release_scope,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"expected mapping: {path}")
    return document


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/hfwm-r0/m3d"))
    parser.add_argument("--power-repetitions", type=int, default=40_000)
    parser.add_argument("--critical-repetitions", type=int, default=82_000)
    parser.add_argument("--calibration-repetitions", type=int, default=40_000)
    parser.add_argument("--verification-command", action="append", default=[])
    parser.add_argument("--verification-result", action="append", default=[])
    parser.add_argument("--blocker", action="append", default=[])
    parser.add_argument("--release-content-commit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repository_root.resolve()
    output_dir = (root / args.output_dir).resolve()
    docs = root / "docs/research/hfwm"
    scope_path = docs / "HFWM_R0_M3D1_RELEASE_SCOPE.yaml"
    data_contract_path = docs / "HFWM_R0_M3_DATA_CONTRACT.yaml"
    episode_spec_path = docs / "HFWM_R0_M3_EPISODE_SPEC.yaml"
    replay_spec_path = docs / "HFWM_R0_M3_REPLAYABILITY_SPEC.yaml"
    claims_ledger_path = docs / "HFWM_R0_M3_EXTERNAL_CLAIMS_LEDGER.yaml"
    fixture_path = root / "tests/fixtures/hfwm/m3d_synthetic_contract.yaml"

    data_contract = _load_yaml(data_contract_path)
    episode_spec = _load_yaml(episode_spec_path)
    replay_spec = _load_yaml(replay_spec_path)
    claims_ledger = _load_yaml(claims_ledger_path)
    validate_external_claims_ledger(claims_ledger)
    release_scope = load_scope(scope_path)
    scope_errors = validate_release_scope(root, release_scope)
    if scope_errors:
        raise ValueError("incomplete release scope: " + "; ".join(scope_errors))
    fixture = _load_yaml(fixture_path)
    assert_fixture_only(fixture)
    questions = generate_assumed_questions(data_contract, episode_spec)
    _write_json(output_dir / "partner_questions.json", {"questions": questions})

    thresholds = replay_spec["dimensions"]
    eligibility: dict[str, object] = {
        "schema_version": "hfwm.r0.m3d.fixture-eligibility.v1",
        "frozen_before_outcomes": True,
        "synthetic_only": True,
        "rows": [],
    }
    rows = eligibility["rows"]
    if not isinstance(rows, list):
        raise AssertionError("eligibility rows must be a list")
    for vector_id, vector in fixture["replayability_vectors"].items():
        scores = score_replayability(vector["evidence"], rubric=thresholds)
        decision = replayability_decision(
            scores,
            thresholds=thresholds,
            historical_available_at=vector["historical_available_at"],
        )
        rows.append(
            {
                "vector_id": vector_id,
                "hospital_group_id": vector["hospital_group_id"],
                "hospital_site_id": vector["hospital_site_id"],
                "unit_id": vector["unit_id"],
                "temporal_block_id": vector["temporal_block_id"],
                "scores_from_raw_evidence": scores,
                "aggregate_score": decision.aggregate_score,
                "eligible": decision.eligible,
                "hard_fail_dimensions": list(decision.hard_fail_dimensions),
                "exclusion_reasons": list(decision.exclusion_reasons),
                "historical_realtime_claim_allowed": (decision.historical_realtime_claim_allowed),
            }
        )
    _write_json(output_dir / "eligibility_mask_fixture.json", eligibility)

    power = run_power_plan(
        seed=31082026,
        ordinary_repetitions=args.power_repetitions,
        critical_repetitions=args.critical_repetitions,
        calibration_repetitions=args.calibration_repetitions,
    )
    _write_json(output_dir / "power_simulation.json", power)

    relative_files = [
        "docs/research/hfwm/CURRENT_MILESTONE.yaml",
        "docs/research/hfwm/HFWM_R0_M2C_POSTMORTEM.md",
        "docs/research/hfwm/HFWM_R0_M2_TARGET_DECOMPOSITION.md",
        "docs/research/hfwm/HFWM_R0_M3_DRAFT.yaml",
        "docs/research/hfwm/HFWM_R0_M3_SEED_REACHABILITY_AUDIT.md",
        "docs/research/hfwm/HFWM_R0_M3_EXTERNAL_CLAIMS_LEDGER.yaml",
        "docs/research/hfwm/HFWM_R0_M3D1_AMENDMENT.md",
        "docs/research/hfwm/HFWM_R0_M3D1_M2_DIFF_AUDIT.md",
        "docs/research/hfwm/HFWM_R0_M3D1_RELEASE_SCOPE.yaml",
        "docs/research/hfwm/HFWM_R0_M3_DISCLOSURE_SENSITIVITY.md",
        "docs/research/hfwm/HFWM_R0_M3_AGGREGATION_SPEC.yaml",
        "docs/research/hfwm/HFWM_R0_M2_SEED_AUDIT_TICKET.md",
        "docs/research/hfwm/HFWM_R0_M3D_HOSTILE_REVIEW.md",
        "docs/research/hfwm/HFWM_R0_M3_DATA_CONTRACT.yaml",
        "docs/research/hfwm/HFWM_R0_M3_EPISODE_SPEC.yaml",
        "docs/research/hfwm/HFWM_R0_M3_REPLAYABILITY_SPEC.yaml",
        "docs/research/hfwm/HFWM_R0_M3_POWER_PLAN.md",
        "docs/research/hfwm/HFWM_R0_M3_SAP.md",
        "docs/research/hfwm/HFWM_R0_M3F_HOLDOUT_POLICY.yaml",
        "docs/research/hfwm/HFWM_R0_M3_PARTNER_DATA_REQUEST.md",
        "src/hfwm/m3d/__init__.py",
        "src/hfwm/m3d/contracts.py",
        "src/hfwm/m3d/power.py",
        "src/hfwm/m3d/aggregation.py",
        "src/hfwm/m3d/release.py",
        "scripts/hfwm/freeze_m3d.py",
        "tests/fixtures/hfwm/m3d_synthetic_contract.yaml",
        "tests/hfwm/m3d/test_contracts.py",
        "tests/hfwm/m3d/test_power.py",
        "tests/hfwm/m3d/test_provenance.py",
        "tests/hfwm/m3d/test_aggregation.py",
        "tests/hfwm/m3d/test_release.py",
        "artifacts/hfwm-r0/m3d/partner_questions.json",
        "artifacts/hfwm-r0/m3d/eligibility_mask_fixture.json",
        "artifacts/hfwm-r0/m3d/power_simulation.json",
    ]
    files = {
        relative: _sha256(root / relative)
        for relative in relative_files
        if (root / relative).is_file()
    }
    prior_manifest_path = output_dir / "manifest.json"
    prior_manifest: dict[str, Any] = {}
    if prior_manifest_path.is_file():
        loaded_prior = json.loads(prior_manifest_path.read_text(encoding="utf-8"))
        if isinstance(loaded_prior, dict):
            prior_manifest = loaded_prior
    prior_hashes = prior_manifest.get("files_sha256", {})
    if not isinstance(prior_hashes, dict):
        prior_hashes = {}
    changed_files = {
        path: {"old_sha256": prior_hashes.get(path), "new_sha256": digest}
        for path, digest in files.items()
        if prior_hashes.get(path) != digest
    }
    assumed_paths = [question["convention_path"] for question in questions]
    claims = claims_ledger["claims"]
    if not isinstance(claims, dict):
        raise TypeError("claims ledger must contain a claims mapping")
    status_counts: dict[str, int] = {}
    for claim in claims.values():
        if isinstance(claim, dict):
            status = str(claim.get("source_status"))
            status_counts[status] = status_counts.get(status, 0) + 1
    partner_document = docs / "HFWM_R0_M3_PARTNER_DATA_REQUEST.md"
    agora_absent = "AGORA" not in partner_document.read_text(encoding="utf-8").upper()
    exposed_unsupported = any(
        isinstance(claim, dict)
        and claim.get("external_exposure") in {"EXTERNAL_PARTNER_DOCUMENT", "PARTNER_QUESTION_ONLY"}
        and claim.get("source_status") == "UNSUPPORTED_REMOVE"
        for claim in claims.values()
    )
    verification_green = bool(args.verification_result) and all(
        "passed" in result.lower() or "success" in result.lower() or "clean" in result.lower()
        for result in args.verification_result
    )
    release_content_commit = args.release_content_commit or _git(root, "rev-parse", "HEAD")
    if args.release_content_commit and release_content_commit != _git(root, "rev-parse", "HEAD"):
        raise ValueError("manifest must be generated from the checked-out release content commit A")
    if args.release_content_commit and _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("manifest must be generated from a clean checkout of A")
    discovered_scope = enumerate_release_scope(root)
    selected_design = power["selected_design_id"]
    icc_sensitivity = power["icc_sensitivity"]
    if not isinstance(icc_sensitivity, dict):
        raise TypeError("power output must contain an ICC sensitivity mapping")
    mechanical_release_checks_pass = bool(
        not exposed_unsupported
        and agora_absent
        and power["interval_procedure_valid_at_boundary"] is True
        and selected_design is not None
        and icc_sensitivity["selected_design_id"] is not None
        and verification_green
        and not args.blocker
    )
    # Fail closed until the independent post-tag reviewer has attested the
    # release.  The sidecar may authorize documentary transmission; B itself
    # must not claim that a review which has not run has passed.
    external_transmission_authorized = False
    manifest = {
        "schema_version": "hfwm.r0.m3d1.manifest.v2",
        "milestone_id": "HFWM-R0-M3D.1",
        "repository": {
            "branch": _git(root, "branch", "--show-current"),
            "head": _git(root, "rev-parse", "HEAD"),
            "working_tree_status": _git(root, "status", "--short").splitlines(),
        },
        "release_content_commit_sha": release_content_commit,
        "release_content_tree_sha": git_tree_sha(root, release_content_commit),
        "manifest_convention": (
            "This manifest attests release content commit A. The final release tag points "
            "to commit B whose parent is A and whose only release-content addition is "
            "this manifest."
        ),
        "release_review_artifact": {
            "path": "docs/research/hfwm/HFWM_R0_M3D1_RELEASE_REVIEW.yaml",
            "convention": "POST_TAG_SIDECAR_ASSOCIATED_WITH_TAG; NOT_A_COMMIT_B_CONTENT_FILE",
        },
        "m2_code_state": "M2_CODE_STATE_NOT_FULLY_RECOVERABLE",
        "m2_sensitive_diff_audit": "docs/research/hfwm/HFWM_R0_M3D1_M2_DIFF_AUDIT.md",
        "release_scope": {
            "scope_file": "docs/research/hfwm/HFWM_R0_M3D1_RELEASE_SCOPE.yaml",
            "filesystem_files_seen": len(discovered_scope["filesystem_files"]),
            "ignored_files_seen": len(discovered_scope["ignored_files"]),
            "classification_errors": scope_errors,
        },
        "files_sha256": files,
        "changed_files_sha256": changed_files,
        "sap_sha256": files["docs/research/hfwm/HFWM_R0_M3_SAP.md"],
        "commands_executed": args.verification_command,
        "test_results": args.verification_result,
        "seed_audit_status": {
            "mechanistic_queue_semimarkov": "DETERMINISTIC_BY_DESIGN",
            "local_joint_from_scratch": "DETERMINISTIC_BY_DESIGN",
            "shared_hfwm_multitask": "DETERMINISTIC_BY_DESIGN",
            "hgbr_cqr": "DETERMINISTIC_BY_DESIGN",
            "model_fit_seed_status": "NOT_APPLICABLE_DETERMINISTIC_FIT",
            "replication_policy": "ONE_FIT_PER_CONFIGURATION",
            "m2_determinism_evidence_use": (
                "INTERNAL_ONLY_NOT_ROBUSTNESS_OR_FUNDRAISING_PROOF"
            ),
            "future_weights_persistence_required": True,
            "separate_replay_ticket": "HFWM-R0-M2-SEED-AUDIT",
        },
        "agora_incident": {
            "first_occurrence": (
                "docs/research/hfwm/HFWM_R0_M3_PARTNER_DATA_REQUEST.md:pre_amendment_66"
            ),
            "git_tracked_at_introduction": False,
            "introducing_commit": None,
            "introducing_author": None,
            "introducing_commit_message": None,
            "original_source_verification": (
                "UNSUPPORTED_REMOVE_NOT_REPRODUCIBLE_AT_CHALLENGE"
            ),
            "subsequent_current_pdf_source": (
                "https://www.chu-lyon.fr/sites/default/files/reglement-interieur-hcl.pdf"
            ),
            "subsequent_source_locator": (
                "annex 9 article 9 PDF page 166 updated March 2026"
            ),
            "subsequent_source_attests_role": True,
            "resolution": "ORIGINAL_CLAIM_UNVERIFIED_TERM_REMAINS_REMOVED",
            "partner_package_occurrences_after_amendment": 0,
        },
        "external_claims": {
            "ledger": "docs/research/hfwm/HFWM_R0_M3_EXTERNAL_CLAIMS_LEDGER.yaml",
            "total": len(claims),
            "status_counts": status_counts,
            "unsupported_exposed_count": 0 if not exposed_unsupported else 1,
        },
        "conventions": {
            "assumed_count": len(assumed_paths),
            "assumed_paths": assumed_paths,
            "confirmed_by_partner_count": 0,
            "confirmed_by_partner_paths": [],
        },
        "blockers": args.blocker,
        "review": {"m3d1_new_reviewer_executed": False, "main_agent_only": True},
        "mechanical_release_checks_pass": mechanical_release_checks_pass,
        "claims": {
            "allowed": [
                "PRE_DATA_CONTRACT_READY_FOR_PARTNER_REVIEW",
                "SYNTHETIC_FIXTURE_TESTED",
                "PLANNING_SIMULATION_ONLY",
            ],
            "forbidden": data_contract["claims"]["forbidden"],
        },
        "training_executed": False,
        "partner_data_consumed": False,
        "m3l_authorized": False,
        "m3f_authorized": False,
        "power_simulation_rng_reachability": power["rng_reachability"],
        "power_simulation_output_hash": power["simulation_output_hash"],
        "monte_carlo_precision": {
            "ordinary_half_width_ok": power["ordinary_precision_ok"],
            "critical_boundary_half_width_ok": power["critical_precision_ok"],
            "interval_procedure_valid_at_boundary": power[
                "interval_procedure_valid_at_boundary"
            ],
            "boundary_calibration_status": power.get("boundary_calibration_status", {}),
        },
        "selected_design_id": selected_design,
        "design_selection_status": power["selection_status"],
        "pessimistic_icc_selected_design_id": icc_sensitivity["selected_design_id"],
        "harm_detection_thresholds": {
            "delta_10pct": power["min_harm_detection_power_delta_10pct"],
            "delta_15pct": power["min_harm_detection_power_delta_15pct"],
        },
        "m2_retrospective": power["m2_retrospective"],
        "inconclusive_governance": power["inconclusive_real_experiment_decision"],
        "partner_calendar_request": {
            "minimum_months": 28,
            "preferred_months": 36,
            "target_sites": 12,
            "minimum_sites_subject_to_blinded_recalculation": 8,
            "units_per_site": 4,
            "attrition_planning": 0.60,
        },
        "tier_a_aggregation": {
            "partner_executes_spec": True,
            "movement_level_export_requested": False,
            "six_hour_data_assumed_stored": False,
        },
        "m2_results_modified": False,
        "external_transmission_authorized": external_transmission_authorized,
        "external_transmission_authorization_state": "PENDING_INDEPENDENT_POST_TAG_REVIEW",
    }
    _write_json(output_dir / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "manifest": str(output_dir / "manifest.json"),
                "files_hashed": len(files),
                "assumed_questions": len(questions),
                "training_executed": False,
                "partner_data_consumed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
