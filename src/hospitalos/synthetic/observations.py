"""Closed observation contract and adapter for v0.4.1 unit-state deliveries."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Annotated, Any, Literal, Self

import numpy as np
from pydantic import Field, StrictInt, model_validator

from .config import FrozenConfig, HospitalConfig
from .v041 import hospsim, observation

_HS: Any = hospsim
_OBS: Any = observation
Count = Annotated[StrictInt, Field(ge=0)]
Hour = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class ObservedState(FrozenConfig):
    """Allowlist: no hidden simulator state, outcome, or future target is accepted."""

    lits_ouverts: Count
    lits_occupes: Count
    lits_propres_libres: Count
    lits_sales_ou_nettoyage: Count
    patients_heberges_presents: Count
    attente_urgences_nb: Count
    attente_urgences_4h_plus: Count
    sortants_medicaux_presents: Count
    en_attente_aval: Count
    en_attente_transport: Count
    en_attente_imagerie: Count
    en_attente_avis: Count
    en_attente_aide_domicile: Count
    charge_soins_min_h: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    soignants_presents: Count
    ide_presents: Count
    as_presents: Count


class Delivery(FrozenConfig):
    delivery_id: str
    event_id: str
    event_version: Annotated[StrictInt, Field(ge=1)]
    hospital_id: str
    pole_id: str
    unit_id: str
    source: Literal["GESTION_LITS"] = "GESTION_LITS"
    event_h: Hour
    recorded_h: Hour
    ingested_h: Hour
    available_h: Hour
    replaces_version: Annotated[StrictInt, Field(ge=1)] | None = None
    values: ObservedState
    synthetic: Literal[True] = True

    @model_validator(mode="after")
    def ordered_clocks(self) -> Self:
        if not self.event_h <= self.recorded_h <= self.ingested_h <= self.available_h:
            raise ValueError("Require event <= recorded <= ingested <= available")
        if self.event_version == 1 and self.replaces_version is not None:
            raise ValueError("Initial version cannot replace a version")
        if self.event_version > 1 and self.replaces_version != self.event_version - 1:
            raise ValueError("A revision must identify the immediately preceding version")
        return self

    def content_key(self) -> str:
        """Transport retries may have different receipt times, but identical source content."""
        return self.model_dump_json(exclude={"delivery_id", "ingested_h", "available_h"})


def observe_snapshots(events: Iterable[dict[str, Any]], config: HospitalConfig) -> list[Delivery]:
    """Use the reference observation noise without re-running or changing physics.

    The simulator's state labelled h describes the END of [h, h+1). Its observation
    clock starts at h+1, before adding recording, ingestion and availability delays.
    Only ETAT_UNITE events enter this lot's observed stream.
    """
    offset = config.warmup_days * 24
    start = config.start - dt.timedelta(days=config.warmup_days)
    dates = [start + dt.timedelta(days=day) for day in range(config.warmup_days + config.days)]
    holidays = _HS.jours_feries(range(start.year, dates[-1].year + 1))
    calendar = SimpleNamespace(
        ndays=len(dates),
        ouvre=np.array([day.weekday() < 5 and day not in holidays for day in dates]),
        doy=np.array([day.timetuple().tm_yday for day in dates]),
    )
    snapshots = []
    seen = set()
    slots = set()
    for event in events:
        if event["type"] != "ETAT_UNITE":
            continue
        unit = event["unit_id"]
        if (
            event["hospital_id"] != config.hospital_id
            or config.unit_poles.get(unit) != event["pole_id"]
        ):
            raise ValueError("Snapshot topology does not match the hospital config")
        if event["event_id"] in seen:
            raise ValueError("Duplicate truth event ID")
        seen.add(event["event_id"])
        if type(event["h"]) is not int or not -offset <= event["h"] < config.days * 24:
            raise ValueError("Truth snapshot is outside the simulation interval")
        slot = (unit, event["h"])
        if slot in slots:
            raise ValueError("Duplicate truth unit-hour snapshot")
        slots.add(slot)
        snapshots.append(
            {
                "event_id": event["event_id"],
                "h": event["h"] + offset + 1,
                "type": "ETAT_UNITE",
                "unite": unit,
                "sejour": None,
                "payload": event["payload"],
            }
        )
    if len(slots) != len(dates) * 24 * len(config.units):
        raise ValueError("Incomplete truth snapshot grid")
    snapshots.sort(key=lambda row: (row["h"], row["event_id"]))
    delivered, _ = _OBS.observer(snapshots, calendar, config.seed, np.datetime64(start))
    result = []
    for row in delivered:
        if row["t_disponible"] - offset > config.days * 24:
            continue  # freeze the dataset at its extraction boundary
        result.append(
            Delivery(
                delivery_id=f"{config.hospital_id}:{row['delivery_id']}",
                event_id=row["event_id"],
                event_version=row["event_version"],
                hospital_id=config.hospital_id,
                pole_id=config.unit_poles[row["unite"]],
                unit_id=row["unite"],
                event_h=row["t_evenement"] - offset,
                recorded_h=row["t_saisie"] - offset,
                ingested_h=row["t_ingestion"] - offset,
                available_h=row["t_disponible"] - offset,
                replaces_version=row["remplace_version"],
                values=ObservedState.model_validate(
                    {key: row["payload"][key] for key in ObservedState.model_fields}
                ),
            )
        )
    return result
