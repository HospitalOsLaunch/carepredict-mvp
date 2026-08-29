"""Deterministic in-memory common-cohort construction from the P-0D corpus."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

import numpy as np

from hfwm.corpus import TemporalCorpus
from hfwm.evaluation.canonical import semantic_hash
from p0d import CanonicalEvent

from .contracts import (
    HORIZONS,
    TASKS,
    FloatArray,
    PreparedCohort,
    PreparedWindow,
    RunProfile,
    TrainingSiteData,
)


def prepare_common_cohort(corpus: TemporalCorpus, profile: RunProfile) -> PreparedCohort:
    """Build train arrays and one identical complete-target test cohort for all models."""
    if tuple(corpus.config.horizons_hours) != HORIZONS:
        raise ValueError("corpus horizons differ from the preregistered 6/24/72 contract")
    events_by_episode = _events_by_episode(corpus.events)
    eventual_by_episode_time = _eventual_by_episode_time(corpus)
    state_series: dict[str, tuple[FloatArray, FloatArray, FloatArray, FloatArray]] = {}
    for episode in corpus.episodes:
        state_series[episode.episode_id] = _point_in_time_episode_series(
            episode.start_at,
            episode.end_at,
            events_by_episode[episode.episode_id],
        )

    assignment_by_episode = {item.episode_id: item.split for item in corpus.assignments}
    episodes_by_site: dict[str, list[str]] = defaultdict(list)
    episode_by_id = {episode.episode_id: episode for episode in corpus.episodes}
    for episode in corpus.episodes:
        if assignment_by_episode[episode.episode_id] == "train":
            episodes_by_site[episode.site_id].append(episode.episode_id)
    training_by_site: dict[str, TrainingSiteData] = {}
    for site_id, episode_ids in sorted(episodes_by_site.items()):
        ordered_ids = sorted(episode_ids)
        values = np.stack([state_series[episode_id][0] for episode_id in ordered_ids])
        masks = np.stack([state_series[episode_id][1] for episode_id in ordered_ids])
        recording = np.stack([state_series[episode_id][2] for episode_id in ordered_ids])
        training_by_site[site_id] = TrainingSiteData(
            site_id=site_id,
            trajectories=values,
            observed_mask=masks,
            recording_process=recording,
        )
    train_iqr = _train_iqr(training_by_site)

    unit_events: dict[tuple[str, str], list[CanonicalEvent]] = defaultdict(list)
    for event in corpus.events:
        if event.event_type == "hourly_unit_state_observed":
            unit_events[(event.site_id, event.unit_id)].append(event)
    prepared_windows: list[PreparedWindow] = []
    candidate_windows = sorted(
        (window for window in corpus.windows if window.split == "test"),
        key=lambda item: (item.origin_at, item.episode_id),
    )
    for window in candidate_windows:
        episode = episode_by_id[window.episode_id]
        offset = int((window.origin_at - episode.start_at).total_seconds() // 3600)
        history_offset = int(
            (window.history_start_at - episode.start_at).total_seconds() // 3600
        )
        values, masks, recording, capacities = state_series[window.episode_id]
        if not 0 <= history_offset <= offset < values.shape[0]:
            continue
        truths: dict[int, FloatArray] = {}
        seasonal: dict[int, FloatArray] = {}
        visible_unit = _active_events_as_of(
            unit_events[(episode.site_id, episode.unit_id)], window.origin_at
        )
        complete = True
        for horizon in HORIZONS:
            target_time = window.origin_at + timedelta(hours=horizon)
            target_event = eventual_by_episode_time.get((window.episode_id, target_time))
            seasonal_event = _latest_at_or_before(
                visible_unit, target_time - timedelta(hours=168)
            )
            truth = _payload_vector(target_event.payload) if target_event is not None else None
            seasonal_value = (
                _payload_vector(seasonal_event.payload) if seasonal_event is not None else None
            )
            if truth is None or seasonal_value is None:
                complete = False
                break
            truths[horizon] = truth
            seasonal[horizon] = seasonal_value
        if not complete:
            continue
        prepared_windows.append(
            PreparedWindow(
                window_id=semantic_hash(
                    {
                        "episode_id": window.episode_id,
                        "origin_at": window.origin_at.isoformat(),
                        "horizons": list(HORIZONS),
                    }
                ),
                episode_id=window.episode_id,
                site_id=episode.site_id,
                unit_id=episode.unit_id,
                history=values[history_offset:offset].copy(),
                history_mask=masks[history_offset:offset].copy(),
                history_recording=recording[history_offset:offset].copy(),
                current=values[offset].copy(),
                current_mask=masks[offset].copy(),
                recording_process=recording[offset].copy(),
                capacity=float(capacities[offset]),
                truth_by_horizon=truths,
                seasonal_by_horizon=seasonal,
            )
        )
    if profile.max_test_windows is not None:
        prepared_windows = prepared_windows[: profile.max_test_windows]
    if not prepared_windows:
        raise ValueError("no complete common test window satisfies every model and horizon")
    cohort_payload = {
        "corpus_hash": corpus.corpus_hash,
        "source_id": corpus.source_id,
        "tasks": list(TASKS),
        "horizons": list(HORIZONS),
        "train_sites": sorted(training_by_site),
        "train_shapes": {
            site_id: list(data.trajectories.shape)
            for site_id, data in sorted(training_by_site.items())
        },
        "test_window_ids": [window.window_id for window in prepared_windows],
        "train_iqr": train_iqr.tolist(),
    }
    return PreparedCohort(
        corpus_hash=corpus.corpus_hash,
        cohort_hash=semantic_hash(cohort_payload),
        source_id=corpus.source_id,
        training_by_site=training_by_site,
        test_windows=tuple(prepared_windows),
        train_iqr=train_iqr,
    )


def _events_by_episode(
    events: Sequence[CanonicalEvent],
) -> dict[str, list[CanonicalEvent]]:
    result: dict[str, list[CanonicalEvent]] = defaultdict(list)
    for event in events:
        if event.event_type != "hourly_unit_state_observed" or not isinstance(
            event.payload, Mapping
        ):
            continue
        episode_id = event.payload.get("episode_id")
        if isinstance(episode_id, str):
            result[episode_id].append(event)
    return result


def _eventual_by_episode_time(
    corpus: TemporalCorpus,
) -> dict[tuple[str, datetime], CanonicalEvent]:
    eventual = corpus.ledger.replay(corpus.latest_possible_availability() + timedelta(hours=1))
    result: dict[tuple[str, datetime], CanonicalEvent] = {}
    for episode_id, events in _events_by_episode(eventual).items():
        for event in events:
            result[(episode_id, event.event_time)] = event
    return result


def _active_events_as_of(
    events: Sequence[CanonicalEvent], as_of: datetime
) -> dict[datetime, CanonicalEvent]:
    active_by_id: dict[str, CanonicalEvent] = {}
    for event in sorted(events, key=lambda item: (item.available_at, item.replay_key())):
        if event.available_at > as_of:
            break
        if event.correction_of is not None:
            active_by_id.pop(event.correction_of, None)
        active_by_id[event.event_id] = event
    return {
        event.event_time: event
        for event in sorted(active_by_id.values(), key=lambda item: item.replay_key())
        if event.event_time <= as_of
    }


def _latest_at_or_before(
    events_by_time: Mapping[datetime, CanonicalEvent], instant: datetime
) -> CanonicalEvent | None:
    eligible = [event for event_time, event in events_by_time.items() if event_time <= instant]
    return max(eligible, key=lambda item: item.replay_key()) if eligible else None


def _point_in_time_episode_series(
    start_at: datetime,
    end_at: datetime,
    events: Sequence[CanonicalEvent],
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    steps = int((end_at - start_at).total_seconds() // 3600) + 1
    values = np.zeros((steps, len(TASKS)), dtype=np.float64)
    masks = np.zeros_like(values)
    recording = np.zeros((steps, 2), dtype=np.float64)
    capacities = np.zeros(steps, dtype=np.float64)
    ordered = sorted(events, key=lambda item: (item.available_at, item.replay_key()))
    active: dict[str, CanonicalEvent] = {}
    cursor = 0
    previous = np.zeros(len(TASKS), dtype=np.float64)
    previous_capacity = 0.0
    for step in range(steps):
        as_of = start_at + timedelta(hours=step)
        while cursor < len(ordered) and ordered[cursor].available_at <= as_of:
            event = ordered[cursor]
            if event.correction_of is not None:
                active.pop(event.correction_of, None)
            active[event.event_id] = event
            cursor += 1
        visible = [event for event in active.values() if event.event_time <= as_of]
        latest = max(visible, key=lambda item: item.replay_key()) if visible else None
        if latest is None:
            values[step] = previous
            capacities[step] = previous_capacity
            continue
        vector, mask = _payload_vector_with_mask(latest.payload)
        current = np.where(mask > 0.0, vector, previous)
        values[step] = current
        masks[step] = mask
        delay = (latest.available_at - latest.event_time).total_seconds() / 3600.0
        recording[step] = [max(0.0, delay), float(np.mean(1.0 - mask))]
        capacity = _payload_number(latest.payload, "capacity")
        capacities[step] = capacity if capacity is not None else previous_capacity
        previous = current
        previous_capacity = capacities[step]
    return values, masks, recording, capacities


def _payload_vector(payload: object) -> FloatArray | None:
    vector, mask = _payload_vector_with_mask(payload)
    return vector if np.all(mask == 1.0) else None


def _payload_vector_with_mask(payload: object) -> tuple[FloatArray, FloatArray]:
    if not isinstance(payload, Mapping):
        return np.zeros(len(TASKS), dtype=np.float64), np.zeros(len(TASKS), dtype=np.float64)
    raw_values = (
        payload.get("occupancy"),
        payload.get("inflow"),
        payload.get("discharges"),
        payload.get("staffing"),
        (
            float(payload["pressure_bp"]) / 10_000.0
            if isinstance(payload.get("pressure_bp"), (int, float))
            and not isinstance(payload.get("pressure_bp"), bool)
            else None
        ),
    )
    converted: list[float] = []
    observed: list[float] = []
    for value in raw_values:
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and np.isfinite(float(value))
        ):
            converted.append(float(value))
            observed.append(1.0)
        else:
            converted.append(0.0)
            observed.append(0.0)
    mask = np.asarray(observed, dtype=np.float64)
    vector = np.asarray(converted, dtype=np.float64)
    return vector, mask


def _payload_number(payload: object, key: str) -> float | None:
    if not isinstance(payload, Mapping):
        return None
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if np.isfinite(number) else None


def _train_iqr(training_by_site: Mapping[str, TrainingSiteData]) -> FloatArray:
    per_feature: list[list[float]] = [[] for _ in TASKS]
    for data in training_by_site.values():
        for feature in range(len(TASKS)):
            selected = data.observed_mask[:, :, feature] > 0.0
            per_feature[feature].extend(data.trajectories[:, :, feature][selected].tolist())
    iqr = np.asarray(
        [
            float(np.quantile(values, 0.75) - np.quantile(values, 0.25)) if values else 0.0
            for values in per_feature
        ],
        dtype=np.float64,
    )
    if np.any(iqr <= 0.0) or not np.all(np.isfinite(iqr)):
        raise ValueError("train-only IQR is zero/non-finite for at least one preregistered task")
    return iqr
