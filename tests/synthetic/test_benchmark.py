"""Leakage, common coverage, hierarchy, held-out worlds and frozen execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from hospitalos.synthetic import benchmark as b
from hospitalos.synthetic.asof import AsOfRow, Source
from hospitalos.synthetic.cohort import _sha, freeze, materialize
from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.generate import _csv
from hospitalos.synthetic.observations import ObservedState
from hospitalos.synthetic.registry import CohortPlan


@pytest.fixture
def config() -> HospitalConfig:
    return HospitalConfig.model_validate(
        {
            "hospital_id": "H",
            "seed": 1,
            "start": "2025-01-01",
            "days": 10,
            "warmup_days": 0,
            "partition": "train",
            "poles": [
                {
                    "pole_id": f"P{i}",
                    "units": [
                        {
                            "unit_id": f"U{i}",
                            "template": "CSG",
                            "beds": 20,
                            "isolation_beds": 0,
                            "oxygen_beds": 0,
                        }
                    ],
                }
                for i in range(2)
            ],
        }
    )


def rows_for(config: HospitalConfig) -> list[AsOfRow]:
    rows = []
    for hour in range(config.days * 24):
        for unit in config.units:
            values = dict.fromkeys(b.FIELDS, 0)
            values.update(lits_ouverts=20, lits_occupes=hour, attente_urgences_nb=hour)
            rows.append(
                AsOfRow(
                    sample_id=f"R:{unit.unit_id}@{hour}",
                    run_id="R",
                    hospital_id=config.hospital_id,
                    entity_id=unit.unit_id,
                    level="unit",
                    partition=config.partition,
                    decision_h=hour,
                    total_units=1,
                    observed_units=1,
                    missing=False,
                    stale=False,
                    stale_after_h=6.0,
                    max_age_h=0.0,
                    max_available_h=float(hour),
                    sources=(
                        Source(
                            unit_id=unit.unit_id,
                            event_id=f"E_{unit.unit_id}_{hour}",
                            version=1,
                            event_h=float(hour),
                            available_h=float(hour),
                        ),
                    ),
                    values=ObservedState.model_validate(values),
                )
            )
    return rows


def test_seasonality_points_to_target_week_not_decision_week(config: HospitalConfig) -> None:
    samples = b.prepare_samples(rows_for(config), config, "R")
    assert samples.rows[0].decision_h == 168
    assert samples.persistence[0, 0] == 168
    assert samples.seasonal[0, 0] == 24  # target 192 - one week = 24, not 0
    assert samples.x[0, b.feature_names().index("lag24_lits_occupes_per_open_bed")] == 144 / 20
    assert samples.x[0, b.feature_names().index("lag168_lits_occupes_per_open_bed")] == 0


def test_future_observations_cannot_change_earlier_features(config: HospitalConfig) -> None:
    original = rows_for(config)
    changed = [
        row.model_copy(update={"values": row.values.model_copy(update={"lits_occupes": 9999})})
        if row.decision_h > 180 and row.values
        else row
        for row in original
    ]
    a, z = [b.prepare_samples(rows, config, "R") for rows in (original, changed)]
    mask = np.array([r.decision_h <= 180 for r in a.rows])
    np.testing.assert_array_equal(a.x[mask], z.x[mask])
    np.testing.assert_array_equal(a.seasonal[mask], z.seasonal[mask])


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "world", "source", "sample"])
def test_feature_mutations_fail(config: HospitalConfig, mutation: str) -> None:
    rows = rows_for(config)
    if mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "missing":
        rows.pop()
    else:
        options: dict[str, dict[str, Any]] = {
            "world": {"hospital_id": "OTHER"},
            "source": {"sources": (rows[0].sources[0].model_copy(update={"unit_id": "U1"}),)},
            "sample": {"sample_id": "R:U1@0"},
        }
        rows[0] = rows[0].model_copy(update=options[mutation])
    with pytest.raises(ValueError):
        b.prepare_samples(rows, config, "R")


def test_common_abstention_and_exact_hierarchical_sums(config: HospitalConfig) -> None:
    rows = rows_for(config)
    # Only one unit's seasonal observation is unavailable for decision 168.
    rows[48] = rows[48].model_copy(
        update={
            "values": None,
            "missing": True,
            "sources": (),
            "observed_units": 0,
            "max_age_h": None,
            "max_available_h": None,
        }
    )
    samples = b.prepare_samples(rows, config, "R")
    forecasts, _ = b.aggregate_predictions(
        samples,
        {
            b.METHODS[0]: samples.persistence,
            b.METHODS[1]: samples.seasonal,
            b.METHODS[2]: np.ones_like(samples.persistence),
        },
        config,
    )
    for method in b.METHODS:
        at168 = {
            r["entity_id"]: r for r in forecasts if r["decision_h"] == 168 and r["method"] == method
        }
        assert at168["H"]["status"] == at168["U0"]["status"] == "common_support_abstention"
        assert at168["U1"]["status"] == "available"
        at169 = {
            r["entity_id"]: r for r in forecasts if r["decision_h"] == 169 and r["method"] == method
        }
        for target in b.TARGETS:
            key = f"prediction_{target}"
            assert at169["H"][key] == at169["U0"][key] + at169["U1"][key]
            assert at169["P0"][key] == at169["U0"][key]


def test_metrics_do_not_weight_larger_hospitals_more() -> None:
    metrics = []
    for hospital, replicates, units, error in (("A", 2, 3, 1), ("B", 1, 1, 9)):
        for rep in range(replicates):
            for unit in range(units):
                metrics.append(
                    {
                        "hospital_id": hospital,
                        "world_id": f"{hospital}{rep}",
                        "entity_id": f"U{unit}",
                        "method": b.METHODS[0],
                        "level": "unit",
                        "target": b.TARGETS[0],
                        "n_scored": 100,
                        "coverage": 1.0,
                        "mae": error,
                        "rmse": error,
                        "bias": error,
                    }
                )
    report = b.summarize(metrics)
    assert report["macro"][0]["mae"] == 5
    assert report["macro"][0]["n_hospitals"] == 2


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    root = tmp_path_factory.mktemp("benchmark")
    raw = json.loads(Path("configs/synthetic/cohort_baselines_v1.json").read_text())
    raw.update(cohort_id="C_BENCH_FIXTURE", days=10, warmup_days=2)
    for structure in raw["structures"]:
        structure.update(hospitals=1, replicates=1)
    registry, cohort, protocol = root / "registry", root / "cohort", root / "protocol.json"
    freeze(CohortPlan.model_validate(raw), registry)
    materialize(registry, cohort, with_learning=True)
    b.freeze_protocol(registry, cohort, protocol)
    return registry, cohort, protocol


def test_training_does_not_use_validation_labels_and_outputs_reproduce(
    dataset: tuple[Path, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, cohort, protocol = dataset
    first = b.run_benchmark(registry, cohort, protocol, tmp_path / "first")
    original = b.read_targets

    def changed(root: Path, samples: b.Samples, config: HospitalConfig) -> b.FloatArray:
        values = original(root, samples, config)
        if config.partition == "validation":
            # The fitted artifact must already exist before ANY validation-label read.
            assert len(list(tmp_path.glob(".benchmark-*/benchmark/models.pkl"))) == 1
            assert list(tmp_path.glob(".benchmark-*/benchmark/*_predictions.csv"))
            return values + 10000
        return values

    monkeypatch.setattr(b, "read_targets", changed)
    second = b.run_benchmark(registry, cohort, protocol, tmp_path / "second")
    assert (tmp_path / "first/models.pkl").read_bytes() == (
        tmp_path / "second/models.pkl"
    ).read_bytes()
    for path in (tmp_path / "first").glob("*_predictions.csv"):
        assert path.read_bytes() == (tmp_path / "second" / path.name).read_bytes()
    assert first["macro"] != second["macro"]
    assert not first["test_opened"]
    manifest = json.loads((tmp_path / "first/manifest.json").read_text())
    for name, sha in manifest["files_sha256"].items():
        assert _sha(tmp_path / "first" / name) == sha
    assert not (cohort / "test").exists()
    assert len(manifest["reserved_test_worlds"]) == 1
    # All methods have the same coverage; no method-specific easy subset.
    assert len({r["coverage"] for r in first["macro"] if r["level"] == "unit"}) == 1
    assert sum(r["n_fit"] for r in first["training_rows"]) > 0


def test_protocol_is_immutable_and_changes_rejected(
    dataset: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    registry, cohort, protocol = dataset
    with pytest.raises(FileExistsError):
        b.freeze_protocol(registry, cohort, protocol)
    altered = json.loads(protocol.read_text())
    altered["model_parameters"]["max_iter"] = 2
    forged = tmp_path / "protocol.json"
    forged.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="Frozen protocol"):
        b.run_benchmark(registry, cohort, forged, tmp_path / "no_result")
    assert not (tmp_path / "no_result").exists()


@pytest.mark.parametrize("mutation", ["test", "world", "missing", "checksum", "path"])
def test_cohort_mutations_rejected(
    dataset: tuple[Path, Path, Path],
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, cohort, _ = dataset
    path = cohort / "manifest.json"
    content = json.loads(path.read_text())
    if mutation == "test":
        content["test_access"]["opened"] = True
    elif mutation == "world":
        content["worlds"][0]["hospital_id"] = "FORGED"
    elif mutation == "missing":
        content["worlds"].pop()
    elif mutation == "checksum":
        content["worlds"][0]["learning_manifest_sha256"] = "FORGED"
    else:
        content["worlds"][0]["learning_path"] = "../outside"
    original = Path.read_text

    def read(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == path:
            return json.dumps(content)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError):
        b.verify_inputs(registry, cohort)


@pytest.mark.parametrize("mutation", ["censor", "horizon", "duplicate", "missing", "nan"])
def test_label_mutations_rejected(
    dataset: tuple[Path, Path, Path],
    tmp_path: Path,
    mutation: str,
) -> None:
    registry_path, cohort, _ = dataset
    registry, records = b.verify_inputs(registry_path, cohort)
    record = records[0]
    world = next(w for w in registry.worlds if w.world_id == record["world_id"])
    root = cohort / record["learning_path"]
    samples = b.read_samples(root, world, record)
    y = b.read_targets(root, samples, world.config)
    assert np.isnan(y[-1]).all()
    assert np.isfinite(y[0]).all()
    # Exercise the exact censor boundary: t+24 == end remains observable.
    boundary = next(
        i for i, r in enumerate(samples.rows) if r.decision_h + 24 == world.config.days * 24
    )
    assert np.isfinite(y[boundary]).all()
    import csv

    with (root / "targets/occupancy_load_queue_24h.csv").open() as stream:
        labels = list(csv.DictReader(stream))
    sid = samples.rows[-1 if mutation == "censor" else 0].sample_id
    row = next(r for r in labels if r["sample_id"] == sid)
    if mutation == "censor":
        row[f"target_{b.TARGETS[0]}"] = "1"
    elif mutation == "horizon":
        row["target_h"] = str(int(row["target_h"]) + 1)
    elif mutation == "duplicate":
        labels.append(row)
    elif mutation == "missing":
        labels.remove(row)
    else:
        row[f"target_{b.TARGETS[0]}"] = "nan"
    (tmp_path / "targets").mkdir()
    _csv(tmp_path / "targets/occupancy_load_queue_24h.csv", labels)
    with pytest.raises(ValueError):
        b.read_targets(tmp_path, samples, world.config)
