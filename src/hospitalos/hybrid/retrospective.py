"""As-of preparation endpoint audit; no hospital connector or real-model approval.

An observed completion of the mapped preparation task is the endpoint. Discharge,
clinical clearance and silence in an incomplete feed cannot substitute for it.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from hospitalos.operational.contract import Closed, Identifier, instant

from .preparation import PreparationFeatures
from .survival import PreparationRecord, TemporalProtocol


class PreparationEvent(Closed):
    record_id: Identifier
    event_id: Identifier
    revision: Annotated[StrictInt, Field(ge=1)] = 1
    hospital_id: Identifier
    patient_id: Identifier
    episode_id: Identifier
    source: Identifier
    kind: Literal[
        "pending",
        "completed",
        "departed",
        "cancelled",
        "eligibility_revoked",
        "death",
        "transferred",
    ]
    occurred_at: datetime
    available_at: datetime
    retracted: StrictBool = False

    @field_validator("occurred_at", "available_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def clocks(self) -> Self:
        if self.occurred_at > self.available_at:
            raise ValueError("Only observed events, with occurrence <= availability, are accepted")
        return self


class Followup(Closed):
    from_at: datetime
    through: datetime
    available_at: datetime
    complete: StrictBool

    @field_validator("from_at", "through", "available_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def clocks(self) -> Self:
        if not self.from_at <= self.through <= self.available_at:
            raise ValueError("Follow-up requires from <= through <= availability")
        return self


class Landmark(Closed):
    hospital_id: Identifier
    patient_id: Identifier
    episode_id: Identifier
    unit_id: Identifier
    source: Identifier
    mapping_version: Identifier
    provenance: Literal["synthetic_fixture", "observed_unvalidated"]
    origin: datetime
    snapshot_available_at: datetime
    eligible_at_origin: StrictBool | None
    features: PreparationFeatures
    followup: Followup | None = None

    @field_validator("origin", "snapshot_available_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def calendar(self) -> Self:
        if (
            self.features.hour_utc != self.origin.hour
            or self.features.weekday_utc != self.origin.weekday()
        ):
            raise ValueError("Calendar features must describe the origin")
        return self


class RetrospectiveBatch(Closed):
    schema_version: Literal["PREPARATION_ENDPOINT_AUDIT_1"] = "PREPARATION_ENDPOINT_AUDIT_1"
    protocol: TemporalProtocol
    landmarks: Annotated[tuple[Landmark, ...], Field(min_length=1)]
    events: tuple[PreparationEvent, ...]

    @model_validator(mode="after")
    def identities(self) -> Self:
        episodes = {(m.hospital_id, m.episode_id): m for m in self.landmarks}
        patients = {(m.hospital_id, m.patient_id) for m in self.landmarks}
        if len(episodes) != len(self.landmarks) or len(patients) != len(self.landmarks):
            raise ValueError("One landmark per patient and episode is required")
        if len({e.record_id for e in self.events}) != len(self.events):
            raise ValueError("Duplicate physical event records")
        for event in self.events:
            m = episodes.get((event.hospital_id, event.episode_id))
            if m is None or m.patient_id != event.patient_id:
                raise ValueError("Event has no matching episode/patient landmark")
        return self


class Outcome(Closed):
    landmark: Landmark
    partition: Literal["train", "calibration", "validation", "test"]
    status: Literal["completed", "right_censored"]
    followed_seconds: Annotated[float, Field(gt=0, le=86400, allow_inf_nan=False)]
    known_by: datetime
    label_cutoff: datetime
    endpoint_record_id: str | None


class Exclusion(Closed):
    hospital_id: str
    episode_id: str
    reason: str


class CohortAudit(Closed):
    schema_version: Literal["PREPARATION_COHORT_AUDIT_1"] = "PREPARATION_COHORT_AUDIT_1"
    evidence: Literal["endpoint_quality_audit_only"] = "endpoint_quality_audit_only"
    real_training_approved: Literal[False] = False
    outcomes: tuple[Outcome, ...]
    exclusions: tuple[Exclusion, ...]
    counts_by_partition: dict[str, int]
    exclusions_by_reason: dict[str, int]


def visible(
    events: tuple[PreparationEvent, ...], at: datetime, *, include_retracted: bool = False
) -> tuple[PreparationEvent, ...]:
    """Corrections after at cannot change the view; conflicting visible revisions fail."""
    groups: dict[tuple[str, str], list[PreparationEvent]] = defaultdict(list)
    for e in events:
        if e.available_at <= at:
            groups[(e.source, e.event_id)].append(e)
    result = []
    for versions in groups.values():
        if len({e.revision for e in versions}) != len(versions):
            raise ValueError("conflicting_event_revisions")
        ordered = sorted(versions, key=lambda e: e.revision)
        if any(
            a.available_at > b.available_at for a, b in zip(ordered[:-1], ordered[1:], strict=True)
        ):
            raise ValueError("nonmonotone_revision_availability")
        latest = ordered[-1]
        if not latest.retracted or include_retracted:
            result.append(latest)
    return tuple(sorted(result, key=lambda e: (e.occurred_at, e.record_id)))


def derive(
    m: Landmark, events: tuple[PreparationEvent, ...], name: str, cutoff: datetime
) -> Outcome:
    if m.snapshot_available_at > m.origin:
        raise ValueError("snapshot_unavailable_at_origin")
    if m.eligible_at_origin is not True:
        raise ValueError("eligibility_not_confirmed")
    # Filter by availability before any revision/source assessment.
    known = tuple(e for e in events if e.available_at <= cutoff)
    if any(e.source != m.source for e in known):
        raise ValueError("unexpected_event_source")
    at_origin = visible(known, m.origin)
    prior = tuple(e for e in at_origin if e.occurred_at <= m.origin)
    if not prior or prior[-1].kind != "pending" or any(e.kind != "pending" for e in prior):
        raise ValueError("pending_preparation_not_confirmed_at_origin")
    followup = m.followup
    if followup is None or not followup.complete or followup.available_at > cutoff:
        raise ValueError("continuous_followup_not_confirmed")
    if not followup.from_at <= m.origin < followup.through:
        raise ValueError("followup_does_not_cover_origin")
    end = min(followup.through, m.origin + timedelta(hours=24))
    labels = visible(known, cutoff)
    if not any(e.kind == "pending" and e.occurred_at <= m.origin for e in labels):
        raise ValueError("origin_pending_evidence_retracted")
    if any(e.kind != "pending" and e.occurred_at <= m.origin for e in labels):
        raise ValueError("late_evidence_invalidates_origin")
    # A deletion of a completion cannot be converted into an apparently negative label.
    for e in visible(known, cutoff, include_retracted=True):
        if e.retracted and e.occurred_at <= end:
            raise ValueError("retracted_event_requires_adjudication")
    completions = tuple(
        e for e in labels if e.kind == "completed" and m.origin < e.occurred_at <= end
    )
    if len(completions) > 1:
        raise ValueError("ambiguous_preparation_completion")
    target = completions[0] if completions else None
    endpoint = target.occurred_at if target else end
    competing = tuple(
        e
        for e in labels
        if e.kind not in {"pending", "completed"} and m.origin < e.occurred_at <= endpoint
    )
    if competing:
        if target is not None and all(
            e.kind == "departed" and e.occurred_at == endpoint for e in competing
        ):
            pass  # Co-timed actual departure corroborates, but never substitutes for completion.
        else:
            raise ValueError(
                "departure_without_preparation_endpoint"
                if competing[0].kind == "departed"
                else "competing_event_requires_adjudication"
            )
    return Outcome.model_validate(
        {
            "landmark": m,
            "partition": name,
            "status": "completed" if target else "right_censored",
            "followed_seconds": (endpoint - m.origin).total_seconds(),
            "known_by": max(
                followup.available_at,
                m.snapshot_available_at,
                *(e.available_at for e in labels if e.occurred_at <= endpoint),
            ),
            "label_cutoff": cutoff,
            "endpoint_record_id": target.record_id if target else None,
        }
    )


def audit(batch: RetrospectiveBatch) -> CohortAudit:
    names = ("train", "calibration", "validation", "test")
    outcomes, exclusions = [], []
    for m in sorted(batch.landmarks, key=lambda m: (m.origin, m.hospital_id, m.episode_id)):
        matches = [
            n
            for n in names
            if getattr(batch.protocol, n).start <= m.origin < getattr(batch.protocol, n).end
        ]
        if len(matches) != 1:
            raise ValueError("Landmark outside predeclared temporal windows")
        name = matches[0]
        events = tuple(
            e
            for e in batch.events
            if (e.hospital_id, e.episode_id) == (m.hospital_id, m.episode_id)
        )
        try:
            outcomes.append(
                derive(m, events, name, getattr(batch.protocol, name).labels_available_by)
            )
        except ValueError as error:
            exclusions.append(
                Exclusion(hospital_id=m.hospital_id, episode_id=m.episode_id, reason=str(error))
            )
    return CohortAudit(
        outcomes=tuple(outcomes),
        exclusions=tuple(exclusions),
        counts_by_partition={name: sum(o.partition == name for o in outcomes) for name in names},
        exclusions_by_reason=dict(Counter(e.reason for e in exclusions)),
    )


def synthetic_record(outcome: Outcome) -> PreparationRecord:
    """Test bridge only; observed data require a separately reviewed training protocol."""
    m = outcome.landmark
    if m.provenance != "synthetic_fixture":
        raise ValueError("Observed endpoint audit does not authorize real-data training")
    if outcome.followed_seconds % 60:
        raise ValueError("Subminute endpoints need an explicit discretization protocol")
    return PreparationRecord(
        episode_id=m.episode_id,
        patient_id=m.patient_id,
        hospital_id=m.hospital_id,
        unit_id=m.unit_id,
        origin=m.origin,
        features_available_at=m.snapshot_available_at,
        features=m.features,
        followed_minutes=int(outcome.followed_seconds / 60),
        event_observed=outcome.status == "completed",
        label_available_at=outcome.known_by,
    )


def demo_batch() -> RetrospectiveBatch:
    from .learning_demo import protocol, synthetic_records

    split = protocol()
    landmarks, events = [], []
    for r in synthetic_records(split, counts=(12, 4, 4, 4)):
        landmarks.append(
            Landmark(
                hospital_id=r.hospital_id,
                patient_id=r.patient_id,
                episode_id=r.episode_id,
                unit_id=r.unit_id,
                source="fictional-task-feed",
                mapping_version="fictional-v1",
                provenance="synthetic_fixture",
                origin=r.origin,
                snapshot_available_at=r.features_available_at,
                eligible_at_origin=True,
                features=r.features,
                followup=Followup(
                    from_at=r.origin,
                    through=r.origin + timedelta(minutes=r.followed_minutes),
                    available_at=r.label_available_at,
                    complete=True,
                ),
            )
        )
        pending = PreparationEvent(
            record_id=f"{r.episode_id}:pending",
            event_id=f"{r.episode_id}:pending",
            hospital_id=r.hospital_id,
            patient_id=r.patient_id,
            episode_id=r.episode_id,
            source="fictional-task-feed",
            kind="pending",
            occurred_at=r.origin,
            available_at=r.origin,
        )
        events.append(pending)
        if r.event_observed:
            events.append(
                pending.model_copy(
                    update={
                        "record_id": f"{r.episode_id}:complete",
                        "event_id": f"{r.episode_id}:complete",
                        "kind": "completed",
                        "occurred_at": r.origin + timedelta(minutes=r.followed_minutes),
                        "available_at": r.label_available_at,
                    }
                )
            )
    # One deliberately unusable endpoint demonstrates exclusion rather than relabeling.
    index = next(i for i, e in enumerate(events) if e.kind == "completed")
    events[index] = events[index].model_copy(update={"kind": "departed"})
    return RetrospectiveBatch(protocol=split, landmarks=tuple(landmarks), events=tuple(events))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Canonical JSON batch, read locally")
    source.add_argument("--demo", action="store_true")
    source.add_argument("--schema", action="store_true")
    parser.add_argument(
        "--show-input", action="store_true", help="Emit only the synthetic demo input"
    )
    args = parser.parse_args()
    if args.schema:
        print(json.dumps(RetrospectiveBatch.model_json_schema(), indent=2))
        return
    if args.show_input and not args.demo:
        parser.error("--show-input is limited to the synthetic demo")
    try:
        batch = (
            demo_batch()
            if args.demo
            else RetrospectiveBatch.model_validate_json(args.input.read_text())
        )
    except (ValueError, OSError):
        parser.error(
            "Invalid or unreadable canonical batch; inspect the local input against --schema"
        )
    if args.show_input:
        print(batch.model_dump_json(indent=2))
        return
    try:
        result = audit(batch)
    except ValueError:
        parser.error("Invalid cohort boundaries; inspect the predeclared temporal protocol")
    # CLI emits aggregate quality only, not patient-level records.
    print(json.dumps(result.model_dump(mode="json", exclude={"outcomes", "exclusions"}), indent=2))


if __name__ == "__main__":
    main()
