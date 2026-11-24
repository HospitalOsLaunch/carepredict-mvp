"""Versioned operational offers and demand observed for one unit at the decision origin."""

from collections import Counter
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator

from hospitalos.decision_support.contracts import AdmissionRequest, ReinforcementOption
from hospitalos.decision_support.resources import lending_violations, touched_hours
from hospitalos.operational.contract import Closed, Identifier, instant


class StaffOffer(Closed):
    option: ReinforcementOption
    staff_id: Identifier
    # Explicit locally validated capacity difference for this skill and shift.
    staffed_places: Annotated[StrictInt, Field(ge=1, le=100)]
    committed: bool = False

    @model_validator(mode="after")
    def interval(self) -> Self:
        if self.option.end <= self.option.start:
            raise ValueError("Empty staff interval")
        if self.committed and self.option.confirmation != "confirmed":
            raise ValueError("A committed shift requires confirmation")
        return self


class Booking(Closed):
    request: AdmissionRequest
    window_start: datetime
    window_end: datetime
    status: Literal["booked", "cancelled"] = "booked"
    prepared_bed: Identifier | None = None

    @field_validator("window_start", "window_end")
    @classmethod
    def clock(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def window(self) -> Self:
        if not self.window_start <= self.request.expected_arrival < self.window_end:
            raise ValueError("Expected arrival outside authorised window")
        return self


class UnitSchedule(Closed):
    kind: Literal["unit_schedule"] = "unit_schedule"
    id: Identifier  # beneficiary unit
    # Total authorised staff-minutes across all offers including recorded commitments.
    budget_minutes: Annotated[StrictInt, Field(ge=0)]
    offers: Annotated[tuple[StaffOffer, ...], Field(max_length=32)] = ()
    admissions: Annotated[tuple[Booking, ...], Field(max_length=200)] = ()

    @model_validator(mode="after")
    def unique(self) -> Self:
        for ids in (
            [x.option.option_id for x in self.offers],
            [x.request.request_id for x in self.admissions],
        ):
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate unit schedule identity")
        return self

    def staff_errors(self, ids: set[str]) -> tuple[str, ...]:
        chosen = [o for o in self.offers if o.committed or o.option.option_id in ids]
        if any(o.option.confirmation != "confirmed" for o in chosen):
            return ("reinforcement_unconfirmed",)
        if any(o.option.lending_unit == self.id for o in chosen):
            return ("invalid_lending_unit",)
        if (
            sum((o.option.end - o.option.start).total_seconds() for o in chosen)
            > 60 * self.budget_minutes
        ):
            return ("reinforcement_budget",)
        for i, a in enumerate(chosen):
            if any(
                b.staff_id == a.staff_id
                and b.option.start < a.option.end
                and a.option.start < b.option.end
                for b in chosen[:i]
            ):
                return ("staff_double_booking",)
        return tuple(
            lending_violations([o.option for o in chosen], [o.option for o in self.offers])
        )

    def claims_for(self, slot: str) -> Counter[str]:
        offer = next(o for o in self.offers if o.option.option_id == slot)
        keys = Counter({f"offer:{self.id}:{slot}": 1})
        for h in touched_hours(offer.option.start, offer.option.end):
            keys[f"staff:{offer.staff_id}:{h.isoformat()}"] += 1
            if offer.option.lending_unit:
                keys[
                    f"lender:{offer.option.lending_unit}:{offer.option.skill}:{h.isoformat()}"
                ] += 1
        return keys
