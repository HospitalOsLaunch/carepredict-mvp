"""Typed boundary around the imported v0.4.1 simulation (internally untyped)."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import numpy as np

from .config import HospitalConfig
from .v041 import hospsim, run

# Keep dynamic legacy calls confined to this boundary.
_HS: Any = hospsim
_RUN: Any = run
RESOURCE_ARRAYS = {
    "cleaning": "cap_nettoyage",
    "imaging": "cap_imagerie",
    "transport": "cap_transport",
    "specialist": "cap_avis",
}


@dataclass
class SimulationResult:
    simulation: Any
    journal: Any
    resources: list[dict[str, Any]]
    checks: dict[str, int]


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
    return _HS.Sim(exo, "pole", config.warmup_days * 24, exo.H)


def simulate(config: HospitalConfig) -> SimulationResult:
    sim = build_simulation(config)
    state = _HS.State(sim.x)
    journal = _RUN.Journal(sim)
    checks: Counter[str] = Counter()
    resources = []
    for hour in range(sim.x.H):
        before = [len(occupied) for occupied in state.occ]
        metrics = sim.step(state, hour, politique=True, log=journal)
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
        if hour >= sim.h0_rec:
            resources.append(
                {
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
            )
    violations = {
        key: value for key, value in checks.items() if key != "heures_controlees" and value
    }
    if violations:
        raise RuntimeError(f"Simulation invariant violations: {violations}")
    return SimulationResult(sim, journal, resources, dict(checks))
