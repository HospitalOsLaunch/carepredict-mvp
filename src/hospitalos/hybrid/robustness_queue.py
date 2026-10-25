"""Small competing-departure fixture and independently integrated event oracle.

This benchmark is not the API's hospital engine. One already-requested departure
competes with one optional additional request, across three fictional units.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import numpy as np

from .continuous import Array

HORIZON = 360.0


@dataclass(frozen=True)
class Context:
    at: datetime
    features: Array
    transport: Array
    cleaning: Array
    clearance_age: Array
    waiting: int
    announced_shock: bool


def context(seed: int, index: int, at: datetime, features: Array, announced: bool) -> Context:
    rng = np.random.default_rng(seed * 100003 + index)
    return Context(
        at,
        features,
        rng.integers(20, 61, 3).astype(float),
        rng.integers(20, 61, 3).astype(float),
        rng.uniform(0, 180, 3),
        int(rng.integers(3, 7)),
        announced,
    )


def overlap(start: Array, end: Array, left: float, right: float) -> Array:
    return cast(Array, np.maximum(0, np.minimum(end, right) - np.maximum(start, left)))


def queue_cost(c: Context, preparation: Array, action: int, shock: bool) -> Array:
    """Vectorized event calculation; returns waiting, staffing and transport exposure."""
    if action not in (0, 1, 2) or preparation.ndim != 2 or preparation.shape[1] != 3:
        raise ValueError("Invalid fixture action/shape")
    requested = [0] if action == 0 else [0, action]
    ready = preparation[:, requested]
    order = np.argsort(ready, axis=1, kind="stable")
    row = np.arange(len(preparation))
    available = np.zeros(len(preparation))
    saving = np.zeros(len(preparation))
    staffed = np.full(len(preparation), 360.0 if shock else 0.0)
    transport = np.zeros(len(preparation))
    for position in range(len(requested)):
        patient = np.asarray(requested)[order[:, position]]
        start = np.maximum(preparation[row, patient], available)
        if shock:
            start = np.where((start >= 90) & (start < 180), 180, start)
        departure = start + c.transport[patient]
        admit = departure + c.cleaning[patient]
        if shock:
            admit = np.where((admit >= 120) & (admit < 240), 240, admit)
            staffed -= overlap(departure, admit, 120, 240)
            transport += overlap(start, departure + 30, 90, 180)
        saving += np.maximum(0, HORIZON - admit)
        available = departure + 30
    return cast(Array, np.c_[c.waiting * HORIZON - saving, staffed, transport])


def event_oracle(c: Context, preparation: Array, action: int, shock: bool) -> Array:
    """Scalar event engine; integrates actual occupancy/queue/resource trajectories."""
    events: list[tuple[float, str, int]] = []
    for p in [0] if action == 0 else [0, action]:
        if math.isfinite(float(preparation[p])):
            heapq.heappush(events, (float(preparation[p]), "ready", p))
    if shock:
        events.extend(
            [
                (90, "transport_off", -1),
                (180, "transport_on", -1),
                (120, "staff_off", -1),
                (240, "staff_on", -1),
            ]
        )
        heapq.heapify(events)
    occupancy = [2, 2, 2]
    capacity, transport_capacity, busy = 2, 1, 0
    pending: list[tuple[float, int]] = []
    clean: set[int] = set()
    waiting = c.waiting
    last = 0.0
    total = np.zeros(3)
    while events:
        time = min(events[0][0], HORIZON)
        total += (time - last) * np.array(
            [
                waiting,
                sum(max(0, n - capacity) for n in occupancy),
                max(0, busy - transport_capacity),
            ]
        )
        last = time
        if time >= HORIZON:
            break
        while events and events[0][0] == time:
            _, kind, p = heapq.heappop(events)
            if kind == "ready":
                heapq.heappush(pending, (time, p))
            elif kind == "depart":
                occupancy[p] -= 1
            elif kind == "clean":
                clean.add(p)
            elif kind == "return":
                busy -= 1
            elif kind == "transport_off":
                transport_capacity = 0
            elif kind == "transport_on":
                transport_capacity = 1
            elif kind == "staff_off":
                capacity = 1
            elif kind == "staff_on":
                capacity = 2
        for p in sorted(clean.copy()):
            if occupancy[p] < capacity:
                occupancy[p] += 1
                waiting -= 1
                clean.remove(p)
        if pending and busy < transport_capacity:
            _, p = heapq.heappop(pending)
            busy += 1
            depart = time + float(c.transport[p])
            for t, kind in (
                (depart, "depart"),
                (depart + 30, "return"),
                (depart + float(c.cleaning[p]), "clean"),
            ):
                heapq.heappush(events, (t, kind, p))
    if last < HORIZON:
        total += (HORIZON - last) * np.array(
            [
                waiting,
                sum(max(0, n - capacity) for n in occupancy),
                max(0, busy - transport_capacity),
            ]
        )
    return total


def action_scores(c: Context, sampled: Array) -> tuple[Array, Array]:
    costs = np.stack([queue_cost(c, sampled, action, c.announced_shock) for action in (0, 1, 2)])
    waiting = costs[..., 0]
    tail = np.sort(waiting, axis=1)[:, -max(1, math.ceil(len(sampled) / 10)) :].mean(axis=1)
    objective = 0.75 * waiting.mean(axis=1) + 0.25 * tail
    valid = ~np.any(costs[:, :, 1:] > costs[0:1, :, 1:] + 1e-9, axis=(1, 2))
    return objective, valid


def choose(scores: tuple[Array, Array]) -> int:
    objective, valid = scores
    return int(np.argmin(np.where(valid, objective, np.inf)))


def guard(
    reference: tuple[Array, Array], challenger: tuple[Array, Array], candidate: int, fallback: int
) -> tuple[int, str]:
    def assess(action: int) -> tuple[bool, float]:
        regret = 0.0
        for objective, valid in (reference, challenger):
            if not valid[action] or objective[action] > objective[0] + 1e-9:
                return False, math.inf
            regret = max(regret, float(objective[action] - np.min(objective[valid])))
        return True, regret

    valid, regret = assess(candidate)
    if valid and regret <= 30:
        return candidate, "recommend" if candidate else "no_change"
    if assess(fallback)[0]:
        return fallback, "fallback_disagreement"
    return 0, "abstain_disagreement"
