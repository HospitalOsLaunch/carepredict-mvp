from __future__ import annotations

from pathlib import Path

import pytest

from hfwm.corpus import CorpusConfig, TemporalCorpus, build_temporal_corpus
from hfwm.data_slice import build_point_in_time_data_slice
from p0d import sha256_json


@pytest.fixture(scope="module")
def corpus() -> TemporalCorpus:
    return build_temporal_corpus(
        CorpusConfig(
            organization_count=3,
            episodes_per_unit=4,
            episode_hours=96,
            history_hours=20,
            horizons_hours=(6, 24),
            purge_gap_hours=24,
            window_stride_hours=6,
        )
    )


def test_deterministic_dataset_build(corpus: TemporalCorpus) -> None:
    first = build_point_in_time_data_slice(corpus=corpus)
    second = build_point_in_time_data_slice(corpus=corpus)

    assert first.dataset_hash == second.dataset_hash
    assert first.dataset == second.dataset
    payload = {key: value for key, value in first.dataset.items() if key != "dataset_hash"}
    assert sha256_json(payload) == first.dataset_hash
    assert first.dataset_manifest["targets"] == [
        {"name": "occupancy", "unit": "patients", "aggregation": "end_of_horizon"},
        {"name": "inflow", "unit": "patients/6h", "aggregation": "sum_over_horizon"},
    ]


def test_temporal_leakage(corpus: TemporalCorpus) -> None:
    result = build_point_in_time_data_slice(corpus=corpus)
    report = result.temporal_leakage_report
    rows = result.dataset["rows"]

    assert report["status"] == "PASS"
    assert report["temporal_violation_count"] == 0
    assert report["cross_split_contamination_count"] == 0
    assert report["overlapping_episode_count"] == 0
    assert isinstance(rows, list)
    assert all(isinstance(row, dict) and row["feature_snapshot_id"] for row in rows)


def test_split_before_windowing(corpus: TemporalCorpus) -> None:
    result = build_point_in_time_data_slice(corpus=corpus)
    assignments = result.split_manifest["assignments"]
    rows = result.dataset["rows"]
    assert isinstance(assignments, list)
    assert isinstance(rows, list)
    split_by_episode = {
        row["episode_id"]: row["split"] for row in assignments if isinstance(row, dict)
    }

    assert result.dataset_manifest["split_before_windowing"] is True
    assert set(split_by_episode.values()) == {"train", "validation", "test"}
    assert all(
        row["split"] == split_by_episode[row["episode_id"]]
        for row in rows
        if isinstance(row, dict)
    )


def test_export_contains_required_artifacts(
    corpus: TemporalCorpus, tmp_path: Path
) -> None:
    result = build_point_in_time_data_slice(corpus=corpus)
    paths = result.export(tmp_path)

    assert {path.name for path in paths} == {
        "dataset.json",
        "dataset_manifest.json",
        "split_manifest.json",
        "temporal_leakage_report.json",
    }
    assert all(path.read_bytes().endswith(b"\n") for path in paths)
