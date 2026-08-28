from __future__ import annotations

from dataclasses import replace

import pytest

from hfwm.contracts import (
    DOS_CONTRACT_VERSION,
    HDB_CONTRACT_VERSION,
    HDC_CONTRACT_VERSION,
    SAS_CONTRACT_VERSION,
    ActionExecutionStatus,
    ContractValidationError,
    DOSRecord,
    HDBBenchmark,
    HDBPartition,
    HDCEpisode,
    HoldoutDimension,
    ProvenancePointer,
    SASRelease,
    SignatureStatus,
    parse_json_bytes,
)


def provenance() -> ProvenancePointer:
    return ProvenancePointer(
        ledger_ref="ledger://snapshot/1",
        source_event_ids=("event-1", "event-2"),
        source_ledger_hash="a" * 64,
        build_code_version="06914578",
        schema_versions=("p0d.event.v1", "htl.contract.v1"),
        as_of="2026-01-01T00:00:00Z",
    )


def test_hdc_round_trip_and_semantic_hash() -> None:
    episode = HDCEpisode(
        contract_version=HDC_CONTRACT_VERSION,
        episode_id="episode-1",
        htl_registry_hash="b" * 64,
        snapshot_hash="c" * 64,
        history_event_ids=("event-1",),
        belief_state_ref="state://episode-1/t0",
        future_event_ids=("event-2",),
        context_ref="context://episode-1/t0",
        decision_record_ids=(),
        action_record_ids=(),
        outcome_event_ids=("event-2",),
        provenance=provenance(),
        partition_id="test-2026",
    )
    restored = HDCEpisode.from_dict(parse_json_bytes(episode.to_json_bytes()))
    assert restored == episode
    assert restored.semantic_hash() == episode.semantic_hash()


def test_dos_never_promotes_intention_to_execution() -> None:
    with pytest.raises(ContractValidationError, match="cannot be inferred"):
        DOSRecord(
            contract_version=DOS_CONTRACT_VERSION,
            record_id="decision-1",
            episode_id="episode-1",
            as_of="2026-01-01T00:00:00Z",
            available_option_refs=("option://1",),
            exposed_information_ref="screen://1",
            opened_at="2026-01-01T00:00:00Z",
            human_choice_ref="intention://1",
            human_reason_ref=None,
            execution_status=ActionExecutionStatus.INTENTION_ONLY,
            executed_action_ref="action://1",
            dose_ref="dose://1",
            timing_ref="timing://1",
            deviation_ref=None,
            concurrent_action_refs=(),
            outcome_ref=None,
            support_ref="support://1",
            uncertainty_ref="uncertainty://1",
            provenance=provenance(),
        )


def test_dos_executed_record_round_trip_requires_dose_and_timing() -> None:
    record = DOSRecord(
        contract_version=DOS_CONTRACT_VERSION,
        record_id="decision-2",
        episode_id="episode-1",
        as_of="2026-01-01T00:00:00Z",
        available_option_refs=("option://1",),
        exposed_information_ref="screen://1",
        opened_at="2026-01-01T00:00:00Z",
        human_choice_ref="choice://1",
        human_reason_ref="reason://1",
        execution_status=ActionExecutionStatus.EXECUTED,
        executed_action_ref="action://1",
        dose_ref="dose://1",
        timing_ref="timing://1",
        deviation_ref="deviation://none",
        concurrent_action_refs=("action://2",),
        outcome_ref="outcome://1",
        support_ref="support://1",
        uncertainty_ref="uncertainty://1",
        provenance=provenance(),
    )
    assert DOSRecord.from_dict(parse_json_bytes(record.to_json_bytes())) == record


def partition() -> HDBPartition:
    return HDBPartition(
        partition_id="test-site-a",
        role="test",
        holdout_dimensions=(HoldoutDimension.SITE, HoldoutDimension.TEMPORAL),
        organization_ids=("org-a",),
        site_ids=("site-a",),
        unit_ids=("unit-a",),
        episode_ids=("episode-1",),
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-02-01T00:00:00Z",
        semantic_hashes=("d" * 64,),
        deduplication_rule_version="dedup.v1",
        minimum_temporal_gap_hours=72,
        transformation_versions=("transform.v1",),
        external_checkpoint_exposures=(),
    )


def test_hdb_requires_split_before_windowing_and_round_trips() -> None:
    with pytest.raises(ContractValidationError, match="split_before_windowing"):
        HDBBenchmark(
            contract_version=HDB_CONTRACT_VERSION,
            benchmark_id="hdb-r0",
            benchmark_version="1",
            htl_registry_hash="e" * 64,
            tasks=("occupancy",),
            horizons_hours=(6, 24, 72),
            partitions=(partition(),),
            corruption_suites=("late_arrival",),
            anti_contamination_rules=("episode_disjoint",),
            split_before_windowing=False,
        )
    benchmark = HDBBenchmark(
        contract_version=HDB_CONTRACT_VERSION,
        benchmark_id="hdb-r0",
        benchmark_version="1",
        htl_registry_hash="e" * 64,
        tasks=("occupancy", "inflow"),
        horizons_hours=(6, 24, 72),
        partitions=(partition(),),
        corruption_suites=("late_arrival", "silent_source"),
        anti_contamination_rules=("episode_disjoint", "semantic_dedup"),
        split_before_windowing=True,
    )
    assert HDBBenchmark.from_dict(parse_json_bytes(benchmark.to_json_bytes())) == benchmark


def test_sas_enforces_frozen_backbone_budget_signature_and_round_trip() -> None:
    release = SASRelease(
        contract_version=SAS_CONTRACT_VERSION,
        release_id="sas-site-a",
        release_version="1",
        site_id="site-a",
        backbone_hash="1" * 64,
        freeze_backbone=True,
        htl_mapping_hash="2" * 64,
        recording_process_model_hash="3" * 64,
        adapter_hash="4" * 64,
        calibration_hash="5" * 64,
        adaptation_dataset_hash="6" * 64,
        local_data_budget=100,
        local_data_used=80,
        compute_budget_ref="budget://sas-r0",
        from_scratch_control_ref="run://local-control",
        signature_status=SignatureStatus.UNSIGNED,
        signature_ref=None,
        rollback_to_version=None,
    )
    assert SASRelease.from_dict(parse_json_bytes(release.to_json_bytes())) == release

    with pytest.raises(ContractValidationError, match="exceeds"):
        replace(release, local_data_used=101)
