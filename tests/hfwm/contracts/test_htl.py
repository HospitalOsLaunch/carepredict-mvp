from __future__ import annotations

import pytest

from hfwm.contracts import ContractValidationError, parse_json_bytes
from hfwm.htl import (
    HTL_CONTRACT_VERSION,
    ConstraintClass,
    HTLRegistry,
    SemanticDefinition,
    SemanticKind,
    SiteMapping,
    TransitionRule,
    ValueKind,
)


def semantic(semantic_id: str, kind: SemanticKind = SemanticKind.EVENT) -> SemanticDefinition:
    return SemanticDefinition(
        semantic_id=semantic_id,
        kind=kind,
        canonical_name=semantic_id,
        definition=f"Definition for {semantic_id}",
        value_kind=ValueKind.NUMBER,
        unit="count",
        allowed_values=(),
        parent_semantic_id=None,
        constraint_class=(
            ConstraintClass.HARD
            if kind == SemanticKind.CONSTRAINT
            else ConstraintClass.NOT_APPLICABLE
        ),
        schema_version="1",
    )


def test_htl_round_trip_and_hash_are_stable_across_registry_order() -> None:
    admission = semantic("event.admission")
    capacity = semantic("capacity.beds", SemanticKind.CAPACITY)
    mapping = SiteMapping(
        mapping_id="mapping.site-a.admission",
        mapping_version="1",
        site_id="site-a",
        source_system="fhir",
        source_schema_version="r4",
        local_code="ADM",
        semantic_id="event.admission",
        transform_id="identity",
        transform_parameters=(("timezone", "Europe/Paris"),),
        valid_from="2026-01-01T00:00:00+01:00",
        valid_to=None,
        evidence_ref="mapping-review/site-a/v1",
    )
    first = HTLRegistry(HTL_CONTRACT_VERSION, "r0.1", (admission, capacity), (mapping,))
    reordered = HTLRegistry(HTL_CONTRACT_VERSION, "r0.1", (capacity, admission), (mapping,))

    restored = HTLRegistry.from_dict(parse_json_bytes(first.to_json_bytes()))
    assert restored == first
    assert first.semantic_hash() == reordered.semantic_hash()
    assert restored.semantic_hash() == first.semantic_hash()


def test_htl_keeps_common_semantics_separate_from_site_mapping() -> None:
    definition = semantic("event.discharge")
    assert "site_id" not in definition.to_dict()
    assert "local_code" not in definition.to_dict()


def test_htl_rejects_unknown_site_mapping_target_and_unknown_fields() -> None:
    mapping = SiteMapping(
        mapping_id="mapping.site-a.unknown",
        mapping_version="1",
        site_id="site-a",
        source_system="source",
        source_schema_version="1",
        local_code="X",
        semantic_id="event.unknown",
        transform_id="identity",
        transform_parameters=(),
        valid_from="2026-01-01T00:00:00Z",
        valid_to=None,
        evidence_ref="review/1",
    )
    with pytest.raises(ContractValidationError, match="unknown semantic"):
        HTLRegistry(HTL_CONTRACT_VERSION, "r0.1", (semantic("event.known"),), (mapping,))

    payload = semantic("event.known").to_dict()
    payload["surprise"] = "forbidden"
    with pytest.raises(ContractValidationError, match="unknown fields"):
        SemanticDefinition.from_dict(payload)


def test_constraint_classification_is_explicit() -> None:
    with pytest.raises(ContractValidationError, match="constraint_class"):
        SemanticDefinition(
            semantic_id="constraint.patient-flow",
            kind=SemanticKind.CONSTRAINT,
            canonical_name="Patient flow",
            definition="Patient conservation",
            value_kind=ValueKind.BOOLEAN,
            unit=None,
            allowed_values=(),
            parent_semantic_id=None,
            constraint_class=ConstraintClass.NOT_APPLICABLE,
            schema_version="1",
        )


def test_transition_grammar_closes_trigger_state_relation_and_constraint_references() -> None:
    trigger = semantic("event.admission", SemanticKind.EVENT)
    state_before = semantic("state.waiting", SemanticKind.STATE)
    state_after = semantic("state.present", SemanticKind.STATE)
    relation = semantic("relation.assigned-to", SemanticKind.RELATION)
    constraint = semantic("constraint.patient-flow", SemanticKind.CONSTRAINT)
    rule = TransitionRule(
        rule_id="transition.admission",
        trigger_semantic_id=trigger.semantic_id,
        input_state_ids=(state_before.semantic_id,),
        output_state_ids=(state_after.semantic_id,),
        relation_ids=(relation.semantic_id,),
        constraint_ids=(constraint.semantic_id,),
        schema_version="1",
    )
    registry = HTLRegistry(
        HTL_CONTRACT_VERSION,
        "r0.1",
        (trigger, state_before, state_after, relation, constraint),
        (),
        (rule,),
    )
    assert HTLRegistry.from_dict(parse_json_bytes(registry.to_json_bytes())) == registry

    invalid = TransitionRule(
        rule_id="transition.invalid",
        trigger_semantic_id=trigger.semantic_id,
        input_state_ids=(trigger.semantic_id,),
        output_state_ids=(state_after.semantic_id,),
        relation_ids=(),
        constraint_ids=(),
        schema_version="1",
    )
    with pytest.raises(ContractValidationError, match="expects .* to be state"):
        HTLRegistry(
            HTL_CONTRACT_VERSION,
            "r0.1",
            (trigger, state_after),
            (),
            (invalid,),
        )
