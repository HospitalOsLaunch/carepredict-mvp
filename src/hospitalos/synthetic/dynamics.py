"""Alternative arrival, discharge and workforce mechanisms; no global parameter edits.

All constants are versioned engineering assumptions, not clinical estimates. Separate
random streams prevent a staffing variant from changing the incoming patient cohort.
"""

from __future__ import annotations

import datetime as dt
import math
from copy import deepcopy
from typing import Any

import numpy as np

from .config import HospitalConfig
from .mechanisms import ResourceSimulation
from .v041 import hospsim

_HS: Any = hospsim


class DynamicsExo(_HS.Exo):  # type: ignore[misc]
    def __init__(self, *args: Any, config: HospitalConfig, **kwargs: Any):
        self.dynamics = config.dynamics
        self.clinical = config.clinical
        super().__init__(*args, **kwargs)

    def destination_probabilities(self, spec: dict[str, Any], age: int, dep: int) -> Any:
        if self.clinical.destinations == "v041":
            return super().destination_probabilities(spec, age, dep)
        weights = np.asarray(spec["dest"], dtype=float).copy()
        # Death risk is separate from the conditional distribution among survivors.
        death = float(weights[_HS.DECES] / weights.sum())
        death *= max(0.3, 1 + self.clinical.death_age_slope * (age - 75))
        death *= 1 + self.clinical.death_dependence_slope * (dep - 1)
        death = min(1.0, death)
        weights[_HS.DECES] = 0
        weights[_HS.SMR] *= max(0.2, 1 + 0.35 * (dep - 2))
        weights[_HS.EHPAD] *= max(0.1, 1 + 0.6 * (dep - 2)) if age >= 75 else 0.3
        weights *= (1 - death) / weights.sum()
        weights[_HS.DECES] = death
        return weights

    def _capacites_et_effectifs(self, rng: Any) -> None:
        # Consume exactly the reference draws, preserving patients/services/policy RNG.
        closure_rng = deepcopy(rng)
        super()._capacites_et_effectifs(rng)
        variant = self.dynamics.staffing
        if variant == "v041":
            return
        random = np.random.default_rng(np.random.SeedSequence([self.seed, 7001]))
        # Replay the reference calendar/maintenance draws without its shortage closures.
        # Still consume its absence/replacement draws to retain the next unit's RNG position.
        reference_closed = np.zeros((self.U, self.ndays), dtype=int)
        for u, spec in enumerate(self.specs):
            beds = spec["lits"]
            for day in range(self.ndays):
                reference_closed[u, day] = max(
                    round(spec["fermeture_ete"] * beds) if self.ete[day] else 0,
                    round(spec["fermeture_noel"] * beds) if self.noel[day] else 0,
                )
            day = 0
            while day < self.ndays:
                if closure_rng.random() < 0.03:
                    number = int(closure_rng.integers(1, 3))
                    duration = int(closure_rng.integers(1, 6))
                    reference_closed[u, day : day + duration] += number
                    day += duration
                day += 1
            for day in range(self.ndays):
                rate = float(
                    np.clip(
                        _HS.P["absence_base"]
                        + _HS.P["absence_grippe"] * self.grippe[day]
                        + closure_rng.normal(0, 0.01),
                        0.02,
                        0.25,
                    )
                )
                for shift in range(3):
                    absent = closure_rng.binomial(self.prevus[u, 3 * day + shift + 1], rate)
                    closure_rng.binomial(
                        absent,
                        _HS.P["remplacement_jour"] if shift < 2 else _HS.P["remplacement_nuit"],
                    )
        if closure_rng.bit_generator.state != rng.bit_generator.state:
            raise RuntimeError("Reference closure replay diverged")
        if variant == "persistent_absence_v1":
            for u in range(self.U):
                absent = 0
                for sid in range(1, 3 * self.ndays + 1):
                    planned = int(self.prevus[u, sid])
                    surviving = int(random.binomial(min(absent, planned), 0.75))
                    absent = surviving + int(random.binomial(planned - surviving, 0.025))
                    self.absents[u, sid] = absent
                    self.remplaces[u, sid] = random.binomial(absent, 0.35)
        else:
            # A finite hospital float pool, allocated to the largest unmet deficits.
            self.remplaces[:] = 0
            for sid in range(1, 3 * self.ndays + 1):
                available = int(self.prevus[:, sid].sum() // 12)
                deficits = self.absents[:, sid].copy()
                for _ in range(available):
                    u = int(np.argmax(deficits))
                    if deficits[u] == 0:
                        break
                    self.remplaces[u, sid] += 1
                    deficits[u] -= 1
        shortage = (
            self.absents[:, 1 : 3 * self.ndays : 3] - self.remplaces[:, 1 : 3 * self.ndays : 3]
        )
        extra = 2 * (shortage >= 2)
        self.ferme_jour = np.minimum(reference_closed + extra, self.lits[:, None] - 4)
        for u in range(self.U):
            for day in range(self.ndays):
                self.fermes[u, day * 24 + 7 : (day + 1) * 24 + 7] = self.ferme_jour[u, day]
            self.fermes[u, :7] = self.ferme_jour[u, 0]

    def _patients(self, rng: Any) -> None:
        if self.dynamics.arrivals == "v041":
            super()._patients(rng)
            return
        random = np.random.default_rng(np.random.SeedSequence([self.seed, 7002]))
        # Shared day intensity creates correlated bursts across units, mean one.
        intensity = np.asarray(random.gamma(2.0, 0.5, self.ndays))
        columns: dict[str, list[Any]] = {
            k: []
            for k in (
                "unit",
                "src",
                "arr_h",
                "arr_min",
                "age",
                "femme",
                "dep",
                "iso",
                "oxy",
                "img",
                "los_med_h",
                "dest",
                "aval_j",
                "u_heure",
                "u_weekend",
                "nett_h",
                "u_pression",
                "u_readm",
                "u_saisie",
                "u_hors_pole",
                "montee_h",
                "avis",
                "mob",
                "aide",
                "aide_delai_h",
            )
        }
        for u, spec in enumerate(self.specs):
            lam = self.lambda_unite(u)
            for day in range(self.ndays):
                season = 1 + spec["saison"] * max(
                    math.cos(2 * math.pi * (self.doy[day] - 15) / 365), -0.3
                )
                epidemic = (1 + spec["grippe"] * self.grippe[day]) * (
                    1 + spec["canicule"] * self.canicule[day]
                )
                means = [
                    lam[0]
                    * season
                    * epidemic
                    * _HS.DOW_URG[self.dow[day]]
                    * (0.95 if self.ferie[day] else 1),
                    lam[1]
                    * _HS.DOW_PROG[self.dow[day]]
                    * (0.5 if self.noel[day] else 1)
                    * (0.8 if self.ete[day] else 1)
                    if self.ouvre[day]
                    else 0,
                    lam[2] * (0.6 if self.dow[day] >= 5 else 1.15),
                ]
                for source, mean in enumerate(means):
                    if self.dynamics.arrivals == "appointments_v1" and source == _HS.PROG:
                        # Fixed appointment slots with attendance; same expected daily volume.
                        slots = math.ceil(mean / 0.85)
                        count = int(random.binomial(slots, mean / slots)) if slots else 0
                        hours = [8 + i % 6 for i in range(count)]
                    else:
                        factor = (
                            intensity[day]
                            if self.dynamics.arrivals == "shared_bursts_v1" and source == _HS.URG
                            else 1
                        )
                        count = int(random.poisson(mean * factor))
                        if source == _HS.URG:
                            hours = random.choice(24, count, p=_HS.PROFIL_DECISION_URG).tolist()
                        else:
                            hours = random.integers(
                                8 if source == _HS.PROG else 9,
                                14 if source == _HS.PROG else 20,
                                count,
                            ).tolist()
                    for hour in hours:
                        self._un_patient(rng, columns, u, spec, source, day * 24 + int(hour))
        order = np.argsort(
            np.asarray(columns["arr_h"]) * 60 + np.asarray(columns["arr_min"]), kind="stable"
        )
        self.pat = {key: np.asarray(values)[order] for key, values in columns.items()}
        self.N = len(order)
        self.arrivees: list[list[int]] = [[] for _ in range(self.H)]
        for pid, hour in enumerate(self.pat["arr_h"]):
            self.arrivees[int(hour)].append(pid)


def discharge_time(sim: Any, patient: Any, variant: str) -> int:
    """Plan based on readiness and destination, never on future resource availability."""
    pid = patient.pid
    destination = int(sim.p_dest[pid])
    ready = int(patient.ready_h)
    if destination == _HS.DECES:
        return ready
    if destination == _HS.SMR and getattr(sim, "smr", None) is not None:
        return ready + 1
    if destination == _HS.DOM:
        ready = max(ready, int(patient.aide_h))
    else:
        ready += max(24, math.ceil(float(sim.x.pat["aval_j"][pid]) * 24))
    earliest = ready + 1
    if variant == "rolling_v1":
        # Daily 08-20 service, including weekends; no morning cut-off.
        day, hour = divmod(earliest, 24)
        return day * 24 + 8 if hour < 8 else earliest if hour < 20 else (day + 1) * 24 + 8
    # One daily round, weekdays only for all live destinations.
    day, hour = divmod(earliest, 24)
    if hour > 14:
        day += 1
    # Calendar calculation continues beyond export cutoff; truth stays censored by exporter.

    while True:
        date = sim.x.debut + dt.timedelta(days=day)
        if date.weekday() < 5 and date not in _HS.jours_feries([date.year]):
            return day * 24 + 14
        day += 1


class DynamicSimulation(_HS.Sim):  # type: ignore[misc]
    def __init__(self, exo: Any, config: HospitalConfig):
        super().__init__(exo, "pole", config.warmup_days * 24, exo.H)
        self.config = config

    def planifier(self, patient: Any) -> int:
        return discharge_time(self, patient, self.config.dynamics.discharges)


class DynamicResourceSimulation(ResourceSimulation):
    def planifier(self, patient: Any) -> int:
        return discharge_time(self, patient, self.config.dynamics.discharges)
