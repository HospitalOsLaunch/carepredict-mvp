"""
## DÉCISION
Sous coût asymétrique, sous-dimensionner la charge de soins coûte plus cher que
sur-dimensionner. Le scoring consomme donc la borne haute conforme comme pire-cas
crédible, afin de transformer la garantie de couverture en prudence opérationnelle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class ActionContext:
    """Contexte minimal consommé par une stratégie de scoring."""

    load_pred: float
    interval_lo: float | None = None
    interval_hi: float | None = None
    surge_flag: int = 0
    horizon: int = 48
    threshold: float | None = None
    capacity: float | None = None


@dataclass(frozen=True)
class ActionScore:
    """Score de décision auditable."""

    risk_score: float
    recommended_level: int
    rationale: str
    uncertainty_aware: bool


class ScoringStrategy(Protocol):
    """Frontière propre : intervalle calibré en entrée, score de décision en sortie."""

    def score(self, ctx: ActionContext) -> ActionScore:
        """Retourne un score de risque sans recalibrer l'intervalle."""


class PointEstimateScoring:
    """Repli rétrocompatible lorsque l'intervalle conforme n'est pas fourni."""

    def score(self, ctx: ActionContext) -> ActionScore:
        """Score historique basé sur la prédiction ponctuelle."""
        ref = _reference(ctx)
        risk = _clip01(ctx.load_pred / ref)
        return ActionScore(
            risk_score=risk,
            recommended_level=_level(risk),
            rationale=f"Score ponctuel : prédiction={ctx.load_pred:.1f}, référence={ref:.1f}.",
            uncertainty_aware=False,
        )


class ConformalRiskScoring:
    """Scoring risque-conscient lisant un intervalle CQR déjà conforme."""

    def __init__(self, asymmetry: float = 3.0, width_weight: float = 0.15) -> None:
        self.asymmetry = asymmetry
        self.width_weight = width_weight

    def score(self, ctx: ActionContext) -> ActionScore:
        """Score non décroissant avec la borne haute et prudent sous surge."""
        if ctx.interval_lo is None or ctx.interval_hi is None:
            return PointEstimateScoring().score(ctx)
        lo = float(ctx.interval_lo)
        hi = float(ctx.interval_hi)
        med = float(ctx.load_pred)
        if hi < lo:
            raise ValueError("Intervalle conforme invalide : hi < lo.")

        # On lit l'intervalle tel quel : aucune calibration ni mutation en aval.
        asymmetry_weight = self.asymmetry / (1.0 + self.asymmetry)
        decision_point = med + asymmetry_weight * max(hi - med, 0.0)
        ref = _reference(ctx)
        width_factor = self.width_weight * max(hi - lo, 0.0) / ref
        surge_factor = 0.05 if int(ctx.surge_flag) == 1 else 0.0
        risk = _clip01(decision_point / ref + width_factor + surge_factor)
        return ActionScore(
            risk_score=risk,
            recommended_level=_level(risk),
            rationale=(
                f"surge={int(ctx.surge_flag)}, borne haute conforme={hi:.1f}, "
                f"référence={ref:.1f} → niveau { _level(risk) }."
            ),
            uncertainty_aware=True,
        )


def _reference(ctx: ActionContext) -> float:
    """Capacité si connue, sinon seuil calibré Gate A.1/A.2."""
    ref = ctx.capacity if ctx.capacity is not None else ctx.threshold
    if ref is None or ref <= 0:
        raise ValueError("capacity ou threshold positif requis pour scorer.")
    return float(ref)


def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def _level(risk_score: float) -> int:
    if risk_score >= 0.90:
        return 3
    if risk_score >= 0.70:
        return 2
    if risk_score >= 0.50:
        return 1
    return 0


def assert_scoring_invariants() -> None:
    """Assertions isolées du world model pour les garanties décisionnelles."""
    scorer = ConformalRiskScoring()
    base = ActionContext(load_pred=90, interval_lo=80, interval_hi=100, threshold=120)
    high = ActionContext(load_pred=90, interval_lo=80, interval_hi=140, threshold=120)
    assert scorer.score(high).risk_score >= scorer.score(base).risk_score

    normal = scorer.score(ActionContext(load_pred=90, interval_lo=80, interval_hi=110, threshold=120))
    surge = scorer.score(ActionContext(load_pred=90, interval_lo=60, interval_hi=140, threshold=120, surge_flag=1))
    assert surge.recommended_level >= normal.recommended_level

    lo, hi = 60.0, 140.0
    ctx = ActionContext(load_pred=90, interval_lo=lo, interval_hi=hi, threshold=120)
    _ = scorer.score(ctx)
    assert ctx.interval_lo == lo and ctx.interval_hi == hi

    fallback = scorer.score(ActionContext(load_pred=90, threshold=120))
    assert fallback.uncertainty_aware is False


if __name__ == "__main__":
    assert_scoring_invariants()
    print("[scoring] invariants OK")
