"""Local single-unit live-observation and shadow contracts; no SI authorization."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator

from hospitalos.operational.contract import Closed, Identifier, instant

from .models import FactEvent, State
from .planning import Plan
from .simulation import Assumptions

Resource = Literal["staffed", "cleaning", "transport", "downstream"]


class LivePolicy(Closed):
    schema_version: Literal["LIVE_UNIT_POLICY_1"] = "LIVE_UNIT_POLICY_1"
    hospital_id: Identifier
    unit_id: Identifier
    sources: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    mode: Literal["shadow", "sandbox"] = "shadow"
    # Research operating points; the pilot must define and approve its own values.
    fact_ttl_seconds: Annotated[StrictInt, Field(ge=1, le=3600)] = 300
    resource_ttl_seconds: Annotated[StrictInt, Field(ge=1, le=3600)] = 120
    proposal_ttl_seconds: Annotated[StrictInt, Field(ge=1, le=900)] = 120
    hold_ttl_seconds: Annotated[StrictInt, Field(ge=1, le=300)] = 60

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("Duplicate source")
        return self


class Availability(Closed):
    resource: Resource
    target_id: Identifier
    available: Annotated[StrictInt, Field(ge=0)] | None
    source: Identifier
    observed_at: datetime
    evidence_ref: Identifier

    @field_validator("observed_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)

    @property
    def key(self) -> str:
        return f"{self.resource}:{self.target_id}"


class ObservationBatch(Closed):
    schema_version: Literal["LIVE_OBSERVATION_BATCH_1"] = "LIVE_OBSERVATION_BATCH_1"
    batch_id: Identifier
    hospital_id: Identifier
    source: Identifier
    manifest_version: Annotated[StrictInt, Field(ge=1)]
    expected_entities: Annotated[tuple[str, ...], Field(min_length=1, max_length=400)]
    events: Annotated[tuple[FactEvent, ...], Field(max_length=2000)] = ()
    availability: Annotated[tuple[Availability, ...], Field(max_length=100)] = ()

    @model_validator(mode="after")
    def identities(self) -> Self:
        if len(set(self.expected_entities)) != len(self.expected_entities):
            raise ValueError("Duplicate manifest entity")
        if any(e.hospital_id != self.hospital_id or e.source != self.source for e in self.events):
            raise ValueError("Batch hospital/source mismatch")
        if any(a.source != self.source for a in self.availability):
            raise ValueError("Availability source mismatch")
        if len({a.key for a in self.availability}) != len(self.availability):
            raise ValueError("Duplicate resource confirmation")
        return self


class ResourceBudget(Closed):
    key: str
    observed_available: int | None
    held: int
    remaining: int | None
    observations: tuple[Availability, ...]
    issues: tuple[str, ...]


class LiveSnapshot(Closed):
    schema_version: Literal["LIVE_UNIT_SNAPSHOT_1"] = "LIVE_UNIT_SNAPSHOT_1"
    mode: Literal["shadow", "sandbox"]
    state: State
    manifest_version: int
    expected_entities: tuple[str, ...]
    events: tuple[FactEvent, ...]
    resources: tuple[ResourceBudget, ...]
    received_at_by_source: dict[str, str]
    semantic_fingerprint: str
    policy_fingerprint: str
    issues: tuple[str, ...]
    warnings: tuple[str, ...]


class PlanningOptions(Closed):
    assumptions: Assumptions = Assumptions()
    horizon_minutes: Annotated[StrictInt, Field(ge=1, le=1440)] = 360
    scenarios: Annotated[StrictInt, Field(ge=1, le=128)] = 32
    seed: Annotated[StrictInt, Field(ge=0)] = 7


class Assessment(Closed):
    schema_version: Literal["LIVE_ASSESSMENT_1"] = "LIVE_ASSESSMENT_1"
    snapshot: LiveSnapshot
    plan: Plan | None
    gate_reasons: tuple[str, ...]
    expires_at: datetime


class ShadowEpisode(Closed):
    schema_version: Literal["SHADOW_EPISODE_1"] = "SHADOW_EPISODE_1"
    episode_id: str
    mode: Literal["shadow_only_no_execution"] = "shadow_only_no_execution"
    assessment: Assessment
    commands_emitted: Literal[0] = 0
    causal_effect_established: Literal[False] = False


class SandboxCommand(Closed):
    command_id: str
    proposal_id: str
    hospital_id: Identifier
    action: dict[str, str | None]
    mode: Literal["local_sandbox_only"] = "local_sandbox_only"
    external_execution: Literal[False] = False
