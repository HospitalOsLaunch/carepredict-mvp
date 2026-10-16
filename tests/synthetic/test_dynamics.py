"""Mechanism isolation, holdouts and dynamics checks on disposable development fixtures."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.counterfactual import validate_pair
from hospitalos.synthetic.dynamics import discharge_time
from hospitalos.synthetic.engine import _HS, build_simulation, simulate
from hospitalos.synthetic.generate import generate
from hospitalos.synthetic.policy import NoRecommendationPolicy
from hospitalos.synthetic.policy_loop import run_policy
from hospitalos.synthetic.registry import CohortPlan, Registry, compile_registry, validate_worlds

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = {
    "arrivals": ["v041", "shared_bursts_v1", "appointments_v1"],
    "discharges": ["v041", "daily_rounds_v1", "rolling_v1"],
    "staffing": ["v041", "persistent_absence_v1", "shared_float_v1"],
}


def config(**changes: Any) -> HospitalConfig:
    raw = json.loads((ROOT / "configs/synthetic/hospital_two_poles.json").read_text())
    raw.update({"days": 7, "warmup_days": 7, **changes})
    return HospitalConfig.model_validate(raw)


def plan(axis: str) -> CohortPlan:
    return CohortPlan.model_validate(
        {
            "cohort_id": "C_DYNAMICS_FIXTURE",
            "seed": 73,
            "start": "2025-01-01",
            "days": 2,
            "warmup_days": 1,
            "split_axis": axis,
            "structures": [
                {
                    "structure_id": f"S_{partition}",
                    "partition": partition,
                    "poles": [["MED_POLY"], ["CSG"]],
                    "hospitals": 1,
                    "replicates": 1,
                    "dynamics": {axis: variant},
                }
                for partition, variant in zip(
                    ("train", "validation", "test"), VARIANTS[axis], strict=True
                )
            ],
        }
    )


@pytest.mark.parametrize("axis", VARIANTS)
def test_axis_reservation_and_mutations(axis: str) -> None:
    original = plan(axis)
    registry = compile_registry(original)
    assert len(registry.worlds) == 3
    assert registry.summary()["reserved_axis"] == axis
    raw = original.model_dump()
    raw["structures"][1]["dynamics"][axis] = "v041"
    with pytest.raises(ValidationError, match="mechanism crosses"):
        CohortPlan.model_validate(raw)
    raw_registry = registry.model_dump()
    raw_registry["worlds"][0]["config"]["dynamics"][axis] = "v041"
    with pytest.raises(ValidationError):
        Registry.model_validate(raw_registry)
    first = registry.worlds[0]
    altered = first.config.model_dump()
    altered.update(partition="train", hospital_id="H_OTHER", seed=19)
    other = first.model_copy(
        update={"world_id": "W_OTHER", "config": HospitalConfig.model_validate(altered)}
    )
    with pytest.raises(ValueError, match="crosses partitions"):
        validate_worlds((first, other), split_axis=original.split_axis)


@pytest.mark.parametrize("axis", VARIANTS)
def test_unknown_variant_rejected(axis: str) -> None:
    with pytest.raises(ValidationError):
        config(dynamics={axis: "unknown"})


@pytest.mark.parametrize("staffing", VARIANTS["staffing"][1:])
def test_staffing_keeps_patients_services_and_policy_draws(staffing: str) -> None:
    baseline = build_simulation(config()).x
    alternative = build_simulation(config(dynamics={"staffing": staffing})).x
    for key in baseline.pat:
        np.testing.assert_array_equal(baseline.pat[key], alternative.pat[key])
    for name in ("u_politique", "u_reco", "u_expo", "u_renfort", "cap_imagerie", "prevus"):
        np.testing.assert_array_equal(getattr(baseline, name), getattr(alternative, name))
    assert np.all(alternative.absents <= alternative.prevus)
    assert np.all(alternative.remplaces <= alternative.absents)
    assert np.all(alternative.remplaces >= 0)
    if staffing == "shared_float_v1":
        assert np.all(alternative.remplaces.sum(axis=0) <= alternative.prevus.sum(axis=0) // 12)
    assert not np.array_equal(baseline.remplaces, alternative.remplaces)


def test_persistent_absences_have_temporal_dependence() -> None:
    x = build_simulation(
        config(days=365, warmup_days=0, dynamics={"staffing": "persistent_absence_v1"})
    ).x
    values = x.absents[:, 1:1096].astype(float)
    assert np.corrcoef(values[:, :-1].ravel(), values[:, 1:].ravel())[0, 1] > 0.35


def test_arrival_bursts_are_shared_and_overdispersed() -> None:
    x = build_simulation(
        config(days=365, warmup_days=0, dynamics={"arrivals": "shared_bursts_v1"})
    ).x
    counts = np.zeros((x.U, x.ndays))
    for pid in range(x.N):
        if x.pat["src"][pid] == _HS.URG:
            counts[int(x.pat["unit"][pid]), int(x.pat["arr_h"][pid]) // 24] += 1
    totals = counts.sum(axis=0)
    assert totals.var() / totals.mean() > 2
    assert np.corrcoef(counts)[0, 1] > 0.15
    assert sum(map(len, x.arrivees)) == x.N
    assert sorted(pid for ids in x.arrivees for pid in ids) == list(range(x.N))


def test_appointments_are_bounded_and_use_working_days() -> None:
    x = build_simulation(config(days=90, warmup_days=0, dynamics={"arrivals": "appointments_v1"})).x
    ids = np.flatnonzero(x.pat["src"] == _HS.PROG)
    assert len(ids) > 0
    for pid in ids:
        day, hour = divmod(int(x.pat["arr_h"][pid]), 24)
        assert x.ouvre[day] and 8 <= hour < 14


@pytest.mark.parametrize("variant", VARIANTS["discharges"][1:])
@pytest.mark.parametrize("dest", [0, 1, 2, 3, 4])
def test_discharge_readiness_and_calendar(variant: str, dest: int) -> None:
    sim = SimpleNamespace(
        p_dest=[dest], x=SimpleNamespace(debut=dt.date(2025, 1, 3), pat={"aval_j": [1.25]})
    )  # Friday
    patient = SimpleNamespace(pid=0, ready_h=16, aide_h=18)
    result = discharge_time(sim, patient, variant)
    if dest == _HS.DECES:
        assert result == 16
        return
    assert result >= (19 if dest == _HS.DOM else 47)
    if variant == "daily_rounds_v1":
        assert result % 24 == 14
        assert (sim.x.debut + dt.timedelta(days=result // 24)).weekday() < 5
    else:
        assert 8 <= result % 24 < 20


@pytest.mark.parametrize("family", ["v041", "local_v1", "hybrid_v1"])
@pytest.mark.parametrize(
    "variants",
    [
        {
            "arrivals": "shared_bursts_v1",
            "discharges": "daily_rounds_v1",
            "staffing": "persistent_absence_v1",
        },
        {"arrivals": "appointments_v1", "discharges": "rolling_v1", "staffing": "shared_float_v1"},
    ],
)
def test_composed_physics_conserves_patients_and_resources(
    family: str, variants: dict[str, str]
) -> None:
    result = simulate(config(mechanism_family=family, dynamics=variants))
    assert result.checks["heures_controlees"] == 14 * 24
    assert all(v == 0 for k, v in result.checks.items() if k != "heures_controlees")


def test_alternative_export_byte_reproducibility(tmp_path: Path) -> None:
    configured = config(
        days=2,
        warmup_days=1,
        dynamics={
            "arrivals": "shared_bursts_v1",
            "discharges": "rolling_v1",
            "staffing": "shared_float_v1",
        },
    )
    generate(configured, tmp_path / "one")
    generate(configured, tmp_path / "two")
    for file in (tmp_path / "one").rglob("*"):
        if file.is_file():
            assert (
                file.read_bytes()
                == (tmp_path / "two" / file.relative_to(tmp_path / "one")).read_bytes()
            )


def test_dynamics_not_a_valid_paired_resource_switch() -> None:
    with pytest.raises(ValueError, match="only mechanism"):
        validate_pair(config(), config(dynamics={"arrivals": "shared_bursts_v1"}), 9, 72)


def test_policy_loop_with_alternative_dynamics(tmp_path: Path) -> None:
    run_policy(
        config(
            days=2,
            warmup_days=1,
            dynamics={
                "arrivals": "appointments_v1",
                "discharges": "daily_rounds_v1",
                "staffing": "persistent_absence_v1",
            },
        ),
        NoRecommendationPolicy(),
        tmp_path / "policy",
    )
    manifest = json.loads((tmp_path / "policy/manifest.json").read_text())
    assert manifest["status"] == "complete"


def test_default_exogenous_arrays_are_identical_to_imported_engine() -> None:
    sim = build_simulation(config())
    x = sim.x
    previous = _HS.Exo(
        x.unit_names,
        x.debut,
        x.debut + dt.timedelta(days=x.ndays),
        x.seed,
        echelles=x.echelles,
        unit_specs=dict(zip(x.unit_names, x.specs, strict=True)),
    )
    for name, value in vars(previous).items():
        if isinstance(value, np.ndarray):
            np.testing.assert_array_equal(getattr(x, name), value)
    for name, value in previous.pat.items():
        np.testing.assert_array_equal(x.pat[name], value)


@pytest.mark.parametrize("axis", VARIANTS)
def test_holdout_materialization_stays_closed(axis: str, tmp_path: Path) -> None:
    from hospitalos.synthetic.cohort import freeze, materialize

    registry = freeze(plan(axis), tmp_path / "registry")
    result = materialize(tmp_path / "registry", tmp_path / "runs", with_learning=True)
    assert result["test_access"]["opened"] is False
    assert not (tmp_path / "runs/test").exists()
    assert result["reserved_world_ids"] == [
        w.world_id for w in registry.worlds if w.config.partition == "test"
    ]
    assert len(result["worlds"]) == 2
    with pytest.raises(ValueError, match="test_protocol"):
        materialize(tmp_path / "registry", tmp_path / "forbidden", partitions=("test",))
    assert not (tmp_path / "forbidden").exists()
