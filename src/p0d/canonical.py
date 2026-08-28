"""Canonical, immutable P-0D event representation."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TypeAlias

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


class CanonicalEventError(ValueError):
    """An event cannot enter the canonical P-0D ledger."""


def utc_datetime(value: datetime, field: str = "timestamp") -> datetime:
    """Return one explicit UTC timestamp and reject naive datetimes."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CanonicalEventError(f"{field} must be timezone-aware")
    offset = value.utcoffset()
    if offset is None:
        raise CanonicalEventError(f"{field} has no explicit UTC offset")
    return value.astimezone(UTC)


def utc_text(value: datetime) -> str:
    """Serialize a timestamp in the sole P-0D UTC representation."""

    normalized = utc_datetime(value)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _freeze_json(value: object, path: str = "payload") -> JsonValue:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalEventError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalEventError(f"{path} object keys must be strings")
            frozen[key] = _freeze_json(item, f"{path}.{key}")
        return MappingProxyType(dict(sorted(frozen.items())))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json(item, f"{path}[]") for item in value)
    raise CanonicalEventError(f"{path} contains unsupported type {type(value).__name__}")


def thaw_json(value: JsonValue) -> object:
    """Return a JSON-serializable detached representation."""

    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def canonical_json_bytes(value: object) -> bytes:
    """Encode supported JSON using a stable, whitespace-free representation."""

    frozen = _freeze_json(value)
    return json.dumps(
        thaw_json(frozen),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class CanonicalEvent:
    """One immutable assertion in event time and knowledge time."""

    event_id: str
    event_type: str
    entity_type: str
    entity_id: str
    source_system: str
    site_id: str
    unit_id: str
    event_time: datetime
    recorded_at: datetime
    available_at: datetime
    ingested_at: datetime
    schema_version: int
    correction_of: str | None
    payload_hash: str
    lineage: tuple[str, ...]
    payload: JsonValue

    def __post_init__(self) -> None:
        for field in (
            "event_id",
            "event_type",
            "entity_type",
            "entity_id",
            "source_system",
            "site_id",
            "unit_id",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise CanonicalEventError(f"{field} must be a non-empty string")
        if type(self.schema_version) is not int or self.schema_version < 1:
            raise CanonicalEventError("schema_version must be a positive integer")
        if self.correction_of == self.event_id:
            raise CanonicalEventError("an event cannot correct itself")
        if self.correction_of is not None and not self.correction_of.strip():
            raise CanonicalEventError("correction_of must be absent or non-empty")
        if (
            not isinstance(self.payload_hash, str)
            or len(self.payload_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.payload_hash)
        ):
            raise CanonicalEventError("payload_hash must be lowercase SHA-256")
        timestamps = ("event_time", "recorded_at", "available_at", "ingested_at")
        for field in timestamps:
            object.__setattr__(self, field, utc_datetime(getattr(self, field), field))
        if self.available_at > self.ingested_at:
            raise CanonicalEventError("available_at cannot be later than ingested_at")
        lineage = tuple(self.lineage)
        if any(not isinstance(item, str) or not item for item in lineage):
            raise CanonicalEventError("lineage entries must be non-empty strings")
        if len(lineage) != len(set(lineage)):
            raise CanonicalEventError("lineage entries must be unique")
        object.__setattr__(self, "lineage", lineage)
        frozen_payload = _freeze_json(self.payload)
        object.__setattr__(self, "payload", frozen_payload)
        if sha256_json(frozen_payload) != self.payload_hash:
            raise CanonicalEventError("payload_hash differs from canonical payload bytes")

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        source_system: str,
        site_id: str,
        unit_id: str,
        event_time: datetime,
        recorded_at: datetime,
        available_at: datetime,
        ingested_at: datetime,
        schema_version: int,
        payload: object,
        correction_of: str | None = None,
        lineage: Sequence[str] = (),
    ) -> CanonicalEvent:
        frozen_payload = _freeze_json(payload)
        return cls(
            event_id=event_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            source_system=source_system,
            site_id=site_id,
            unit_id=unit_id,
            event_time=event_time,
            recorded_at=recorded_at,
            available_at=available_at,
            ingested_at=ingested_at,
            schema_version=schema_version,
            correction_of=correction_of,
            payload_hash=sha256_json(frozen_payload),
            lineage=tuple(lineage),
            payload=frozen_payload,
        )

    def semantic_key(self) -> tuple[object, ...]:
        """Identity of an assertion independent of transport retries."""

        return (
            self.event_type,
            self.entity_type,
            self.entity_id,
            self.source_system,
            self.site_id,
            self.unit_id,
            self.event_time,
            self.schema_version,
            self.correction_of,
            self.payload_hash,
            self.lineage,
        )

    def replay_key(self) -> tuple[object, ...]:
        """Total deterministic ordering for replay."""

        return (
            self.event_time,
            self.available_at,
            self.recorded_at,
            self.ingested_at,
            self.event_type,
            self.entity_type,
            self.entity_id,
            self.source_system,
            self.site_id,
            self.unit_id,
            self.event_id,
        )

    def manifest_record(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "source_system": self.source_system,
            "site_id": self.site_id,
            "unit_id": self.unit_id,
            "event_time": utc_text(self.event_time),
            "recorded_at": utc_text(self.recorded_at),
            "available_at": utc_text(self.available_at),
            "ingested_at": utc_text(self.ingested_at),
            "schema_version": self.schema_version,
            "correction_of": self.correction_of,
            "payload_hash": self.payload_hash,
            "lineage": list(self.lineage),
        }
