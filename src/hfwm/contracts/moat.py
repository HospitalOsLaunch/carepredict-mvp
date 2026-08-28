"""Versioned contracts for the four persisted HFWM MOAT assets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .serialization import (
    ContractValidationError,
    JSONValue,
    StableContract,
    require_bool,
    require_int,
    require_list,
    require_string,
    require_string_tuple,
    require_timestamp,
    strict_object,
)

HDC_CONTRACT_VERSION = "hdc.episode.v1"
DOS_CONTRACT_VERSION = "dos.decision_outcome.v1"
HDB_CONTRACT_VERSION = "hdb.benchmark.v1"
SAS_CONTRACT_VERSION = "sas.release.v1"


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)


def _optional_string(value: JSONValue, path: str) -> str | None:
    if value is None:
        return None
    return require_string(value, path)


def _require_version(actual: str, expected: str, asset: str) -> None:
    if actual != expected:
        raise ContractValidationError(f"unsupported {asset} contract version {actual!r}")


@dataclass(frozen=True, slots=True)
class ProvenancePointer(StableContract):
    ledger_ref: str
    source_event_ids: tuple[str, ...]
    source_ledger_hash: str
    build_code_version: str
    schema_versions: tuple[str, ...]
    as_of: str

    def __post_init__(self) -> None:
        if not self.source_event_ids:
            raise ContractValidationError("source_event_ids must not be empty")
        if len(self.source_event_ids) != len(set(self.source_event_ids)):
            raise ContractValidationError("source_event_ids contains duplicates")
        require_timestamp(self.as_of, "$.as_of")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "as_of": self.as_of,
            "build_code_version": self.build_code_version,
            "ledger_ref": self.ledger_ref,
            "schema_versions": list(self.schema_versions),
            "source_event_ids": list(self.source_event_ids),
            "source_ledger_hash": self.source_ledger_hash,
        }

    @classmethod
    def from_dict(cls, value: JSONValue) -> ProvenancePointer:
        fields = frozenset(
            {
                "as_of",
                "build_code_version",
                "ledger_ref",
                "schema_versions",
                "source_event_ids",
                "source_ledger_hash",
            }
        )
        obj = strict_object(value, required=fields)
        return cls(
            ledger_ref=require_string(obj["ledger_ref"], "$.ledger_ref"),
            source_event_ids=require_string_tuple(obj["source_event_ids"], "$.source_event_ids"),
            source_ledger_hash=require_string(obj["source_ledger_hash"], "$.source_ledger_hash"),
            build_code_version=require_string(obj["build_code_version"], "$.build_code_version"),
            schema_versions=require_string_tuple(obj["schema_versions"], "$.schema_versions"),
            as_of=require_timestamp(obj["as_of"], "$.as_of"),
        )


@dataclass(frozen=True, slots=True)
class HDCEpisode(StableContract):
    contract_version: str
    episode_id: str
    htl_registry_hash: str
    snapshot_hash: str
    history_event_ids: tuple[str, ...]
    belief_state_ref: str
    future_event_ids: tuple[str, ...]
    context_ref: str
    decision_record_ids: tuple[str, ...]
    action_record_ids: tuple[str, ...]
    outcome_event_ids: tuple[str, ...]
    provenance: ProvenancePointer
    partition_id: str

    def __post_init__(self) -> None:
        _require_version(self.contract_version, HDC_CONTRACT_VERSION, "HDC")
        if not self.history_event_ids:
            raise ContractValidationError("HDC episode requires point-in-time history")
        if not self.future_event_ids:
            raise ContractValidationError("HDC episode requires an observed joint future")
        for name, values in (
            ("history_event_ids", self.history_event_ids),
            ("future_event_ids", self.future_event_ids),
            ("decision_record_ids", self.decision_record_ids),
            ("action_record_ids", self.action_record_ids),
            ("outcome_event_ids", self.outcome_event_ids),
        ):
            if len(values) != len(set(values)):
                raise ContractValidationError(f"{name} contains duplicates")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "action_record_ids": list(self.action_record_ids),
            "belief_state_ref": self.belief_state_ref,
            "context_ref": self.context_ref,
            "contract_version": self.contract_version,
            "decision_record_ids": list(self.decision_record_ids),
            "episode_id": self.episode_id,
            "future_event_ids": list(self.future_event_ids),
            "history_event_ids": list(self.history_event_ids),
            "htl_registry_hash": self.htl_registry_hash,
            "outcome_event_ids": list(self.outcome_event_ids),
            "partition_id": self.partition_id,
            "provenance": self.provenance.to_dict(),
            "snapshot_hash": self.snapshot_hash,
        }

    @classmethod
    def from_dict(cls, value: JSONValue) -> HDCEpisode:
        fields = frozenset(
            {
                "action_record_ids",
                "belief_state_ref",
                "context_ref",
                "contract_version",
                "decision_record_ids",
                "episode_id",
                "future_event_ids",
                "history_event_ids",
                "htl_registry_hash",
                "outcome_event_ids",
                "partition_id",
                "provenance",
                "snapshot_hash",
            }
        )
        obj = strict_object(value, required=fields)
        return cls(
            contract_version=require_string(obj["contract_version"], "$.contract_version"),
            episode_id=require_string(obj["episode_id"], "$.episode_id"),
            htl_registry_hash=require_string(obj["htl_registry_hash"], "$.htl_registry_hash"),
            snapshot_hash=require_string(obj["snapshot_hash"], "$.snapshot_hash"),
            history_event_ids=require_string_tuple(obj["history_event_ids"], "$.history_event_ids"),
            belief_state_ref=require_string(obj["belief_state_ref"], "$.belief_state_ref"),
            future_event_ids=require_string_tuple(obj["future_event_ids"], "$.future_event_ids"),
            context_ref=require_string(obj["context_ref"], "$.context_ref"),
            decision_record_ids=require_string_tuple(
                obj["decision_record_ids"], "$.decision_record_ids"
            ),
            action_record_ids=require_string_tuple(obj["action_record_ids"], "$.action_record_ids"),
            outcome_event_ids=require_string_tuple(obj["outcome_event_ids"], "$.outcome_event_ids"),
            provenance=ProvenancePointer.from_dict(obj["provenance"]),
            partition_id=require_string(obj["partition_id"], "$.partition_id"),
        )


class ActionExecutionStatus(StrEnum):
    NOT_OBSERVED = "not_observed"
    INTENTION_ONLY = "intention_only"
    PARTIALLY_OBSERVED = "partially_observed"
    EXECUTED = "executed"


@dataclass(frozen=True, slots=True)
class DOSRecord(StableContract):
    contract_version: str
    record_id: str
    episode_id: str
    as_of: str
    available_option_refs: tuple[str, ...]
    exposed_information_ref: str | None
    opened_at: str | None
    human_choice_ref: str | None
    human_reason_ref: str | None
    execution_status: ActionExecutionStatus
    executed_action_ref: str | None
    dose_ref: str | None
    timing_ref: str | None
    deviation_ref: str | None
    concurrent_action_refs: tuple[str, ...]
    outcome_ref: str | None
    support_ref: str
    uncertainty_ref: str
    provenance: ProvenancePointer

    def __post_init__(self) -> None:
        _require_version(self.contract_version, DOS_CONTRACT_VERSION, "DOS")
        require_timestamp(self.as_of, "$.as_of")
        if self.opened_at is not None:
            require_timestamp(self.opened_at, "$.opened_at")
        execution_fields = (self.executed_action_ref, self.dose_ref, self.timing_ref)
        if self.execution_status == ActionExecutionStatus.EXECUTED and any(
            value is None for value in execution_fields
        ):
            raise ContractValidationError(
                "executed actions require executed_action_ref, dose_ref and timing_ref"
            )
        if self.execution_status in {
            ActionExecutionStatus.NOT_OBSERVED,
            ActionExecutionStatus.INTENTION_ONLY,
        } and any(value is not None for value in execution_fields):
            raise ContractValidationError(
                "execution details cannot be inferred for absent or intention-only actions"
            )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "as_of": self.as_of,
            "available_option_refs": list(self.available_option_refs),
            "concurrent_action_refs": list(self.concurrent_action_refs),
            "contract_version": self.contract_version,
            "deviation_ref": self.deviation_ref,
            "dose_ref": self.dose_ref,
            "episode_id": self.episode_id,
            "executed_action_ref": self.executed_action_ref,
            "execution_status": self.execution_status.value,
            "exposed_information_ref": self.exposed_information_ref,
            "human_choice_ref": self.human_choice_ref,
            "human_reason_ref": self.human_reason_ref,
            "opened_at": self.opened_at,
            "outcome_ref": self.outcome_ref,
            "provenance": self.provenance.to_dict(),
            "record_id": self.record_id,
            "support_ref": self.support_ref,
            "timing_ref": self.timing_ref,
            "uncertainty_ref": self.uncertainty_ref,
        }

    @classmethod
    def from_dict(cls, value: JSONValue) -> DOSRecord:
        fields = frozenset(
            {
                "as_of",
                "available_option_refs",
                "concurrent_action_refs",
                "contract_version",
                "deviation_ref",
                "dose_ref",
                "episode_id",
                "executed_action_ref",
                "execution_status",
                "exposed_information_ref",
                "human_choice_ref",
                "human_reason_ref",
                "opened_at",
                "outcome_ref",
                "provenance",
                "record_id",
                "support_ref",
                "timing_ref",
                "uncertainty_ref",
            }
        )
        obj = strict_object(value, required=fields)
        try:
            status = ActionExecutionStatus(
                require_string(obj["execution_status"], "$.execution_status")
            )
        except ValueError as error:
            raise ContractValidationError("invalid action execution status") from error
        return cls(
            contract_version=require_string(obj["contract_version"], "$.contract_version"),
            record_id=require_string(obj["record_id"], "$.record_id"),
            episode_id=require_string(obj["episode_id"], "$.episode_id"),
            as_of=require_timestamp(obj["as_of"], "$.as_of"),
            available_option_refs=require_string_tuple(
                obj["available_option_refs"], "$.available_option_refs"
            ),
            exposed_information_ref=_optional_string(
                obj["exposed_information_ref"], "$.exposed_information_ref"
            ),
            opened_at=_optional_string(obj["opened_at"], "$.opened_at"),
            human_choice_ref=_optional_string(obj["human_choice_ref"], "$.human_choice_ref"),
            human_reason_ref=_optional_string(obj["human_reason_ref"], "$.human_reason_ref"),
            execution_status=status,
            executed_action_ref=_optional_string(
                obj["executed_action_ref"], "$.executed_action_ref"
            ),
            dose_ref=_optional_string(obj["dose_ref"], "$.dose_ref"),
            timing_ref=_optional_string(obj["timing_ref"], "$.timing_ref"),
            deviation_ref=_optional_string(obj["deviation_ref"], "$.deviation_ref"),
            concurrent_action_refs=require_string_tuple(
                obj["concurrent_action_refs"], "$.concurrent_action_refs"
            ),
            outcome_ref=_optional_string(obj["outcome_ref"], "$.outcome_ref"),
            support_ref=require_string(obj["support_ref"], "$.support_ref"),
            uncertainty_ref=require_string(obj["uncertainty_ref"], "$.uncertainty_ref"),
            provenance=ProvenancePointer.from_dict(obj["provenance"]),
        )


class HoldoutDimension(StrEnum):
    TEMPORAL = "temporal"
    ORGANIZATION = "organization"
    SITE = "site"
    UNIT = "unit"
    UNIT_FAMILY = "unit_family"
    REGIME = "regime"


@dataclass(frozen=True, slots=True)
class HDBPartition(StableContract):
    partition_id: str
    role: str
    holdout_dimensions: tuple[HoldoutDimension, ...]
    organization_ids: tuple[str, ...]
    site_ids: tuple[str, ...]
    unit_ids: tuple[str, ...]
    episode_ids: tuple[str, ...]
    period_start: str
    period_end: str
    semantic_hashes: tuple[str, ...]
    deduplication_rule_version: str
    minimum_temporal_gap_hours: int
    transformation_versions: tuple[str, ...]
    external_checkpoint_exposures: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.role not in {"train", "validation", "test", "calibration"}:
            raise ContractValidationError("invalid HDB partition role")
        require_timestamp(self.period_start, "$.period_start")
        require_timestamp(self.period_end, "$.period_end")
        if _instant(self.period_end) <= _instant(self.period_start):
            raise ContractValidationError("period_end must be after period_start")
        if not self.episode_ids:
            raise ContractValidationError("HDB partition must name its episodes")
        if len(self.episode_ids) != len(set(self.episode_ids)):
            raise ContractValidationError("episode_ids contains duplicates")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "deduplication_rule_version": self.deduplication_rule_version,
            "episode_ids": list(self.episode_ids),
            "external_checkpoint_exposures": list(self.external_checkpoint_exposures),
            "holdout_dimensions": [item.value for item in self.holdout_dimensions],
            "minimum_temporal_gap_hours": self.minimum_temporal_gap_hours,
            "organization_ids": list(self.organization_ids),
            "partition_id": self.partition_id,
            "period_end": self.period_end,
            "period_start": self.period_start,
            "role": self.role,
            "semantic_hashes": list(self.semantic_hashes),
            "site_ids": list(self.site_ids),
            "transformation_versions": list(self.transformation_versions),
            "unit_ids": list(self.unit_ids),
        }

    @classmethod
    def from_dict(cls, value: JSONValue) -> HDBPartition:
        fields = frozenset(
            {
                "deduplication_rule_version",
                "episode_ids",
                "external_checkpoint_exposures",
                "holdout_dimensions",
                "minimum_temporal_gap_hours",
                "organization_ids",
                "partition_id",
                "period_end",
                "period_start",
                "role",
                "semantic_hashes",
                "site_ids",
                "transformation_versions",
                "unit_ids",
            }
        )
        obj = strict_object(value, required=fields)
        dimensions: list[HoldoutDimension] = []
        holdout_items = require_list(obj["holdout_dimensions"], "$.holdout_dimensions")
        for index, item in enumerate(holdout_items):
            try:
                dimensions.append(
                    HoldoutDimension(require_string(item, f"$.holdout_dimensions[{index}]"))
                )
            except ValueError as error:
                raise ContractValidationError("invalid holdout dimension") from error
        return cls(
            partition_id=require_string(obj["partition_id"], "$.partition_id"),
            role=require_string(obj["role"], "$.role"),
            holdout_dimensions=tuple(dimensions),
            organization_ids=require_string_tuple(obj["organization_ids"], "$.organization_ids"),
            site_ids=require_string_tuple(obj["site_ids"], "$.site_ids"),
            unit_ids=require_string_tuple(obj["unit_ids"], "$.unit_ids"),
            episode_ids=require_string_tuple(obj["episode_ids"], "$.episode_ids"),
            period_start=require_timestamp(obj["period_start"], "$.period_start"),
            period_end=require_timestamp(obj["period_end"], "$.period_end"),
            semantic_hashes=require_string_tuple(obj["semantic_hashes"], "$.semantic_hashes"),
            deduplication_rule_version=require_string(
                obj["deduplication_rule_version"], "$.deduplication_rule_version"
            ),
            minimum_temporal_gap_hours=require_int(
                obj["minimum_temporal_gap_hours"], "$.minimum_temporal_gap_hours", minimum=0
            ),
            transformation_versions=require_string_tuple(
                obj["transformation_versions"], "$.transformation_versions"
            ),
            external_checkpoint_exposures=require_string_tuple(
                obj["external_checkpoint_exposures"], "$.external_checkpoint_exposures"
            ),
        )


@dataclass(frozen=True, slots=True)
class HDBBenchmark(StableContract):
    contract_version: str
    benchmark_id: str
    benchmark_version: str
    htl_registry_hash: str
    tasks: tuple[str, ...]
    horizons_hours: tuple[int, ...]
    partitions: tuple[HDBPartition, ...]
    corruption_suites: tuple[str, ...]
    anti_contamination_rules: tuple[str, ...]
    split_before_windowing: bool

    def __post_init__(self) -> None:
        _require_version(self.contract_version, HDB_CONTRACT_VERSION, "HDB")
        if not self.tasks or not self.horizons_hours or not self.partitions:
            raise ContractValidationError("HDB requires tasks, horizons and partitions")
        if any(horizon <= 0 for horizon in self.horizons_hours):
            raise ContractValidationError("HDB horizons must be positive")
        if not self.split_before_windowing:
            raise ContractValidationError("HDB requires split_before_windowing=true")
        ids = [partition.partition_id for partition in self.partitions]
        if len(ids) != len(set(ids)):
            raise ContractValidationError("partition_id values must be unique")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "anti_contamination_rules": list(self.anti_contamination_rules),
            "benchmark_id": self.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "contract_version": self.contract_version,
            "corruption_suites": list(self.corruption_suites),
            "horizons_hours": list(self.horizons_hours),
            "htl_registry_hash": self.htl_registry_hash,
            "partitions": [item.to_dict() for item in self.partitions],
            "split_before_windowing": self.split_before_windowing,
            "tasks": list(self.tasks),
        }

    @classmethod
    def from_dict(cls, value: JSONValue) -> HDBBenchmark:
        fields = frozenset(
            {
                "anti_contamination_rules",
                "benchmark_id",
                "benchmark_version",
                "contract_version",
                "corruption_suites",
                "horizons_hours",
                "htl_registry_hash",
                "partitions",
                "split_before_windowing",
                "tasks",
            }
        )
        obj = strict_object(value, required=fields)
        return cls(
            contract_version=require_string(obj["contract_version"], "$.contract_version"),
            benchmark_id=require_string(obj["benchmark_id"], "$.benchmark_id"),
            benchmark_version=require_string(obj["benchmark_version"], "$.benchmark_version"),
            htl_registry_hash=require_string(obj["htl_registry_hash"], "$.htl_registry_hash"),
            tasks=require_string_tuple(obj["tasks"], "$.tasks"),
            horizons_hours=tuple(
                require_int(item, f"$.horizons_hours[{index}]", minimum=1)
                for index, item in enumerate(
                    require_list(obj["horizons_hours"], "$.horizons_hours")
                )
            ),
            partitions=tuple(
                HDBPartition.from_dict(item)
                for item in require_list(obj["partitions"], "$.partitions")
            ),
            corruption_suites=require_string_tuple(obj["corruption_suites"], "$.corruption_suites"),
            anti_contamination_rules=require_string_tuple(
                obj["anti_contamination_rules"], "$.anti_contamination_rules"
            ),
            split_before_windowing=require_bool(
                obj["split_before_windowing"], "$.split_before_windowing"
            ),
        )


class SignatureStatus(StrEnum):
    UNSIGNED = "unsigned"
    SIGNED = "signed"


@dataclass(frozen=True, slots=True)
class SASRelease(StableContract):
    contract_version: str
    release_id: str
    release_version: str
    site_id: str
    backbone_hash: str
    freeze_backbone: bool
    htl_mapping_hash: str
    recording_process_model_hash: str
    adapter_hash: str
    calibration_hash: str
    adaptation_dataset_hash: str
    local_data_budget: int
    local_data_used: int
    compute_budget_ref: str
    from_scratch_control_ref: str
    signature_status: SignatureStatus
    signature_ref: str | None
    rollback_to_version: str | None

    def __post_init__(self) -> None:
        _require_version(self.contract_version, SAS_CONTRACT_VERSION, "SAS")
        if not self.freeze_backbone:
            raise ContractValidationError("HFWM-R0 SAS contract requires a frozen backbone")
        if self.local_data_used > self.local_data_budget:
            raise ContractValidationError("local_data_used exceeds the pre-registered budget")
        if self.signature_status == SignatureStatus.SIGNED and self.signature_ref is None:
            raise ContractValidationError("signed SAS release requires signature_ref")
        if self.signature_status == SignatureStatus.UNSIGNED and self.signature_ref is not None:
            raise ContractValidationError("unsigned SAS release cannot carry signature_ref")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "adaptation_dataset_hash": self.adaptation_dataset_hash,
            "adapter_hash": self.adapter_hash,
            "backbone_hash": self.backbone_hash,
            "calibration_hash": self.calibration_hash,
            "compute_budget_ref": self.compute_budget_ref,
            "contract_version": self.contract_version,
            "freeze_backbone": self.freeze_backbone,
            "from_scratch_control_ref": self.from_scratch_control_ref,
            "htl_mapping_hash": self.htl_mapping_hash,
            "local_data_budget": self.local_data_budget,
            "local_data_used": self.local_data_used,
            "recording_process_model_hash": self.recording_process_model_hash,
            "release_id": self.release_id,
            "release_version": self.release_version,
            "rollback_to_version": self.rollback_to_version,
            "signature_ref": self.signature_ref,
            "signature_status": self.signature_status.value,
            "site_id": self.site_id,
        }

    @classmethod
    def from_dict(cls, value: JSONValue) -> SASRelease:
        fields = frozenset(
            {
                "adaptation_dataset_hash",
                "adapter_hash",
                "backbone_hash",
                "calibration_hash",
                "compute_budget_ref",
                "contract_version",
                "freeze_backbone",
                "from_scratch_control_ref",
                "htl_mapping_hash",
                "local_data_budget",
                "local_data_used",
                "recording_process_model_hash",
                "release_id",
                "release_version",
                "rollback_to_version",
                "signature_ref",
                "signature_status",
                "site_id",
            }
        )
        obj = strict_object(value, required=fields)
        try:
            status = SignatureStatus(require_string(obj["signature_status"], "$.signature_status"))
        except ValueError as error:
            raise ContractValidationError("invalid SAS signature status") from error
        return cls(
            contract_version=require_string(obj["contract_version"], "$.contract_version"),
            release_id=require_string(obj["release_id"], "$.release_id"),
            release_version=require_string(obj["release_version"], "$.release_version"),
            site_id=require_string(obj["site_id"], "$.site_id"),
            backbone_hash=require_string(obj["backbone_hash"], "$.backbone_hash"),
            freeze_backbone=require_bool(obj["freeze_backbone"], "$.freeze_backbone"),
            htl_mapping_hash=require_string(obj["htl_mapping_hash"], "$.htl_mapping_hash"),
            recording_process_model_hash=require_string(
                obj["recording_process_model_hash"], "$.recording_process_model_hash"
            ),
            adapter_hash=require_string(obj["adapter_hash"], "$.adapter_hash"),
            calibration_hash=require_string(obj["calibration_hash"], "$.calibration_hash"),
            adaptation_dataset_hash=require_string(
                obj["adaptation_dataset_hash"], "$.adaptation_dataset_hash"
            ),
            local_data_budget=require_int(
                obj["local_data_budget"], "$.local_data_budget", minimum=0
            ),
            local_data_used=require_int(obj["local_data_used"], "$.local_data_used", minimum=0),
            compute_budget_ref=require_string(obj["compute_budget_ref"], "$.compute_budget_ref"),
            from_scratch_control_ref=require_string(
                obj["from_scratch_control_ref"], "$.from_scratch_control_ref"
            ),
            signature_status=status,
            signature_ref=_optional_string(obj["signature_ref"], "$.signature_ref"),
            rollback_to_version=_optional_string(
                obj["rollback_to_version"], "$.rollback_to_version"
            ),
        )
