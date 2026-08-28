from __future__ import annotations

import math

import pytest

from hfwm.contracts import (
    ComponentIdentity,
    ContractValidationError,
    HospitalTokenizer,
    TokenBatch,
    TokenizerInput,
    canonical_json_bytes,
    semantic_sha256,
)
from hfwm.contracts.serialization import JSONValue


class ExampleTokenizer:
    identity = ComponentIdentity(
        component_type="HospitalTokenizer",
        implementation_id="example",
        contract_version="hfwm.architecture.v1",
        implementation_version="0",
    )

    def encode(self, batch: TokenizerInput) -> TokenBatch:
        return TokenBatch(
            values=(),
            attention_mask=(),
            entity_ids=(),
            event_ids=(),
            available_at=(batch.as_of,),
            provenance=(),
        )


def test_canonical_bytes_and_hash_ignore_mapping_insertion_order() -> None:
    first: JSONValue = {"é": [1, True], "a": {"z": None}}
    second: JSONValue = {"a": {"z": None}, "é": [1, True]}

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert semantic_sha256(first) == semantic_sha256(second)


def test_canonical_bytes_reject_non_finite_values() -> None:
    with pytest.raises(ContractValidationError, match="non-finite"):
        canonical_json_bytes({"invalid": math.nan})


def test_architecture_contract_is_runtime_interchangeable() -> None:
    tokenizer = ExampleTokenizer()
    assert isinstance(tokenizer, HospitalTokenizer)

    batch = tokenizer.encode(
        TokenizerInput(
            events=(),
            time_series={},
            entity_graph={},
            capacities={},
            resources={},
            context={},
            actions=(),
            recording_process={},
            schema_versions={},
            as_of="2026-01-01T00:00:00Z",
        )
    )
    assert batch.available_at == ("2026-01-01T00:00:00Z",)
