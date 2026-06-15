"""Unit tests for Gate A recommendation scoring."""

from __future__ import annotations

import pytest

from services.api.recommend.levers import LeverCandidate
from services.api.recommend.scoring import (
    ForecastContext,
    ForecastPoint,
    ORToolsScorer,
    RuleBasedScorer,
    severity_from_context,
)


def _context(*, peak: float = 1780.0, hours: int = 6) -> ForecastContext:
    points = tuple(
        ForecastPoint(
            step_index=index + 1,
            predicted_siips=peak if index < hours else 1200.0,
            lower_90=peak - 80.0,
            upper_90=peak + 90.0,
        )
        for index in range(12)
    )
    return ForecastContext(
        service_id="rea-001",
        horizon_h=48,
        threshold=1600.0,
        peak_siips=peak,
        peak_step=1,
        hours_above_threshold=hours,
        total_excess_siips=sum(max(point.predicted_siips - 1600.0, 0.0) for point in points),
        forecast=points,
    )


def _candidate(*, feasibility: float = 0.8, cost: float = 1.2) -> LeverCandidate:
    return LeverCandidate(
        service_id="rea-001",
        lever="move_staff",
        title="Réallouer 2 IDE vers Réanimation",
        feasibility=feasibility,
        cost=cost,
        impact_factor=0.3,
    )


def test_rule_based_scorer_returns_normalized_stable_action() -> None:
    action = RuleBasedScorer().score(_candidate(), _context())

    assert action.id.startswith("rec_")
    assert action.service_id == "rea-001"
    assert action.status == "proposed"
    assert 0.0 <= action.score <= 1.0
    assert action.projected_impact_siips < 0.0
    assert action.severity == "critical"
    assert "Pic de charge prévu" in action.rationale


def test_rule_based_scorer_rewards_feasibility_and_cost() -> None:
    scorer = RuleBasedScorer()
    strong = scorer.score(_candidate(feasibility=0.9, cost=1.0), _context())
    weak = scorer.score(_candidate(feasibility=0.3, cost=2.0), _context())

    assert strong.score > weak.score


def test_severity_from_context_thresholds() -> None:
    assert severity_from_context(_context(peak=1820.0, hours=6)) == "critical"
    assert severity_from_context(_context(peak=1700.0, hours=3)) == "high"
    assert severity_from_context(_context(peak=1620.0, hours=1)) == "elevated"
    assert severity_from_context(_context(peak=1400.0, hours=0)) == "normal"


def test_ortools_scorer_is_explicitly_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        ORToolsScorer().score(_candidate(), _context())
