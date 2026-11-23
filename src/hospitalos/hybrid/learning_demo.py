"""Reproducible synthetic preparation experiment; prints results, writes no artifacts.

The generator emits discrete preparation completion times, never a total stay.
It is a plumbing/estimation experiment, not a hospital-effectiveness benchmark.
"""

from __future__ import annotations

import json
import math
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from .demo import pathway_request
from .planning import PlanRequest
from .preparation import EDGES, PreparationFeatures
from .survival import (
    Partitions,
    PreparationRecord,
    Selection,
    TemporalProtocol,
    Window,
    evaluate,
    forecast_preparation,
    partition,
    select_model,
)


def protocol() -> TemporalProtocol:
    origin = datetime(2026, 9, 1, tzinfo=UTC)

    def window(start: int, end: int) -> Window:
        return Window(
            start=origin + timedelta(days=start),
            end=origin + timedelta(days=end),
            labels_available_by=origin + timedelta(days=end + 1),
        )

    return TemporalProtocol(
        train=window(0, 14),
        calibration=window(16, 19),
        validation=window(21, 24),
        test=window(26, 29),
    )


def synthetic_records(
    split: TemporalProtocol,
    *,
    counts: tuple[int, int, int, int] = (600, 200, 200, 300),
    seed: int = 20261024,
) -> tuple[PreparationRecord, ...]:
    """Independent context/outcome/censoring RNG streams; no latent truth in features.

    Event times lie on EDGES. Censoring is independent of context and event time;
    this makes the marginal IPCW assumption appropriate for this fixture only.
    """
    if any(n < 1 for n in counts):
        raise ValueError("Each synthetic partition needs at least one record")
    context, outcome, censoring = (random.Random(seed + i) for i in range(3))
    records = []
    for name, count in zip(("train", "calibration", "validation", "test"), counts, strict=True):
        window = getattr(split, name)
        span = int((window.end - window.start).total_seconds() // 60)
        for i in range(count):
            at = window.start + timedelta(minutes=context.randrange(span))
            features = PreparationFeatures(
                occupied_per_staffed_bed=context.choice((0.3, 0.6, 0.9, 1.2, 1.5)),
                waiting_per_staffed_bed=context.choice((0.0, 0.5, 1.0, 1.5)),
                hour_utc=at.hour,
                weekday_utc=at.weekday(),
            )
            completion = 1441
            for j, edge in enumerate(EDGES):
                logit = (
                    -0.8
                    + 0.18 * j
                    - 2.0 * (features.occupied_per_staffed_bed - 0.8)
                    - 0.7 * features.waiting_per_staffed_bed
                    + 0.3 * math.sin(2 * math.pi * at.hour / 24)
                )
                if outcome.random() < 1 / (1 + math.exp(-logit)):
                    completion = edge
                    break
            followup = censoring.choice((90, 180, 300, 600, 1440, 1440, 1440))
            observed = completion <= followup
            records.append(
                PreparationRecord(
                    episode_id=f"synthetic-{name}-{i}",
                    patient_id=f"synthetic-{name}-{i}",
                    hospital_id="fictional-hospital",
                    unit_id="medicine",
                    origin=at,
                    features_available_at=at,
                    features=features,
                    followed_minutes=min(completion, followup),
                    event_observed=observed,
                    label_available_at=at + timedelta(days=1),
                )
            )
    return tuple(records)


def train_demo() -> tuple[Selection, Partitions]:
    split = protocol()
    data = partition(synthetic_records(split), split)
    selection = select_model(data.train, data.calibration, data.validation, split)
    return selection, data


def experiment_report(selection: Selection, data: Partitions) -> dict[str, Any]:
    # The model selection is already locked before any test metrics are computed.
    return {
        "status": "synthetic_research_only",
        "target": "residual_preparation_before_resource_queue",
        "protocol": protocol().model_dump(mode="json"),
        "counts": {
            name: len(getattr(data, name))
            for name in ("train", "calibration", "validation", "test")
        },
        "selection_rule": "lowest_validation_interval_nll; pooled_hazard_wins_ties",
        "selected": selection.selected.name,
        "model_id": selection.selected.model_id,
        "model_available_at": selection.selected.available_at.isoformat(),
        "calibration_logit_offsets": {m.name: m.offset for m in selection.candidates},
        "validation": selection.validation,
        "test": {m.name: evaluate(m, data.test, selection.censoring) for m in selection.candidates},
        "limitations": [
            "single_fictional_site_unit_and_generator",
            "one_origin_per_patient",
            "independent_censoring_assumed",
            "no_real_calibration_or_clinical_gain_established",
            "no_prediction_of_medical_clearance_or_competing_risks",
            "remaining_transport_cleaning_and_arrivals_are_hypotheses",
        ],
    }


def learned_request() -> PlanRequest:
    selection, _ = train_demo()
    request = pathway_request()
    forecasts = forecast_preparation(selection.selected, request.state())
    return PlanRequest.model_validate({**request.model_dump(), "preparation": forecasts})


def main() -> None:
    selection, data = train_demo()
    print(json.dumps(experiment_report(selection, data), indent=2))


if __name__ == "__main__":
    main()
