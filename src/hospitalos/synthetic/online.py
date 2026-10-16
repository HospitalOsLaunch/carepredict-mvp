"""Stream snapshot noise while physics advances; release receipts only when available."""

from __future__ import annotations

import heapq
from typing import Any

from .config import HospitalConfig
from .observation_profiles import observation_stream
from .observations import Delivery, ObservedState


class OnlineSnapshots:
    def __init__(self, config: HospitalConfig, calendar: Any):
        self.config = config
        self.offset = config.warmup_days * 24
        self.adapter = observation_stream(config, calendar)
        self.pending: list[tuple[float, str, int, str, Delivery]] = []
        self.delivered: list[Delivery] = []
        self.next_hour = 0
        self.boundary = -self.offset

    def push(self, hour: int, snapshots: list[dict[str, Any]]) -> None:
        if hour != self.next_hour or len(snapshots) != len(self.config.units):
            raise ValueError("Expected the next complete hourly snapshot batch")
        if any(row["h"] != hour or row["u"] != u for u, row in enumerate(snapshots)):
            raise ValueError("Snapshot grid mismatch")
        self.next_hour += 1
        for u, row in enumerate(snapshots):
            unit = self.config.units[u].unit_id
            event_id = f"{self.config.hospital_id}:STATE:{hour:08d}:{u:04d}"
            event = {
                "event_id": event_id,
                "h": hour + 1,
                "type": "ETAT_UNITE",
                "unite": unit,
                "sejour": None,
                "payload": {k: v for k, v in row.items() if k not in ("u", "h")},
            }
            for receipt, raw in enumerate(self.adapter.observe(event)):
                delivery = Delivery(
                    delivery_id=f"{event_id}:receipt{receipt}",
                    event_id=event_id,
                    event_version=raw["event_version"],
                    hospital_id=self.config.hospital_id,
                    unit_id=unit,
                    pole_id=self.config.unit_poles[unit],
                    event_h=raw["t_evenement"] - self.offset,
                    recorded_h=raw["t_saisie"] - self.offset,
                    ingested_h=raw["t_ingestion"] - self.offset,
                    available_h=raw["t_disponible"] - self.offset,
                    replaces_version=raw["remplace_version"],
                    values=ObservedState.model_validate(
                        {key: raw["payload"][key] for key in ObservedState.model_fields}
                    ),
                )
                heapq.heappush(
                    self.pending,
                    (
                        delivery.available_h,
                        event_id,
                        delivery.event_version,
                        delivery.delivery_id,
                        delivery,
                    ),
                )

    def receive(self, boundary: int) -> tuple[Delivery, ...]:
        if boundary < self.boundary or boundary > self.next_hour - self.offset:
            raise ValueError("Cannot receive observations before or beyond the simulated boundary")
        self.boundary = boundary
        receipts = []
        while self.pending and self.pending[0][0] <= boundary:
            receipts.append(heapq.heappop(self.pending)[-1])
        self.delivered.extend(receipts)
        return tuple(receipts)
