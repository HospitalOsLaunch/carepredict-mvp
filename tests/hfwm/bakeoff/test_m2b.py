"""Pre-run integrity tests for the frozen M2B execution harness."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

from hfwm.bakeoff.m2b import (
    DATASET_HASH,
    FROZEN_BUNDLE_SHA256,
    FROZEN_MANIFEST_SHA256,
    M2BExecutionError,
    _authorize,
    _load_episodes,
    _train_iqr,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PREREGISTRATION = REPOSITORY_ROOT / "docs" / "research" / "hfwm"


def test_frozen_protocol_resolves_exact_m1_slice_without_running_models() -> None:
    """Authorization and data identity are checked before any model fit."""

    protocol = _authorize(REPOSITORY_ROOT, PREREGISTRATION)
    episodes, _ = _load_episodes(Path(protocol["dataset_path"]))
    split_counts = {
        split: len([episode for episode in episodes if episode.split == split])
        for split in ("train", "validation", "test")
    }
    train_iqr = _train_iqr([episode for episode in episodes if episode.split == "train"])

    assert protocol["document"]["m1_references"]["dataset_hash"] == DATASET_HASH
    assert (
        FROZEN_MANIFEST_SHA256 == "0115779941afea37605a0e221e8f82bf2494349aee92fdb339455dc572a334e2"
    )
    assert (
        FROZEN_BUNDLE_SHA256 == "384c4e5ae707edabcf19523b5fd782f4301ca405722aa71fab31d90e141c37e6"
    )
    assert split_counts == {"train": 42, "validation": 9, "test": 9}
    assert np.all(train_iqr > 0.0)


def test_authorization_rejects_any_post_preregistration_manifest_change(
    tmp_path: Path,
) -> None:
    """A changed threshold or metric cannot silently start the M2B run."""

    copied = tmp_path / "hfwm"
    shutil.copytree(PREREGISTRATION, copied)
    manifest = copied / "HFWM_R0_BAKEOFF.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(M2BExecutionError, match="manifest hash changed"):
        _authorize(REPOSITORY_ROOT, copied)
