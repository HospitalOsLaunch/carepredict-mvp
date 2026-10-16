"""Observation-only plugin contract and two engineering policies, without simulator access."""

from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import math
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, StrictInt, model_validator

from .asof import AsOfRow
from .config import FrozenConfig, Identifier

Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)]
Probabilities = tuple[Probability, Probability, Probability, Probability]
LEVER_NAMES = (
    "anticipation_sorties",
    "lits_supplementaires",
    "renfort_soignant",
    "acceleration_aval",
)


class PolicyDescriptor(FrozenConfig):
    policy_id: Identifier
    version: Annotated[str, Field(min_length=1, max_length=100)]
    artifact_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class SiteUnit(FrozenConfig):
    unit_id: Identifier
    pole_id: Identifier
    specialty: Literal["MED_POLY", "CSG", "PNEUMO", "CARDIO"]


class PolicySite(FrozenConfig):
    hospital_id: Identifier
    start: dt.date
    clock: Literal["fixed UTC+01:00"] = "fixed UTC+01:00"
    units: tuple[SiteUnit, ...]


class PolicyContext(FrozenConfig):
    decision_h: Annotated[StrictInt, Field(ge=0)]
    timestamp: str
    observations: tuple[AsOfRow, ...]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if not self.observations or any(r.decision_h != self.decision_h for r in self.observations):
            raise ValueError("Context observations must share the decision boundary")
        if len({r.hospital_id for r in self.observations}) != 1:
            raise ValueError("Context spans multiple hospitals")
        return self

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class UnitRecommendation(FrozenConfig):
    unit_id: Identifier
    probabilities: Probabilities
    reason: Annotated[str, Field(min_length=1, max_length=200)]


class RecommendationBatch(FrozenConfig):
    descriptor: PolicyDescriptor
    decision_h: Annotated[StrictInt, Field(ge=0)]
    context_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    units: tuple[UnitRecommendation, ...]


class Policy(Protocol):
    @property
    def descriptor(self) -> PolicyDescriptor: ...

    def reset(self, site: PolicySite) -> None: ...

    def recommend(self, context: PolicyContext) -> RecommendationBatch: ...


class NoRecommendationPolicy:
    """No system recommendation; the independently simulated cadre may still act."""

    @property
    def descriptor(self) -> PolicyDescriptor:
        return PolicyDescriptor(
            policy_id="no_recommendation",
            version="1",
            artifact_sha256=hashlib.sha256(
                inspect.getsource(NoRecommendationPolicy).encode()
            ).hexdigest(),
        )

    def reset(self, site: PolicySite) -> None:
        pass

    def recommend(self, context: PolicyContext) -> RecommendationBatch:
        return RecommendationBatch(
            descriptor=self.descriptor,
            decision_h=context.decision_h,
            context_sha256=context.fingerprint,
            units=tuple(
                UnitRecommendation(
                    unit_id=r.entity_id,
                    probabilities=(0.0, 0.0, 0.0, 0.0),
                    reason="no_system_recommendation",
                )
                for r in context.observations
                if r.level == "unit"
            ),
        )


class ObservedRulePolicy(NoRecommendationPolicy):
    """Uncalibrated interface exercise; no trained model and no efficacy claim."""

    @property
    def descriptor(self) -> PolicyDescriptor:
        return PolicyDescriptor(
            policy_id="observed_rules",
            version="1",
            artifact_sha256=hashlib.sha256(
                inspect.getsource(ObservedRulePolicy).encode()
            ).hexdigest(),
        )

    def recommend(self, context: PolicyContext) -> RecommendationBatch:
        units = []
        for row in context.observations:
            if row.level != "unit":
                continue
            v = row.values
            q: Probabilities = (0.0, 0.0, 0.0, 0.0)
            reason = "missing_or_stale_observation"
            if v is not None and not row.stale:
                occ = v.lits_occupes / max(v.lits_ouverts, 1)
                ratio = v.charge_soins_min_h / (max(v.soignants_presents, 1) * 60 * 0.84)
                downstream = v.en_attente_aval + v.en_attente_aide_domicile

                def sigmoid(logit: float, upper: float = 0.95) -> float:
                    return max(0.05, min(upper, 1 / (1 + math.exp(-max(-50.0, min(50.0, logit))))))

                q = (
                    sigmoid(-1 + 4 * (occ - 0.85) + 0.3 * v.attente_urgences_nb)
                    if v.sortants_medicaux_presents
                    else 0.0,
                    sigmoid(-2.5 + 6 * (occ - 0.95) + 0.5 * v.attente_urgences_4h_plus, 0.8),
                    sigmoid(-2 + 3 * (ratio - 1), 0.9),
                    sigmoid(-1.5 + 0.3 * downstream) if downstream else 0.0,
                )
                reason = "observed_pressure_rules_uncalibrated"
            units.append(UnitRecommendation(unit_id=row.entity_id, probabilities=q, reason=reason))
        return RecommendationBatch(
            descriptor=self.descriptor,
            decision_h=context.decision_h,
            context_sha256=context.fingerprint,
            units=tuple(units),
        )
