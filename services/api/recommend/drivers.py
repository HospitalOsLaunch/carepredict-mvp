"""Readable risk and priority explanations for Action Engine recommendations."""

from __future__ import annotations

from dataclasses import dataclass

from services.api.recommend.scoring import ForecastContext, ScoredAction, severity_from_context


@dataclass(frozen=True, slots=True)
class RiskExplanation:
    """Business-readable decomposition of the forecast risk context."""

    excess_pts: float
    excess_ratio: float
    duration_h: int
    severity_reason: str
    peak_timing: str
    summary: str


@dataclass(frozen=True, slots=True)
class PriorityExplanation:
    """Business-readable decomposition of the action prioritization."""

    excess_anchor: float
    feasibility: float
    cost: float
    raw_score: float
    score_component: float
    summary: str


@dataclass(frozen=True, slots=True)
class RecommendationExplanation:
    """Complete explanation attached to one recommendation."""

    risk: RiskExplanation
    priority: PriorityExplanation
    scope_note: str


def explain_risk(ctx: ForecastContext) -> RiskExplanation:
    """Explain the already-computed forecast risk without changing its severity."""
    excess_pts = max(ctx.peak_siips - ctx.threshold, 0.0)
    excess_ratio = excess_pts / ctx.threshold if ctx.threshold > 0.0 else 0.0
    peak_timing = f"T+{ctx.peak_step}h"
    reason = _severity_reason(ctx, excess_pts, excess_ratio)
    return RiskExplanation(
        excess_pts=round(excess_pts, 2),
        excess_ratio=round(excess_ratio, 4),
        duration_h=ctx.hours_above_threshold,
        severity_reason=reason,
        peak_timing=peak_timing,
        summary=(
            f"Charge prévue {ctx.peak_siips:.0f} vs seuil {ctx.threshold:.0f} : "
            f"dépassement +{excess_pts:.0f} pts (+{excess_ratio:.0%}) pendant "
            f"{ctx.hours_above_threshold}h, pic à {peak_timing}."
        ),
    )


def explain_priority(scored_action: ScoredAction, ctx: ForecastContext) -> PriorityExplanation:
    """Explain priority components already present in the scored action and context."""
    excess_anchor = max(ctx.peak_siips - ctx.threshold, 0.0)
    return PriorityExplanation(
        excess_anchor=round(excess_anchor, 2),
        feasibility=round(scored_action.feasibility, 4),
        cost=round(scored_action.cost, 4),
        raw_score=round(scored_action.raw_score, 4),
        score_component=scored_action.score,
        summary=(
            f"Priorisée car elle cible un dépassement de {excess_anchor:.0f} pts "
            f"avec une faisabilité de {scored_action.feasibility:.0%} "
            f"et un coût relatif {scored_action.cost:.2f}."
        ),
    )


def recommendation_explanation(
    scored_action: ScoredAction, ctx: ForecastContext
) -> RecommendationExplanation:
    """Build the complete explanation object for one scored recommendation."""
    return RecommendationExplanation(
        risk=explain_risk(ctx),
        priority=explain_priority(scored_action, ctx),
        scope_note=(
            "Explication basée sur la prévision de charge uniquement ; "
            "les drivers d'aval et de flux ne sont pas encore disponibles."
        ),
    )


def _severity_reason(ctx: ForecastContext, excess_pts: float, excess_ratio: float) -> str:
    severity = severity_from_context(ctx)
    if severity == "critical":
        if excess_pts >= ctx.threshold * 0.12:
            return f"dépassement {excess_ratio:.0%} >= seuil critique 12%"
        return f"durée {ctx.hours_above_threshold}h >= seuil critique 6h"
    if severity == "high":
        if excess_pts >= ctx.threshold * 0.06:
            return f"dépassement {excess_ratio:.0%} >= seuil haut 6%"
        return f"durée {ctx.hours_above_threshold}h >= seuil haut 3h"
    if severity == "elevated":
        return "charge prévue au-dessus du seuil"
    return "charge prévue sous le seuil"
