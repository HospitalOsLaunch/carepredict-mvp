from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
import yaml

from hfwm.contracts import (
    DATA_RIGHTS_CONTRACT_VERSION,
    ContractValidationError,
    DataRightsRegistry,
    RightsDecision,
    RightsUse,
    SourceRights,
    parse_json_bytes,
)
from hfwm.contracts.serialization import JSONValue

ROOT = Path(__file__).resolve().parents[3]


def test_rights_document_is_strict_deny_by_default_registry() -> None:
    document = cast(
        JSONValue,
        yaml.safe_load(
            (ROOT / "docs/research/hfwm/HFWM_R0_DATA_RIGHTS.yaml").read_text(encoding="utf-8")
        ),
    )
    registry = DataRightsRegistry.from_dict(document)

    assert registry.contract_version == DATA_RIGHTS_CONTRACT_VERSION
    assert registry.default_decision == RightsDecision.DENIED
    assert registry.sources
    assert registry.authorize("hfwm_r0_internal_synthetic_fixture", RightsUse.TRAINING)
    assert registry.authorize("hfwm_r0_internal_synthetic_fixture", RightsUse.EVALUATION)
    synthetic = next(
        source
        for source in registry.sources
        if source.source_id == "hfwm_r0_internal_synthetic_fixture"
    )
    assert synthetic.decision == RightsDecision.ALLOWED
    assert synthetic.publication_allowed is False
    assert synthetic.weights_allowed is False
    assert all(
        source.decision == RightsDecision.DENIED
        for source in registry.sources
        if source.source_id != "hfwm_r0_internal_synthetic_fixture"
    )
    assert not registry.authorize("unknown-source", RightsUse.TRAINING)
    assert not registry.authorize("mimic_iv", RightsUse.EVALUATION)
    restored = DataRightsRegistry.from_dict(parse_json_bytes(registry.to_json_bytes()))
    assert restored == registry
    assert restored.semantic_hash() == registry.semantic_hash()


def test_unverified_source_cannot_be_allowed() -> None:
    with pytest.raises(ContractValidationError, match="unverified"):
        SourceRights(
            source_id="unknown",
            owner="NOT_VERIFIED",
            licence="NOT_VERIFIED",
            allowed_purposes=("research",),
            training_allowed=True,
            evaluation_allowed=False,
            derived_features_allowed=False,
            embeddings_allowed=False,
            weights_allowed=False,
            cross_site_learning_allowed=False,
            benchmark_allowed=False,
            publication_allowed=False,
            retention="one year",
            deletion_obligations="delete on expiry",
            territory="EU",
            expiry="2027-01-01",
            decision=RightsDecision.ALLOWED,
            evidence_refs=("rights-review/1",),
        )


def test_spec_preregisters_three_families_and_negative_statuses() -> None:
    spec = yaml.safe_load(
        (ROOT / "docs/research/hfwm/HFWM_R0_SPEC.yaml").read_text(encoding="utf-8")
    )

    assert spec["main_runs_authorized"] is True
    assert spec["primary_families"]["maximum_count"] == 3
    assert len(spec["primary_families"]["candidates"]) == 3
    assert spec["actions"]["status"] == "ACTION_CONDITIONING_NOT_IDENTIFIABLE"
    assert spec["foundation"]["status"] == "FOUNDATION_EVIDENCE_INSUFFICIENT"
    assert "CAUSAL_EFFECT" in spec["forbidden_claims"]
