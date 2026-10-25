"""Versioned, fictional operations hypotheses. Never clinical calibration claims."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, model_validator

from hospitalos.operational.contract import Closed, Identifier

Positive = Annotated[StrictInt, Field(ge=1, le=86400)]


class HospitalConfig(Closed):
    schema_version: Literal["VIRTUAL_HOSPITAL_1"] = "VIRTUAL_HOSPITAL_1"
    hospital_id: Identifier
    name: str
    unit_id: Identifier = "geriatrie"
    unit_name: str = "Court séjour gériatrique"
    regime: Literal["nominal", "influx", "cleaning_constrained"] = "nominal"
    beds: Annotated[StrictInt, Field(ge=4, le=40)] = 14
    staffed_beds: Annotated[StrictInt, Field(ge=1, le=40)] = 14
    cleaning_teams: Annotated[StrictInt, Field(ge=1, le=4)] = 1
    oxygen_beds: tuple[int, ...] = (2, 5, 8, 11)
    initially_occupied: Annotated[StrictInt, Field(ge=0, le=38)] = 10
    initial_waiting: Annotated[StrictInt, Field(ge=1, le=20)] = 2
    observation_seconds: Positive = 60
    delivery_seconds: Annotated[StrictInt, Field(ge=1, le=60)] = 30
    cleaning_seconds: tuple[Positive, ...] = (900, 1200, 1500)
    interarrival_seconds: tuple[Positive, ...] = (1200, 1800, 2400)
    peak_interarrival_seconds: tuple[Positive, ...] = (480, 720, 900)
    clinical_stay_seconds: tuple[Positive, ...] = (14400, 21600, 28800)
    departure_delay_seconds: Positive = 600
    max_active_patients: Annotated[StrictInt, Field(ge=40, le=120)] = 120

    @model_validator(mode="after")
    def valid(self) -> Self:
        if not self.initially_occupied <= self.staffed_beds <= self.beds:
            raise ValueError("initial occupancy <= staffed capacity <= beds required")
        if self.initially_occupied > self.beds - 2:
            raise ValueError("keep two initially dirty beds")
        if len(set(self.oxygen_beds)) != len(self.oxygen_beds) or any(
            not 1 <= n <= self.beds for n in self.oxygen_beds
        ):
            raise ValueError("invalid oxygen bed indices")
        if not all(
            (
                self.cleaning_seconds,
                self.interarrival_seconds,
                self.peak_interarrival_seconds,
                self.clinical_stay_seconds,
            )
        ):
            raise ValueError("duration supports must not be empty")
        if self.observation_seconds + self.delivery_seconds > 120:
            raise ValueError("normal source cadence must fit the resource freshness contract")
        return self


def hospitals() -> tuple[HospitalConfig, ...]:
    return (
        HospitalConfig(hospital_id="X1", name="Hôpital X1"),
        HospitalConfig(hospital_id="X2", name="Hôpital X2", regime="influx", delivery_seconds=45),
        HospitalConfig(
            hospital_id="X3",
            name="Hôpital X3",
            regime="cleaning_constrained",
            cleaning_seconds=(1800, 2700, 3600),
            delivery_seconds=60,
        ),
    )
