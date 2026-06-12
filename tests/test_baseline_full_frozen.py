"""Immutability lock for the frozen full-window v1 baseline artifact."""

from __future__ import annotations

import hashlib
from pathlib import Path


def test_frozen_full_baseline_sha256_matches_sidecar() -> None:
    """Frozen full-window baseline JSON changes only when its SHA sidecar is updated too."""
    baseline_path = Path("artifacts/baseline_v1_full.json")
    sha_path = Path("artifacts/baseline_v1_full.sha256")
    expected = sha_path.read_text(encoding="utf-8").strip()
    actual = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    assert actual == expected
