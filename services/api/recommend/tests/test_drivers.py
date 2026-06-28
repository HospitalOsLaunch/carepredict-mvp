"""Tests for readable Action Engine risk drivers."""

from __future__ import annotations

from services.api.recommend.drivers import explain_priority, explain_risk, recommendation_explanation
from services.api.recommend.levers import LeverCandidate
from services.api.recommend.scoring import ForecastContext, ForecastPoint, RuleBasedScorer, severity_from_context


def _context(*, peak: float, threshold: float = 1000.0, hours: int = 1) -> ForecastContext:
    points = tuple(
        ForecastPoint(
            step_index=index + 1,
            predicted_siips=peak if index < hours else threshold - 10.0,
            lower_90=peak - 20.0,
            upper_90=peak + 30.0,
        )
        for index in range(12)
    )
    return ForecastContext(
        service_id="urg-001",
        horizon_h=48,
        threshold=threshold,
        peak_siips=peak,
        peak_step=1,
        hours_above_threshold=hours,
        total_excess_siips=sum(max(point.predicted_siips - threshold, 0.0) for point in points),
        forecast=points,
    )


def _candidate() -> LeverCandidate:
    return LeverCandidate(
        service_id="urg-001",
        lever="prioritize_discharge",
        title="Prioriser les sorties confirmées",
        feasibility=0.75,
        cost=1.25,
        impact_factor=0.3,
    )


def test_explain_risk_reports_exact_excess_duration_and_peak() -> None:
    explanation = explain_risk(_context(peak=1140.0, threshold=1000.0, hours=8))

    assert explanation.excess_pts == 140.0
    assert explanation.excess_ratio == 0.14
    assert explanation.duration_h == 8
    assert explanation.peak_timing == "T+1h"
    assert "Charge prévue 1140 vs seuil 1000" in explanation.summary


def test_explain_risk_critical_reason_matches_severity_branch() -> None:
    excess_driven = _context(peak=1140.0, threshold=1000.0, hours=1)
    duration_driven = _context(peak=1030.0, threshold=1000.0, hours=6)

    assert severity_from_context(excess_driven) == "critical"
    assert "12%" in explain_risk(excess_driven).severity_reason
    assert severity_from_context(duration_driven) == "critical"
    assert "6h" in explain_risk(duration_driven).severity_reason


def test_explain_risk_never_contradicts_severity_from_context() -> None:
    contexts = [
        _context(peak=1140.0, threshold=1000.0, hours=1),
        _context(peak=1070.0, threshold=1000.0, hours=1),
        _context(peak=1020.0, threshold=1000.0, hours=1),
        _context(peak=980.0, threshold=1000.0, hours=0),
    ]

    for ctx in contexts:
        severity = severity_from_context(ctx)
        reason = explain_risk(ctx).severity_reason
        if severity == "critical":
            assert "critique" in reason
        elif severity == "high":
            assert "haut" in reason
        elif severity == "elevated":
            assert "au-dessus du seuil" in reason
        else:
            assert "sous le seuil" in reason


def test_explain_priority_reads_scored_action_components() -> None:
    ctx = _context(peak=1140.0, threshold=1000.0, hours=8)
    action = RuleBasedScorer().score(_candidate(), ctx)

    explanation = explain_priority(action, ctx)

    assert explanation.excess_anchor == 140.0
    assert explanation.feasibility == action.feasibility
    assert explanation.cost == action.cost
    assert explanation.raw_score == action.raw_score
    assert explanation.score_component == action.score
    assert "coût relatif 1.25" in explanation.summary


def test_recommendation_explanation_keeps_forecast_scope_honest() -> None:
    ctx = _context(peak=1140.0, threshold=1000.0, hours=8)
    action = RuleBasedScorer().score(_candidate(), ctx)

    explanation = recommendation_explanation(action, ctx)

    assert explanation.risk.excess_pts == 140.0
    assert explanation.priority.score_component == action.score
    assert "prévision de charge uniquement" in explanation.scope_note
    assert "flux" in explanation.scope_note
