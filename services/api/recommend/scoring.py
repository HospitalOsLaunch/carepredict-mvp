"""Scoring strategies for operational recommendation candidates.

``RuleBasedScorer`` is the Gate A scorer. It uses deterministic heuristics on
forecast excess over threshold. ``ORToolsScorer`` is intentionally only a seam
for a later gate: an optimizer can plug in here without changing ``engine.py``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from services.api.recommend.levers import LeverCandidate
from services.api.schemas.actions import ActionSeverity


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    """One forecasted SIIPS point used by the recommendation engine."""

    step_index: int
    predicted_siips: float
    lower_90: float
    upper_90: float


@dataclass(frozen=True, slots=True)
class ForecastContext:
    """Risk context derived from a service forecast."""

    service_id: str
    horizon_h: int
    threshold: float
    peak_siips: float
    peak_step: int
    hours_above_threshold: int
    total_excess_siips: float
    forecast: tuple[ForecastPoint, ...]


@dataclass(frozen=True, slots=True)
class ScoredAction:
    """Candidate action after scoring."""

    id: str
    service_id: str
    lever: str
    title: str
    severity: ActionSeverity
    score: float
    projected_impact_siips: float
    feasibility: float
    cost: float
    raw_score: float
    rationale: str
    horizon_h: int
    status: str = "proposed"


class ScoringStrategy(Protocol):
    """Protocol implemented by recommendation scoring strategies."""

    def score(self, candidate: LeverCandidate, ctx: ForecastContext) -> ScoredAction:
        """Score a candidate lever in a forecast context."""


class RuleBasedScorer:
    """Gate A deterministic scorer.

    # GATE A: heuristic impact, replaced by simulate in GATE B.
    score = projected_impact * feasibility / cost, normalized to [0,1].
    """

    def score(self, candidate: LeverCandidate, ctx: ForecastContext) -> ScoredAction:
        """Return a deterministic score for a candidate intervention."""
        excess_anchor = max(ctx.peak_siips - ctx.threshold, 0.0)
        load_anchor = max(ctx.total_excess_siips / max(ctx.hours_above_threshold, 1), excess_anchor)
        projected_impact = -round(load_anchor * candidate.impact_factor, 2)
        raw_score = abs(projected_impact) * candidate.feasibility / max(candidate.cost, 1e-6)
        normalized = max(0.0, min(1.0, raw_score / max(ctx.threshold * 0.08, 1.0)))
        severity = severity_from_context(ctx)
        stable_hash = hashlib.sha1(
            f"{ctx.service_id}:{candidate.lever}:{ctx.peak_step}:{ctx.horizon_h}".encode("utf-8")
        ).hexdigest()[:10]
        return ScoredAction(
            id=f"rec_{stable_hash}",
            service_id=ctx.service_id,
            lever=candidate.lever,
            title=candidate.title,
            severity=severity,
            score=round(normalized, 4),
            projected_impact_siips=projected_impact,
            feasibility=candidate.feasibility,
            cost=candidate.cost,
            raw_score=round(raw_score, 4),
            rationale=(
                f"Pic de charge prévu T+{ctx.peak_step}h dépassant le seuil de "
                f"{excess_anchor:.1f} pts sur {ctx.hours_above_threshold}h."
            ),
            horizon_h=ctx.horizon_h,
        )


class ORToolsScorer:
    """Future optimizer seam; OR-Tools is deliberately out of scope for Gate A."""

    def score(self, candidate: LeverCandidate, ctx: ForecastContext) -> ScoredAction:
        """Raise until an optimization gate implements this scorer."""
        raise NotImplementedError("ORToolsScorer is planned for a later gate")


def severity_from_context(ctx: ForecastContext) -> ActionSeverity:
    """Map forecast excess to a recommendation severity."""
    excess = max(ctx.peak_siips - ctx.threshold, 0.0)
    if excess >= ctx.threshold * 0.12 or ctx.hours_above_threshold >= 6:
        return "critical"
    if excess >= ctx.threshold * 0.06 or ctx.hours_above_threshold >= 3:
        return "high"
    if excess > 0.0:
        return "elevated"
    return "normal"
