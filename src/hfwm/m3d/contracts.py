"""Executable contracts for the HFWM-R0 M3D pre-data milestone.

This module processes only specifications and strictly synthetic fixtures. It does
not load partner data and contains no model fitting entrypoint.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeAlias

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]

CONVENTION_STATUSES = frozenset({"assumed", "confirmed_by_partner"})
CONVENTION_OWNERS = frozenset({"DIM", "DPI", "DSI", "DIRECTION_DES_SOINS", "DPO", "OTHER"})
DATA_IN_HAND_STATUSES = frozenset(
    {
        "DATA_IN_HAND",
        "PARTNER_CONFIRMED_FROM_DATA",
        "M3E_ELIGIBLE",
        "OBSERVED_ON_PARTNER_DATA",
    }
)
EXTERNAL_CLAIM_STATUSES = frozenset(
    {
        "SOURCED_OFFICIAL",
        "SOURCED_PARTNER_INTERNAL",
        "ASSUMED_QUESTION_ONLY",
        "UNSUPPORTED_REMOVE",
        "NOT_EXTERNAL_FACT",
    }
)


def _canonical_bytes(value: JSONValue) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_hash(value: JSONValue) -> str:
    """Hash a JSON-compatible value using the repository canonical form."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def weights_hash(learned_parameters: Mapping[str, JSONValue]) -> str:
    """Hash only canonical serialized learned weights or parameters."""
    return canonical_hash(dict(learned_parameters))


def configuration_hash(configuration: Mapping[str, JSONValue]) -> str:
    """Hash the complete configuration, including its seed when present."""
    return canonical_hash(dict(configuration))


def prediction_hash(predictions: Sequence[JSONValue]) -> str:
    """Hash only the non-rounded prediction payload."""
    return canonical_hash(list(predictions))


def simulation_output_hash(output: Mapping[str, JSONValue]) -> str:
    """Hash simulation outputs without allowing the hash field to hash itself."""
    unhashed = {
        key: value for key, value in output.items() if key != "simulation_output_hash"
    }
    return canonical_hash(unhashed)


def validate_external_claims_ledger(document: Mapping[str, Any]) -> None:
    """Reject unregistered or unsupported facts exposed to a partner."""
    claims = document.get("claims")
    files = document.get("files_audited")
    if not isinstance(claims, dict) or not isinstance(files, list):
        raise ValueError("claims and files_audited are required")
    registered = set(claims)
    errors: list[str] = []
    for claim_id, raw_claim in claims.items():
        if not isinstance(raw_claim, dict):
            errors.append(f"{claim_id}: claim must be a mapping")
            continue
        required = {
            "claim_id",
            "claim_text",
            "claim_type",
            "file",
            "line",
            "external_exposure",
            "source_status",
            "source_type",
            "source_reference",
            "source_locator",
            "retrieved_or_verified_at",
            "supports_claim",
            "required_action",
        }
        missing = sorted(required - set(raw_claim))
        if missing:
            errors.append(f"{claim_id}: missing {','.join(missing)}")
        status = raw_claim.get("source_status")
        if status not in EXTERNAL_CLAIM_STATUSES:
            errors.append(f"{claim_id}: invalid source_status")
        if status == "SOURCED_OFFICIAL" and raw_claim.get("attests_asserted_role") is not True:
            errors.append(f"{claim_id}: official source does not attest asserted role or fact")
        exposure = raw_claim.get("external_exposure")
        is_exposed = exposure in {"EXTERNAL_PARTNER_DOCUMENT", "PARTNER_QUESTION_ONLY"}
        if is_exposed and status == "UNSUPPORTED_REMOVE":
            errors.append(f"{claim_id}: unsupported claim exposed")
        unsupported_exposed_fact = (
            is_exposed
            and raw_claim.get("supports_claim") is not True
            and status != "ASSUMED_QUESTION_ONLY"
        )
        if unsupported_exposed_fact:
            errors.append(f"{claim_id}: exposed factual claim lacks support")
        if status == "ASSUMED_QUESTION_ONLY" and exposure != "PARTNER_QUESTION_ONLY":
            errors.append(f"{claim_id}: assumed claim may appear only as a question")
    for index, raw_file in enumerate(files):
        if not isinstance(raw_file, dict) or not isinstance(raw_file.get("file"), str):
            errors.append(f"files_audited[{index}]: invalid file record")
            continue
        claim_ids = raw_file.get("external_claim_ids")
        if not isinstance(claim_ids, list):
            errors.append(f"files_audited[{index}]: external_claim_ids must be a list")
            continue
        unknown = sorted(str(value) for value in claim_ids if value not in registered)
        if unknown:
            errors.append(f"files_audited[{index}]: unknown claims {','.join(unknown)}")
    if errors:
        raise ValueError("; ".join(errors))


def occupancy_rate(patient_census_count: float, open_bed_count: float) -> float:
    """Return the time-aligned rate; the denominator must be strictly positive."""
    if not math.isfinite(patient_census_count) or patient_census_count < 0:
        raise ValueError("patient_census_count must be finite and non-negative")
    if not math.isfinite(open_bed_count) or open_bed_count <= 0:
        raise ValueError("open_bed_count must be finite and positive")
    return patient_census_count / open_bed_count


def stock_flow_next(
    census: int,
    *,
    external_entries: int,
    internal_inbound_transfers: int,
    external_exits: int,
    internal_outbound_transfers: int,
    other_signed_census_adjustments: int,
) -> int:
    """Apply the closed census identity to an explicitly defined count."""
    values = (
        census,
        external_entries,
        internal_inbound_transfers,
        external_exits,
        internal_outbound_transfers,
        other_signed_census_adjustments,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise TypeError("stock-flow identity accepts integer counts only")
    result = (
        census
        + external_entries
        + internal_inbound_transfers
        - external_exits
        - internal_outbound_transfers
        + other_signed_census_adjustments
    )
    if result < 0:
        raise ValueError("stock-flow identity produced a negative census")
    return result


def independent_cluster_key(record: Mapping[str, JSONValue]) -> tuple[str, str, str]:
    """Return the frozen analysis cluster; unit is deliberately not independent."""
    required = ("hospital_group_id", "hospital_site_id", "temporal_block_id")
    values = tuple(record.get(key) for key in required)
    if not all(isinstance(value, str) and value for value in values):
        raise ValueError("group, site and temporal block identifiers are required")
    return values[0], values[1], values[2]  # type: ignore[return-value]


def validate_transfer_coupling(events: Sequence[Mapping[str, JSONValue]]) -> list[str]:
    """Return transfer IDs that do not have one outbound and one matching inbound leg."""
    paired: dict[str, list[Mapping[str, JSONValue]]] = {}
    for index, event in enumerate(events):
        if event.get("event_type") not in {
            "internal_inbound_transfer",
            "internal_outbound_transfer",
        }:
            continue
        transfer_id = event.get("transfer_event_id")
        if isinstance(transfer_id, str) and transfer_id:
            pair_key = f"id:{transfer_id}"
        else:
            source_record_id = event.get("source_record_id")
            source = event.get("source_unit_id")
            destination = event.get("destination_unit_id")
            event_time = event.get("event_time")
            if not all(
                isinstance(value, str) and value
                for value in (source_record_id, source, destination, event_time)
            ):
                paired[f"missing:{index}"] = [event]
                continue
            pair_key = f"fallback:{source_record_id}:{source}:{destination}:{event_time}"
        paired.setdefault(pair_key, []).append(event)
    broken: list[str] = []
    for transfer_id, legs in paired.items():
        kinds = {leg.get("event_type") for leg in legs}
        if len(legs) != 2 or kinds != {
            "internal_inbound_transfer",
            "internal_outbound_transfer",
        }:
            broken.append(transfer_id.removeprefix("id:"))
            continue
        outbound = next(leg for leg in legs if leg["event_type"] == "internal_outbound_transfer")
        inbound = next(leg for leg in legs if leg["event_type"] == "internal_inbound_transfer")
        if (
            outbound.get("source_unit_id") != inbound.get("source_unit_id")
            or outbound.get("destination_unit_id") != inbound.get("destination_unit_id")
            or outbound.get("event_time") != inbound.get("event_time")
        ):
            broken.append(transfer_id.removeprefix("id:"))
    return sorted(broken)


def _walk(value: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    found: list[tuple[tuple[str, ...], Any]] = [(path, value)]
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(_walk(child, (*path, str(key))))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk(child, (*path, str(index))))
    return found


def validate_conventions(document: Mapping[str, Any]) -> None:
    """Require complete ownership/evidence metadata on every convention object."""
    errors: list[str] = []
    for path, value in _walk(document):
        if not isinstance(value, dict) or "status" not in value:
            continue
        status = value["status"]
        if status not in CONVENTION_STATUSES:
            continue
        owner = value.get("owner_to_confirm")
        if owner not in CONVENTION_OWNERS:
            errors.append(f"{'.'.join(path)}: invalid owner_to_confirm")
        if "evidence" not in value:
            errors.append(f"{'.'.join(path)}: missing evidence")
        if status == "assumed" and not isinstance(value.get("question"), str):
            errors.append(f"{'.'.join(path)}: assumed convention missing question")
    if errors:
        raise ValueError("; ".join(errors))


def generate_assumed_questions(*documents: Mapping[str, Any]) -> list[dict[str, str]]:
    """Generate the partner question register from all assumed conventions."""
    questions: list[dict[str, str]] = []
    for document_index, document in enumerate(documents):
        validate_conventions(document)
        for path, value in _walk(document):
            if not isinstance(value, dict) or value.get("status") != "assumed":
                continue
            question = value.get("question")
            owner = value.get("owner_to_confirm")
            if isinstance(question, str) and isinstance(owner, str):
                questions.append(
                    {
                        "convention_path": f"document[{document_index}].{'.'.join(path)}",
                        "owner_to_confirm": owner,
                        "question": question,
                    }
                )
    return sorted(questions, key=lambda item: item["convention_path"])


def assert_fixture_only(document: Mapping[str, Any]) -> None:
    """Prevent synthetic M3D fixtures from manufacturing a data-in-hand status."""
    if document.get("synthetic_only") is not True:
        raise ValueError("M3D fixtures must declare synthetic_only: true")
    for path, value in _walk(document):
        if isinstance(value, str) and value in DATA_IN_HAND_STATUSES:
            raise ValueError(f"data-in-hand status forbidden in M3D fixture at {'.'.join(path)}")


@dataclass(frozen=True, slots=True)
class ReplayabilityDecision:
    """Frozen eligibility result for one site/unit/temporal block."""

    aggregate_score: float
    eligible: bool
    hard_fail_dimensions: tuple[str, ...]
    exclusion_reasons: tuple[str, ...]
    historical_realtime_claim_allowed: bool


def _check_passes(value: JSONValue, check: Mapping[str, JSONValue]) -> bool:
    kind = check.get("kind")
    if kind == "boolean_true":
        return value is True
    if kind == "minimum":
        minimum = check.get("value")
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and isinstance(minimum, (int, float))
            and not isinstance(minimum, bool)
            and float(value) >= float(minimum)
        )
    if kind == "maximum":
        maximum = check.get("value")
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and isinstance(maximum, (int, float))
            and not isinstance(maximum, bool)
            and float(value) <= float(maximum)
        )
    raise ValueError(f"unsupported replayability check kind: {kind}")


def score_replayability(
    evidence: Mapping[str, Mapping[str, JSONValue]],
    *,
    rubric: Mapping[str, Mapping[str, JSONValue]],
) -> dict[str, float]:
    """Transform raw evidence into deterministic 0–100 dimension scores.

    Missing evidence always fails its check. Each rubric check has an explicit
    weight and boolean/minimum/maximum tolerance.
    """
    scores: dict[str, float] = {}
    for dimension, specification in rubric.items():
        raw_checks = specification.get("checks")
        if not isinstance(raw_checks, list) or not raw_checks:
            raise ValueError(f"missing replayability rubric checks: {dimension}")
        dimension_evidence = evidence.get(dimension, {})
        earned = 0.0
        total = 0.0
        for raw_check in raw_checks:
            if not isinstance(raw_check, dict):
                raise ValueError(f"invalid replayability check: {dimension}")
            check_id = raw_check.get("id")
            weight = raw_check.get("weight")
            if not isinstance(check_id, str) or not isinstance(weight, (int, float)):
                raise ValueError(f"invalid replayability check metadata: {dimension}")
            if isinstance(weight, bool) or float(weight) <= 0:
                raise ValueError(f"invalid replayability weight: {dimension}.{check_id}")
            total += float(weight)
            if _check_passes(dimension_evidence.get(check_id), raw_check):
                earned += float(weight)
        scores[dimension] = 100.0 * earned / total
    return scores


def replayability_decision(
    scores: Mapping[str, float],
    *,
    thresholds: Mapping[str, Mapping[str, JSONValue]],
    historical_available_at: bool,
) -> ReplayabilityDecision:
    """Apply pre-data thresholds; an aggregate score can never hide a hard fail."""
    expected = set(thresholds)
    if set(scores) != expected:
        raise ValueError("replayability dimensions differ from frozen thresholds")
    hard_fails: list[str] = []
    reasons: list[str] = []
    for dimension in sorted(expected):
        score = scores[dimension]
        minimum = thresholds[dimension].get("minimum")
        blocking = thresholds[dimension].get("blocking_for_retrospective")
        if not isinstance(score, (int, float)) or not 0 <= float(score) <= 100:
            raise ValueError(f"invalid replayability score: {dimension}")
        if not isinstance(minimum, (int, float)) or not isinstance(blocking, bool):
            raise ValueError(f"invalid replayability threshold: {dimension}")
        if float(score) < float(minimum):
            reasons.append(f"{dimension}_below_{minimum:g}")
            if blocking:
                hard_fails.append(dimension)
    if not historical_available_at:
        reasons.append("historical_available_at_missing_retro_only")
    return ReplayabilityDecision(
        aggregate_score=sum(float(value) for value in scores.values()) / len(scores),
        eligible=not hard_fails,
        hard_fail_dimensions=tuple(hard_fails),
        exclusion_reasons=tuple(reasons),
        historical_realtime_claim_allowed=historical_available_at and not hard_fails,
    )
