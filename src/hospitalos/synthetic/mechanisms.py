"""Operational mechanisms sharing the inherited patient dynamics and exogenous draws."""

from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .config import HospitalConfig, SharedResources
from .v041 import hospsim

_HS: Any = hospsim
RESOURCE_ARRAYS = {
    "cleaning": "cap_nettoyage",
    "imaging": "cap_imagerie",
    "transport": "cap_transport",
    "specialist": "cap_avis",
}


def scopes(config: HospitalConfig) -> dict[str, str]:
    if config.mechanism_family == "v041":
        return dict.fromkeys(RESOURCE_ARRAYS, "hospital")
    if config.mechanism_family == "local_v1":
        return dict.fromkeys(RESOURCE_ARRAYS, "pole")
    return {
        "cleaning": "pole",
        "transport": "pole",
        "imaging": "hospital",
        "specialist": "hospital",
    }


def allocate(capacities: NDArray[np.int64], weights: NDArray[np.float64]) -> NDArray[np.int64]:
    """Weighted deficit allocation; integer totals conserved at every hour, no RNG consumed."""
    if np.any(weights < 0) or not np.isfinite(weights).all() or weights.sum() <= 0:
        raise ValueError("Pool weights must be finite, nonnegative and nonzero in total")
    if np.any(capacities < 0):
        raise ValueError("Negative capacity")
    proportions = weights / weights.sum()
    credits = np.zeros(len(weights))
    result = np.zeros((len(weights), len(capacities)), dtype=np.int64)
    for hour, capacity in enumerate(capacities):
        credits += int(capacity) * proportions
        for _ in range(int(capacity)):
            pool = int(np.argmax(credits))
            result[pool, hour] += 1
            credits[pool] -= 1
    return result


class Pools:
    def __init__(self, exo: Any, config: HospitalConfig):
        self.scopes = scopes(config)
        self.unit_poles = [
            next(i for i, p in enumerate(config.poles) if u.unit_id in {x.unit_id for x in p.units})
            for u in config.units
        ]
        overrides = {item.pole_id: item.weights for item in config.pole_resource_weights}
        self.capacity: dict[str, NDArray[np.int64]] = {}
        self.owners: dict[str, list[int]] = {}
        self.labels: dict[str, list[str]] = {}
        for resource, attr in RESOURCE_ARRAYS.items():
            total = np.asarray(getattr(exo, attr), dtype=np.int64)
            if self.scopes[resource] == "hospital":
                self.capacity[resource] = total[None, :]
                self.owners[resource] = [0] * len(config.units)
                self.labels[resource] = [config.hospital_id]
            else:
                weights = np.asarray(
                    [
                        sum(u.beds for u in p.units)
                        * getattr(overrides.get(p.pole_id, SharedResources()), resource)
                        for p in config.poles
                    ],
                    dtype=float,
                )
                self.capacity[resource] = allocate(total, weights)
                self.owners[resource] = self.unit_poles
                self.labels[resource] = [p.pole_id for p in config.poles]

    def budget(self, resource: str, hour: int) -> list[int]:
        return [int(x) for x in self.capacity[resource][:, hour]]


# The only untyped base is the vendored simulator; the new orchestration is typed.
class ResourceSimulation(_HS.Sim):  # type: ignore[misc]
    def __init__(self, exo: Any, config: HospitalConfig):
        super().__init__(exo, "pole", config.warmup_days * 24, exo.H)
        self.config = config
        self.pools = Pools(exo, config)
        self.links = {(link.origin, link.destination) for link in config.routing_links}
        self.started: dict[str, list[int]] = {}
        self.limits: dict[str, list[int]] = {}

    def _cross_allowed(self, origin: int, destination: int) -> bool:
        if origin == destination:
            return True
        if self.config.mechanism_family == "local_v1":
            return False
        names = [p.pole_id for p in self.config.poles]
        return not self.links or (names[origin], names[destination]) in self.links

    def hosting_candidates(self, st: Any, u: int, p: Any, h: int) -> list[tuple[int, int]]:
        origin = self.pools.unit_poles[u]
        candidates = []
        for v in range(self.U):
            destination = self.pools.unit_poles[v]
            if v == u or not self._cross_allowed(origin, destination):
                continue
            if destination != origin and h - p.dec_h < self.config.cross_pole_delay_h:
                continue
            free = int(self.libres(st, v, h))
            if free >= _HS.P["heberg_libres_min"]:
                candidates.append((free, v))
        return sorted(
            candidates, key=lambda t: (self.pools.unit_poles[t[1]] != origin, -t[0], -t[1])
        )

    def start_transports(self, st: Any, h: int, log: Any, m: Any) -> list[int]:
        remaining = self.pools.budget("transport", h)
        self.limits["transport"] = list(remaining)
        self.started["transport"] = [0] * len(remaining)
        waiting: deque[Any] = deque()
        while st.q_tr:
            pid, requested = st.q_tr.popleft()
            patient = st.patients.get(pid)
            if patient is None:
                continue
            pool = self.pools.owners["transport"][patient.unit]
            if remaining[pool] <= 0:
                waiting.append((pid, requested))
                continue
            remaining[pool] -= 1
            self.started["transport"][pool] += 1
            if log is not None:
                log.tache_debut(f"TR-{pid}", h)
                log.tache_fin(f"TR-{pid}", h)
            self.sortir(st, patient, h, log, m)
        st.q_tr = waiting
        return remaining

    def repatriate(self, st: Any, h: int, log: Any, m: Any, remaining: list[int]) -> None:
        if not 9 <= h % 24 < 17:
            return
        for origin in range(self.U):
            pool = self.pools.owners["transport"][origin]
            for patient in list(st.occ[origin].values()):
                if remaining[pool] <= 0:
                    break
                destination = patient.home
                if (
                    destination == origin
                    or patient.dis_h - h < _HS.P["rapatriement_marge_h"]
                    or patient.tr
                    or st.q_urg[destination]
                    or st.q_prog[destination]
                    or not self._cross_allowed(
                        self.pools.unit_poles[origin], self.pools.unit_poles[destination]
                    )
                ):
                    continue
                bed = int(self.lit_compatible(st, destination, patient.pid, h))
                if bed < 0:
                    continue
                remaining[pool] -= 1
                self.started["transport"][pool] += 1
                previous_bed = patient.bed
                self.liberer(st, patient, h, log)
                patient.unit, patient.bed = destination, bed
                patient.rapat += 1
                st.occ[destination][patient.pid] = patient
                st.bed_pid[destination][bed] = patient.pid
                m["transf_out"][origin] += 1
                m["transf_in"][destination] += 1
                if log is not None:
                    log.event(
                        h,
                        "TRANSFERT_INTERNE",
                        destination,
                        patient.pid,
                        depuis=self.x.unit_names[origin],
                        lit_origine=previous_bed,
                        lit=bed,
                    )

    def start_services(self, st: Any, h: int, log: Any) -> None:
        remaining = self.pools.budget("cleaning", h)
        for task in st.net_cours:
            remaining[self.pools.owners["cleaning"][task[1]]] -= 1
        remaining = [max(0, x) for x in remaining]
        self.limits["cleaning"] = list(remaining)
        self.started["cleaning"] = [0] * len(remaining)
        waiting: deque[Any] = deque()
        while st.q_net:
            task = st.q_net.popleft()
            unit, bed, duration, requested = task
            pool = self.pools.owners["cleaning"][unit]
            if remaining[pool] <= 0:
                waiting.append(task)
                continue
            remaining[pool] -= 1
            self.started["cleaning"][pool] += 1
            st.bed_sale[unit][bed] = 2
            st.net_cours.append((h + duration, unit, bed, requested, h))
            if log is not None:
                log.tache_debut(f"NET-{unit}-{bed}-{requested}", h)
        st.q_net = waiting
        for resource, queue_name, running_name, prefix, duration in (
            ("imaging", "q_img", "img_cours", "IMG", 1),
            ("specialist", "q_avis", "avis_cours", "AVIS", _HS.P["avis_duree_h"]),
        ):
            remaining = self.pools.budget(resource, h)
            self.limits[resource] = list(remaining)
            self.started[resource] = [0] * len(remaining)
            queue = getattr(st, queue_name)
            deferred: deque[tuple[int, int]] = deque()
            while queue:
                pid, requested = queue.popleft()
                patient = st.patients.get(pid)
                if patient is None:
                    continue
                pool = self.pools.owners[resource][patient.unit]
                if remaining[pool] <= 0:
                    deferred.append((pid, requested))
                    continue
                remaining[pool] -= 1
                self.started[resource][pool] += 1
                getattr(st, running_name).append((h + duration, pid, requested, h))
                if log is not None:
                    log.tache_debut(f"{prefix}-{pid}", h)
            setattr(st, queue_name, deferred)

    def resource_rows(self, st: Any, h: int) -> list[dict[str, Any]]:
        rows = []
        for resource, queue_name in (
            ("cleaning", "q_net"),
            ("imaging", "q_img"),
            ("transport", "q_tr"),
            ("specialist", "q_avis"),
        ):
            capacities = self.pools.budget(resource, h)
            waiting = [0] * len(capacities)
            busy = [0] * len(capacities)
            for task in getattr(st, queue_name):
                if resource == "cleaning":
                    unit = task[0]
                else:
                    patient = st.patients.get(task[0])
                    if patient is None:
                        continue
                    unit = patient.unit
                waiting[self.pools.owners[resource][unit]] += 1
            if resource == "cleaning":
                for task in st.net_cours:
                    busy[self.pools.owners[resource][task[1]]] += 1
            for pool, capacity in enumerate(capacities):
                started = self.started[resource][pool]
                limit = self.limits[resource][pool]
                if started > limit:
                    raise RuntimeError(f"Pool capacity exceeded: {resource}/{pool} at {h}")
                rows.append(
                    {
                        "h": h - self.h0_rec,
                        "resource": resource,
                        "scope": self.pools.scopes[resource],
                        "pool_id": self.pools.labels[resource][pool],
                        "capacity": capacity,
                        "start_limit": limit,
                        "started": started,
                        "queue": waiting[pool],
                        "active_cleaning": busy[pool],
                    }
                )
            if sum(capacities) != int(getattr(self.x, RESOURCE_ARRAYS[resource])[h]):
                raise RuntimeError("Pool allocation changed total hospital capacity")
        return rows
