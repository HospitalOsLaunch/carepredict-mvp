"""Typed boundary around the imported v0.4.1 simulation (internally untyped)."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import numpy as np

from .config import HospitalConfig
from .mechanisms import RESOURCE_ARRAYS, ResourceSimulation
from .v041 import hospsim, run

# Keep dynamic legacy calls confined to this boundary.
_HS: Any = hospsim
_RUN: Any = run


@dataclass
class SimulationResult:
    simulation: Any
    journal: Any
    resources: list[dict[str, Any]]
    checks: dict[str, int]
    resource_pools: list[dict[str, Any]]


def simulation_from_exo(exo: Any, config: HospitalConfig) -> Any:
    if config.mechanism_family == "v041":
        return _HS.Sim(exo, "pole", config.warmup_days * 24, exo.H)
    return ResourceSimulation(exo, config)


def build_simulation(config: HospitalConfig) -> Any:
    """One Exo/State for the whole hospital; no per-pole independent simulations."""
    specs = {}
    for unit in config.units:
        spec = deepcopy(_HS.UNITS[unit.template])
        spec.update(
            nom=unit.unit_id,
            lits=unit.beds,
            lits_isolement=unit.isolation_beds,
            lits_oxygene=unit.oxygen_beds,
        )
        specs[unit.unit_id] = spec
    start = config.start - dt.timedelta(days=config.warmup_days)
    end = config.start + dt.timedelta(days=config.days)
    exo = _HS.Exo(
        list(specs),
        start,
        end,
        config.seed,
        echelles={unit.unit_id: unit.arrival_scale for unit in config.units},
        unit_specs=specs,
    )
    for name, attr in RESOURCE_ARRAYS.items():
        multiplier = getattr(config.shared_resources, name)
        setattr(exo, attr, np.floor(getattr(exo, attr) * multiplier).astype(int))
    # Legacy "pole" means pooled beds and resources. Here its perimeter is the hospital.
    return simulation_from_exo(exo, config)


def advance_checked(
    sim: Any,
    state: Any,
    hour: int,
    journal: Any,
    checks: Counter[str],
    *,
    politique: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """One physical step with the same invariants in batch and policy environments."""
    before = [len(occupied) for occupied in state.occ]
    metrics = sim.step(state, hour, politique=politique, log=journal)
    _RUN.verifier(sim, state, hour, checks)
    for unit in range(sim.U):
        expected = (
            before[unit]
            + metrics["entrees"][unit]
            - metrics["sorties"][unit]
            + metrics["transf_in"][unit]
            - metrics["transf_out"][unit]
        )
        checks["conservation_stock_flux"] += int(expected != len(state.occ[unit]))
    checks["transferts_internes_equilibres"] += int(
        sum(metrics["transf_in"]) != sum(metrics["transf_out"])
    )
    pool_rows = sim.resource_rows(state, hour) if isinstance(sim, ResourceSimulation) else []
    resource = {
        "h": hour - sim.h0_rec,
        **{
            f"capacity_{name}": int(getattr(sim.x, attr)[hour])
            for name, attr in RESOURCE_ARRAYS.items()
        },
        "queue_cleaning": len(state.q_net),
        "queue_imaging": len(state.q_img),
        "queue_transport": len(state.q_tr),
        "queue_specialist": len(state.q_avis),
    }
    return resource, pool_rows


def simulate(config: HospitalConfig) -> SimulationResult:
    sim = build_simulation(config)
    state = _HS.State(sim.x)
    journal = _RUN.Journal(sim)
    checks: Counter[str] = Counter()
    resources = []
    resource_pools = []
    for hour in range(sim.x.H):
        resource, pools = advance_checked(sim, state, hour, journal, checks, politique=True)
        if hour >= sim.h0_rec:
            resources.append(resource)
            resource_pools.extend(pools)
    violations = {
        key: value for key, value in checks.items() if key != "heures_controlees" and value
    }
    if violations:
        raise RuntimeError(f"Simulation invariant violations: {violations}")
    return SimulationResult(sim, journal, resources, dict(checks), resource_pools)
