"""Strict, dependency-free serialization primitives for HFWM contracts."""

from __future__ import annotations

import hashlib
import json
import math
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TypeAlias, cast

JSONScalar: TypeAlias = None | bool | int | float | str
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


class ContractValidationError(ValueError):
    """Raised when an external payload does not satisfy an HFWM contract."""


def _validate_json(value: JSONValue, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError(f"{path}: non-finite floats are forbidden")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractValidationError(f"{path}: object keys must be strings")
            _validate_json(item, f"{path}.{key}")
        return
    raise ContractValidationError(f"{path}: unsupported JSON type {type(value).__name__}")


def canonical_json_bytes(value: JSONValue) -> bytes:
    """Return the sole canonical byte representation used by HFWM-R0.

    The representation is deterministic across mapping insertion orders. It is not
    claimed to implement RFC 8785; the exact local contract is versioned here.
    """

    _validate_json(value)
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def semantic_sha256(value: JSONValue) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def parse_json_bytes(raw: bytes) -> JSONValue:
    try:
        parsed = cast(JSONValue, json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractValidationError("payload is not valid UTF-8 JSON") from error
    _validate_json(parsed)
    return parsed


def strict_object(
    value: JSONValue,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    path: str = "$",
) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{path}: expected object")
    actual = frozenset(value)
    missing = required - actual
    unknown = actual - required - optional
    if missing:
        raise ContractValidationError(f"{path}: missing fields {sorted(missing)}")
    if unknown:
        raise ContractValidationError(f"{path}: unknown fields {sorted(unknown)}")
    return value


def require_string(value: JSONValue, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(f"{path}: expected string")
    if not allow_empty and not value.strip():
        raise ContractValidationError(f"{path}: empty string is forbidden")
    return value


def require_bool(value: JSONValue, path: str) -> bool:
    if not isinstance(value, bool):
        raise ContractValidationError(f"{path}: expected boolean")
    return value


def require_int(value: JSONValue, path: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{path}: expected integer")
    if minimum is not None and value < minimum:
        raise ContractValidationError(f"{path}: must be >= {minimum}")
    return value


def require_number(value: JSONValue, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{path}: expected number")
    number = float(value)
    if not math.isfinite(number):
        raise ContractValidationError(f"{path}: non-finite number is forbidden")
    return number


def require_object(value: JSONValue, path: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{path}: expected object")
    return value


def require_list(value: JSONValue, path: str) -> list[JSONValue]:
    if not isinstance(value, list):
        raise ContractValidationError(f"{path}: expected array")
    return value


def require_string_tuple(value: JSONValue, path: str) -> tuple[str, ...]:
    items = require_list(value, path)
    result = tuple(require_string(item, f"{path}[{index}]") for index, item in enumerate(items))
    if len(result) != len(set(result)):
        raise ContractValidationError(f"{path}: duplicate values are forbidden")
    return result


def require_timestamp(value: JSONValue, path: str) -> str:
    timestamp = require_string(value, path)
    normalized = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ContractValidationError(f"{path}: expected an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractValidationError(f"{path}: timezone offset is required")
    return timestamp


def json_mapping(value: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    """Make an owned JSON mapping and validate it recursively."""

    result = dict(value)
    _validate_json(result)
    return result


def json_sequence(value: Sequence[JSONValue]) -> list[JSONValue]:
    result = list(value)
    _validate_json(result)
    return result


class StableContract(ABC):
    """Mixin for immutable contracts with deterministic bytes and hashes."""

    @abstractmethod
    def to_dict(self) -> dict[str, JSONValue]:
        """Return the complete versioned payload."""

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def semantic_hash(self) -> str:
        return semantic_sha256(self.to_dict())
