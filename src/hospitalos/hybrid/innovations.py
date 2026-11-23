"""Policy-independent indexed random innovations for paired scenarios."""

import hashlib


def draw(support: tuple[int, ...], seed: int, scenario: int, mechanism: str, entity: str) -> int:
    key = f"{seed}|{scenario}|{mechanism}|{entity}".encode()
    index = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % len(support)
    return support[index]


def uniform(seed: int, scenario: int, mechanism: str, entity: str) -> float:
    key = f"{seed}|{scenario}|{mechanism}|{entity}".encode()
    bits = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") >> 11
    return bits / 2**53
