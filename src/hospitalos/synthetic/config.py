"""Validated, immutable topology for one synthetic hospital and one partition."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
Multiplier = Annotated[float, Field(ge=0, le=10, allow_inf_nan=False, strict=True)]
MechanismFamily = Literal["v041", "local_v1", "hybrid_v1"]
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)]
DelayMinutes = Annotated[float, Field(ge=0, le=10080, allow_inf_nan=False, strict=True)]


class FrozenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DynamicsConfig(FrozenConfig):
    """Versioned engineering hypotheses, independent of resource pooling."""

    arrivals: Literal["v041", "shared_bursts_v1", "appointments_v1"] = "v041"
    discharges: Literal["v041", "daily_rounds_v1", "rolling_v1"] = "v041"
    staffing: Literal["v041", "persistent_absence_v1", "shared_float_v1"] = "v041"


class DocumentaryConfig(FrozenConfig):
    """Source-document mechanisms, independent of physical discharge and transport."""

    staff_forecasts: Literal["v041", "admission_prior_v1", "milestones_v1"] = "v041"
    downstream_confirmation: Literal["v041", "request_delay_v1", "review_capacity_v1"] = "v041"


class ClinicalConfig(FrozenConfig):
    """Scenario assumptions, not clinically estimated risks."""

    destinations: Literal["v041", "conditional_survival_v1"] = "v041"
    death_age_slope: Annotated[float, Field(ge=0, le=0.1, allow_inf_nan=False)] = 0.03
    death_dependence_slope: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 0.0

    @model_validator(mode="after")
    def active_parameters(self) -> Self:
        if self.destinations == "v041" and (
            self.death_age_slope != 0.03 or self.death_dependence_slope != 0.0
        ):
            raise ValueError("Clinical parameters require conditional_survival_v1")
        return self


class SMRConfig(FrozenConfig):
    """One finite shared pool; all numerical defaults are uncalibrated hypotheses."""

    mode: Literal["legacy_delay", "finite_v1"] = "legacy_delay"
    beds: Annotated[StrictInt, Field(ge=0, le=2000)] = 0
    oxygen_beds: Annotated[StrictInt, Field(ge=0)] = 0
    isolation_beds: Annotated[StrictInt, Field(ge=0)] = 0
    preparation_h: Annotated[StrictInt, Field(ge=1, le=720)] = 24
    review_hour: Annotated[StrictInt, Field(ge=0, le=23)] = 10
    reservation_ttl_h: Annotated[StrictInt, Field(ge=1, le=168)] = 48
    retry_h: Annotated[StrictInt, Field(ge=1, le=168)] = 24
    stay_median_days: Annotated[float, Field(gt=0, le=180, allow_inf_nan=False)] = 21.0
    stay_sigma: Annotated[float, Field(ge=0, le=2, allow_inf_nan=False)] = 0.45
    external_arrivals_per_day: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] = 0.0
    external_oxygen_probability: Probability = 0.2
    external_isolation_probability: Probability = 0.05
    external_patience_h: Annotated[StrictInt, Field(ge=1, le=8760)] = 168

    @model_validator(mode="after")
    def valid_pool(self) -> Self:
        if not self.isolation_beds <= self.oxygen_beds <= self.beds:
            raise ValueError("Require isolation_beds <= oxygen_beds <= SMR beds")
        if self.mode == "legacy_delay" and any(
            getattr(self, k) != f.default for k, f in type(self).model_fields.items() if k != "mode"
        ):
            raise ValueError("SMR parameters require finite_v1")
        return self


class ObservationOutage(FrozenConfig):
    outage_id: Identifier
    starts_at: dt.datetime
    ends_at: dt.datetime
    unit_ids: tuple[Identifier, ...] = ()  # Empty means all hospital units.

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        for value in (self.starts_at, self.ends_at):
            if (
                value.utcoffset() != dt.timedelta(hours=1)
                or value.minute
                or value.second
                or value.microsecond
            ):
                raise ValueError("Outages require whole hours at explicit fixed UTC+01:00")
        if self.ends_at <= self.starts_at:
            raise ValueError("Outage end must be strictly after start")
        if len(set(self.unit_ids)) != len(self.unit_ids):
            raise ValueError("Duplicate outage unit")
        return self


class ObservationProfile(FrozenConfig):
    """Snapshot observation hypotheses, never parameters of hospital physics."""

    mode: Literal["v041", "site_v1"] = "v041"
    missing_probability: Probability = 0.015
    load_missing_multiplier: Multiplier = 2.0
    recording_delay_median_minutes: DelayMinutes = 12.0
    recording_delay_sigma: Annotated[float, Field(ge=0, le=3, strict=True, allow_inf_nan=False)] = (
        0.9
    )
    ingestion_delay_min_minutes: DelayMinutes = 1.0
    ingestion_delay_max_minutes: DelayMinutes = 15.0
    availability_delay_minutes: DelayMinutes = 0.5
    load_delay_multiplier: Multiplier = 1.6
    ready_documented_probability: Probability = 0.6
    downstream_documented_probability: Probability = 0.8
    charge_noise_sigma: Annotated[float, Field(ge=0, le=3, strict=True, allow_inf_nan=False)] = 0.1
    revision_probability: Probability = 0.02
    revision_delay_min_h: Annotated[
        float, Field(gt=0, le=720, strict=True, allow_inf_nan=False)
    ] = 6.0
    revision_delay_max_h: Annotated[
        float, Field(gt=0, le=720, strict=True, allow_inf_nan=False)
    ] = 48.0
    duplicate_probability: Probability = 0.008
    outages: tuple[ObservationOutage, ...] = ()

    @model_validator(mode="after")
    def valid_profile(self) -> Self:
        for low, high in (
            (self.ingestion_delay_min_minutes, self.ingestion_delay_max_minutes),
            (self.revision_delay_min_h, self.revision_delay_max_h),
        ):
            if low > high:
                raise ValueError("Reversed observation delay range")
        if self.mode == "v041" and any(
            getattr(self, key) != field.default
            for key, field in type(self).model_fields.items()
            if key != "mode"
        ):
            raise ValueError("Custom observation parameters require site_v1")
        if len({o.outage_id for o in self.outages}) != len(self.outages):
            raise ValueError("Duplicate outage_id")
        return self


class ChangeWindow(FrozenConfig):
    change_id: Identifier
    starts_at: dt.datetime
    ends_at: dt.datetime | None = None

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        for value in (self.starts_at, self.ends_at):
            if value is not None and (
                value.utcoffset() != dt.timedelta(hours=1)
                or value.minute
                or value.second
                or value.microsecond
            ):
                raise ValueError("Changes require whole hours at explicit fixed UTC+01:00")
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("Change end must be strictly after start")
        return self


class BedClosure(ChangeWindow):
    kind: Literal["bed_closure"]
    unit_id: Identifier
    additional_closed_beds: Annotated[StrictInt, Field(ge=1, le=200)]


class ServiceCapacityChange(ChangeWindow):
    kind: Literal["service_capacity"]
    resource: Literal["cleaning", "imaging", "transport", "specialist"]
    multiplier: Multiplier


class StaffingShortage(ChangeWindow):
    kind: Literal["staffing_shortage"]
    unit_id: Identifier
    additional_absent: Annotated[StrictInt, Field(ge=1, le=200)]

    @model_validator(mode="after")
    def full_shifts(self) -> Self:
        # The inherited sid() uses midnight, 07:00 and 15:00 boundaries.
        if any(v is not None and v.hour not in (0, 7, 15) for v in (self.starts_at, self.ends_at)):
            raise ValueError("Staff shortages must start/end at 00:00, 07:00 or 15:00")
        return self


OrganisationalChange = Annotated[
    BedClosure | ServiceCapacityChange | StaffingShortage, Field(discriminator="kind")
]


class UnitConfig(FrozenConfig):
    unit_id: Identifier
    template: Literal["MED_POLY", "CSG", "PNEUMO", "CARDIO"]
    beds: Annotated[StrictInt, Field(ge=4, le=200)]
    isolation_beds: Annotated[StrictInt, Field(ge=0)]
    oxygen_beds: Annotated[StrictInt, Field(ge=0)]
    arrival_scale: Multiplier = 1.0

    @model_validator(mode="after")
    def compatible_beds(self) -> Self:
        # In the inherited engine, isolation beds are a subset of oxygen beds.
        if not self.isolation_beds <= self.oxygen_beds <= self.beds:
            raise ValueError("Require isolation_beds <= oxygen_beds <= beds")
        return self


class PoleConfig(FrozenConfig):
    pole_id: Identifier
    units: Annotated[tuple[UnitConfig, ...], Field(min_length=1)]


class SharedResources(FrozenConfig):
    """Hospital-wide multipliers; capacities rounded down to integer slots/agents."""

    cleaning: Multiplier = 1.0
    imaging: Multiplier = 1.0
    transport: Multiplier = 1.0
    specialist: Multiplier = 1.0


class PoleResourceWeights(FrozenConfig):
    pole_id: Identifier
    weights: SharedResources = SharedResources()


class RoutingLink(FrozenConfig):
    origin: Identifier
    destination: Identifier


class HospitalConfig(FrozenConfig):
    schema_version: Literal["0.1"] = "0.1"
    hospital_id: Identifier
    seed: Annotated[StrictInt, Field(ge=0, le=2**32 - 1)]
    start: dt.date
    days: Annotated[StrictInt, Field(ge=1, le=366)] = 365
    warmup_days: Annotated[StrictInt, Field(ge=0, le=365)] = 61
    partition: Literal["development", "train", "validation", "test"] = "development"
    mechanism_family: MechanismFamily = "v041"
    dynamics: DynamicsConfig = DynamicsConfig()
    documentary: DocumentaryConfig = DocumentaryConfig()
    clinical: ClinicalConfig = ClinicalConfig()
    smr: SMRConfig = SMRConfig()
    observation: ObservationProfile = ObservationProfile()
    changes: tuple[OrganisationalChange, ...] = ()
    poles: Annotated[tuple[PoleConfig, ...], Field(min_length=1)]
    shared_resources: SharedResources = SharedResources()
    pole_resource_weights: tuple[PoleResourceWeights, ...] = ()
    routing_links: tuple[RoutingLink, ...] = ()
    cross_pole_delay_h: Annotated[StrictInt, Field(ge=1, le=168)] = 12

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        ids = [self.hospital_id]
        ids.extend(pole.pole_id for pole in self.poles)
        ids.extend(unit.unit_id for pole in self.poles for unit in pole.units)
        if len(ids) != len(set(ids)):
            raise ValueError("Hospital, pole and unit IDs must be unique within the hospital")
        pole_ids = {pole.pole_id for pole in self.poles}
        if self.mechanism_family != "v041" and len(pole_ids) < 2:
            raise ValueError("Local/hybrid mechanisms require at least two poles")
        weights = {item.pole_id: item.weights for item in self.pole_resource_weights}
        if len(weights) != len(self.pole_resource_weights) or not weights.keys() <= pole_ids:
            raise ValueError("Resource weights must name unique known poles")
        if self.mechanism_family == "v041" and (weights or self.routing_links):
            raise ValueError("v041 retains hospital pooling and unrestricted routing")
        if self.mechanism_family == "local_v1" and self.routing_links:
            raise ValueError("Local routing cannot have cross-pole links")
        if self.mechanism_family != "hybrid_v1" and self.cross_pole_delay_h != 12:
            raise ValueError("Cross-pole delay is configurable only for hybrid_v1")
        if self.mechanism_family == "hybrid_v1" and any(
            w.imaging != 1.0 or w.specialist != 1.0 for w in weights.values()
        ):
            raise ValueError("Hybrid imaging/specialist are shared, without local weights")
        for resource in ("cleaning", "imaging", "transport", "specialist"):
            if not any(getattr(weights.get(p, SharedResources()), resource) > 0 for p in pole_ids):
                raise ValueError(f"At least one pole must receive {resource} capacity")
        links = {(link.origin, link.destination) for link in self.routing_links}
        if len(links) != len(self.routing_links):
            raise ValueError("Duplicate routing link")
        if any(a not in pole_ids or b not in pole_ids or a == b for a, b in links):
            raise ValueError("Routing links must connect distinct known poles")
        # Fail before simulation if the warm-up or end would exceed datetime bounds.
        try:
            self.start - dt.timedelta(days=self.warmup_days)
            self.start + dt.timedelta(days=self.days)
        except OverflowError as exc:
            raise ValueError("Simulation dates are out of range") from exc
        recorded_start = dt.datetime.combine(
            self.start, dt.time(), dt.timezone(dt.timedelta(hours=1))
        )
        recorded_end = recorded_start + dt.timedelta(days=self.days)
        windows: dict[tuple[str, str], list[tuple[dt.datetime, dt.datetime]]] = {}
        change_ids = [c.change_id for c in self.changes]
        if len(set(change_ids)) != len(change_ids):
            raise ValueError("Duplicate change_id")
        units = {u.unit_id: u for u in self.units}
        outage_windows: dict[str, list[tuple[dt.datetime, dt.datetime]]] = {}
        for outage in self.observation.outages:
            if not recorded_start <= outage.starts_at < outage.ends_at <= recorded_end:
                raise ValueError("Outages must lie inside the recorded interval")
            if not set(outage.unit_ids) <= units.keys():
                raise ValueError("Outage names an unknown unit")
            for unit_id in outage.unit_ids or tuple(units):
                outage_windows.setdefault(unit_id, []).append((outage.starts_at, outage.ends_at))
        for group in outage_windows.values():
            ordered = sorted(group)
            if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:], strict=False)):
                raise ValueError("Overlapping outages for the same unit")
        for change in self.changes:
            end = change.ends_at or recorded_end
            if not recorded_start <= change.starts_at < recorded_end or end > recorded_end:
                raise ValueError("Changes must lie inside the recorded interval")
            if isinstance(change, ServiceCapacityChange):
                target: str = change.resource
            else:
                target = change.unit_id
                if target not in units:
                    raise ValueError("Change names an unknown unit")
                if (
                    isinstance(change, BedClosure)
                    and change.additional_closed_beds > units[target].beds
                ):
                    raise ValueError("Requested bed closure exceeds physical standard beds")
            windows.setdefault((change.kind, target), []).append((change.starts_at, end))
        for group in windows.values():
            ordered = sorted(group)
            if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:], strict=False)):
                raise ValueError("Overlapping changes for the same kind and target")
        return self

    @property
    def units(self) -> tuple[UnitConfig, ...]:
        return tuple(unit for pole in self.poles for unit in pole.units)

    @property
    def unit_poles(self) -> dict[str, str]:
        return {unit.unit_id: pole.pole_id for pole in self.poles for unit in pole.units}

    @property
    def fingerprint(self) -> str:
        # Preserve existing v041 dataset/world identities when adding inactive options.
        inactive = (
            {"pole_resource_weights", "routing_links", "cross_pole_delay_h"}
            if self.mechanism_family == "v041"
            else set()
        )
        if not self.changes:
            inactive.add("changes")
        if self.dynamics == DynamicsConfig():
            inactive.add("dynamics")
        if self.documentary == DocumentaryConfig():
            inactive.add("documentary")
        if self.clinical == ClinicalConfig():
            inactive.add("clinical")
        if self.smr == SMRConfig():
            inactive.add("smr")
        if self.observation == ObservationProfile():
            inactive.add("observation")
        return hashlib.sha256(self.model_dump_json(exclude=inactive).encode()).hexdigest()


def load_config(path: Path) -> HospitalConfig:
    return HospitalConfig.model_validate_json(path.read_text(encoding="utf-8"))


def validate_partition_isolation(configs: list[HospitalConfig]) -> None:
    """A hospital ID cannot occur in two partitions, even with different seeds."""
    partitions: dict[str, str] = {}
    for config in configs:
        previous = partitions.setdefault(config.hospital_id, config.partition)
        if previous != config.partition:
            raise ValueError(f"Hospital {config.hospital_id} crosses partitions")
