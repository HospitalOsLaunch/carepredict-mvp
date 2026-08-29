"""Explicit bridge from the shared HFWM temporal corpus to the frozen baseline."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from hfwm.corpus import TemporalCorpus
from p0d import CanonicalEvent

from .model import (
    HORIZONS_HOURS,
    TARGETS,
    BaselineSplits,
    ForecastExample,
    TrajectoryPoint,
)


def _episode_id(event: CanonicalEvent) -> str | None:
    payload = event.payload
    if not isinstance(payload, Mapping):
        return None
    value = payload.get("episode_id")
    return value if isinstance(value, str) else None


def _values(event: CanonicalEvent) -> dict[str, float | None]:
    payload = event.payload
    if not isinstance(payload, Mapping):
        raise ValueError("HFWM corpus state payload must be an object")
    result: dict[str, float | None] = {}
    source_names = {
        "occupancy": "occupancy",
        "inflow": "inflow",
        "discharges": "discharges",
        "staffing": "staffing",
        "pressure": "pressure_bp",
    }
    for target, source in source_names.items():
        raw = payload.get(source)
        if raw is None:
            result[target] = None
        elif isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"corpus field {source!r} must be numeric or null")
        else:
            result[target] = float(raw)
    return result


def adapt_temporal_corpus(corpus: TemporalCorpus) -> BaselineSplits:
    """Use the corpus' frozen windows, PIT snapshots and eventual future labels.

    This function does no I/O.  History is replayed at each forecast origin while
    labels come from the eventual corrected ledger and remain in ``future_targets``.
    """

    if corpus.hdb_benchmark.tasks != TARGETS:
        raise ValueError("baseline tasks differ from the frozen HFWM benchmark")
    if corpus.hdb_benchmark.horizons_hours != HORIZONS_HOURS:
        raise ValueError("baseline horizons differ from the frozen HFWM benchmark")
    eventual = corpus.ledger.replay(
        corpus.latest_possible_availability() + timedelta(hours=1)
    )
    eventual_by_episode_and_time = {
        (_episode_id(event), event.event_time): event
        for event in eventual
        if _episode_id(event) is not None
    }
    rows: dict[str, list[ForecastExample]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    for window in corpus.windows:
        snapshot = corpus.ledger.replay(window.origin_at)
        history = tuple(
            TrajectoryPoint(
                record_id=event.event_id,
                observed_at=event.event_time,
                available_at=event.available_at,
                values=_values(event),
            )
            for event in snapshot
            if _episode_id(event) == window.episode_id
            and window.history_start_at <= event.event_time <= window.origin_at
        )
        if not history:
            raise ValueError(f"window {window.episode_id} has no point-in-time history")
        targets: dict[str, dict[int, float | None]] = {
            target: {} for target in TARGETS
        }
        for horizon in HORIZONS_HOURS:
            future = eventual_by_episode_and_time.get(
                (window.episode_id, window.origin_at + timedelta(hours=horizon))
            )
            values = _values(future) if future is not None else dict.fromkeys(TARGETS)
            for target in TARGETS:
                targets[target][horizon] = values[target]
        rows[window.split].append(
            ForecastExample(
                row_id=f"{window.episode_id}@{window.origin_at.isoformat()}",
                episode_id=window.episode_id,
                site_id=window.site_id,
                origin_at=window.origin_at,
                history=history,
                future_targets=targets,
            )
        )
    return BaselineSplits(
        train=tuple(rows["train"]),
        validation=tuple(rows["validation"]),
        test=tuple(rows["test"]),
    )
