"""Tests for frozen metrics and fail-closed claim scanning."""

from __future__ import annotations

import math

import pytest

from hfwm.evaluation.claims import scan_claims, validate_declared_claims
from hfwm.evaluation.metrics import (
    bootstrap_relative_gain_ci,
    interval_coverage,
    pinball_loss,
    point_metrics,
    relative_gain,
)


def test_point_probabilistic_and_relative_metrics() -> None:
    """Frozen metric implementations produce expected deterministic values."""
    metrics = point_metrics([10.0, 20.0], [8.0, 23.0])
    assert metrics.count == 2
    assert metrics.mae == 2.5
    assert math.isclose(metrics.rmse, math.sqrt(6.5))
    assert pinball_loss([10.0], [8.0], quantile=0.5) == 1.0
    assert interval_coverage([10.0, 20.0], [9.0, 21.0], [11.0, 23.0]) == 0.5
    assert relative_gain(candidate_score=9.0, comparator_score=10.0) == pytest.approx(0.1)


def test_bootstrap_relative_gain_is_seeded() -> None:
    """Paired bootstrap intervals are stable for a frozen seed."""
    candidate = [0.8, 0.9, 1.0, 1.1]
    comparator = [1.0, 1.1, 1.2, 1.3]
    assert bootstrap_relative_gain_ci(candidate, comparator, seed=42, draws=100) == (
        bootstrap_relative_gain_ci(candidate, comparator, seed=42, draws=100)
    )


def test_claim_scan_blocks_forbidden_claims_but_not_allowed_status() -> None:
    """Generated evidence cannot silently claim validation or causality."""
    findings = scan_claims(
        [
            ("report.md", "Candidate is validated at Nantes.\nNo causal effect is established."),
            ("safe.md", "HOSPITAL_WORLD_MODEL_CANDIDATE SHADOW_ONLY"),
        ]
    )
    assert [(finding.source, finding.line, finding.claim) for finding in findings] == [
        ("report.md", 1, "VALIDATED AT NANTES"),
        ("report.md", 2, "CAUSAL EFFECT"),
    ]
    assert validate_declared_claims(["SHADOW_ONLY"]) == []
    assert validate_declared_claims(["MAGIC_MODEL"]) == ["MAGIC_MODEL"]
