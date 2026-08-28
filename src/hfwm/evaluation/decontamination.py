"""Deterministic exact and near-duplicate contamination controls."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from hfwm.evaluation.canonical import semantic_hash

_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ContaminationRecord:
    """Minimal record used for cross-partition contamination audits."""

    record_id: str
    episode_id: str
    split: str
    correction_of: str | None
    semantic_hash: str
    semantic_text: str


@dataclass(frozen=True)
class ContaminationFinding:
    """One fail-closed contamination finding."""

    kind: str
    left_id: str
    right_id: str
    left_split: str
    right_split: str
    score: float


def normalized_semantic_text(value: str) -> str:
    """Normalize free text for deterministic near-duplicate comparison."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(_TOKEN.findall(normalized))


def semantic_payload_hash(
    payload: Mapping[str, Any], *, excluded_fields: Sequence[str] = ()
) -> str:
    """Hash semantic content while excluding preregistered volatile fields."""
    excluded = frozenset(excluded_fields)
    return semantic_hash({key: payload[key] for key in sorted(payload) if key not in excluded})


def token_shingles(value: str, *, width: int = 3) -> frozenset[tuple[str, ...]]:
    """Return word shingles for a near-duplicate audit."""
    if width <= 0:
        raise ValueError("shingle width must be positive")
    tokens = normalized_semantic_text(value).split()
    if not tokens:
        return frozenset()
    if len(tokens) < width:
        return frozenset({tuple(tokens)})
    return frozenset(
        tuple(tokens[index : index + width]) for index in range(len(tokens) - width + 1)
    )


def jaccard_similarity(left: frozenset[Any], right: frozenset[Any]) -> float:
    """Return Jaccard similarity with deterministic empty-set semantics."""
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def audit_contamination(
    records: Iterable[ContaminationRecord],
    *,
    near_duplicate_threshold: float = 0.92,
    shingle_width: int = 3,
) -> tuple[ContaminationFinding, ...]:
    """Find cross-split episode, correction, exact and near duplicates."""
    if not 0.0 <= near_duplicate_threshold <= 1.0:
        raise ValueError("near_duplicate_threshold must be in [0, 1]")
    materialized = sorted(records, key=lambda item: item.record_id)
    if len({record.record_id for record in materialized}) != len(materialized):
        raise ValueError("duplicate record_id")
    by_id = {record.record_id: record for record in materialized}
    findings: dict[tuple[str, str, str], ContaminationFinding] = {}

    by_episode: dict[str, list[ContaminationRecord]] = defaultdict(list)
    by_hash: dict[str, list[ContaminationRecord]] = defaultdict(list)
    for record in materialized:
        by_episode[record.episode_id].append(record)
        by_hash[record.semantic_hash].append(record)
        if record.correction_of is not None and record.correction_of in by_id:
            parent = by_id[record.correction_of]
            if parent.split != record.split:
                _add_finding(findings, "correction_cross_split", parent, record, 1.0)

    for members in by_episode.values():
        _pair_cross_split(findings, "episode_cross_split", members, score=1.0)
    for members in by_hash.values():
        _pair_cross_split(findings, "exact_semantic_duplicate", members, score=1.0)

    shingles = {
        record.record_id: token_shingles(record.semantic_text, width=shingle_width)
        for record in materialized
    }
    for index, left in enumerate(materialized):
        for right in materialized[index + 1 :]:
            if left.split == right.split or left.semantic_hash == right.semantic_hash:
                continue
            score = jaccard_similarity(shingles[left.record_id], shingles[right.record_id])
            if score >= near_duplicate_threshold:
                _add_finding(findings, "near_semantic_duplicate", left, right, score)
    return tuple(findings[key] for key in sorted(findings))


def _pair_cross_split(
    findings: dict[tuple[str, str, str], ContaminationFinding],
    kind: str,
    members: list[ContaminationRecord],
    *,
    score: float,
) -> None:
    for index, left in enumerate(members):
        for right in members[index + 1 :]:
            if left.split != right.split:
                _add_finding(findings, kind, left, right, score)


def _add_finding(
    findings: dict[tuple[str, str, str], ContaminationFinding],
    kind: str,
    left: ContaminationRecord,
    right: ContaminationRecord,
    score: float,
) -> None:
    first, second = sorted((left, right), key=lambda item: item.record_id)
    key = (kind, first.record_id, second.record_id)
    findings[key] = ContaminationFinding(
        kind=kind,
        left_id=first.record_id,
        right_id=second.record_id,
        left_split=first.split,
        right_split=second.split,
        score=score,
    )
