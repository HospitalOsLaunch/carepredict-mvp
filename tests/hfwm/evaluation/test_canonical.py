"""Tests for deterministic content-addressed manifests."""

from __future__ import annotations

from pathlib import Path

from hfwm.evaluation.canonical import (
    build_file_manifest,
    canonical_json_bytes,
    semantic_hash,
    verify_file_manifest,
)


def test_canonical_json_and_hash_ignore_mapping_order() -> None:
    """Canonical identities do not depend on insertion order."""
    left = {"b": [2, 1], "a": {"z": True}}
    right = {"a": {"z": True}, "b": [2, 1]}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert semantic_hash(left) == semantic_hash(right)


def test_manifest_is_deterministic_and_detects_change(tmp_path: Path) -> None:
    """Manifest order is stable and content changes fail verification."""
    first = tmp_path / "b.txt"
    second = tmp_path / "a.txt"
    first.write_text("bravo", encoding="utf-8")
    second.write_text("alpha", encoding="utf-8")
    manifest = build_file_manifest([first, second], root=tmp_path)
    assert [entry["logical_name"] for entry in manifest["entries"]] == ["a.txt", "b.txt"]
    assert verify_file_manifest(manifest, root=tmp_path) == []
    first.write_text("changed", encoding="utf-8")
    assert verify_file_manifest(manifest, root=tmp_path) == [
        "sha256 mismatch: b.txt",
        "size mismatch: b.txt",
    ]


def test_manifest_rejects_path_outside_root(tmp_path: Path) -> None:
    """Logical manifests cannot address files outside their declared root."""
    child = tmp_path / "child"
    child.mkdir()
    external = tmp_path / "outside.txt"
    external.write_text("x", encoding="utf-8")
    try:
        build_file_manifest([external], root=child)
    except ValueError as exc:
        assert "escapes root" in str(exc)
    else:
        raise AssertionError("escaping path was accepted")
