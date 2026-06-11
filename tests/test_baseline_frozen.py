"""Immutability lock for the frozen v1 baseline artifact."""

from __future__ import annotations

import hashlib
from pathlib import Path


def test_frozen_baseline_sha256_matches_sidecar() -> None:
    """Frozen baseline JSON changes only when the SHA sidecar is updated too."""
    baseline_path = Path("artifacts/baseline_v1.json")
    sha_path = Path("artifacts/baseline_v1.sha256")
    expected = sha_path.read_text(encoding="utf-8").strip()
    actual = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    assert actual == expected
