"""Canonical serialization and content-addressed manifests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON-compatible data deterministically."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """Return a lowercase SHA-256 digest."""
    return hashlib.sha256(value).hexdigest()


def semantic_hash(value: Any) -> str:
    """Hash structured content after canonical JSON serialization."""
    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: Path) -> str:
    """Hash a file without modifying it."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ManifestEntry:
    """One immutable manifest entry."""

    logical_name: str
    sha256: str
    size_bytes: int


def build_file_manifest(paths: Iterable[Path], *, root: Path) -> dict[str, Any]:
    """Build an in-memory deterministic manifest for files below ``root``."""
    resolved_root = root.resolve(strict=True)
    entries: list[ManifestEntry] = []
    for candidate in sorted(paths, key=lambda item: item.as_posix()):
        resolved = candidate.resolve(strict=True)
        try:
            logical_name = resolved.relative_to(resolved_root).as_posix()
        except ValueError as exc:
            raise ValueError(f"manifest path escapes root: {candidate}") from exc
        if not resolved.is_file():
            raise ValueError(f"manifest entry is not a file: {candidate}")
        entries.append(
            ManifestEntry(
                logical_name=logical_name,
                sha256=sha256_file(resolved),
                size_bytes=resolved.stat().st_size,
            )
        )
    payload = {
        "schema_version": "hfwm.file-manifest.v1",
        "entries": [entry.__dict__ for entry in entries],
    }
    return {**payload, "manifest_sha256": semantic_hash(payload)}


def verify_file_manifest(manifest: Mapping[str, Any], *, root: Path) -> list[str]:
    """Return deterministic validation errors for a file manifest."""
    errors: list[str] = []
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list):
        return ["entries must be a list"]
    expected_payload = {
        "schema_version": manifest.get("schema_version"),
        "entries": raw_entries,
    }
    if manifest.get("manifest_sha256") != semantic_hash(expected_payload):
        errors.append("manifest_sha256 mismatch")
    for index, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            errors.append(f"entries[{index}] must be an object")
            continue
        logical_name = entry.get("logical_name")
        if not isinstance(logical_name, str):
            errors.append(f"entries[{index}].logical_name must be a string")
            continue
        path = root / logical_name
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root.resolve(strict=True))
        except (FileNotFoundError, ValueError):
            errors.append(f"missing or escaping manifest path: {logical_name}")
            continue
        if not resolved.is_file():
            errors.append(f"manifest path is not a file: {logical_name}")
            continue
        if entry.get("size_bytes") != resolved.stat().st_size:
            errors.append(f"size mismatch: {logical_name}")
        if entry.get("sha256") != sha256_file(resolved):
            errors.append(f"sha256 mismatch: {logical_name}")
    return sorted(errors)
