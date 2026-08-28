"""Canonical Hospital Transition Language (HTL) contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from hfwm.contracts.serialization import (
    ContractValidationError,
    JSONValue,
    StableContract,
    require_list,
    require_string,
    require_string_tuple,
    require_timestamp,
    strict_object,
)

HTL_CONTRACT_VERSION = "htl.contract.v1"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")


class SemanticKind(StrEnum):
    STATE = "state"
    EVENT = "event"
    ENTITY = "entity"
    RELATION = "relation"
    CAPACITY = "capacity"
    QUEUE = "queue"
    FLOW = "flow"
    RESOURCE = "resource"
    STAFFING = "staffing"
    DECISION = "decision"
    ACTION = "action"
    OUTCOME = "outcome"
    CORRECTION = "correction"
    OBSERVATION_PROCESS = "observation_process"
    CONSTRAINT = "constraint"


class ValueKind(StrEnum):
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    STRING = "string"
    CATEGORY = "category"
    TIMESTAMP = "timestamp"
    DURATION = "duration"
    REFERENCE = "reference"
    OBJECT = "object"


class ConstraintClass(StrEnum):
    HARD = "hard"
    SOFT = "soft"
    APPROXIMATE = "approximate"
    NOT_APPLICABLE = "not_applicable"


def _validate_identifier(value: str, path: str) -> None:
    if _IDENTIFIER.fullmatch(value) is None:
        raise ContractValidationError(f"{path}: invalid canonical identifier {value!r}")


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)


@dataclass(frozen=True, slots=True)
class SemanticDefinition(StableContract):
    semantic_id: str
    kind: SemanticKind
    canonical_name: str
    definition: str
    value_kind: ValueKind
    unit: str | None
    allowed_values: tuple[str, ...]
    parent_semantic_id: str | None
    constraint_class: ConstraintClass
    schema_version: str

    def __post_init__(self) -> None:
        _validate_identifier(self.semantic_id, "$.semantic_id")
        if not self.canonical_name.strip() or not self.definition.strip():
            raise ContractValidationError("canonical_name and definition must be non-empty")
        if self.value_kind == ValueKind.CATEGORY and not self.allowed_values:
            raise ContractValidationError("categorical semantics require allowed_values")
        if self.kind == SemanticKind.CONSTRAINT:
            if self.constraint_class == ConstraintClass.NOT_APPLICABLE:
                raise ContractValidationError("constraint semantics require a constraint_class")
        elif self.constraint_class != ConstraintClass.NOT_APPLICABLE:
            raise ContractValidationError("constraint_class is reserved for constraint semantics")
        if self.parent_semantic_id is not None:
            _validate_identifier(self.parent_semantic_id, "$.parent_semantic_id")
        if len(self.allowed_values) != len(set(self.allowed_values)):
            raise ContractValidationError("allowed_values contains duplicates")
        object.__setattr__(self, "allowed_values", tuple(sorted(self.allowed_values)))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "allowed_values": list(self.allowed_values),
            "canonical_name": self.canonical_name,
            "constraint_class": self.constraint_class.value,
            "definition": self.definition,
            "kind": self.kind.value,
            "parent_semantic_id": self.parent_semantic_id,
            "schema_version": self.schema_version,
            "semantic_id": self.semantic_id,
            "unit": self.unit,
            "value_kind": self.value_kind.value,
        }

    @classmethod
    def from_dict(cls, value: JSONValue) -> SemanticDefinition:
        obj = strict_object(
            value,
            required=frozenset(
                {
                    "allowed_values",
                    "canonical_name",
                    "constraint_class",
                    "definition",
                    "kind",
                    "parent_semantic_id",
                    "schema_version",
                    "semantic_id",
                    "unit",
                    "value_kind",
                }
            ),
        )
        parent_raw = obj["parent_semantic_id"]
        unit_raw = obj["unit"]
        if parent_raw is not None and not isinstance(parent_raw, str):
            raise ContractValidationError("$.parent_semantic_id: expected string or null")
        if unit_raw is not None and not isinstance(unit_raw, str):
            raise ContractValidationError("$.unit: expected string or null")
        try:
            kind = SemanticKind(require_string(obj["kind"], "$.kind"))
            value_kind = ValueKind(require_string(obj["value_kind"], "$.value_kind"))
            constraint_class = ConstraintClass(
                require_string(obj["constraint_class"], "$.constraint_class")
            )
        except ValueError as error:
            raise ContractValidationError("invalid HTL enum value") from error
        return cls(
            semantic_id=require_string(obj["semantic_id"], "$.semantic_id"),
            kind=kind,
            canonical_name=require_string(obj["canonical_name"], "$.canonical_name"),
            definition=require_string(obj["definition"], "$.definition"),
            value_kind=value_kind,
            unit=unit_raw,
            allowed_values=require_string_tuple(obj["allowed_values"], "$.allowed_values"),
            parent_semantic_id=parent_raw,
            constraint_class=constraint_class,
            schema_version=require_string(obj["schema_version"], "$.schema_version"),
        )


@dataclass(frozen=True, slots=True)
class SiteMapping(StableContract):
    mapping_id: str
    mapping_version: str
    site_id: str
    source_system: str
    source_schema_version: str
    local_code: str
    semantic_id: str
    transform_id: str
    transform_parameters: tuple[tuple[str, str], ...]
    valid_from: str
    valid_to: str | None
    evidence_ref: str

    def __post_init__(self) -> None:
        _validate_identifier(self.mapping_id, "$.mapping_id")
        _validate_identifier(self.semantic_id, "$.semantic_id")
        if not all(
            value.strip()
            for value in (
                self.mapping_version,
                self.site_id,
                self.source_system,
                self.source_schema_version,
                self.local_code,
                self.transform_id,
                self.evidence_ref,
            )
        ):
            raise ContractValidationError("site mapping fields must be non-empty")
        if len(self.transform_parameters) != len({key for key, _ in self.transform_parameters}):
            raise ContractValidationError("transform parameter keys must be unique")
        object.__setattr__(
            self,
            "transform_parameters",
            tuple(sorted(self.transform_parameters, key=lambda item: item[0])),
        )
        require_timestamp(self.valid_from, "$.valid_from")
        if self.valid_to is not None:
            require_timestamp(self.valid_to, "$.valid_to")
            if _instant(self.valid_to) <= _instant(self.valid_from):
                raise ContractValidationError("valid_to must be after valid_from")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "evidence_ref": self.evidence_ref,
            "local_code": self.local_code,
            "mapping_id": self.mapping_id,
            "mapping_version": self.mapping_version,
            "semantic_id": self.semantic_id,
            "site_id": self.site_id,
            "source_schema_version": self.source_schema_version,
            "source_system": self.source_system,
            "transform_id": self.transform_id,
            "transform_parameters": [
                {"name": name, "value": parameter} for name, parameter in self.transform_parameters
            ],
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
        }

    @classmethod
    def from_dict(cls, value: JSONValue) -> SiteMapping:
        fields = frozenset(
            {
                "evidence_ref",
                "local_code",
                "mapping_id",
                "mapping_version",
                "semantic_id",
                "site_id",
                "source_schema_version",
                "source_system",
                "transform_id",
                "transform_parameters",
                "valid_from",
                "valid_to",
            }
        )
        obj = strict_object(value, required=fields)
        parameters: list[tuple[str, str]] = []
        raw_parameters = require_list(obj["transform_parameters"], "$.transform_parameters")
        for index, raw in enumerate(raw_parameters):
            parameter = strict_object(
                raw,
                required=frozenset({"name", "value"}),
                path=f"$.transform_parameters[{index}]",
            )
            parameters.append(
                (
                    require_string(parameter["name"], f"$.transform_parameters[{index}].name"),
                    require_string(
                        parameter["value"],
                        f"$.transform_parameters[{index}].value",
                        allow_empty=True,
                    ),
                )
            )
        valid_to_raw = obj["valid_to"]
        if valid_to_raw is not None and not isinstance(valid_to_raw, str):
            raise ContractValidationError("$.valid_to: expected string or null")
        return cls(
            mapping_id=require_string(obj["mapping_id"], "$.mapping_id"),
            mapping_version=require_string(obj["mapping_version"], "$.mapping_version"),
            site_id=require_string(obj["site_id"], "$.site_id"),
            source_system=require_string(obj["source_system"], "$.source_system"),
            source_schema_version=require_string(
                obj["source_schema_version"], "$.source_schema_version"
            ),
            local_code=require_string(obj["local_code"], "$.local_code"),
            semantic_id=require_string(obj["semantic_id"], "$.semantic_id"),
            transform_id=require_string(obj["transform_id"], "$.transform_id"),
            transform_parameters=tuple(parameters),
            valid_from=require_timestamp(obj["valid_from"], "$.valid_from"),
            valid_to=valid_to_raw,
            evidence_ref=require_string(obj["evidence_ref"], "$.evidence_ref"),
        )


@dataclass(frozen=True, slots=True)
class TransitionRule(StableContract):
    rule_id: str
    trigger_semantic_id: str
    input_state_ids: tuple[str, ...]
    output_state_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    constraint_ids: tuple[str, ...]
    schema_version: str

    def __post_init__(self) -> None:
        _validate_identifier(self.rule_id, "$.rule_id")
        _validate_identifier(self.trigger_semantic_id, "$.trigger_semantic_id")
        if not self.output_state_ids:
            raise ContractValidationError("transition rule requires at least one output state")
        for name, identifiers in (
            ("input_state_ids", self.input_state_ids),
            ("output_state_ids", self.output_state_ids),
            ("relation_ids", self.relation_ids),
            ("constraint_ids", self.constraint_ids),
        ):
            if len(identifiers) != len(set(identifiers)):
                raise ContractValidationError(f"{name} contains duplicates")
            for identifier in identifiers:
                _validate_identifier(identifier, f"$.{name}")
        if not self.schema_version.strip():
            raise ContractValidationError("transition rule schema_version must be non-empty")
        object.__setattr__(self, "input_state_ids", tuple(sorted(self.input_state_ids)))
        object.__setattr__(self, "output_state_ids", tuple(sorted(self.output_state_ids)))
        object.__setattr__(self, "relation_ids", tuple(sorted(self.relation_ids)))
        object.__setattr__(self, "constraint_ids", tuple(sorted(self.constraint_ids)))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "constraint_ids": list(self.constraint_ids),
            "input_state_ids": list(self.input_state_ids),
            "output_state_ids": list(self.output_state_ids),
            "relation_ids": list(self.relation_ids),
            "rule_id": self.rule_id,
            "schema_version": self.schema_version,
            "trigger_semantic_id": self.trigger_semantic_id,
        }

    @classmethod
    def from_dict(cls, value: JSONValue) -> TransitionRule:
        obj = strict_object(
            value,
            required=frozenset(
                {
                    "constraint_ids",
                    "input_state_ids",
                    "output_state_ids",
                    "relation_ids",
                    "rule_id",
                    "schema_version",
                    "trigger_semantic_id",
                }
            ),
        )
        return cls(
            rule_id=require_string(obj["rule_id"], "$.rule_id"),
            trigger_semantic_id=require_string(obj["trigger_semantic_id"], "$.trigger_semantic_id"),
            input_state_ids=require_string_tuple(obj["input_state_ids"], "$.input_state_ids"),
            output_state_ids=require_string_tuple(obj["output_state_ids"], "$.output_state_ids"),
            relation_ids=require_string_tuple(obj["relation_ids"], "$.relation_ids"),
            constraint_ids=require_string_tuple(obj["constraint_ids"], "$.constraint_ids"),
            schema_version=require_string(obj["schema_version"], "$.schema_version"),
        )


@dataclass(frozen=True, slots=True)
class HTLRegistry(StableContract):
    contract_version: str
    registry_version: str
    semantics: tuple[SemanticDefinition, ...]
    site_mappings: tuple[SiteMapping, ...]
    transition_rules: tuple[TransitionRule, ...] = ()

    def __post_init__(self) -> None:
        if self.contract_version != HTL_CONTRACT_VERSION:
            raise ContractValidationError(
                f"unsupported HTL contract version {self.contract_version!r}"
            )
        semantic_ids = [item.semantic_id for item in self.semantics]
        if len(semantic_ids) != len(set(semantic_ids)):
            raise ContractValidationError("semantic_id values must be unique")
        mapping_ids = [item.mapping_id for item in self.site_mappings]
        if len(mapping_ids) != len(set(mapping_ids)):
            raise ContractValidationError("mapping_id values must be unique")
        rule_ids = [item.rule_id for item in self.transition_rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ContractValidationError("rule_id values must be unique")
        known = set(semantic_ids)
        for semantic in self.semantics:
            if semantic.parent_semantic_id is not None and semantic.parent_semantic_id not in known:
                raise ContractValidationError(
                    f"unknown parent semantic {semantic.parent_semantic_id!r}"
                )
        for mapping in self.site_mappings:
            if mapping.semantic_id not in known:
                raise ContractValidationError(
                    f"site mapping references unknown semantic {mapping.semantic_id!r}"
                )
        semantic_by_id = {item.semantic_id: item for item in self.semantics}
        for rule in self.transition_rules:
            references = (
                (rule.trigger_semantic_id, SemanticKind.EVENT),
                *((identifier, SemanticKind.STATE) for identifier in rule.input_state_ids),
                *((identifier, SemanticKind.STATE) for identifier in rule.output_state_ids),
                *((identifier, SemanticKind.RELATION) for identifier in rule.relation_ids),
                *((identifier, SemanticKind.CONSTRAINT) for identifier in rule.constraint_ids),
            )
            for identifier, expected_kind in references:
                referenced_semantic = semantic_by_id.get(identifier)
                if referenced_semantic is None:
                    raise ContractValidationError(
                        f"transition rule references unknown semantic {identifier!r}"
                    )
                if referenced_semantic.kind != expected_kind:
                    raise ContractValidationError(
                        f"transition rule expects {identifier!r} to be {expected_kind.value}"
                    )
        object.__setattr__(
            self, "semantics", tuple(sorted(self.semantics, key=lambda item: item.semantic_id))
        )
        object.__setattr__(
            self,
            "site_mappings",
            tuple(sorted(self.site_mappings, key=lambda item: item.mapping_id)),
        )
        object.__setattr__(
            self,
            "transition_rules",
            tuple(sorted(self.transition_rules, key=lambda item: item.rule_id)),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "contract_version": self.contract_version,
            "registry_version": self.registry_version,
            "semantics": [
                item.to_dict() for item in sorted(self.semantics, key=lambda item: item.semantic_id)
            ],
            "site_mappings": [
                item.to_dict()
                for item in sorted(self.site_mappings, key=lambda item: item.mapping_id)
            ],
            "transition_rules": [
                item.to_dict()
                for item in sorted(self.transition_rules, key=lambda item: item.rule_id)
            ],
        }

    @classmethod
    def from_dict(cls, value: JSONValue) -> HTLRegistry:
        obj = strict_object(
            value,
            required=frozenset(
                {
                    "contract_version",
                    "registry_version",
                    "semantics",
                    "site_mappings",
                    "transition_rules",
                }
            ),
        )
        semantics = tuple(
            SemanticDefinition.from_dict(item)
            for item in require_list(obj["semantics"], "$.semantics")
        )
        mappings = tuple(
            SiteMapping.from_dict(item)
            for item in require_list(obj["site_mappings"], "$.site_mappings")
        )
        rules = tuple(
            TransitionRule.from_dict(item)
            for item in require_list(obj["transition_rules"], "$.transition_rules")
        )
        return cls(
            contract_version=require_string(obj["contract_version"], "$.contract_version"),
            registry_version=require_string(obj["registry_version"], "$.registry_version"),
            semantics=semantics,
            site_mappings=mappings,
            transition_rules=rules,
        )
