"""Canonical Schema v1 loader & deterministic validator (HOS-002).

Source of truth: ``canonical_schema.yaml`` (same directory). This module parses
the frozen contract into typed specs and validates records against it,
fail-closed. It is intentionally dependency-light (stdlib + PyYAML) so it can run
inside the offline enclave and be reused by the Nantes preflight (HOS-003) and
the Validator v2 (HOS-006).

Design invariants:
    * Deterministic: identical input -> identical, sorted violation list.
    * Fail-closed: anything not provably valid is a violation.
    * No sensitive echo: violation messages never copy raw values, only field
      names, expected types and coordinates.
    * Bitemporal: every record carries ``event_time`` and ``available_at``
      (tz-aware Europe/Paris, DST-correct). ``available_at`` is the basis of the
      Temporal-Leakage Gate (HOS-010); this module only enforces presence and
      timezone. Delegated by design:
        - cross-field ordering ``available_at >= event_time`` and
          "not in the future" checks are owned by the Validator v2 (HOS-006);
        - the leakage comparison ``available_at <= inference_origin`` is HOS-010.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

_SCHEMA_PATH = Path(__file__).with_name("canonical_schema.yaml")
_PARIS = ZoneInfo("Europe/Paris")


class Sensitivity(StrEnum):
    OPERATIONAL = "operational"
    RESTRICTED = "restricted"
    FORBIDDEN = "forbidden"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class ViolationCode(StrEnum):
    UNKNOWN_DOMAIN = "unknown_domain"
    MISSING_REQUIRED = "missing_required"
    UNKNOWN_FIELD = "unknown_field"
    NULL_NOT_ALLOWED = "null_not_allowed"
    TYPE_MISMATCH = "type_mismatch"
    OUT_OF_RANGE = "out_of_range"
    ENUM_VIOLATION = "enum_violation"
    TIMESTAMP_INVALID = "timestamp_invalid"
    TIMESTAMP_NOT_TZ_AWARE = "timestamp_not_tz_aware"
    TIMEZONE_MISMATCH = "timezone_mismatch"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str
    nullable: bool = False
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    values: tuple[str, ...] | None = None
    sensitivity: Sensitivity = Sensitivity.OPERATIONAL
    description: str | None = None


@dataclass(frozen=True)
class DomainSpec:
    name: str
    description: str
    fields: dict[str, FieldSpec]


@dataclass(frozen=True)
class CanonicalSchemaSpec:
    version: str
    timezone: str
    frozen_until: str
    temporal: dict[str, FieldSpec]
    identity: dict[str, FieldSpec]
    domains: dict[str, DomainSpec]
    extensions_status: str

    def domain(self, name: str) -> DomainSpec | None:
        return self.domains.get(name)


@dataclass(frozen=True, order=True)
class SchemaViolation:
    """A single, deterministic schema violation. Ordering is stable for sorting."""

    domain: str
    field: str
    code: ViolationCode
    severity: Severity
    location: str
    message: str
    remediation: str

    def to_dict(self) -> dict[str, str]:
        return {
            "domain": self.domain,
            "field": self.field,
            "code": self.code.value,
            "severity": self.severity.value,
            "location": self.location,
            "message": self.message,
            "remediation": self.remediation,
        }


def _field_from_yaml(name: str, raw: dict[str, Any]) -> FieldSpec:
    values = raw.get("values")
    return FieldSpec(
        name=name,
        type=str(raw["type"]),
        nullable=bool(raw.get("nullable", raw.get("required", True) is False)),
        unit=raw.get("unit"),
        minimum=raw.get("minimum"),
        maximum=raw.get("maximum"),
        values=tuple(values) if values is not None else None,
        sensitivity=Sensitivity(raw.get("sensitivity", "operational")),
        description=raw.get("description"),
    )


def _required_field_from_yaml(name: str, raw: dict[str, Any]) -> FieldSpec:
    # temporal / identity fields are declared with `required: true`.
    return FieldSpec(
        name=name,
        type=str(raw["type"]),
        nullable=not bool(raw.get("required", True)),
        sensitivity=Sensitivity(raw.get("sensitivity", "operational")),
        description=raw.get("description"),
    )


@lru_cache(maxsize=4)
def load_canonical_schema(path: str | None = None) -> CanonicalSchemaSpec:
    """Load and parse the canonical schema. Cached by path."""
    schema_path = Path(path) if path else _SCHEMA_PATH
    with schema_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    temporal = {n: _required_field_from_yaml(n, spec) for n, spec in raw["temporal"].items()}
    identity = {n: _required_field_from_yaml(n, spec) for n, spec in raw["identity"].items()}
    domains: dict[str, DomainSpec] = {}
    for dname, dspec in raw["domains"].items():
        fields = {fn: _field_from_yaml(fn, fs) for fn, fs in dspec["fields"].items()}
        domains[dname] = DomainSpec(
            name=dname, description=dspec.get("description", ""), fields=fields
        )

    return CanonicalSchemaSpec(
        version=str(raw["version"]),
        timezone=str(raw["timezone"]),
        frozen_until=str(raw["frozen_until"]),
        temporal=temporal,
        identity=identity,
        domains=domains,
        extensions_status=str(raw["extensions"]["status"]),
    )


SCHEMA_VERSION: str = load_canonical_schema().version


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _check_scalar_type(spec: FieldSpec, value: Any) -> ViolationCode | None:
    """Return a violation code if ``value`` does not match ``spec.type``, else None."""
    declared = spec.type
    if declared == "string":
        return None if isinstance(value, str) else ViolationCode.TYPE_MISMATCH
    if declared == "integer":
        return (
            None
            if (isinstance(value, int) and not _is_bool(value))
            else ViolationCode.TYPE_MISMATCH
        )
    if declared == "number":
        ok = isinstance(value, (int, float)) and not _is_bool(value)
        return None if ok else ViolationCode.TYPE_MISMATCH
    if declared == "enum":
        if not isinstance(value, str):
            return ViolationCode.TYPE_MISMATCH
        return None if (spec.values and value in spec.values) else ViolationCode.ENUM_VIOLATION
    if declared == "datetime":
        return _check_datetime(value)
    # Unknown declared type in schema is a hard failure (fail-closed).
    return ViolationCode.TYPE_MISMATCH


def _check_datetime(value: Any) -> ViolationCode | None:
    if not isinstance(value, str):
        return ViolationCode.TIMESTAMP_INVALID
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return ViolationCode.TIMESTAMP_INVALID
    if parsed.tzinfo is None:
        return ViolationCode.TIMESTAMP_NOT_TZ_AWARE
    # Instant-correct check: the record's UTC offset must equal the Europe/Paris
    # local offset *at that instant* (DST-aware). This rejects a wrong Paris
    # offset for the date (e.g. +01:00 in July) and non-Paris offsets/UTC alike.
    # Timestamps must be expressed in Europe/Paris local time (contract).
    if parsed.utcoffset() == parsed.astimezone(_PARIS).utcoffset():
        return None
    return ViolationCode.TIMEZONE_MISMATCH


def _violation(
    domain: str, field_name: str, code: ViolationCode, index: int, message: str, remediation: str
) -> SchemaViolation:
    return SchemaViolation(
        domain=domain,
        field=field_name,
        code=code,
        severity=Severity.ERROR,
        location=f"record[{index}].{field_name}" if field_name else f"record[{index}]",
        message=message,
        remediation=remediation,
    )


def _validate_field(domain: str, spec: FieldSpec, value: Any, index: int) -> list[SchemaViolation]:
    out: list[SchemaViolation] = []
    if value is None:
        if not spec.nullable:
            out.append(
                _violation(
                    domain,
                    spec.name,
                    ViolationCode.NULL_NOT_ALLOWED,
                    index,
                    f"'{spec.name}' is not nullable",
                    "Provide a non-null value.",
                )
            )
        return out
    type_code = _check_scalar_type(spec, value)
    if type_code is not None:
        expected = (
            spec.type
            if type_code != ViolationCode.ENUM_VIOLATION
            else f"one of {list(spec.values or ())}"
        )
        out.append(
            _violation(
                domain,
                spec.name,
                type_code,
                index,
                f"'{spec.name}' expected {expected}",
                f"Emit '{spec.name}' as {spec.type}.",
            )
        )
        return out  # do not range-check a mistyped value
    if isinstance(value, (int, float)) and not _is_bool(value):
        if spec.minimum is not None and value < spec.minimum:
            out.append(
                _violation(
                    domain,
                    spec.name,
                    ViolationCode.OUT_OF_RANGE,
                    index,
                    f"'{spec.name}' below minimum {spec.minimum}",
                    f"Ensure '{spec.name}' >= {spec.minimum}.",
                )
            )
        if spec.maximum is not None and value > spec.maximum:
            out.append(
                _violation(
                    domain,
                    spec.name,
                    ViolationCode.OUT_OF_RANGE,
                    index,
                    f"'{spec.name}' above maximum {spec.maximum}",
                    f"Ensure '{spec.name}' <= {spec.maximum}.",
                )
            )
    return out


def validate_record(
    spec: CanonicalSchemaSpec, domain: str, record: dict[str, Any], *, index: int = 0
) -> list[SchemaViolation]:
    """Validate a single canonical record for ``domain``. Deterministic, fail-closed.

    Checks identity + temporal presence/typing, then domain fields: unknown
    fields (closed schema), nullability, type, range and enum membership.
    Returns a sorted list of :class:`SchemaViolation` (empty == valid).
    """
    violations: list[SchemaViolation] = []
    domain_spec = spec.domain(domain)
    if domain_spec is None:
        return [
            _violation(
                domain,
                "",
                ViolationCode.UNKNOWN_DOMAIN,
                index,
                f"unknown domain '{domain}'",
                f"Use one of {sorted(spec.domains)}.",
            )
        ]

    known: set[str] = set(spec.identity) | set(spec.temporal) | set(domain_spec.fields)

    # Identity + temporal (all required).
    for name, fspec in {**spec.identity, **spec.temporal}.items():
        if name not in record:
            violations.append(
                _violation(
                    domain,
                    name,
                    ViolationCode.MISSING_REQUIRED,
                    index,
                    f"required '{name}' missing",
                    f"Include '{name}'.",
                )
            )
        else:
            violations.extend(_validate_field(domain, fspec, record[name], index))

    # Domain fields.
    for name, fspec in domain_spec.fields.items():
        if name not in record:
            if not fspec.nullable:
                violations.append(
                    _violation(
                        domain,
                        name,
                        ViolationCode.MISSING_REQUIRED,
                        index,
                        f"required '{name}' missing",
                        f"Include '{name}'.",
                    )
                )
        else:
            violations.extend(_validate_field(domain, fspec, record[name], index))

    # Unknown / forbidden extra fields (closed schema => fail-closed).
    for name in record:
        if name not in known:
            violations.append(
                _violation(
                    domain,
                    name,
                    ViolationCode.UNKNOWN_FIELD,
                    index,
                    f"unknown field '{name}' (schema is closed)",
                    "Remove the field or open a new schema version via ADR.",
                )
            )

    return sorted(violations)


def core_fingerprint(spec: CanonicalSchemaSpec) -> str:
    """Stable SHA-256 over the frozen core (version + identity + temporal + domains).

    Any change to the core without a version bump changes this fingerprint and
    breaks the compatibility test, per HOS-002 acceptance criteria.
    """

    def field_repr(f: FieldSpec) -> dict[str, Any]:
        return {
            "type": f.type,
            "nullable": f.nullable,
            "unit": f.unit,
            "minimum": f.minimum,
            "maximum": f.maximum,
            "values": list(f.values) if f.values else None,
            "sensitivity": f.sensitivity.value,
        }

    core = {
        "version": spec.version,
        "timezone": spec.timezone,
        # The closed `extensions` zone is part of the frozen contract (ADR-0001):
        # reopening it must break the compatibility gate.
        "extensions_status": spec.extensions_status,
        "identity": {n: field_repr(f) for n, f in sorted(spec.identity.items())},
        "temporal": {n: field_repr(f) for n, f in sorted(spec.temporal.items())},
        "domains": {
            d: {n: field_repr(f) for n, f in sorted(ds.fields.items())}
            for d, ds in sorted(spec.domains.items())
        },
    }
    payload = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Pinned fingerprint of Canonical Schema v1.0.0 core. Regenerate ONLY together
# with a version bump: `python -m services.connectors.schemas.canonical_schema`.
FROZEN_CORE_FINGERPRINT: str = "4e0d96bb9d45e9d10b2d4c274730274a6167ffed4fba89a8dcecb2eb5bf1e138"


def stamp_provenance(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Attach schema version + run_id to a pipeline output (HOS-012 provenance)."""
    stamped = dict(payload)
    stamped["schema_version"] = SCHEMA_VERSION
    stamped["run_id"] = run_id
    return stamped


if __name__ == "__main__":  # pragma: no cover - developer utility
    _spec = load_canonical_schema()
    print(f"Canonical Schema v{_spec.version}")
    print(f"core_fingerprint = {core_fingerprint(_spec)}")
