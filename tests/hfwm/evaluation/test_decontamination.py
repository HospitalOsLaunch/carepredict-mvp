"""Tests for exact, correction and near-duplicate audits."""

from __future__ import annotations

from hfwm.evaluation.decontamination import (
    ContaminationRecord,
    audit_contamination,
    semantic_payload_hash,
)


def _record(
    record_id: str,
    *,
    episode: str,
    split: str,
    digest: str,
    text: str,
    correction_of: str | None = None,
) -> ContaminationRecord:
    return ContaminationRecord(record_id, episode, split, correction_of, digest, text)


def test_audit_finds_episode_correction_exact_and_near_cross_split() -> None:
    """Every preregistered contamination class is fail-closed across splits."""
    records = (
        _record("r1", episode="e1", split="train", digest="h1", text="alpha beta gamma delta"),
        _record("r2", episode="e1", split="test", digest="h2", text="different words only"),
        _record(
            "r3",
            episode="e3",
            split="test",
            digest="h1",
            text="another payload",
            correction_of="r1",
        ),
        _record(
            "r4",
            episode="e4",
            split="test",
            digest="h4",
            text="Alpha beta gamma delta extra",
        ),
    )
    kinds = {
        finding.kind
        for finding in audit_contamination(records, near_duplicate_threshold=0.60)
    }
    assert kinds == {
        "correction_cross_split",
        "episode_cross_split",
        "exact_semantic_duplicate",
        "near_semantic_duplicate",
    }


def test_semantic_hash_excludes_only_declared_volatile_fields() -> None:
    """Declared ingestion metadata does not alter semantic payload identity."""
    left = {"target": 10, "ingested_at": "a", "unit": "u"}
    right = {"target": 10, "ingested_at": "b", "unit": "u"}
    assert semantic_payload_hash(left, excluded_fields=("ingested_at",)) == semantic_payload_hash(
        right, excluded_fields=("ingested_at",)
    )
    assert semantic_payload_hash(left) != semantic_payload_hash(right)


def test_no_cross_split_overlap_returns_no_findings() -> None:
    """Distinct partition content passes the audit."""
    records = (
        _record("r1", episode="e1", split="train", digest="h1", text="alpha beta gamma"),
        _record("r2", episode="e2", split="test", digest="h2", text="theta lambda omega"),
    )
    assert audit_contamination(records) == ()
