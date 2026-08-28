"""Deterministic, first-party synthetic temporal corpus construction."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime, timedelta

from hfwm.contracts import (
    HDB_CONTRACT_VERSION,
    HDC_CONTRACT_VERSION,
    HDBBenchmark,
    HDBPartition,
    HDCEpisode,
    HoldoutDimension,
    ProvenancePointer,
)
from hfwm.evaluation.decontamination import ContaminationRecord, audit_contamination
from hfwm.evaluation.splits import (
    Episode,
    SplitAssignment,
    assign_temporal_splits,
    create_windows,
    split_manifest,
)
from hfwm.htl import (
    HTL_CONTRACT_VERSION,
    ConstraintClass,
    HTLRegistry,
    SemanticDefinition,
    SemanticKind,
    SiteMapping,
    TransitionRule,
    ValueKind,
)
from p0d import CanonicalEvent, EventLedger, sha256_json, utc_text

from .model import (
    BUILD_CODE_VERSION,
    CORPUS_SCHEMA,
    SOURCE_ID,
    CorpusConfig,
    RecordingInterval,
    TemporalCorpus,
    json_compatible,
)

_STATE_EVENT = "hourly_unit_state_observed"
_EVENT_SCHEMA = "p0d.event.v1"
_TRANSFORMATION_VERSION = "hfwm-r0-internal-synthetic-transform.v1"


def _stable_int(*parts: object, modulus: int) -> int:
    raw = "\0".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") % modulus


def _identifier(prefix: str, *parts: object) -> str:
    normalized = "-".join(str(part).replace("_", "-") for part in parts)
    return f"{prefix}-{normalized}"


def _semantic(
    semantic_id: str,
    kind: SemanticKind,
    *,
    value_kind: ValueKind,
    unit: str | None,
    definition: str,
    constraint_class: ConstraintClass = ConstraintClass.NOT_APPLICABLE,
) -> SemanticDefinition:
    return SemanticDefinition(
        semantic_id=semantic_id,
        kind=kind,
        canonical_name=semantic_id,
        definition=definition,
        value_kind=value_kind,
        unit=unit,
        allowed_values=(),
        parent_semantic_id=None,
        constraint_class=constraint_class,
        schema_version="1",
    )


def build_htl_registry(config: CorpusConfig) -> HTLRegistry:
    """Build the canonical semantics and explicit per-pseudo-site mappings."""

    semantics = (
        _semantic(
            "event.hourly-unit-state",
            SemanticKind.EVENT,
            value_kind=ValueKind.OBJECT,
            unit=None,
            definition="An hourly operational state observation for one synthetic unit.",
        ),
        _semantic(
            "state.occupancy",
            SemanticKind.STATE,
            value_kind=ValueKind.INTEGER,
            unit="patients",
            definition="Patients occupying a synthetic unit at the end of an hour.",
        ),
        _semantic(
            "flow.inflow",
            SemanticKind.FLOW,
            value_kind=ValueKind.INTEGER,
            unit="patients/hour",
            definition="Admissions accepted by a synthetic unit during an hour.",
        ),
        _semantic(
            "flow.discharges",
            SemanticKind.FLOW,
            value_kind=ValueKind.INTEGER,
            unit="patients/hour",
            definition="Patients discharged from a synthetic unit during an hour.",
        ),
        _semantic(
            "staffing.available",
            SemanticKind.STAFFING,
            value_kind=ValueKind.INTEGER,
            unit="synthetic-staff",
            definition="Synthetic staff available during an hour.",
        ),
        _semantic(
            "state.pressure",
            SemanticKind.STATE,
            value_kind=ValueKind.INTEGER,
            unit="basis-points",
            definition="Deterministic synthetic pressure index; not a clinical measure.",
        ),
        _semantic(
            "capacity.beds",
            SemanticKind.CAPACITY,
            value_kind=ValueKind.INTEGER,
            unit="synthetic-beds",
            definition="Maximum synthetic occupancy of a unit.",
        ),
        _semantic(
            "relation.episode-assigned-to-unit",
            SemanticKind.RELATION,
            value_kind=ValueKind.REFERENCE,
            unit=None,
            definition="Associates a synthetic episode with its synthetic unit.",
        ),
        _semantic(
            "constraint.patient-conservation",
            SemanticKind.CONSTRAINT,
            value_kind=ValueKind.BOOLEAN,
            unit=None,
            definition="Occupancy equals previous occupancy plus inflow minus discharges.",
            constraint_class=ConstraintClass.HARD,
        ),
        _semantic(
            "constraint.capacity-bound",
            SemanticKind.CONSTRAINT,
            value_kind=ValueKind.BOOLEAN,
            unit=None,
            definition="Synthetic occupancy remains between zero and synthetic capacity.",
            constraint_class=ConstraintClass.HARD,
        ),
        _semantic(
            "observation-process.availability-delay",
            SemanticKind.OBSERVATION_PROCESS,
            value_kind=ValueKind.DURATION,
            unit="hours",
            definition="Delay between event time and point-in-time availability.",
        ),
        _semantic(
            "observation-process.missingness",
            SemanticKind.OBSERVATION_PROCESS,
            value_kind=ValueKind.OBJECT,
            unit=None,
            definition="Fields not emitted by the synthetic recording process.",
        ),
        _semantic(
            "observation-process.silent-source",
            SemanticKind.OBSERVATION_PROCESS,
            value_kind=ValueKind.BOOLEAN,
            unit=None,
            definition="Expected operational observation absent while a status signal remains.",
        ),
    )
    mapped_semantics = (
        "event.hourly-unit-state",
        "state.occupancy",
        "flow.inflow",
        "flow.discharges",
        "staffing.available",
        "state.pressure",
        "capacity.beds",
        "observation-process.availability-delay",
        "observation-process.missingness",
        "observation-process.silent-source",
    )
    mappings: list[SiteMapping] = []
    for organization_index in range(config.organization_count):
        for site_index in range(config.sites_per_organization):
            site_id = _identifier("synthetic-site", organization_index, site_index)
            for semantic_id in mapped_semantics:
                token = semantic_id.replace(".", "-")
                mappings.append(
                    SiteMapping(
                        mapping_id=_identifier("mapping", site_id, token),
                        mapping_version="1",
                        site_id=site_id,
                        source_system=SOURCE_ID,
                        source_schema_version="1",
                        local_code=semantic_id,
                        semantic_id=semantic_id,
                        transform_id="identity",
                        transform_parameters=(("synthetic_only", "true"),),
                        valid_from=utc_text(config.start_at),
                        valid_to=None,
                        evidence_ref="code://hfwm.corpus.generator/build_htl_registry",
                    )
                )
    rule = TransitionRule(
        rule_id="transition.hourly-unit-state",
        trigger_semantic_id="event.hourly-unit-state",
        input_state_ids=("state.occupancy", "state.pressure"),
        output_state_ids=("state.occupancy", "state.pressure"),
        relation_ids=("relation.episode-assigned-to-unit",),
        constraint_ids=("constraint.capacity-bound", "constraint.patient-conservation"),
        schema_version="1",
    )
    return HTLRegistry(
        contract_version=HTL_CONTRACT_VERSION,
        registry_version="hfwm-r0.internal-synthetic.v1",
        semantics=semantics,
        site_mappings=tuple(mappings),
        transition_rules=(rule,),
    )


def _state_payload(
    *,
    organization_id: str,
    episode_id: str,
    hour_index: int,
    capacity: int,
    occupancy: int,
    inflow: int,
    discharges: int,
    staffing: int,
    pressure_bp: int,
    missing_fields: tuple[str, ...],
    recording_regime: str,
    quality_status: str,
) -> dict[str, object]:
    return {
        "organization_id": organization_id,
        "episode_id": episode_id,
        "hour_index": hour_index,
        "capacity": capacity,
        "occupancy": occupancy,
        "inflow": inflow,
        "discharges": discharges,
        "staffing": None if "staffing" in missing_fields else staffing,
        "pressure_bp": None if "pressure_bp" in missing_fields else pressure_bp,
        "missing_fields": list(missing_fields),
        "recording_regime": recording_regime,
        "quality_status": quality_status,
        "synthetic_only": True,
    }


def _event(
    *,
    event_id: str,
    event_type: str,
    organization_id: str,
    site_id: str,
    unit_id: str,
    episode_id: str,
    event_time: datetime,
    delay_hours: int,
    payload: Mapping[str, object],
    correction_of: str | None = None,
) -> CanonicalEvent:
    available_at = event_time + timedelta(hours=delay_hours)
    return CanonicalEvent.create(
        event_id=event_id,
        event_type=event_type,
        entity_type="synthetic_unit_episode",
        entity_id=episode_id,
        source_system=SOURCE_ID,
        site_id=site_id,
        unit_id=unit_id,
        event_time=event_time,
        recorded_at=available_at,
        available_at=available_at,
        ingested_at=available_at + timedelta(minutes=5),
        schema_version=1,
        correction_of=correction_of,
        lineage=(
            f"source:{SOURCE_ID}",
            f"organization:{organization_id}",
            f"episode:{episode_id}",
            "generator:hfwm-r0-temporal-corpus-v1",
        ),
        payload=payload,
    )


def _build_event_stream(
    config: CorpusConfig,
) -> tuple[tuple[CanonicalEvent, ...], tuple[RecordingInterval, ...]]:
    events: list[CanonicalEvent] = []
    silent_intervals: list[RecordingInterval] = []
    episode_span = config.episode_hours + config.purge_gap_hours
    for organization_index in range(config.organization_count):
        organization_id = _identifier("synthetic-org", organization_index)
        for site_index in range(config.sites_per_organization):
            site_id = _identifier("synthetic-site", organization_index, site_index)
            for unit_index in range(config.units_per_site):
                unit_id = _identifier(
                    "synthetic-unit", organization_index, site_index, unit_index
                )
                for episode_index in range(config.episodes_per_unit):
                    episode_id = _identifier(
                        "synthetic-episode",
                        organization_index,
                        site_index,
                        unit_index,
                        episode_index,
                    )
                    start_at = config.start_at + timedelta(hours=episode_index * episode_span)
                    capacity = 24 + 4 * ((organization_index + site_index + unit_index) % 4)
                    occupancy = capacity // 2 + episode_index % 3
                    silent_start = max(12, min(config.episode_hours - 8, config.history_hours // 3))
                    silent_length = min(5, config.episode_hours - silent_start - 1)
                    silent_intervals.append(
                        RecordingInterval(
                            organization_id=organization_id,
                            site_id=site_id,
                            unit_id=unit_id,
                            episode_id=episode_id,
                            start_at=start_at + timedelta(hours=silent_start),
                            end_at=start_at + timedelta(hours=silent_start + silent_length),
                            expected_event_type=_STATE_EVENT,
                        )
                    )
                    for hour_index in range(config.episode_hours):
                        event_time = start_at + timedelta(hours=hour_index)
                        desired_discharges = _stable_int(
                            organization_id,
                            site_id,
                            unit_id,
                            episode_index,
                            hour_index,
                            "discharge",
                            modulus=4,
                        )
                        discharges = min(occupancy, desired_discharges)
                        desired_inflow = _stable_int(
                            organization_id,
                            site_id,
                            unit_id,
                            episode_index,
                            hour_index,
                            "inflow",
                            modulus=5,
                        )
                        inflow = min(desired_inflow, capacity - occupancy + discharges)
                        occupancy = occupancy + inflow - discharges
                        staffing = max(
                            3,
                            (occupancy + 5) // 6
                            + (1 if 7 <= event_time.hour < 19 else 0),
                        )
                        pressure_bp = min(
                            10_000,
                            (occupancy * 6_500) // capacity
                            + (inflow * 2_000) // capacity
                            + max(0, occupancy - 6 * staffing) * 200,
                        )
                        if silent_start <= hour_index < silent_start + silent_length:
                            continue
                        missing_fields: tuple[str, ...]
                        if hour_index % 43 == 11:
                            missing_fields = ("staffing",)
                        elif hour_index % 59 == 17:
                            missing_fields = ("pressure_bp",)
                        else:
                            missing_fields = ()
                        delay_hours = (
                            12
                            if hour_index % 97 == 29
                            else _stable_int(
                                organization_id,
                                unit_id,
                                episode_index,
                                hour_index,
                                "delay",
                                modulus=(
                                    5 if hour_index >= config.episode_hours // 2 else 3
                                ),
                            )
                        )
                        regime = (
                            "regime-b"
                            if hour_index >= config.episode_hours // 2
                            else "regime-a"
                        )
                        original_id = _identifier("event-state", episode_id, hour_index)
                        payload = _state_payload(
                            organization_id=organization_id,
                            episode_id=episode_id,
                            hour_index=hour_index,
                            capacity=capacity,
                            occupancy=occupancy,
                            inflow=inflow,
                            discharges=discharges,
                            staffing=staffing,
                            pressure_bp=pressure_bp,
                            missing_fields=missing_fields,
                            recording_regime=regime,
                            quality_status="original",
                        )
                        original = _event(
                            event_id=original_id,
                            event_type=_STATE_EVENT,
                            organization_id=organization_id,
                            site_id=site_id,
                            unit_id=unit_id,
                            episode_id=episode_id,
                            event_time=event_time,
                            delay_hours=delay_hours,
                            payload=payload,
                        )
                        events.append(original)
                        correction_hour = max(
                            2,
                            min(config.episode_hours - 2, silent_start - 2),
                        )
                        if hour_index == correction_hour:
                            corrected_payload = dict(payload)
                            corrected_payload["quality_status"] = "corrected"
                            corrected_payload["correction_reason"] = (
                                "synthetic-recording-quality-review"
                            )
                            correction_delay = max(delay_hours + 1, 18)
                            events.append(
                                _event(
                                    event_id=_identifier(
                                        "event-correction", episode_id, hour_index
                                    ),
                                    event_type=_STATE_EVENT,
                                    organization_id=organization_id,
                                    site_id=site_id,
                                    unit_id=unit_id,
                                    episode_id=episode_id,
                                    event_time=event_time,
                                    delay_hours=correction_delay,
                                    payload=corrected_payload,
                                    correction_of=original_id,
                                )
                            )
    return tuple(events), tuple(silent_intervals)


def _ledger_hash(events: tuple[CanonicalEvent, ...]) -> str:
    ordered = sorted(events, key=lambda event: event.replay_key())
    return sha256_json([event.manifest_record() for event in ordered])


def _validated_ledger(events: tuple[CanonicalEvent, ...]) -> EventLedger:
    """Validate append semantics in linear time before freezing the persistent value."""

    by_id: dict[str, CanonicalEvent] = {}
    identity_fields = (
        "event_type",
        "entity_type",
        "entity_id",
        "source_system",
        "site_id",
        "unit_id",
        "event_time",
    )
    for event in events:
        if event.event_id in by_id:
            raise ValueError(f"duplicate generated event_id: {event.event_id}")
        if event.correction_of is not None:
            target = by_id.get(event.correction_of)
            if target is None:
                raise ValueError("generated correction target must precede its correction")
            if any(
                getattr(event, field) != getattr(target, field) for field in identity_fields
            ):
                raise ValueError("generated correction changed immutable event identity")
            if (
                event.recorded_at < target.recorded_at
                or event.available_at < target.available_at
                or event.ingested_at < target.ingested_at
            ):
                raise ValueError("generated correction precedes its original assertion")
        by_id[event.event_id] = event
    return EventLedger(events)


def _episode_descriptors(
    config: CorpusConfig, ledger: EventLedger
) -> tuple[Episode, ...]:
    episode_events: dict[str, list[CanonicalEvent]] = {}
    for event in ledger.events:
        if not isinstance(event.payload, Mapping):
            continue
        episode_id = event.payload.get("episode_id")
        if isinstance(episode_id, str):
            episode_events.setdefault(episode_id, []).append(event)
    descriptors: list[Episode] = []
    for episode_id, events in sorted(episode_events.items()):
        first = min(events, key=lambda event: event.event_time)
        first_payload = first.payload
        if not isinstance(first_payload, Mapping):
            raise ValueError("generated event payload must be an object")
        organization_id = first_payload.get("organization_id")
        if not isinstance(organization_id, str):
            raise ValueError("generated event omitted organization_id")
        start_at = min(event.event_time for event in events)
        end_at = max(event.event_time for event in events)
        semantic = sha256_json(
            {
                "organization_id": organization_id,
                "site_id": first.site_id,
                "unit_id": first.unit_id,
                "episode_id": episode_id,
                "start_at": utc_text(start_at),
                "end_at": utc_text(end_at),
                "payload_hashes": sorted({event.payload_hash for event in events}),
            }
        )
        descriptors.append(
            Episode(
                episode_id=episode_id,
                organization_id=organization_id,
                site_id=first.site_id,
                unit_id=first.unit_id,
                start_at=start_at,
                end_at=end_at,
                semantic_hash=semantic,
                correction_family=f"correction-family:{episode_id}",
            )
        )
    expected = (
        config.organization_count
        * config.sites_per_organization
        * config.units_per_site
        * config.episodes_per_unit
    )
    if len(descriptors) != expected:
        raise ValueError("generated episode count differs from closed configuration")
    return tuple(descriptors)


def _build_hdb(
    config: CorpusConfig,
    htl: HTLRegistry,
    episodes: tuple[Episode, ...],
    assignments: tuple[SplitAssignment, ...],
) -> HDBBenchmark:
    assignment_by_id = {item.episode_id: item for item in assignments}
    partitions: list[HDBPartition] = []
    for role in ("train", "validation", "test"):
        members = tuple(
            episode
            for episode in episodes
            if assignment_by_id[episode.episode_id].split == role
        )
        if not members:
            raise ValueError(f"synthetic fixture produced an empty {role} split")
        partitions.append(
            HDBPartition(
                partition_id=f"hfwm-r0-internal-synthetic-{role}",
                role=role,
                holdout_dimensions=(HoldoutDimension.TEMPORAL,),
                organization_ids=tuple(sorted({item.organization_id for item in members})),
                site_ids=tuple(sorted({item.site_id for item in members})),
                unit_ids=tuple(sorted({item.unit_id for item in members})),
                episode_ids=tuple(sorted(item.episode_id for item in members)),
                period_start=utc_text(min(item.start_at for item in members)),
                period_end=utc_text(max(item.end_at for item in members) + timedelta(hours=1)),
                semantic_hashes=tuple(sorted({item.semantic_hash for item in members})),
                deduplication_rule_version="hfwm.semantic-dedup.v1",
                minimum_temporal_gap_hours=config.purge_gap_hours,
                transformation_versions=(_TRANSFORMATION_VERSION,),
                external_checkpoint_exposures=(),
            )
        )
    return HDBBenchmark(
        contract_version=HDB_CONTRACT_VERSION,
        benchmark_id="hfwm-r0-internal-synthetic-hdb",
        benchmark_version="1",
        htl_registry_hash=htl.semantic_hash(),
        tasks=("occupancy", "inflow", "discharges", "staffing", "pressure"),
        horizons_hours=config.horizons_hours,
        partitions=tuple(partitions),
        corruption_suites=(
            "late_arrival",
            "missing_field",
            "recording_regime_shift",
            "silent_source",
            "append_only_correction",
        ),
        anti_contamination_rules=(
            "split_before_windowing",
            "episode_disjoint",
            "correction_family_indivisible",
            "semantic_dedup",
            "near_duplicate_audit",
        ),
        split_before_windowing=True,
    )


def _build_hdc(
    config: CorpusConfig,
    ledger: EventLedger,
    ledger_hash: str,
    htl: HTLRegistry,
    episodes: tuple[Episode, ...],
    assignments: tuple[SplitAssignment, ...],
) -> tuple[HDCEpisode, ...]:
    assignment_by_id = {item.episode_id: item for item in assignments}
    events_by_episode: dict[str, list[CanonicalEvent]] = {}
    for event in ledger.events:
        if not isinstance(event.payload, Mapping):
            continue
        episode_id = event.payload.get("episode_id")
        if isinstance(episode_id, str):
            events_by_episode.setdefault(episode_id, []).append(event)
    results: list[HDCEpisode] = []
    for episode in episodes:
        episode_ledger = EventLedger(tuple(events_by_episode[episode.episode_id]))
        as_of = episode.start_at + timedelta(hours=config.history_hours)
        future_end = as_of + timedelta(hours=max(config.horizons_hours))
        history = tuple(
            event
            for event in episode_ledger.replay(as_of)
            if isinstance(event.payload, Mapping)
        )
        eventual_as_of = future_end + timedelta(hours=24)
        future = tuple(
            event
            for event in episode_ledger.replay(eventual_as_of)
            if isinstance(event.payload, Mapping)
            and as_of < event.event_time <= future_end
        )
        if not history or not future:
            raise ValueError("HDC episode lacks point-in-time history or observed future")
        source_ids = tuple(event.event_id for event in (*history, *future))
        snapshot = episode_ledger.snapshot(as_of)
        provenance = ProvenancePointer(
            ledger_ref=f"memory://{SOURCE_ID}/{ledger_hash}",
            source_event_ids=source_ids,
            source_ledger_hash=ledger_hash,
            build_code_version=BUILD_CODE_VERSION,
            schema_versions=(_EVENT_SCHEMA, HTL_CONTRACT_VERSION),
            as_of=utc_text(as_of),
        )
        results.append(
            HDCEpisode(
                contract_version=HDC_CONTRACT_VERSION,
                episode_id=episode.episode_id,
                htl_registry_hash=htl.semantic_hash(),
                snapshot_hash=snapshot.snapshot_id,
                history_event_ids=tuple(event.event_id for event in history),
                belief_state_ref=f"unmaterialized://belief/{episode.episode_id}/{utc_text(as_of)}",
                future_event_ids=tuple(event.event_id for event in future),
                context_ref=f"synthetic-context://{episode.episode_id}",
                decision_record_ids=(),
                action_record_ids=(),
                outcome_event_ids=tuple(event.event_id for event in future),
                provenance=provenance,
                partition_id=(
                    f"hfwm-r0-internal-synthetic-"
                    f"{assignment_by_id[episode.episode_id].split}"
                ),
            )
        )
    return tuple(results)


def build_contamination_records(
    episodes: tuple[Episode, ...], assignments: tuple[SplitAssignment, ...]
) -> tuple[ContaminationRecord, ...]:
    assignment_by_id = {item.episode_id: item for item in assignments}
    return tuple(
        ContaminationRecord(
            record_id=episode.episode_id,
            episode_id=episode.episode_id,
            split=assignment_by_id[episode.episode_id].split,
            correction_of=None,
            semantic_hash=episode.semantic_hash,
            semantic_text=f"{episode.episode_id} {episode.semantic_hash}",
        )
        for episode in episodes
    )


def build_temporal_corpus(config: CorpusConfig | None = None) -> TemporalCorpus:
    """Build the complete reproducible corpus without filesystem or network I/O."""

    closed_config = config or CorpusConfig()
    events, silent_intervals = _build_event_stream(closed_config)
    ledger = _validated_ledger(events)
    episodes = _episode_descriptors(closed_config, ledger)
    assignments = assign_temporal_splits(episodes)
    windows = create_windows(
        episodes,
        assignments,
        history=timedelta(hours=closed_config.history_hours),
        horizons=tuple(timedelta(hours=value) for value in closed_config.horizons_hours),
        stride=timedelta(hours=closed_config.window_stride_hours),
        purge_gap=timedelta(hours=closed_config.purge_gap_hours),
    )
    split_identity = split_manifest(assignments)
    findings = audit_contamination(build_contamination_records(episodes, assignments))
    if findings:
        raise ValueError("cross-split exact or near-duplicate contamination detected")
    htl = build_htl_registry(closed_config)
    ledger_hash = _ledger_hash(events)
    hdb = _build_hdb(closed_config, htl, episodes, assignments)
    hdc = _build_hdc(
        closed_config,
        ledger,
        ledger_hash,
        htl,
        episodes,
        assignments,
    )
    episode_hashes = [
        {
            "episode_id": episode.episode_id,
            "semantic_hash": episode.semantic_hash,
            "split": next(
                item.split for item in assignments if item.episode_id == episode.episode_id
            ),
        }
        for episode in episodes
    ]
    manifest_payload: dict[str, object] = {
        "schema": CORPUS_SCHEMA,
        "build_code_version": BUILD_CODE_VERSION,
        "source_id": SOURCE_ID,
        "source_kind": "first_party_deterministic_synthetic_fixture",
        "real_organization_count": 0,
        "pseudo_organizations_are_independent_real_organizations": False,
        "data_rights_status": "REQUIRES_PREREGISTERED_REGISTRY_AUTHORIZATION",
        "config": closed_config.to_dict(),
        "ledger_hash": ledger_hash,
        "event_count": len(events),
        "episode_count": len(episodes),
        "window_count": len(windows),
        "correction_count": sum(event.correction_of is not None for event in events),
        "late_arrival_count": sum(event.available_at > event.event_time for event in events),
        "missing_observation_count": sum(
            isinstance(event.payload, Mapping)
            and bool(event.payload.get("missing_fields", ()))
            for event in events
        ),
        "silent_interval_count": len(silent_intervals),
        "recording_regimes": ["regime-a", "regime-b"],
        "htl_registry_hash": htl.semantic_hash(),
        "split_manifest_hash": split_identity["manifest_sha256"],
        "split_before_windowing": True,
        "episode_hashes": episode_hashes,
        "hdb_hash": hdb.semantic_hash(),
        "hdc_hashes": [item.semantic_hash() for item in hdc],
        "dos_status": "NOT_APPLICABLE_NO_DECISIONS_OR_ACTIONS_OBSERVED",
        "dos_record_count": 0,
        "sas_status": "NOT_APPLICABLE_NO_BACKBONE_OR_SITE_ADAPTATION",
        "sas_release_count": 0,
        "action_conditioning_status": "ACTION_CONDITIONING_NOT_IDENTIFIABLE",
        "prohibited_claims": [
            "three_independent_real_organizations",
            "causal_effect",
            "validated_at_nantes",
            "autonomous_execution",
        ],
    }
    corpus_hash = sha256_json(manifest_payload)
    manifest = json_compatible({**manifest_payload, "corpus_hash": corpus_hash})
    return TemporalCorpus(
        config=closed_config,
        source_id=SOURCE_ID,
        events=events,
        ledger=ledger,
        episodes=episodes,
        assignments=assignments,
        windows=windows,
        silent_intervals=silent_intervals,
        htl_registry=htl,
        hdc_episodes=hdc,
        hdb_benchmark=hdb,
        dos_records=(),
        sas_releases=(),
        manifest=manifest,
        corpus_hash=corpus_hash,
    )
