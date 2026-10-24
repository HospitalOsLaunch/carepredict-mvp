"""Research-only distribution mixture, delayed feedback, and decision guard.

The supervisor uses frozen predictions and matured labels, never generator regime
names or oracle losses. Its operating thresholds are empirical, not safety bounds.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator

from hospitalos.operational.contract import Closed, Identifier, instant

from .models import Action
from .planning import Plan
from .preparation import EDGES, PreparationCurve, PreparationForecasts
from .survival import PreparationRecord, observed_cells


def mix_curve(
    reference: PreparationCurve, challenger: PreparationCurve, alpha: float
) -> PreparationCurve:
    if reference.patient_id != challenger.patient_id or not 0 <= alpha <= 1:
        raise ValueError("Mixture requires matching patients and alpha in [0,1]")
    return PreparationCurve(
        patient_id=reference.patient_id,
        mass=tuple(
            (1 - alpha) * a + alpha * b
            for a, b in zip(reference.mass, challenger.mass, strict=True)
        ),
        beyond_24h=(1 - alpha) * reference.beyond_24h + alpha * challenger.beyond_24h,
    )


def mix_forecasts(
    reference: PreparationForecasts,
    challenger: PreparationForecasts,
    alpha: float,
    weight_available_at: datetime,
) -> PreparationForecasts:
    weight_available_at = instant(weight_available_at)
    keys = ("hospital_id", "origin", "state_fingerprint", "target", "evidence")
    if any(getattr(reference, k) != getattr(challenger, k) for k in keys):
        raise ValueError("Forecasts must describe the same state and origin")
    ref, other = (
        {c.patient_id: c for c in reference.curves},
        {c.patient_id: c for c in challenger.curves},
    )
    if ref.keys() != other.keys() or not 0 <= alpha <= 1:
        raise ValueError("Forecast coverage/weight mismatch")
    available = max(
        reference.model_available_at, challenger.model_available_at, weight_available_at
    )
    identity = hashlib.sha256(
        json.dumps(
            {
                "schema": "preparation-mixture-v1",
                "reference": reference.model_id,
                "challenger": challenger.model_id,
                "alpha": alpha,
                "weight_available_at": weight_available_at.isoformat(),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return PreparationForecasts(
        model_id=identity,
        hospital_id=reference.hospital_id,
        origin=reference.origin,
        state_fingerprint=reference.state_fingerprint,
        model_available_at=available,
        curves=tuple(mix_curve(ref[pid], other[pid], alpha) for pid in sorted(ref)),
    )


def curve_loss(curve: PreparationCurve, record: PreparationRecord) -> float:
    """Censored log loss of the mixture distribution, not a mixture of log losses."""
    if curve.patient_id != record.patient_id:
        raise ValueError("Prediction/label patient mismatch")
    if record.event_observed:
        index = next(i for i, t in enumerate(EDGES) if record.followed_minutes <= t)
        probability = curve.mass[index]
    else:
        probability = curve.beyond_24h + sum(
            p for t, p in zip(EDGES, curve.mass, strict=True) if t > record.followed_minutes
        )
    return -math.log(max(probability, 1e-12))


class MixtureSettings(Closed):
    schema_version: Literal["PREPARATION_GUARD_RESEARCH_1"] = "PREPARATION_GUARD_RESEARCH_1"
    reference_model_id: str
    challenger_model_id: str
    hospital_id: Identifier
    unit_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    alpha: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    available_at: datetime
    min_feedback: Annotated[StrictInt, Field(ge=2)] = 12
    feedback_window: Annotated[StrictInt, Field(ge=2)] = 24
    paired_loss_limit: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    reference_loss_limit: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    # Synthetic operating point; needs business validation before operational use.
    regret_budget_patient_minutes: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 30

    @field_validator("available_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def window_size(self) -> Self:
        if self.min_feedback > self.feedback_window:
            raise ValueError("Feedback window smaller than minimum evidence")
        return self


@dataclass(frozen=True)
class Feedback:
    record: PreparationRecord
    reference: PreparationCurve
    issued: PreparationCurve  # Frozen shadow candidate, even while serving the reference.


class Supervisor:
    def __init__(self, settings: MixtureSettings):
        self.settings = settings
        self.clock = settings.available_at
        self.history: list[tuple[float, float]] = []
        self.seen: set[tuple[str, str]] = set()
        self.fallback_at: datetime | None = None
        self.suspended_at: datetime | None = None

    def advance(self, at: datetime) -> None:
        at = instant(at)
        if at < self.clock:
            raise ValueError("Supervisor clock cannot move backwards")
        self.clock = at

    def observe(self, feedback: Feedback, at: datetime) -> None:
        at = instant(at)
        r = feedback.record
        if r.hospital_id != self.settings.hospital_id or r.unit_id not in self.settings.unit_ids:
            raise ValueError("Feedback outside the configured hospital/unit scope")
        if r.label_available_at > at or r.origin < self.settings.available_at:
            raise ValueError("Feedback unavailable or predates the locked strategy")
        key = (r.hospital_id, r.patient_id)
        if key in self.seen:
            raise ValueError("Duplicate feedback patient")
        ref_loss, issued_loss = curve_loss(feedback.reference, r), curve_loss(feedback.issued, r)
        self.advance(at)
        self.seen.add(key)
        if not observed_cells(r):
            return
        self.history.append((issued_loss - ref_loss, ref_loss))
        recent = self.history[-self.settings.feedback_window :]
        if len(recent) < self.settings.min_feedback:
            return
        if (
            statistics.mean(v[0] for v in recent) > self.settings.paired_loss_limit
            and self.fallback_at is None
        ):
            self.fallback_at = at
        if (
            statistics.mean(v[1] for v in recent) > self.settings.reference_loss_limit
            and self.suspended_at is None
        ):
            self.suspended_at = at

    def alpha_at(self, at: datetime) -> float:
        self.advance(at)
        return 0.0 if self.fallback_at is not None else self.settings.alpha


@dataclass(frozen=True)
class GuardedChoice:
    action: Action
    mode: Literal["recommend", "no_change", "fallback_reference", "abstain"]
    reason: str
    alpha: float


def guard_choice(
    reference: Plan, challenger: Plan, mixture: Plan, supervisor: Supervisor
) -> GuardedChoice:
    settings = supervisor.settings
    keys = (
        "hospital_id",
        "state_fingerprint",
        "created_at",
        "seed",
        "scenarios",
        "horizon_minutes",
        "tail_weight",
        "assumptions",
        "future",
    )
    if any(
        getattr(reference, k) != getattr(other, k) for other in (challenger, mixture) for k in keys
    ):
        raise ValueError("Guard comparison requires paired plans")
    if (
        reference.preparation is None
        or challenger.preparation is None
        or mixture.preparation is None
    ):
        raise ValueError("Explicit forecast bundles required")
    if (
        reference.preparation.model_id != settings.reference_model_id
        or challenger.preparation.model_id != settings.challenger_model_id
    ):
        raise ValueError("Models differ from the locked settings")
    alpha = supervisor.alpha_at(reference.created_at)
    if reference.hospital_id != settings.hospital_id:
        raise ValueError("Guard outside configured hospital")
    expected = mix_forecasts(
        reference.preparation,
        challenger.preparation,
        alpha,
        supervisor.fallback_at or settings.available_at,
    )
    if mixture.preparation != expected:
        raise ValueError("Mixture does not match the current locked or supervised weight")
    if supervisor.suspended_at is not None:
        return GuardedChoice(
            Action(kind="no_op"), "abstain", "reference_performance_alarm_requires_review", alpha
        )
    if any(
        p.decision == "abstain" or p.candidates_truncated for p in (reference, challenger, mixture)
    ):
        return GuardedChoice(Action(kind="no_op"), "abstain", "unusable_or_truncated_plan", alpha)
    if supervisor.fallback_at is not None:
        return GuardedChoice(
            reference.selected, "fallback_reference", "matured_paired_loss_alarm", alpha
        )

    def assess(action: Action) -> tuple[bool, float]:
        regret = 0.0
        for p in (reference, challenger):
            match = next((c for c in p.candidates if c.action == action), None)
            baseline = next(c for c in p.candidates if c.action.kind == "no_op")
            valid = [
                c for c in p.candidates if not c.violations and not c.pressure_regression_scenarios
            ]
            if (
                match is None
                or match.violations
                or match.pressure_regression_scenarios
                or match.objective > baseline.objective
            ):
                return False, math.inf
            regret = max(regret, match.objective - min(c.objective for c in valid))
        return True, regret

    valid, regret = assess(mixture.selected)
    if valid and regret <= settings.regret_budget_patient_minutes:
        return GuardedChoice(
            mixture.selected,
            "no_change" if mixture.selected.kind == "no_op" else "recommend",
            "bounded_model_disagreement",
            alpha,
        )
    # Keep a beneficial reference action if both models support its gain over no-op.
    # This fallback is not a worst-case optimality or real-world safety certificate.
    if assess(reference.selected)[0]:
        return GuardedChoice(reference.selected, "fallback_reference", "model_disagreement", alpha)
    return GuardedChoice(Action(kind="no_op"), "abstain", "no_shared_predicted_benefit", alpha)
