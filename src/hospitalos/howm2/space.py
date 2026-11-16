"""Declared key space for fresh establishments (NORM A0). Runtime registration only: the bytes of
the G0-frozen generator are unchanged; the population laws are exactly those of G0."""

from __future__ import annotations

from hospitalos.howm import generator as G
from hospitalos.howm.keys import key

G0_PARTITIONS = dict(G.PARTITION_SIZES)  # snapshot before registration (includes sealed reserve)
NEW = {"HOWM2_REF": ("REF", 200), "HOWM2_DIAG": ("DIAG", 100)}


def register() -> None:
    for p, (pop, n) in NEW.items():
        G.PARTITION_SIZES[p] = n
        G.POPULATION_OF[p] = pop


def g0_keys() -> set[int]:
    return {key("HOWM1", p, i) for p, n in G0_PARTITIONS.items() for i in range(n)}


def new_keys() -> set[int]:
    return {key("HOWM1", p, i) for p, (_, n) in NEW.items() for i in range(n)}
