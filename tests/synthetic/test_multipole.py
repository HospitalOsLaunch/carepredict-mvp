"""Topology, reproducibility, conservation and an actual cross-pole contention test."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections import deque
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from hospitalos.synthetic.config import HospitalConfig, validate_partition_isolation
from hospitalos.synthetic.engine import _HS, build_simulation, simulate
from hospitalos.synthetic.generate import ADDITIVE_FIELDS, aggregate, generate

EXAMPLE = Path(__file__).resolve().parents[2] / "configs/synthetic/hospital_two_poles.json"


@pytest.fixture
def raw_config() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(EXAMPLE.read_text())
    raw.update(days=7, warmup_days=14)
    return raw


@pytest.fixture
def config(raw_config: dict[str, Any]) -> HospitalConfig:
    return HospitalConfig.model_validate(raw_config)


@pytest.mark.parametrize(
    "field,value",
    [
        ("days", 0),
        ("days", True),
        ("days", 367),
        ("seed", -1),
        ("seed", "41"),
        ("warmup_days", -1),
        ("partition", "invalid"),
        ("mechanism_family", "invented"),
        ("hospital_id", "../escape"),
        ("poles", []),
        ("unexpected", 1),
        ("start", "0001-01-01"),
    ],
)
def test_invalid_config_rejected(raw_config: dict[str, Any], field: str, value: Any) -> None:
    raw_config[field] = value
    with pytest.raises(ValidationError):
        HospitalConfig.model_validate(raw_config)


@pytest.mark.parametrize(
    "field,value",
    [
        ("beds", 3),
        ("beds", 10.5),
        ("isolation_beds", 20),
        ("oxygen_beds", 29),
        ("arrival_scale", float("nan")),
        ("arrival_scale", -1.0),
        ("template", "ICU"),
    ],
)
def test_invalid_unit_rejected(raw_config: dict[str, Any], field: str, value: Any) -> None:
    raw_config["poles"][0]["units"][0][field] = value
    with pytest.raises(ValidationError):
        HospitalConfig.model_validate(raw_config)


@pytest.mark.parametrize("kind", ["unit", "pole"])
def test_duplicate_ids_rejected(raw_config: dict[str, Any], kind: str) -> None:
    if kind == "unit":
        raw_config["poles"][1]["units"][0]["unit_id"] = "U_MED"
    else:
        raw_config["poles"][1]["pole_id"] = raw_config["poles"][0]["pole_id"]
    with pytest.raises(ValidationError, match="unique"):
        HospitalConfig.model_validate(raw_config)


def test_partition_guard_includes_different_seeds(config: HospitalConfig) -> None:
    other = HospitalConfig.model_validate({**config.model_dump(), "partition": "test", "seed": 9})
    with pytest.raises(ValueError, match="crosses partitions"):
        validate_partition_isolation([config, other])
    other = HospitalConfig.model_validate({**other.model_dump(), "hospital_id": "H_OTHER"})
    validate_partition_isolation([config, other])


def test_templates_are_not_mutated(config: HospitalConfig) -> None:
    original = deepcopy(_HS.UNITS)
    sim = build_simulation(config)
    sim.x.specs[0]["lits"] = 99
    assert original == _HS.UNITS
    assert build_simulation(config).x.specs[0]["lits"] == 28


def test_changing_seed_changes_arrivals(config: HospitalConfig) -> None:
    other = HospitalConfig.model_validate({**config.model_dump(), "seed": config.seed + 1})
    assert not np.array_equal(
        build_simulation(config).x.pat["arr_h"], build_simulation(other).x.pat["arr_h"]
    )


@pytest.fixture(scope="module")
def outputs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, HospitalConfig]:
    raw = json.loads(EXAMPLE.read_text())
    raw.update(days=7, warmup_days=14)
    config = HospitalConfig.model_validate(raw)
    root = tmp_path_factory.mktemp("multipole")
    first, second = root / "first", root / "second"
    generate(config, first)
    generate(config, second)
    return first, second, config


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def test_byte_identical_replay_and_verified_files(
    outputs: tuple[Path, Path, HospitalConfig],
) -> None:
    first, second, _ = outputs
    for path in first.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (second / path.relative_to(first)).read_bytes()
    manifest = json.loads((first / "manifest.json").read_text())
    for name, digest in manifest["files_sha256"].items():
        assert hashlib.sha256((first / name).read_bytes()).hexdigest() == digest
    assert manifest["checks"]["heures_controlees"] == 21 * 24
    assert all(
        value == 0 for key, value in manifest["checks"].items() if key != "heures_controlees"
    )
    assert manifest["data_role"] == "simulation_truth_not_training_inputs"
    assert not (first / "learning").exists()


def test_hierarchical_conservation(outputs: tuple[Path, Path, HospitalConfig]) -> None:
    first, _, config = outputs
    units = read_csv(first / "truth/units_hourly.csv")
    poles = read_csv(first / "truth/poles_hourly.csv")
    hospital = read_csv(first / "truth/hospital_hourly.csv")
    assert len(units) == config.days * 24 * len(config.units)
    assert len(poles) == config.days * 24 * len(config.poles)
    assert len(hospital) == config.days * 24
    assert len(read_csv(first / "truth/shared_resources_hourly.csv")) == len(hospital)
    for row in hospital:
        members = [unit for unit in units if unit["h"] == row["h"]]
        children = [pole for pole in poles if pole["h"] == row["h"]]
        for field in ADDITIVE_FIELDS:
            assert float(row[field]) == pytest.approx(sum(float(unit[field]) for unit in members))
            assert float(row[field]) == pytest.approx(sum(float(pole[field]) for pole in children))
        assert int(row["transferts_internes_entrants_h"]) == int(
            row["transferts_internes_sortants_h"]
        )


def test_ratios_recomputed_and_uncovered_load_preserved() -> None:
    rows = []
    for charge, capacity in [(200, 100), (0, 300)]:
        rows.append(
            {
                "hospital_id": "H",
                "pole_id": "P",
                "h": 0,
                "timestamp": "t",
                **dict.fromkeys(ADDITIVE_FIELDS, 0),
                "charge_soins_min_h": charge,
                "capacite_soins_min_h": capacity,
                "minutes_non_couvertes_h": max(charge - capacity, 0),
            }
        )
    result = aggregate(rows, "hospital")[0]
    assert result["ratio_charge"] == 0.5  # neither 2.0 (sum) nor 1.0 (unweighted mean)
    assert result["minutes_non_couvertes_h"] == 100  # spare staff elsewhere not implicitly pooled
    assert result["taux_occupation"] is None


def test_events_stop_at_boundary_and_have_unique_ids(
    outputs: tuple[Path, Path, HospitalConfig],
) -> None:
    first, _, config = outputs
    with gzip.open(first / "truth/events.jsonl.gz", "rt") as stream:
        events = [json.loads(line) for line in stream]
    assert len({event["event_id"] for event in events}) == len(events)
    assert min(event["h"] for event in events) == -config.warmup_days * 24
    assert max(event["h"] for event in events) == config.days * 24 - 1
    for event in events:
        assert event["pole_id"] == config.unit_poles[event["unit_id"]]
        if event["stay_id"]:
            assert event["stay_id"].startswith(config.hospital_id + ":")


def test_output_is_not_overwritten(outputs: tuple[Path, Path, HospitalConfig]) -> None:
    first, _, config = outputs
    before = (first / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        generate(config, first)
    assert (first / "manifest.json").read_bytes() == before


def test_pole_grouping_does_not_reset_physics(config: HospitalConfig) -> None:
    raw = config.model_dump()
    raw["poles"] = [{"pole_id": "P_ALL", "units": [unit.model_dump() for unit in config.units]}]
    grouped = HospitalConfig.model_validate(raw)
    assert simulate(config).journal.etats == simulate(grouped).journal.etats


def test_imaging_request_in_one_pole_delays_another(config: HospitalConfig) -> None:
    """Same state and capacity: remove only the request ahead from the other pole."""
    raw = config.model_dump()
    raw["shared_resources"]["imaging"] = 0.0
    sim = build_simulation(HospitalConfig.model_validate(raw))
    state = _HS.State(sim.x)
    selected: dict[str, tuple[int, int]] = {}
    hour = 0
    for hour in range(sim.x.H - 1):
        sim.step(state, hour, politique=False)
        selected = {}
        for pid, demand in state.q_img:
            patient = state.patients.get(pid)
            if patient is not None and sim.p_dest[pid] != _HS.DECES:
                pole = config.unit_poles[sim.x.unit_names[patient.unit]]
                selected.setdefault(pole, (pid, demand))
        if len(selected) == 2:
            break
    assert len(selected) == 2, "Fixture must contain requests from two distinct poles"
    first, second = selected.values()
    blocked, free = state.clone(), state.clone()
    blocked.q_img, free.q_img = deque([first, second]), deque([second])
    sim.x.cap_imagerie[hour + 1] = 1
    sim.step(blocked, hour + 1, politique=False)
    sim.step(free, hour + 1, politique=False)
    assert any(task[1] == first[0] for task in blocked.img_cours)
    assert not any(task[1] == second[0] for task in blocked.img_cours)
    assert any(task[1] == second[0] for task in free.img_cours)
