"""Cohort isolation, reproducibility, tamper detection and end-to-end materialization."""

from __future__ import annotations

import gzip
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hospitalos.synthetic import cohort
from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.registry import (
    CohortPlan,
    Registry,
    World,
    compile_registry,
    structure_key,
    validate_worlds,
)

EXAMPLE = Path(__file__).resolve().parents[2] / "configs/synthetic/cohort_structures_v1.json"


@pytest.fixture
def raw() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(EXAMPLE.read_text())
    value.update(cohort_id="C_TEST_FIXTURE", days=2, warmup_days=2)
    for spec in value["structures"]:
        spec["hospitals"] = 1
    return value


@pytest.fixture
def plan(raw: dict[str, Any]) -> CohortPlan:
    return CohortPlan.model_validate(raw)


def test_replicates_share_hospital_parameters_and_partition(plan: CohortPlan) -> None:
    registry = compile_registry(plan)
    assert len(registry.worlds) == 6
    assert len({w.config.hospital_id for w in registry.worlds}) == 3
    assert len({w.config.seed for w in registry.worlds}) == 6
    for hospital in {w.config.hospital_id for w in registry.worlds}:
        runs = [w.config for w in registry.worlds if w.config.hospital_id == hospital]
        assert runs[0].model_dump(exclude={"seed"}) == runs[1].model_dump(exclude={"seed"})
    assert registry.summary()["mechanism_holdout"] is False


def test_extension_and_structure_reordering_do_not_reshuffle(raw: dict[str, Any]) -> None:
    before = compile_registry(CohortPlan.model_validate(raw))
    raw["structures"].reverse()
    for spec in raw["structures"]:
        spec.update(hospitals=2, replicates=3)
    after = compile_registry(CohortPlan.model_validate(raw))
    for original in before.worlds:
        assert original in after.worlds
    assert before.fingerprint != after.fingerprint


def test_structural_fingerprint_ignores_names_order_and_numeric_parameters(
    plan: CohortPlan,
) -> None:
    original = compile_registry(plan).worlds[0].config
    changed = original.model_dump(mode="json")
    changed.update(hospital_id="H_RENAMED", seed=999, partition="test")
    changed["poles"].reverse()
    for p, pole in enumerate(changed["poles"]):
        pole["pole_id"] = f"OTHER_P{p}"
        pole["units"].reverse()
        for u, unit in enumerate(pole["units"]):
            unit.update(unit_id=f"OTHER_U{p}_{u}", beds=200, arrival_scale=0.5)
    assert structure_key(original) == structure_key(HospitalConfig.model_validate(changed))


def test_renamed_and_reordered_structure_cannot_cross_partitions(raw: dict[str, Any]) -> None:
    duplicate = deepcopy(raw["structures"][0]["poles"])
    duplicate.reverse()
    for pole in duplicate:
        pole.reverse()
    raw["structures"][1]["poles"] = duplicate
    with pytest.raises(ValidationError, match="Structural clone"):
        CohortPlan.model_validate(raw)


def test_hospital_cannot_cross_partitions_even_if_shape_changes(plan: CohortPlan) -> None:
    first, *_, last = compile_registry(plan).worlds
    config = HospitalConfig.model_validate(
        {**last.config.model_dump(), "hospital_id": first.config.hospital_id}
    )
    other = World.model_validate({**last.model_dump(), "config": config})
    with pytest.raises(ValueError, match="hospital crosses"):
        validate_worlds((first, other))


def test_regrouping_poles_does_not_create_unseen_physics(raw: dict[str, Any]) -> None:
    raw["structures"][1]["poles"] = [["MED_POLY"], ["CSG", "PNEUMO", "CARDIO"]]
    with pytest.raises(ValidationError, match="after pole regrouping"):
        CohortPlan.model_validate(raw)


def test_renaming_hospital_does_not_bypass_cross_registry_guard(plan: CohortPlan) -> None:
    first = compile_registry(plan).worlds[0]
    config = HospitalConfig.model_validate(
        {**first.config.model_dump(), "hospital_id": "RENAMED", "seed": 42, "partition": "train"}
    )
    assert first.config.partition == "test"
    other = World.model_validate({**first.model_dump(), "world_id": "OTHER", "config": config})
    with pytest.raises(ValueError, match="structure crosses"):
        validate_worlds((first, other))


def test_g4_claim_refused_with_single_mechanism(raw: dict[str, Any]) -> None:
    raw["split_axis"] = "mechanism"
    with pytest.raises(ValidationError, match="v041 alone cannot test G4"):
        CohortPlan.model_validate(raw)


@pytest.mark.parametrize(
    "field,value",
    [("days", 0), ("seed", True), ("start", "0001-01-01"), ("split_axis", "row_random")],
)
def test_bad_plan(raw: dict[str, Any], field: str, value: Any) -> None:
    raw[field] = value
    with pytest.raises(ValidationError):
        CohortPlan.model_validate(raw)


@pytest.mark.parametrize("kind", ["ranges", "partition", "identity", "count", "mechanism"])
def test_bad_reservation(raw: dict[str, Any], kind: str) -> None:
    if kind == "ranges":
        raw["ranges"]["beds_min"] = 100
    elif kind == "partition":
        raw["structures"][2]["partition"] = "train"
    elif kind == "identity":
        raw["structures"][1]["structure_id"] = raw["structures"][0]["structure_id"]
    elif kind == "count":
        raw["structures"][0]["hospitals"] = 0
    else:
        raw["structures"][0]["mechanism_family"] = "invented"
    with pytest.raises(ValidationError):
        CohortPlan.model_validate(raw)


@pytest.mark.parametrize("mutation", ["omission", "seed", "fingerprint", "duplicate", "parameter"])
def test_registry_mutations_fail(plan: CohortPlan, mutation: str) -> None:
    raw = compile_registry(plan).model_dump(mode="json")
    if mutation == "omission":
        raw["worlds"].pop()
    elif mutation == "seed":
        raw["worlds"][1]["config"]["seed"] = raw["worlds"][0]["config"]["seed"]
    elif mutation == "fingerprint":
        raw["worlds"][0]["structure_sha256"] = "forged"
    elif mutation == "duplicate":
        raw["worlds"].append(raw["worlds"][0])
    else:
        raw["worlds"][1]["config"]["shared_resources"]["imaging"] = 0.1
    with pytest.raises(ValidationError):
        Registry.model_validate(raw)


def test_frozen_registry_reproducible_and_no_overwrite(plan: CohortPlan, tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    cohort.freeze(plan, first)
    cohort.freeze(plan, second)
    for path in first.iterdir():
        assert path.read_bytes() == (second / path.name).read_bytes()
    assert cohort.load_registry(first).plan == plan
    with pytest.raises(FileExistsError):
        cohort.freeze(plan, first)


@pytest.mark.parametrize("target", ["registry", "source", "status", "fingerprint", "runtime"])
def test_tampering_refused(plan: CohortPlan, tmp_path: Path, target: str) -> None:
    source = tmp_path / "registry"
    cohort.freeze(plan, source)
    manifest = json.loads((source / "manifest.json").read_text())
    if target == "registry":
        (source / "registry.json").write_text("{}")
    else:
        field = {
            "source": "source_sha256",
            "status": "status",
            "fingerprint": "registry_sha256",
            "runtime": "runtime",
        }[target]
        manifest[field] = "tampered"
        (source / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        cohort.materialize(source, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_test_partition_requires_explicit_protocol(plan: CohortPlan, tmp_path: Path) -> None:
    cohort.freeze(plan, tmp_path / "registry")
    for protocol in (None, "  "):
        with pytest.raises(ValueError, match="test_protocol"):
            cohort.materialize(
                tmp_path / "registry",
                tmp_path / "output",
                partitions=("test",),
                test_protocol=protocol,
            )
    with pytest.raises(ValueError, match="only valid"):
        cohort.materialize(tmp_path / "registry", tmp_path / "output", test_protocol="PILOT")
    assert not (tmp_path / "output").exists()


def test_atomic_batch_failure_leaves_no_output(
    plan: CohortPlan, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cohort.freeze(plan, tmp_path / "registry")

    def fail(config: HospitalConfig, output: Path) -> dict[str, Any]:
        output.mkdir(parents=True)
        (output / "partial").write_text(config.hospital_id)
        raise ValueError("injected failure")

    monkeypatch.setattr(cohort, "generate", fail)
    with pytest.raises(ValueError, match="injected failure"):
        cohort.materialize(tmp_path / "registry", tmp_path / "output")
    assert list(tmp_path.iterdir()) == [tmp_path / "registry"]


@pytest.fixture(scope="module")
def batch(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any], Registry]:
    raw = json.loads(EXAMPLE.read_text())
    raw.update(cohort_id="C_TEST_FIXTURE", days=2, warmup_days=2)
    for spec in raw["structures"]:
        spec["hospitals"] = 1
    root = tmp_path_factory.mktemp("cohort")
    registry = cohort.freeze(CohortPlan.model_validate(raw), root / "registry")
    manifest = cohort.materialize(root / "registry", root / "first", with_learning=True)
    cohort.materialize(root / "registry", root / "second", with_learning=True)
    return root, manifest, registry


def test_batch_reproducible_and_default_test_unopened(
    batch: tuple[Path, dict[str, Any], Registry],
) -> None:
    root, manifest, registry = batch
    assert len(manifest["worlds"]) == 4
    assert manifest["test_access"] == {"opened": False, "protocol": None}
    assert set(manifest["reserved_world_ids"]) == {
        w.world_id for w in registry.worlds if w.config.partition == "test"
    }
    assert not (root / "first/test").exists()
    for path in (root / "first").rglob("*"):
        if path.is_file():
            assert (
                path.read_bytes()
                == (root / "second" / path.relative_to(root / "first")).read_bytes()
            )
    with pytest.raises(FileExistsError):
        cohort.materialize(root / "registry", root / "first")


def test_every_world_keeps_partition_provenance_and_verified_manifests(
    batch: tuple[Path, dict[str, Any], Registry],
) -> None:
    root, manifest, registry = batch
    assert len({w["learning_run_id"] for w in manifest["worlds"]}) == 4
    for record in manifest["worlds"]:
        world = next(w for w in registry.worlds if w.world_id == record["world_id"])
        assert record["config_sha256"] == world.config.fingerprint
        for role in ("truth", "learning"):
            path = root / "first" / record[f"{role}_path"] / "manifest.json"
            assert (
                hashlib.sha256(path.read_bytes()).hexdigest() == record[f"{role}_manifest_sha256"]
            )
            run = json.loads(path.read_text())
            assert run["partition"] == world.config.partition
            for name, sha in run["files_sha256"].items():
                assert hashlib.sha256((path.parent / name).read_bytes()).hexdigest() == sha
        with gzip.open(
            root / "first" / record["learning_path"] / "features/asof.jsonl.gz", "rt"
        ) as stream:
            rows = [json.loads(line) for line in stream]
        assert len(rows) == world.config.days * 24 * (
            len(world.config.units) + len(world.config.poles) + 1
        )
        assert {r["partition"] for r in rows} == {world.config.partition}
        assert {r["hospital_id"] for r in rows} == {world.config.hospital_id}
        assert all(v == 0 for k, v in record["checks"].items() if k != "heures_controlees")


def test_explicit_test_release_is_logged(batch: tuple[Path, dict[str, Any], Registry]) -> None:
    # A disposable two-day fixture, never the reserved annual benchmark.
    root, _, _ = batch
    manifest = cohort.materialize(
        root / "registry", root / "released", partitions=("test",), test_protocol="UNIT_TEST_ONLY"
    )
    assert manifest["test_access"] == {"opened": True, "protocol": "UNIT_TEST_ONLY"}
    assert len(manifest["worlds"]) == 2
