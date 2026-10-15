"""Paired operational-mechanism switches with common exogenous draws and ongoing policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tempfile
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from .config import HospitalConfig, load_config
from .engine import _HS, _RUN, build_simulation, simulation_from_exo
from .generate import _csv, source_hashes
from .mechanisms import ResourceSimulation

OUTCOMES = {
    "ed_patient_hours": "attente",
    "occupied_bed_hours": "occupes",
    "uncovered_care_minutes": "non_couvert",
    "external_orientations": "hors_perimetre",
    "internal_transfers": "transf_in",
}
MECHANISM_FIELDS = {
    "mechanism_family",
    "pole_resource_weights",
    "routing_links",
    "cross_pole_delay_h",
}


def validate_pair(
    base: HospitalConfig, alternative: HospitalConfig, at_hour: int, horizon: int
) -> None:
    if base.model_dump(exclude=MECHANISM_FIELDS) != alternative.model_dump(
        exclude=MECHANISM_FIELDS
    ):
        raise ValueError("Paired scenarios may change only mechanism, pool weights and routing")
    if type(at_hour) is not int or type(horizon) is not int or at_hour < 0 or horizon < 1:
        raise ValueError("Nonnegative integer decision hour and positive integer horizon required")
    if at_hour + horizon > base.days * 24:
        raise ValueError("Counterfactual horizon crosses the recorded boundary")


def exogenous_fingerprint(exo: Any) -> str:
    hasher = hashlib.sha256()
    for name, value in sorted(vars(exo).items()):
        arrays = value.items() if isinstance(value, dict) else [(name, value)]
        for subname, array in sorted(arrays):
            if isinstance(array, np.ndarray):
                hasher.update(f"{name}/{subname}:{array.dtype}:{array.shape}".encode())
                hasher.update(array.tobytes())
    return hasher.hexdigest()


def compare(
    base: HospitalConfig,
    alternative: HospitalConfig,
    *,
    at_hour: int,
    horizon: int = 72,
) -> dict[str, Any]:
    validate_pair(base, alternative, at_hour, horizon)
    simulation = build_simulation(base)
    state = _HS.State(simulation.x)
    decision = base.warmup_days * 24 + at_hour
    factual_checks: Counter[str] = Counter()
    for hour in range(decision):
        simulation.step(state, hour, politique=True)
        _RUN.verifier(simulation, state, hour, factual_checks)
        if isinstance(simulation, ResourceSimulation):
            simulation.resource_rows(state, hour)
    if any(v for k, v in factual_checks.items() if k != "heures_controlees"):
        raise RuntimeError("Invalid factual prefix")

    totals: dict[str, dict[str, list[float]]] = {}
    checks: dict[str, dict[str, int]] = {}
    pool_checks: dict[str, int] = {}
    exo_hash = exogenous_fingerprint(simulation.x)
    for arm, config in (("baseline", base), ("alternative", alternative)):
        sim = simulation_from_exo(simulation.x, config)
        branch = state.clone()
        accum = {name: np.zeros(sim.U) for name in OUTCOMES}
        violations: Counter[str] = Counter()
        pool_rows_checked = 0
        for hour in range(decision, decision + horizon):
            previous = [len(occupied) for occupied in branch.occ]
            metrics = sim.step(branch, hour, politique=True)
            _RUN.verifier(sim, branch, hour, violations)
            for unit in range(sim.U):
                expected = previous[unit] + metrics["entrees"][unit] - metrics["sorties"][unit]
                expected += metrics["transf_in"][unit] - metrics["transf_out"][unit]
                violations["conservation_stock_flux"] += int(expected != len(branch.occ[unit]))
            violations["transferts_internes_equilibres"] += int(
                sum(metrics["transf_in"]) != sum(metrics["transf_out"])
            )
            if isinstance(sim, ResourceSimulation):
                pool_rows_checked += len(sim.resource_rows(branch, hour))
            for name, metric in OUTCOMES.items():
                accum[name] += metrics[metric]
        if any(v for k, v in violations.items() if k != "heures_controlees"):
            raise RuntimeError("Invalid counterfactual trajectory")
        if exogenous_fingerprint(sim.x) != exo_hash:
            raise RuntimeError("Counterfactual changed shared exogenous draws")
        totals[arm] = {name: array.tolist() for name, array in accum.items()}
        checks[arm] = dict(violations)
        pool_checks[arm] = pool_rows_checked
    entities: list[tuple[str, str, list[int]]] = [
        ("unit", unit.unit_id, [i]) for i, unit in enumerate(base.units)
    ]
    entities.extend(
        (
            "pole",
            pole.pole_id,
            [
                i
                for i, unit in enumerate(base.units)
                if base.unit_poles[unit.unit_id] == pole.pole_id
            ],
        )
        for pole in base.poles
    )
    entities.append(("hospital", base.hospital_id, list(range(len(base.units)))))
    rows = []
    for level, entity_id, indices in entities:
        for outcome in OUTCOMES:
            before = sum(totals["baseline"][outcome][i] for i in indices)
            after = sum(totals["alternative"][outcome][i] for i in indices)
            rows.append(
                {
                    "hospital_id": base.hospital_id,
                    "partition": base.partition,
                    "decision_h": at_hour,
                    "end_h_exclusive": at_hour + horizon,
                    "level": level,
                    "entity_id": entity_id,
                    "outcome": outcome,
                    "baseline": before,
                    "alternative": after,
                    "delta": after - before,
                }
            )
    return {
        "schema_version": "0.1",
        "status": "complete",
        "synthetic_only": True,
        "runtime": {
            "python": platform.python_version(),
            **{name: version(name) for name in ("numpy", "pandas", "pydantic")},
        },
        "data_role": "counterfactual_truth_not_training_features",
        "estimand": (
            "switch operational mechanism at decision boundary for the entire horizon versus "
            "retain baseline; usual behavior policy continues in both arms"
        ),
        "population": (
            "all patients, including arrivals during the horizon, in this one hospital realization"
        ),
        "coupling": "identical cloned hospital state, same exogenous arrays and policy uniforms",
        "timing": (
            "start-of-hour decision; sum end-of-hour states over [decision_h, decision_h+horizon)"
        ),
        "capacity": "same total hourly capacities; local pools redistribute existing capacity",
        "exogenous_sha256": exo_hash,
        "baseline_config_sha256": base.fingerprint,
        "alternative_config_sha256": alternative.fingerprint,
        "baseline_mechanism": base.mechanism_family,
        "alternative_mechanism": alternative.mechanism_family,
        "decision_h": at_hour,
        "horizon_h": horizon,
        "partition": base.partition,
        "checks": checks,
        "checked_pool_rows": pool_checks,
        "source_sha256": source_hashes(),
        "rows": rows,
    }


def export(
    base: HospitalConfig,
    alternative: HospitalConfig,
    output: Path,
    *,
    at_hour: int,
    horizon: int = 72,
    test_protocol: str | None = None,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    if base.partition == "test" and not (test_protocol and test_protocol.strip()):
        raise ValueError("Opening test counterfactuals requires an explicit test_protocol")
    if base.partition != "test" and test_protocol is not None:
        raise ValueError("test_protocol is only valid when opening test")
    report = compare(base, alternative, at_hour=at_hour, horizon=horizon)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".counterfactual-", dir=output.parent) as temporary:
        staging = Path(temporary) / "result"
        staging.mkdir()
        _csv(staging / "outcomes.csv", report["rows"])
        for name, config in (("baseline", base), ("alternative", alternative)):
            (staging / f"{name}_config.json").write_text(config.model_dump_json(indent=2) + "\n")
        manifest = {k: v for k, v in report.items() if k != "rows"}
        manifest.update(
            test_access={"opened": base.partition == "test", "protocol": test_protocol},
            files_sha256={
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(staging.iterdir())
            },
        )
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        staging.rename(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Paired resource/routing mechanism comparison")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--alternative", type=Path, required=True)
    parser.add_argument("--at-hour", type=int, required=True)
    parser.add_argument("--horizon", type=int, default=72)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--test-protocol")
    args = parser.parse_args()
    try:
        report = export(
            load_config(args.config),
            load_config(args.alternative),
            args.output,
            at_hour=args.at_hour,
            horizon=args.horizon,
            test_protocol=args.test_protocol,
        )
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Counterfactual failed: {exc}\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "hospital": [r for r in report["rows"] if r["level"] == "hospital"],
            }
        )
    )


if __name__ == "__main__":
    main()
