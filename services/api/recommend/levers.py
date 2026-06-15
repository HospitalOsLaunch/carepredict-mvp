"""Candidate intervention catalog for Gate A recommendations.

The catalog is intentionally stateless. It contains feasibility and cost
metadata only; model calls and risk scoring live in ``engine.py`` and
``scoring.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.api.schemas.actions import ActionLever


@dataclass(frozen=True, slots=True)
class LeverCandidate:
    """One candidate operational lever for one service."""

    service_id: str
    lever: ActionLever
    title: str
    feasibility: float
    cost: float
    impact_factor: float


_CATALOG: tuple[tuple[ActionLever, str, float, float, float], ...] = (
    ("move_staff", "Réallouer 2 IDE vers {service}", 0.80, 1.20, 0.30),
    ("open_beds", "Ouvrir 3 lits tampon pour {service}", 0.62, 1.45, 0.24),
    ("close_beds", "Fermer temporairement lits non dotés en {service}", 0.42, 1.70, 0.12),
    ("prioritize_discharge", "Prioriser les sorties confirmées en {service}", 0.86, 1.00, 0.34),
    ("rebalance_workload", "Rééquilibrer la charge inter-équipe en {service}", 0.70, 1.10, 0.22),
)

_SERVICE_LABELS: dict[str, str] = {
    "urg-001": "Urgences",
    "med-001": "Médecine",
    "chir-001": "Chirurgie",
    "rea-001": "Réanimation",
    "ssr-001": "SSR",
}


def service_label(service_id: str) -> str:
    """Return a display label for a service id."""
    return _SERVICE_LABELS.get(service_id, service_id)


def candidate_levers(service_id: str) -> list[LeverCandidate]:
    """Return the candidate intervention catalog for one service."""
    label = service_label(service_id)
    return [
        LeverCandidate(
            service_id=service_id,
            lever=lever,
            title=title.format(service=label),
            feasibility=feasibility,
            cost=cost,
            impact_factor=impact_factor,
        )
        for lever, title, feasibility, cost, impact_factor in _CATALOG
    ]
