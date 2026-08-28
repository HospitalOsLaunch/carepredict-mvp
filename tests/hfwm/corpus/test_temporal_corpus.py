from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta

import pytest

from hfwm.contracts import HDBBenchmark, HDCEpisode, parse_json_bytes
from hfwm.corpus import (
    SOURCE_ID,
    CorpusConfig,
    TemporalCorpus,
    build_contamination_records,
    build_temporal_corpus,
)
from hfwm.evaluation.decontamination import audit_contamination
from hfwm.htl import HTLRegistry
from p0d import CanonicalEvent


@pytest.fixture(scope="module")
def config() -> CorpusConfig:
    return CorpusConfig(
        organization_count=3,
        episodes_per_unit=4,
        episode_hours=96,
        history_hours=20,
        horizons_hours=(6, 24),
        purge_gap_hours=24,
        window_stride_hours=6,
    )


@pytest.fixture(scope="module")
def corpus(config: CorpusConfig) -> TemporalCorpus:
    return build_temporal_corpus(config)


def _episode_id(event_payload: object) -> str:
    assert isinstance(event_payload, Mapping)
    value = event_payload.get("episode_id")
    assert isinstance(value, str)
    return value


def _payload(event: CanonicalEvent) -> Mapping[str, object]:
    assert isinstance(event.payload, Mapping)
    return event.payload


def test_source_identity_scope_and_contract_round_trips(corpus: TemporalCorpus) -> None:
    assert corpus.source_id == SOURCE_ID == "hfwm_r0_internal_synthetic_fixture"
    assert {episode.organization_id for episode in corpus.episodes} == {
        "synthetic-org-0",
        "synthetic-org-1",
        "synthetic-org-2",
    }
    assert corpus.manifest["real_organization_count"] == 0
    assert corpus.manifest["pseudo_organizations_are_independent_real_organizations"] is False
    assert corpus.manifest["source_kind"] == "first_party_deterministic_synthetic_fixture"
    assert HTLRegistry.from_dict(parse_json_bytes(corpus.htl_registry.to_json_bytes())) == (
        corpus.htl_registry
    )
    assert HDBBenchmark.from_dict(
        parse_json_bytes(corpus.hdb_benchmark.to_json_bytes())
    ) == corpus.hdb_benchmark
    assert all(
        HDCEpisode.from_dict(parse_json_bytes(episode.to_json_bytes())) == episode
        for episode in corpus.hdc_episodes
    )


def test_build_is_byte_deterministic(config: CorpusConfig, corpus: TemporalCorpus) -> None:
    rebuilt = build_temporal_corpus(config)

    assert rebuilt.corpus_hash == corpus.corpus_hash
    assert rebuilt.manifest == corpus.manifest
    assert rebuilt.htl_registry.semantic_hash() == corpus.htl_registry.semantic_hash()
    assert rebuilt.hdb_benchmark.semantic_hash() == corpus.hdb_benchmark.semantic_hash()
    assert [event.payload_hash for event in rebuilt.events] == [
        event.payload_hash for event in corpus.events
    ]
    assert [episode.semantic_hash() for episode in rebuilt.hdc_episodes] == [
        episode.semantic_hash() for episode in corpus.hdc_episodes
    ]


def test_patient_conservation_and_capacity_between_consecutive_observations(
    corpus: TemporalCorpus,
) -> None:
    eventual = corpus.ledger.replay(corpus.latest_possible_availability() + timedelta(hours=1))
    by_episode: dict[str, list[CanonicalEvent]] = {}
    for event in eventual:
        if event.event_type != "hourly_unit_state_observed":
            continue
        by_episode.setdefault(_episode_id(event.payload), []).append(event)

    checked = 0
    for events in by_episode.values():
        ordered = sorted(events, key=lambda item: item.event_time)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            previous_payload = previous.payload
            current_payload = current.payload
            assert isinstance(previous_payload, Mapping)
            assert isinstance(current_payload, Mapping)
            occupancy = current_payload["occupancy"]
            capacity = current_payload["capacity"]
            assert isinstance(occupancy, int)
            assert isinstance(capacity, int)
            assert 0 <= occupancy <= capacity
            previous_hour = previous_payload["hour_index"]
            current_hour = current_payload["hour_index"]
            assert isinstance(previous_hour, int)
            assert isinstance(current_hour, int)
            if current_hour != previous_hour + 1:
                continue
            previous_occupancy = previous_payload["occupancy"]
            inflow = current_payload["inflow"]
            discharges = current_payload["discharges"]
            assert isinstance(previous_occupancy, int)
            assert isinstance(inflow, int)
            assert isinstance(discharges, int)
            assert occupancy == previous_occupancy + inflow - discharges
            checked += 1
    assert checked > 100


def test_snapshots_exclude_late_arrivals_and_future_facts(corpus: TemporalCorpus) -> None:
    late = next(
        event
        for event in corpus.events
        if event.available_at - event.event_time == timedelta(hours=12)
        and event.correction_of is None
    )
    before = corpus.snapshot(late.available_at - timedelta(seconds=1))
    at_availability = corpus.snapshot(late.available_at)

    assert late.event_id not in {event.event_id for event in before.events}
    assert late.event_id in {event.event_id for event in at_availability.events}
    assert all(event.available_at <= before.as_of for event in before.events)
    assert all(event.event_time <= before.as_of for event in before.events)

    for hdc in corpus.hdc_episodes:
        by_id = {event.event_id: event for event in corpus.events}
        as_of = datetime.fromisoformat(hdc.provenance.as_of.replace("Z", "+00:00"))
        assert all(
            by_id[event_id].event_time <= as_of and by_id[event_id].available_at <= as_of
            for event_id in hdc.history_event_ids
        )
        assert all(by_id[event_id].event_time > as_of for event_id in hdc.future_event_ids)


def test_append_only_correction_changes_replay_only_when_available(
    corpus: TemporalCorpus,
) -> None:
    correction = next(event for event in corpus.events if event.correction_of is not None)
    assert correction.correction_of is not None
    just_before = corpus.ledger.replay(correction.available_at - timedelta(seconds=1))
    at_correction = corpus.ledger.replay(correction.available_at)

    assert correction.correction_of in {event.event_id for event in just_before}
    assert correction.event_id not in {event.event_id for event in just_before}
    assert correction.correction_of not in {event.event_id for event in at_correction}
    assert correction.event_id in {event.event_id for event in at_correction}
    assert correction in corpus.ledger.events


def test_missingness_silence_and_recording_shift_are_observed_not_imputed(
    corpus: TemporalCorpus,
) -> None:
    state_events = tuple(
        event for event in corpus.events if event.event_type == "hourly_unit_state_observed"
    )
    assert any(_payload(event).get("missing_fields") == ("staffing",) for event in state_events)
    assert any(
        _payload(event).get("missing_fields") == ("pressure_bp",) for event in state_events
    )
    assert all(
        _payload(event).get("staffing") is None
        for event in state_events
        if _payload(event).get("missing_fields") == ("staffing",)
    )
    assert all(
        _payload(event).get("pressure_bp") is None
        for event in state_events
        if _payload(event).get("missing_fields") == ("pressure_bp",)
    )
    assert {_payload(event).get("recording_regime") for event in state_events} == {
        "regime-a",
        "regime-b",
    }
    mean_delay: dict[str, float] = {}
    for regime in ("regime-a", "regime-b"):
        delays = tuple(
            (event.available_at - event.event_time).total_seconds()
            for event in state_events
            if event.correction_of is None
            and _payload(event).get("recording_regime") == regime
        )
        mean_delay[regime] = sum(delays) / len(delays)
    assert mean_delay["regime-b"] > mean_delay["regime-a"]
    silent_count = corpus.manifest["silent_interval_count"]
    assert isinstance(silent_count, int)
    assert len(corpus.silent_intervals) == silent_count
    for interval in corpus.silent_intervals:
        assert not any(
            event.site_id == interval.site_id
            and event.unit_id == interval.unit_id
            and _episode_id(event.payload) == interval.episode_id
            and interval.start_at <= event.event_time < interval.end_at
            for event in corpus.events
        )


def test_splits_are_frozen_before_windows_and_near_duplicates_are_contained(
    corpus: TemporalCorpus,
) -> None:
    split_by_episode = {item.episode_id: item.split for item in corpus.assignments}
    group_splits: dict[str, set[str]] = {}
    for assignment in corpus.assignments:
        group_splits.setdefault(assignment.group_id, set()).add(assignment.split)

    assert set(split_by_episode.values()) == {"train", "validation", "test"}
    assert all(len(splits) == 1 for splits in group_splits.values())
    assert all(window.split == split_by_episode[window.episode_id] for window in corpus.windows)
    assert audit_contamination(
        build_contamination_records(corpus.episodes, corpus.assignments)
    ) == ()
    assert corpus.hdb_benchmark.split_before_windowing is True


def test_manifest_and_semantic_hashes_change_with_semantics(
    config: CorpusConfig, corpus: TemporalCorpus
) -> None:
    changed = build_temporal_corpus(
        CorpusConfig(
            organization_count=config.organization_count,
            episodes_per_unit=config.episodes_per_unit,
            episode_hours=config.episode_hours + 1,
            history_hours=config.history_hours,
            horizons_hours=config.horizons_hours,
            purge_gap_hours=config.purge_gap_hours,
            window_stride_hours=config.window_stride_hours,
        )
    )

    assert corpus.manifest["corpus_hash"] == corpus.corpus_hash
    assert corpus.manifest["ledger_hash"] != changed.manifest["ledger_hash"]
    assert corpus.corpus_hash != changed.corpus_hash
    assert len(corpus.corpus_hash) == 64


def test_no_decision_action_execution_or_adaptation_is_inferred(
    corpus: TemporalCorpus,
) -> None:
    forbidden_payload_keys = {
        "action",
        "decision",
        "dose",
        "execution",
        "human_choice",
        "timing",
    }
    assert corpus.dos_records == ()
    assert corpus.sas_releases == ()
    assert all(episode.decision_record_ids == () for episode in corpus.hdc_episodes)
    assert all(episode.action_record_ids == () for episode in corpus.hdc_episodes)
    assert all(
        forbidden_payload_keys.isdisjoint(_payload(event).keys()) for event in corpus.events
    )
    assert corpus.manifest["action_conditioning_status"] == (
        "ACTION_CONDITIONING_NOT_IDENTIFIABLE"
    )
