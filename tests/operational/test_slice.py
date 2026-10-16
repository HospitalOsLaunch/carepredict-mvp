"""Adapter conservation, common-consumer invariants and first learned forecast."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pytest
import torch

from hospitalos.operational.adapter import (
    LEGACY_CLOCK,
    boundary,
    convert,
    export,
    load_observed,
)
from hospitalos.operational.contract import Cursor
from hospitalos.operational.experiment import run, targets
from hospitalos.operational.forecast import (
    TopologyForecaster,
    baseline_predictions,
    build_inputs,
    climatology,
    fit,
    predict,
    score,
)
from hospitalos.synthetic.config import HospitalConfig, load_config
from hospitalos.synthetic.generate import generate
from hospitalos.synthetic.learning import _digest, _events
from hospitalos.synthetic.observations import observe_snapshots


@pytest.fixture(scope="module")
def sample(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, HospitalConfig]:
    root = tmp_path_factory.mktemp("common-interface")
    raw = json.loads(Path("configs/synthetic/hospital_two_poles.json").read_text())
    raw.update(days=12, warmup_days=3)
    raw["documentary"] = {
        "staff_forecasts": "milestones_v1",
        "downstream_confirmation": "request_delay_v1",
    }
    config = HospitalConfig.model_validate(raw)
    generate(config, root / "truth")
    export(root / "truth", root / "observed")
    return root / "truth", root / "observed", config


def test_export_round_trip_and_coarse_feeds_hide_fine_values(
    sample: tuple[Path, Path, HospitalConfig],
) -> None:
    _, path, config = sample
    for mode in ("unit", "pole", "hospital"):
        topo, stream, metadata = load_observed(path, mode)
        assert all(o.level == mode for o in stream)
        cursor = Cursor()
        cursor.advance(boundary(config, config.days * 24), stream, topo)
        assert set(cursor.latest) == set(metadata["modes"][mode]["frontier"])
        assert all("siips_score" not in o.values for o in stream)
        assert metadata["claims"]["engine_europe_paris"] is False


def test_aggregate_uses_same_event_time_and_latest_available_members(
    sample: tuple[Path, Path, HospitalConfig],
) -> None:
    source, path, config = sample
    topo, coarse, _ = load_observed(path, "hospital")
    observed = observe_snapshots(_events(source), config)
    first = coarse[0]
    available = [
        r
        for r in observed
        if boundary(config, r.available_h) <= first.available_at
        and boundary(config, r.event_h) == first.event_time
    ]
    latest = {}
    for row in sorted(available, key=lambda r: r.event_version):
        latest[row.unit_id] = row
    assert first.values["occupancy"] == sum(r.values.lits_occupes for r in latest.values())
    assert len(latest) == len(config.units)
    # Mixed unit/pole coverage is supported without overlapping contributions.
    ids = tuple(u.unit_id for u in config.poles[0].units) + (config.poles[1].pole_id,)
    mixed = convert(observed, config, topo, ids)
    assert {o.level for o in mixed} == {"unit", "pole"}


def test_asof_features_prefix_unchanged_by_future_receipts(
    sample: tuple[Path, Path, HospitalConfig],
) -> None:
    _, path, config = sample
    topo, stream, meta = load_observed(path, "unit")
    start = boundary(config)
    args = (topo, stream, meta["modes"]["unit"]["frontier"], start, config.days * 24)
    full = build_inputs(*args, timezone=LEGACY_CLOCK)
    cutoff = full.origins[2]
    shortened = build_inputs(
        topo,
        [o for o in stream if o.available_at <= cutoff],
        args[2],
        start,
        config.days * 24,
        timezone=LEGACY_CLOCK,
    )
    np.testing.assert_array_equal(full.x[:3], shortened.x[:3])
    assert np.isfinite(full.x).all()
    # Same-clock reference is physically known before the origin, not truth at T.
    assert full.ages.min() >= 0


def test_permutation_equivariance_and_new_node_counts() -> None:
    torch.manual_seed(9)
    model = TopologyForecaster(8).eval()
    x = torch.randn(2, 3, 8)
    a = torch.eye(3)
    order = torch.tensor([2, 0, 1])
    torch.testing.assert_close(model(x[:, order], a[order][:, order]), model(x, a)[:, order])
    assert model(torch.randn(2, 7, 8), torch.eye(7)).shape == (2, 7, 3)


def test_fit_and_all_origin_coherent_mean_scores(sample: tuple[Path, Path, HospitalConfig]) -> None:
    source, path, config = sample
    topo, stream, meta = load_observed(path, "unit")
    data = build_inputs(
        topo,
        stream,
        meta["modes"]["unit"]["frontier"],
        boundary(config),
        config.days * 24,
        timezone=LEGACY_CLOCK,
    )
    y = targets(source, data, _digest(source / "manifest.json"))
    model, losses = fit([data], [y], epochs=3, seed=9, learning_rate=0.002, batch_size=16)
    assert np.isfinite(losses).all()
    p = predict(model, data)
    assert p.shape == y.shape and (p >= 0).all()
    climate = climatology([data], [y])
    methods = {**baseline_predictions(data, climate), "topology_mlp": p}
    scored = score(data, y, methods)
    hosp = [
        r
        for r in scored
        if r["entity_id"] == config.hospital_id
        and r["target"] == "occupancy"
        and r["method"] == "topology_mlp"
        and r["regime"] == "all"
    ][0]
    assert hosp["n"] == len(data.origins)
    assert hosp["mse"] == pytest.approx(
        np.mean((p[:, :, 0].sum(axis=1) - y[:, :, 0].sum(axis=1)) ** 2)
    )
    before = predict(model, data)
    y[:] = 9999  # Scoring labels cannot change predictions or fit an already frozen model.
    np.testing.assert_array_equal(before, predict(model, data))


def test_coarse_input_cannot_publish_unit_predictions(
    sample: tuple[Path, Path, HospitalConfig],
) -> None:
    source, path, config = sample
    topo, stream, meta = load_observed(path, "hospital")
    data = build_inputs(
        topo,
        stream,
        meta["modes"]["hospital"]["frontier"],
        boundary(config),
        config.days * 24,
        timezone=LEGACY_CLOCK,
    )
    y = targets(source, data, _digest(source / "manifest.json"))
    rows = score(data, y, {"perfect": y})
    assert {r["level"] for r in rows} == {"hospital"}


def test_reserved_test_rejected_before_truth_read(tmp_path: Path) -> None:
    config = load_config(Path("configs/synthetic/hospital_two_poles.json"))
    raw = config.model_dump(mode="json")
    raw["partition"] = "test"
    (tmp_path / "config.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="Reserved test"):
        export(tmp_path, tmp_path / "output")


def test_corrupt_observed_payload_rejected(
    sample: tuple[Path, Path, HospitalConfig], tmp_path: Path
) -> None:
    import shutil

    _, path, _ = sample
    shutil.copytree(path, tmp_path / "changed")
    (tmp_path / "changed/observations/unit.jsonl.gz").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        load_observed(tmp_path / "changed", "unit")


def test_incomplete_cohort_is_rejected_before_training(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text('{"status":"incomplete"}')
    with pytest.raises(ValueError, match="cohort"):
        run(tmp_path, tmp_path / "out")


def test_pipeline_freezes_validation_before_labels_and_reloads_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hospitalos.operational import experiment
    from hospitalos.operational.forecast import FloatArray, Inputs, load_frozen_model

    plan = json.loads(Path("configs/operational/experiment_v1.json").read_text())
    plan.update(
        days=12,
        warmup_days=3,
        train_unit_counts=[2],
        validation_unit_counts=[3],
        reserved_test_unit_counts=[4],
        modes=["unit", "hospital"],
        epochs=1,
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))
    cohort = tmp_path / "cohort"
    experiment.prepare(plan_path, cohort)
    assert not (cohort / "H15_test_00").exists()
    original = experiment.targets
    opened: list[str] = []

    def spy(source: Path, data: Inputs, expected_manifest: str) -> FloatArray:
        if "validation" in str(source):
            frozen = list(tmp_path.glob(".experiment15-*/result/predictions_frozen.json"))
            assert len(frozen) == 1
            hashes = json.loads(frozen[0].read_text())
            for name, digest in hashes.items():
                assert _digest(frozen[0].parent / "predictions" / name) == digest
            opened.append("validation")
        return original(source, data, expected_manifest)

    monkeypatch.setattr(experiment, "targets", spy)
    output = tmp_path / "result"
    experiment.run(cohort, output)
    assert len(opened) == 2
    model = load_frozen_model(output)
    observed = cohort / "H15_validation_00/observed"
    topo, stream, metadata = load_observed(observed, "unit")
    data = build_inputs(
        topo,
        stream,
        metadata["modes"]["unit"]["frontier"],
        dt.datetime.fromisoformat(metadata["start"]),
        plan["days"] * 24,
        timezone=LEGACY_CLOCK,
    )
    with np.load(output / "predictions/H15_validation_00_unit.npz") as saved:
        np.testing.assert_array_equal(saved["topology_mlp"], predict(model, data))
