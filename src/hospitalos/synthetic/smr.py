"""Finite SMR allocation. Physics lives in clonable state, never in a document reader.

Scenario need is revealed at current medical readiness. Eligibility here means
oxygen/isolation compatibility only, not a validated clinical SMR admission rule.
All outside demand uses the same FIFO and capacity as the hospital's patients.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from .config import SMRConfig

SMR = 1
Status = Literal["waiting", "reserved", "occupied", "released", "cancelled"]


@dataclass
class Request:
    key: str
    pid: int | None
    unit: int
    requested_h: int
    due_h: int
    oxygen: bool
    isolation: bool
    status: Status = "waiting"
    bed: int | None = None
    reserved_h: int | None = None
    occupied_h: int | None = None
    release_h: int | None = None
    refusals: int = 0


@dataclass
class SMRState:
    requests: dict[str, Request] = field(default_factory=dict)
    internal: dict[int, str] = field(default_factory=dict)
    sequence: dict[int, int] = field(default_factory=dict)
    beds: dict[int, str] = field(default_factory=dict)
    last_h: int = -1


class SMRAllocator:
    def __init__(self, config: SMRConfig, seed: int):
        self.config = config
        self.seed = seed

    def random(self, *key: str | int) -> np.random.Generator:
        value = json.dumps([self.seed, "finite_smr_v1", *key]).encode()
        return np.random.default_rng(int.from_bytes(hashlib.sha256(value).digest()[:16], "big"))

    @staticmethod
    def state(st: Any) -> SMRState:
        if not hasattr(st, "smr_state"):
            st.smr_state = SMRState()
        result: SMRState = st.smr_state
        return result

    @staticmethod
    def event(log: Any, h: int, kind: str, request: Request, **details: Any) -> None:
        if log is not None:
            log.event(
                h,
                "SMR_" + kind,
                request.unit,
                request.pid,
                request_id=request.key,
                origin="hospital" if request.pid is not None else "external",
                **details,
            )

    def compatible(self, r: Request, bed: int) -> bool:
        return (not r.oxygen or bed < self.config.oxygen_beds) and (
            not r.isolation or bed < self.config.isolation_beds
        )

    def free_bed(self, state: SMRState, r: Request) -> int | None:
        # Least specialised compatible place, so flexible patients leave scarce beds free.
        return next(
            (
                b
                for b in reversed(range(self.config.beds))
                if b not in state.beds and self.compatible(r, b)
            ),
            None,
        )

    def cancel(self, st: Any, r: Request, h: int, log: Any, reason: str) -> None:
        state = self.state(st)
        if r.status not in ("waiting", "reserved"):
            raise ValueError("Only pending SMR requests can be cancelled")
        if r.bed is not None:
            del state.beds[r.bed]
        r.status, r.bed, r.reserved_h = "cancelled", None, None
        if r.pid is not None and r.pid in st.patients:
            st.patients[r.pid].conf = False
            st.patients[r.pid].aval_dem = False
            st.patients[r.pid].tr = False
            st.q_tr = deque((pid, t) for pid, t in st.q_tr if pid != r.pid)
        self.event(log, h, "CANCELLED", r, reason=reason)
        if log is not None and r.pid is not None:
            log.event(h, "DEMANDE_AVAL_ANNULEE", r.unit, r.pid, request_id=r.key)

    def occupy(self, state: SMRState, r: Request, h: int, log: Any) -> None:
        if r.status != "reserved" or r.bed is None or state.beds.get(r.bed) != r.key:
            raise RuntimeError("SMR admission requires its own valid reservation")
        random = self.random("stay", r.key)
        duration = math.ceil(
            24 * random.lognormal(math.log(self.config.stay_median_days), self.config.stay_sigma)
        )
        r.status, r.occupied_h, r.release_h = "occupied", h, h + min(4320, max(24, duration))
        # Do not publish the future release date/duration into events.
        self.event(log, h, "ADMITTED", r, bed=r.bed)

    def permits(self, sim: Any, st: Any, p: Any, h: int) -> bool:
        if sim.p_dest[p.pid] != SMR:
            return True
        state = self.state(st)
        r = state.requests.get(state.internal.get(p.pid, ""))
        return bool(
            r is not None
            and r.status == "reserved"
            and r.bed is not None
            and state.beds.get(r.bed) == r.key
            and r.reserved_h is not None
            and h < r.reserved_h + self.config.reservation_ttl_h
            and p.ready_h < h
            and not sim.bloque(p)
        )

    def depart(self, sim: Any, st: Any, p: Any, h: int, log: Any) -> None:
        if not self.permits(sim, st, p, h):
            raise RuntimeError("Hospital departure without eligible SMR reservation")
        state = self.state(st)
        self.occupy(state, state.requests[state.internal[p.pid]], h, log)

    def prepare(self, sim: Any, st: Any, h: int, log: Any) -> None:
        state = self.state(st)
        if h <= state.last_h:
            raise ValueError("SMR physics must advance once per increasing hour")
        state.last_h = h
        for r in state.requests.values():
            if r.status == "occupied" and r.release_h is not None and r.release_h <= h:
                assert r.bed is not None
                del state.beds[r.bed]
                self.event(log, h, "RELEASED", r, bed=r.bed)
                r.status, r.bed = "released", None
            elif r.status in ("waiting", "reserved"):
                p = st.patients.get(r.pid)
                if r.pid is not None:
                    if p is None or sim.p_dest[r.pid] != SMR or p.ready_h > h or sim.bloque(p):
                        self.cancel(st, r, h, log, "readiness_or_need_withdrawn")
                        continue
                    r.unit = p.unit
                elif h - r.requested_h >= self.config.external_patience_h:
                    self.cancel(st, r, h, log, "external_withdrawal")
                    continue
                if (
                    r.status == "reserved"
                    and r.reserved_h is not None
                    and h >= r.reserved_h + self.config.reservation_ttl_h
                ):
                    assert r.bed is not None
                    del state.beds[r.bed]
                    self.event(log, h, "RESERVATION_EXPIRED", r, bed=r.bed)
                    r.status, r.bed, r.reserved_h, r.due_h = (
                        "waiting",
                        None,
                        None,
                        h + self.config.retry_h,
                    )
                    if p is not None:
                        p.conf, p.tr = False, False
                        st.q_tr = deque((pid, t) for pid, t in st.q_tr if pid != r.pid)
                        if log is not None:
                            log.event(h, "DEMANDE_AVAL_ANNULEE", p.unit, p.pid, request_id=r.key)
                            log.event(
                                h, "DEMANDE_AVAL", p.unit, p.pid, type_aval="SMR", request_id=r.key
                            )

        for p in sorted(st.patients.values(), key=lambda p: p.pid):
            previous = state.requests.get(state.internal.get(p.pid, ""))
            if (
                sim.p_dest[p.pid] != SMR
                or p.ready_h > h
                or sim.bloque(p)
                or (previous is not None and previous.status in ("waiting", "reserved"))
            ):
                continue
            seq = state.sequence.get(p.pid, 0) + 1
            state.sequence[p.pid] = seq
            key = f"P{p.pid}:{seq}"
            r = Request(
                key,
                p.pid,
                p.unit,
                h,
                h + self.config.preparation_h,
                bool(sim.p_oxy[p.pid]),
                bool(sim.p_iso[p.pid]),
            )
            state.requests[key], state.internal[p.pid] = r, key
            p.dest_decl, p.aval_dem, p.conf = SMR, True, False
            if getattr(sim, "documentary", None) is not None:
                sim.documentary.requests.pop(p.pid, None)
            self.event(log, h, "REQUESTED", r, oxygen=r.oxygen, isolation=r.isolation)
            if log is not None:
                log.event(
                    h, "DESTINATION_DEMANDEE", p.unit, p.pid, destination_demandee="SMR", revision=1
                )
                log.event(h, "DEMANDE_AVAL", p.unit, p.pid, type_aval="SMR", request_id=key)

        random = self.random("outside", h)
        for index in range(int(random.poisson(self.config.external_arrivals_per_day / 24))):
            key = f"X{h}:{index}"
            r = Request(
                key,
                None,
                0,
                h,
                h + self.config.preparation_h,
                bool(random.random() < self.config.external_oxygen_probability),
                bool(random.random() < self.config.external_isolation_probability),
            )
            state.requests[key] = r
            self.event(log, h, "REQUESTED", r, oxygen=r.oxygen, isolation=r.isolation)

        if h % 24 == self.config.review_hour and sim.x.ouvre[h // 24]:
            for r in sorted(state.requests.values(), key=lambda r: (r.requested_h, r.key)):
                if r.status != "waiting" or r.due_h > h:
                    continue
                bed = self.free_bed(state, r)
                if bed is None:
                    r.refusals += 1
                    self.event(log, h, "DEFERRED", r, reason="no_compatible_available_bed")
                    continue
                r.status, r.bed, r.reserved_h = "reserved", bed, h
                state.beds[bed] = r.key
                self.event(log, h, "RESERVED", r, bed=bed)
                if r.pid is None:
                    self.occupy(state, r, h, log)
                else:
                    p = st.patients[r.pid]
                    p.conf = True
                    if log is not None:
                        log.event(
                            h,
                            "PLACE_AVAL_CONFIRMEE",
                            p.unit,
                            p.pid,
                            type_aval="SMR",
                            request_id=r.key,
                        )

    def inspect(self, sim: Any, st: Any, h: int) -> dict[str, int]:
        state = self.state(st)
        active = [r for r in state.requests.values() if r.status in ("reserved", "occupied")]
        if len(active) != len(state.beds) or any(
            r.bed is None
            or not 0 <= r.bed < self.config.beds
            or state.beds.get(r.bed) != r.key
            or not self.compatible(r, r.bed)
            for r in active
        ):
            raise RuntimeError("SMR capacity/ownership/compatibility violated")
        for r in active:
            if r.pid is not None and ((r.status == "reserved") != (r.pid in st.patients)):
                raise RuntimeError("SMR and hospital presence conflict")
        waiting = [r for r in state.requests.values() if r.status == "waiting"]
        return {
            "smr_capacity": self.config.beds,
            "smr_free": self.config.beds - len(active),
            "smr_reserved": sum(r.status == "reserved" for r in active),
            "smr_occupied": sum(r.status == "occupied" for r in active),
            "smr_waiting_internal": sum(r.pid is not None for r in waiting),
            "smr_waiting_external": sum(r.pid is None for r in waiting),
            "smr_waiting_capacity_internal": sum(
                r.pid is not None and r.due_h <= h and self.free_bed(state, r) is None
                for r in waiting
            ),
        }
