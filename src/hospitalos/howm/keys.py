"""Keyed, order-independent random primitives (vectorisable).

A draw is a pure function of its key: (namespace, realisation, primitive, entity, index...). The
same key always gives the same uniform, whatever the number or order of calls (T-GEN-01). Strings
are mapped once to 64-bit integers (BLAKE2b); integers are combined with splitmix64.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

import numpy as np

_M64 = (1 << 64) - 1


@lru_cache(maxsize=1 << 18)
def h64(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), "big")


def _mix(z: int) -> int:
    z = (z + 0x9E3779B97F4A7C15) & _M64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _M64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _M64
    return z ^ (z >> 31)


def key(*parts: object) -> int:
    z = 0x243F6A8885A308D3
    for p in parts:
        v = p if isinstance(p, int) and not isinstance(p, bool) else h64(repr(p))
        z = _mix(z ^ (v & _M64))
    return z


def u(*parts: object) -> float:
    """Uniform in (0, 1) for a key."""
    return ((key(*parts) >> 11) + 0.5) / float(1 << 53)


def u_vec(base: int, idx: np.ndarray) -> np.ndarray:
    """Vectorised uniforms in (0,1): splitmix64 of (base, idx) for an integer array idx."""
    with np.errstate(over="ignore"):
        z = np.uint64(base & _M64) ^ (idx.astype(np.uint64) * np.uint64(0xD1B54A32D192ED03))
        z = z + np.uint64(0x9E3779B97F4A7C15)
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        z = z ^ (z >> np.uint64(31))
    return ((z >> np.uint64(11)).astype(np.float64) + 0.5) / float(1 << 53)
