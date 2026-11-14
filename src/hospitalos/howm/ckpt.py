"""Checkpoint helpers compatible with torch.load(weights_only=True).

RNG states are stored as tensors and plain Python types only (never pickled objects), so a
checkpoint can always be restored without weights_only=False. Loading is refused unless the
file's SHA-256 is the one recorded in the HOWM ledger/receipt (load_verified)."""

from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import Any

import numpy as np
import torch


def pack_rng() -> dict[str, Any]:
    py = random.getstate()
    np_state = np.random.get_state()
    return {
        "python": {
            "version": int(py[0]),
            "state": torch.tensor(py[1], dtype=torch.int64),
            "gauss": py[2] if py[2] is None else float(py[2]),
        },
        "numpy": {
            "keys": torch.tensor(np_state[1].astype(np.int64)),
            "pos": int(np_state[2]),
            "has_gauss": int(np_state[3]),
            "cached": float(np_state[4]),
        },
        "torch": torch.get_rng_state(),
    }


def unpack_rng(s: dict[str, Any]) -> None:
    p = s["python"]
    random.setstate((p["version"], tuple(int(x) for x in p["state"].tolist()), p["gauss"]))
    n = s["numpy"]
    np.random.set_state(
        ("MT19937", n["keys"].numpy().astype(np.uint32), n["pos"], n["has_gauss"], n["cached"])
    )
    torch.set_rng_state(s["torch"])


class CheckpointRefused(RuntimeError):
    pass


def save(obj: dict[str, Any], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    torch.save(obj, tmp)
    tmp.replace(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_verified(path: Path, expected_sha256: str) -> dict[str, Any]:
    """Only tranche-produced checkpoints whose hash was recorded; weights_only=True always."""
    p = Path(path)
    if (
        "evidence/howm1" not in p.resolve().as_posix()
        and "howm1_ckpt" not in p.resolve().as_posix()
    ):
        raise CheckpointRefused(f"not a HOWM-1 checkpoint location: {p}")
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise CheckpointRefused(f"sha256 mismatch for {p}: {digest} != {expected_sha256}")
    return torch.load(p, weights_only=True)
