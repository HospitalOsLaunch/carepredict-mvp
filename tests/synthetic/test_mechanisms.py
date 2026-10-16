"""Mechanism differences, capacity conservation, routing and paired causal simulation."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from hospitalos.synthetic.config import HospitalConfig, load_config
from hospitalos.synthetic.counterfactual import compare, export, validate_pair
from hospitalos.synthetic.engine import _HS, _RUN, build_simulation, simulate, simulation_from_exo
from hospitalos.synthetic.generate import generate
from hospitalos.synthetic.learning import prepare_learning_run
from hospitalos.synthetic.mechanisms import RESOURCE_ARRAYS, allocate
from hospitalos.synthetic.registry import CohortPlan, Registry, compile_registry

EXAMPLE = Path(__file__).resolve().parents[2] / "configs/synthetic/hospital_two_poles.json"


@pytest.fixture
def raw() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(EXAMPLE.read_text())
    value.update(days=7, warmup_days=14)
    return value


def configured(raw: dict[str, Any], family: str) -> HospitalConfig:
    return HospitalConfig.model_validate({**raw, "mechanism_family": family})


def test_existing_v041_configuration_identity_is_preserved() -> None:
    evidence = EXAMPLE.parents[2] / "docs/synthetic/evidence/lot01_annual_manifest.json"
    assert load_config(EXAMPLE).fingerprint == json.loads(evidence.read_text())["config_sha256"]


def test_default_trajectory_matches_lot03_engine(raw: dict[str, Any], tmp_path: Path) -> None:
    # Pin the actual published parent, not an equivalent copy of the new implementation.
    source = subprocess.check_output(
        [
            "git",
            "show",
            "3e9f76522baa5f155adcc3be1487d95911daaefc:src/hospitalos/synthetic/v041/hospsim.py",
        ],
        cwd=EXAMPLE.parents[2],
        text=True,
    )
    path = tmp_path / "reference.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location("lot03_reference", path)
    assert spec is not None and spec.loader is not None
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    config = configured(raw, "v041")
    current = build_simulation(config)
    previous = original.Sim(current.x, "pole", current.h0_rec, current.h1_rec)
    journals = []
    for sim in (current, previous):
        state = _HS.State(sim.x)
        journal = _RUN.Journal(sim)
        for hour in range(sim.x.H):
            sim.step(state, hour, log=journal)
        journals.append(journal)
    assert journals[0].etats == journals[1].etats
    assert journals[0].events == journals[1].events
    assert journals[0].actions == journals[1].actions
    assert journals[0].taches == journals[1].taches


@pytest.mark.parametrize("weights", [[1.0, 1.0], [1.0, 3.0], [0.0, 1.0]])
def test_integer_allocation_preserves_every_hour_and_long_run_shares(weights: list[float]) -> None:
    capacity = np.asarray([0, 1, 3, 0, 2] * 200, dtype=np.int64)
    allocation = allocate(capacity, np.asarray(weights))
    assert (allocation.sum(axis=0) == capacity).all()
    assert (allocation >= 0).all()
    expected = capacity.sum() * np.asarray(weights) / sum(weights)
    assert np.max(np.abs(allocation.sum(axis=1) - expected)) <= 1
    assert np.array_equal(allocation, allocate(capacity, np.asarray(weights)))


@pytest.mark.parametrize("weights", [[0.0, 0.0], [-1.0, 1.0], [float("nan"), 1.0]])
def test_invalid_pool_weights_rejected(weights: list[float]) -> None:
    with pytest.raises(ValueError):
        allocate(np.ones(5, dtype=np.int64), np.asarray(weights))


@pytest.mark.parametrize(
    "mutation", ["unknown_pole", "duplicate_pole", "zero", "link", "duplicate_link", "noop"]
)
def test_invalid_mechanism_configuration(raw: dict[str, Any], mutation: str) -> None:
    raw["mechanism_family"] = "hybrid_v1"
    poles = [p["pole_id"] for p in raw["poles"]]
    if mutation == "unknown_pole":
        raw["pole_resource_weights"] = [{"pole_id": "UNKNOWN"}]
    elif mutation == "duplicate_pole":
        raw["pole_resource_weights"] = [{"pole_id": poles[0]}] * 2
    elif mutation == "zero":
        raw["pole_resource_weights"] = [
            {"pole_id": p, "weights": {"transport": 0.0}} for p in poles
        ]
    elif mutation == "link":
        raw["routing_links"] = [{"origin": poles[0], "destination": "UNKNOWN"}]
    elif mutation == "duplicate_link":
        raw["routing_links"] = [{"origin": poles[0], "destination": poles[1]}] * 2
    else:
        raw["pole_resource_weights"] = [{"pole_id": poles[0], "weights": {"imaging": 2.0}}]
    with pytest.raises(ValidationError):
        HospitalConfig.model_validate(raw)


def test_directed_routing_delay_and_home_pole_priority(raw: dict[str, Any]) -> None:
    raw.update(mechanism_family="hybrid_v1", cross_pole_delay_h=12)
    raw["routing_links"] = [
        {"origin": raw["poles"][0]["pole_id"], "destination": raw["poles"][1]["pole_id"]}
    ]
    sim = build_simulation(HospitalConfig.model_validate(raw))
    sim.x.fermes[:] = 0
    state = _HS.State(sim.x)
    patient = SimpleNamespace(dec_h=0)
    assert [u for _, u in sim.hosting_candidates(state, 0, patient, 6)] == [1]
    later = [u for _, u in sim.hosting_candidates(state, 0, patient, 12)]
    assert later[0] == 1 and set(later) == {1, 2, 3}
    assert [u for _, u in sim.hosting_candidates(state, 2, patient, 12)] == [3]
    local = build_simulation(configured({**raw, "routing_links": []}, "local_v1"))
    local.x.fermes[:] = 0
    assert [u for _, u in local.hosting_candidates(_HS.State(local.x), 0, patient, 100)] == [1]


def test_reserved_imaging_changes_competition_without_adding_capacity(raw: dict[str, Any]) -> None:
    raw["shared_resources"]["imaging"] = 0.0
    for pole in raw["poles"]:
        for unit in pole["units"]:
            unit.update(beds=20, isolation_beds=4, oxygen_beds=20)
    base = configured(raw, "v041")
    sim = build_simulation(base)
    state = _HS.State(sim.x)
    groups: dict[int, list[tuple[int, int]]] = {}
    for h in range(sim.x.H):
        sim.step(state, h, politique=False)
        groups = {0: [], 1: []}
        for pid, requested in state.q_img:
            p = state.patients.get(pid)
            if p is not None and sim.p_dest[pid] != _HS.DECES:
                groups[p.unit // 2].append((pid, requested))
        if len(groups[0]) >= 2 and len(groups[1]) >= 1:
            break
    assert len(groups[0]) >= 2 and len(groups[1]) >= 1
    sim.x.cap_imagerie[:] = 2
    chosen = groups[0][:2] + groups[1][:1]
    state.q_img = deque(chosen)
    state.img_cours = []
    pooled, local = state.clone(), state.clone()
    sim.start_services(pooled, h, None)
    variant = simulation_from_exo(sim.x, configured(raw, "local_v1"))
    variant.start_services(local, h, None)
    assert variant.pools.budget("imaging", h) == [1, 1]
    assert [t[1] for t in pooled.img_cours] == [p[0] for p in chosen[:2]]
    assert [t[1] for t in local.img_cours] == [chosen[0][0], chosen[2][0]]


@pytest.mark.parametrize("family", ["local_v1", "hybrid_v1"])
def test_full_simulation_conserves_resources_and_changes_trajectories(
    raw: dict[str, Any], family: str
) -> None:
    baseline = simulate(configured(raw, "v041"))
    result = simulate(configured(raw, family))
    assert result.journal.etats != baseline.journal.etats
    assert all(v == 0 for k, v in result.checks.items() if k != "heures_controlees")
    assert all(row["started"] <= row["start_limit"] for row in result.resource_pools)
    for resource, attr in RESOURCE_ARRAYS.items():
        rows = [r for r in result.resource_pools if r["resource"] == resource]
        for h in range(raw["days"] * 24):
            assert (
                sum(r["capacity"] for r in rows if r["h"] == h)
                == getattr(result.simulation.x, attr)[h + raw["warmup_days"] * 24]
            )


def test_pool_capacity_mutation_is_detected(raw: dict[str, Any]) -> None:
    sim = build_simulation(configured(raw, "local_v1"))
    state = _HS.State(sim.x)
    sim.step(state, 0)
    sim.started["transport"][0] = sim.limits["transport"][0] + 1
    with pytest.raises(RuntimeError, match="Pool capacity exceeded"):
        sim.resource_rows(state, 0)


@pytest.mark.parametrize("change", ["seed", "start", "days", "hospital_id", "shared_resources"])
def test_counterfactual_cannot_change_exogenous_world(raw: dict[str, Any], change: str) -> None:
    base = configured(raw, "v041")
    altered = dict(raw)
    altered[change] = {
        "seed": 999,
        "start": "2025-02-01",
        "days": 10,
        "hospital_id": "OTHER",
        "shared_resources": {"imaging": 0.5},
    }[change]
    with pytest.raises(ValueError, match="only mechanism"):
        validate_pair(base, configured(altered, "local_v1"), 9, 72)


@pytest.mark.parametrize("at,horizon", [(-1, 72), (0, 0), (100, 72), (True, 72)])
def test_counterfactual_boundaries(raw: dict[str, Any], at: int, horizon: int) -> None:
    with pytest.raises(ValueError):
        validate_pair(configured(raw, "v041"), configured(raw, "local_v1"), at, horizon)


def test_paired_null_effect_reproducibility_and_aggregation(raw: dict[str, Any]) -> None:
    base = configured(raw, "v041")
    same = compare(base, base, at_hour=9)
    assert all(r["delta"] == 0 for r in same["rows"])
    alternative = configured(raw, "local_v1")
    report = compare(base, alternative, at_hour=9)
    assert report == compare(base, alternative, at_hour=9)
    assert report["exogenous_sha256"] == same["exogenous_sha256"]
    for hospital in [r for r in report["rows"] if r["level"] == "hospital"]:
        units = [
            r
            for r in report["rows"]
            if r["level"] == "unit" and r["outcome"] == hospital["outcome"]
        ]
        poles = [
            r
            for r in report["rows"]
            if r["level"] == "pole" and r["outcome"] == hospital["outcome"]
        ]
        for key in ("baseline", "alternative", "delta"):
            assert hospital[key] == pytest.approx(sum(r[key] for r in units))
            assert hospital[key] == pytest.approx(sum(r[key] for r in poles))


def test_counterfactual_exports_and_test_guard(raw: dict[str, Any], tmp_path: Path) -> None:
    base, alternative = configured(raw, "v041"), configured(raw, "hybrid_v1")
    export(base, alternative, tmp_path / "a", at_hour=9)
    export(base, alternative, tmp_path / "b", at_hour=9)
    for path in (tmp_path / "a").iterdir():
        assert path.read_bytes() == (tmp_path / "b" / path.name).read_bytes()
    with pytest.raises(FileExistsError):
        export(base, alternative, tmp_path / "a", at_hour=9)
    raw["partition"] = "test"
    with pytest.raises(ValueError, match="test_protocol"):
        export(configured(raw, "v041"), configured(raw, "local_v1"), tmp_path / "test", at_hour=9)


def test_mechanism_holdout_allows_shared_topology_but_not_family_leakage() -> None:
    plan = CohortPlan.model_validate(
        {
            "cohort_id": "C_MECHANISM_TEST",
            "seed": 42,
            "start": "2025-01-01",
            "days": 2,
            "warmup_days": 2,
            "split_axis": "mechanism",
            "structures": [
                {
                    "structure_id": name,
                    "partition": partition,
                    "mechanism_family": family,
                    "poles": [["MED_POLY", "CSG"], ["PNEUMO", "CARDIO"]],
                    "hospitals": 1,
                    "replicates": 1,
                }
                for name, partition, family in (
                    ("TRAIN", "train", "v041"),
                    ("VAL", "validation", "local_v1"),
                    ("TEST", "test", "hybrid_v1"),
                )
            ],
        }
    )
    registry = compile_registry(plan)
    assert registry.summary()["mechanism_holdout"] is True
    assert len({w.structure_sha256 for w in registry.worlds}) == 1
    assert Registry.model_validate_json(registry.model_dump_json()) == registry
    corrupted = plan.model_dump()
    corrupted["structures"][2]["mechanism_family"] = "local_v1"
    with pytest.raises(ValidationError, match="Mechanism crosses"):
        CohortPlan.model_validate(corrupted)


@pytest.mark.parametrize("family", ["local_v1", "hybrid_v1"])
def test_new_mechanisms_feed_asof_pipeline(
    raw: dict[str, Any], family: str, tmp_path: Path
) -> None:
    config = configured(raw, family)
    generate(config, tmp_path / "truth")
    report = prepare_learning_run(tmp_path / "truth", tmp_path / "learning")
    assert report["partition"] == "development"
    assert (tmp_path / "truth/truth/resource_pools_hourly.csv").exists()
    manifest = json.loads((tmp_path / "learning/manifest.json").read_text())
    assert manifest["counts"]["features"] == raw["days"] * 24 * 7
