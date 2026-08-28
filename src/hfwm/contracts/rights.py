"""Deny-by-default data-rights contract for HFWM assets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .serialization import (
    ContractValidationError,
    JSONValue,
    StableContract,
    require_bool,
    require_list,
    require_string,
    require_string_tuple,
    strict_object,
)

DATA_RIGHTS_CONTRACT_VERSION = "hfwm.data_rights.v1"
_UNVERIFIED_MARKERS = frozenset(
    {"NOT_DOCUMENTED", "NOT_VERIFIED", "NOT_VERIFIED_IN_REPOSITORY", "UNKNOWN"}
)


class RightsDecision(StrEnum):
    DENIED = "denied"
    ALLOWED = "allowed"


class RightsUse(StrEnum):
    TRAINING = "training_allowed"
    EVALUATION = "evaluation_allowed"
    DERIVED_FEATURES = "derived_features_allowed"
    EMBEDDINGS = "embeddings_allowed"
    WEIGHTS = "weights_allowed"
    CROSS_SITE_LEARNING = "cross_site_learning_allowed"
    BENCHMARK = "benchmark_allowed"
    PUBLICATION = "publication_allowed"


@dataclass(frozen=True, slots=True)
class SourceRights(StableContract):
    source_id: str
    owner: str
    licence: str
    allowed_purposes: tuple[str, ...]
    training_allowed: bool
    evaluation_allowed: bool
    derived_features_allowed: bool
    embeddings_allowed: bool
    weights_allowed: bool
    cross_site_learning_allowed: bool
    benchmark_allowed: bool
    publication_allowed: bool
    retention: str
    deletion_obligations: str
    territory: str
    expiry: str
    decision: RightsDecision
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.allowed_purposes) != len(set(self.allowed_purposes)):
            raise ContractValidationError("allowed_purposes contains duplicates")
        allowed_flags = (
            self.training_allowed,
            self.evaluation_allowed,
            self.derived_features_allowed,
            self.embeddings_allowed,
            self.weights_allowed,
            self.cross_site_learning_allowed,
            self.benchmark_allowed,
            self.publication_allowed,
        )
        if self.decision == RightsDecision.DENIED and any(allowed_flags):
            raise ContractValidationError("denied sources cannot enable a use")
        if self.decision == RightsDecision.ALLOWED:
            if not self.allowed_purposes:
                raise ContractValidationError("allowed sources require allowed_purposes")
            if not self.evidence_refs:
                raise ContractValidationError("allowed sources require rights evidence")
            if self.owner in _UNVERIFIED_MARKERS or self.licence in _UNVERIFIED_MARKERS:
                raise ContractValidationError("unverified ownership or licence must remain denied")

    def permits(self, use: RightsUse) -> bool:
        if self.decision != RightsDecision.ALLOWED:
            return False
        values = {
            RightsUse.TRAINING: self.training_allowed,
            RightsUse.EVALUATION: self.evaluation_allowed,
            RightsUse.DERIVED_FEATURES: self.derived_features_allowed,
            RightsUse.EMBEDDINGS: self.embeddings_allowed,
            RightsUse.WEIGHTS: self.weights_allowed,
            RightsUse.CROSS_SITE_LEARNING: self.cross_site_learning_allowed,
            RightsUse.BENCHMARK: self.benchmark_allowed,
            RightsUse.PUBLICATION: self.publication_allowed,
        }
        return values[use]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "allowed_purposes": list(self.allowed_purposes),
            "benchmark_allowed": self.benchmark_allowed,
            "cross_site_learning_allowed": self.cross_site_learning_allowed,
            "decision": self.decision.value,
            "deletion_obligations": self.deletion_obligations,
            "derived_features_allowed": self.derived_features_allowed,
            "embeddings_allowed": self.embeddings_allowed,
            "evaluation_allowed": self.evaluation_allowed,
            "evidence_refs": list(self.evidence_refs),
            "expiry": self.expiry,
            "licence": self.licence,
            "owner": self.owner,
            "publication_allowed": self.publication_allowed,
            "retention": self.retention,
            "source_id": self.source_id,
            "territory": self.territory,
            "training_allowed": self.training_allowed,
            "weights_allowed": self.weights_allowed,
        }

    @classmethod
    def from_dict(cls, value: JSONValue) -> SourceRights:
        fields = frozenset(
            {
                "allowed_purposes",
                "benchmark_allowed",
                "cross_site_learning_allowed",
                "decision",
                "deletion_obligations",
                "derived_features_allowed",
                "embeddings_allowed",
                "evaluation_allowed",
                "evidence_refs",
                "expiry",
                "licence",
                "owner",
                "publication_allowed",
                "retention",
                "source_id",
                "territory",
                "training_allowed",
                "weights_allowed",
            }
        )
        obj = strict_object(value, required=fields)
        try:
            decision = RightsDecision(require_string(obj["decision"], "$.decision"))
        except ValueError as error:
            raise ContractValidationError("invalid rights decision") from error
        return cls(
            source_id=require_string(obj["source_id"], "$.source_id"),
            owner=require_string(obj["owner"], "$.owner"),
            licence=require_string(obj["licence"], "$.licence"),
            allowed_purposes=require_string_tuple(obj["allowed_purposes"], "$.allowed_purposes"),
            training_allowed=require_bool(obj["training_allowed"], "$.training_allowed"),
            evaluation_allowed=require_bool(obj["evaluation_allowed"], "$.evaluation_allowed"),
            derived_features_allowed=require_bool(
                obj["derived_features_allowed"], "$.derived_features_allowed"
            ),
            embeddings_allowed=require_bool(obj["embeddings_allowed"], "$.embeddings_allowed"),
            weights_allowed=require_bool(obj["weights_allowed"], "$.weights_allowed"),
            cross_site_learning_allowed=require_bool(
                obj["cross_site_learning_allowed"], "$.cross_site_learning_allowed"
            ),
            benchmark_allowed=require_bool(obj["benchmark_allowed"], "$.benchmark_allowed"),
            publication_allowed=require_bool(obj["publication_allowed"], "$.publication_allowed"),
            retention=require_string(obj["retention"], "$.retention"),
            deletion_obligations=require_string(
                obj["deletion_obligations"], "$.deletion_obligations"
            ),
            territory=require_string(obj["territory"], "$.territory"),
            expiry=require_string(obj["expiry"], "$.expiry"),
            decision=decision,
            evidence_refs=require_string_tuple(obj["evidence_refs"], "$.evidence_refs"),
        )


@dataclass(frozen=True, slots=True)
class DataRightsRegistry(StableContract):
    contract_version: str
    policy_version: str
    default_decision: RightsDecision
    sources: tuple[SourceRights, ...]

    def __post_init__(self) -> None:
        if self.contract_version != DATA_RIGHTS_CONTRACT_VERSION:
            raise ContractValidationError(
                f"unsupported data-rights contract version {self.contract_version!r}"
            )
        if self.default_decision != RightsDecision.DENIED:
            raise ContractValidationError("data-rights default_decision must be denied")
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ContractValidationError("source_id values must be unique")

    def authorize(self, source_id: str, use: RightsUse) -> bool:
        source = next((item for item in self.sources if item.source_id == source_id), None)
        return source.permits(use) if source is not None else False

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "contract_version": self.contract_version,
            "default_decision": self.default_decision.value,
            "policy_version": self.policy_version,
            "sources": [source.to_dict() for source in self.sources],
        }

    @classmethod
    def from_dict(cls, value: JSONValue) -> DataRightsRegistry:
        obj = strict_object(
            value,
            required=frozenset(
                {"contract_version", "default_decision", "policy_version", "sources"}
            ),
        )
        try:
            decision = RightsDecision(require_string(obj["default_decision"], "$.default_decision"))
        except ValueError as error:
            raise ContractValidationError("invalid default rights decision") from error
        return cls(
            contract_version=require_string(obj["contract_version"], "$.contract_version"),
            policy_version=require_string(obj["policy_version"], "$.policy_version"),
            default_decision=decision,
            sources=tuple(
                SourceRights.from_dict(item) for item in require_list(obj["sources"], "$.sources")
            ),
        )
