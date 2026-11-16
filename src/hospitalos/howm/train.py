"""Resumable training of B2 / H1 (NORM N1, N6.8; A4): Adam, batch 32 origins, <= 60 epochs,
patience 20 on the normalised VAL loss, lr in {3e-4, 1e-3}. Checkpoints every <= 400 s and at the
end of every command (weights, optimiser, scheduler='none', RNG, position, config, code hashes).
Data order is a keyed permutation of (seed, epoch): resuming never changes the sequence.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

from . import ckpt
from .b0 import B0Params
from .corpus import EVID, code_hashes
from .dataset import EstablishmentData
from .keys import key
from .nets import B2, H1, NetConfig, forward_losses, make_batch, total_loss

RUNS = EVID / "train"
MAX_EPOCHS = 60
PATIENCE = 20
BATCH = 32
CKPT_EVERY_S = 400.0


def run_dir(kind: str, lr: float, seed: int) -> Path:
    return RUNS / f"{kind}_lr{lr:g}_s{seed}"


def new_model(kind: str, b0: B0Params, seed: int) -> torch.nn.Module:
    torch.manual_seed(seed)
    return B2(b0, NetConfig("B2")) if kind == "B2" else H1(b0, NetConfig("H1"))


def order(pairs_n: int, seed: int, epoch: int) -> np.ndarray:
    keys_ = np.array([key("HOWM1-order", seed, epoch, i) for i in range(pairs_n)], dtype=np.uint64)
    return np.argsort(keys_, kind="stable")


def evaluate_loss(
    model: torch.nn.Module,
    kind: str,
    pairs: list[tuple[EstablishmentData, int]],
    scales: dict[str, float],
) -> dict[str, Any]:
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    with torch.no_grad():
        for i in range(0, len(pairs), BATCH):
            parts = forward_losses(model, make_batch(pairs[i : i + BATCH], kind))
            for f, (s, n) in parts.items():
                sums[f] = sums.get(f, 0.0) + float(s)
                counts[f] = counts.get(f, 0) + n
    means = {f: sums[f] / max(counts[f], 1) for f in sums}
    return {
        "total": sum(means[f] / scales[f] for f in means if f in scales),
        "means": means,
        "counts": counts,
    }


def _save(
    d: Path,
    name: str,
    model: torch.nn.Module,
    opt: torch.optim.Optimizer,
    st: dict[str, Any],
    cfg: dict[str, Any],
) -> str:
    obj = {
        "model": model.state_dict(),
        "optimizer": opt.state_dict(),
        "scheduler": {"kind": "none"},
        "rng": ckpt.pack_rng(),
        "position": {"epoch": st["epoch"], "batch_pos": st["batch_pos"]},
        "state_json": json.dumps(st),
        "config_json": json.dumps(cfg),
    }
    return ckpt.save(obj, d / name)


def train(
    kind: str,
    lr: float,
    seed: int,
    budget_s: float,
    train_pairs: list[tuple[EstablishmentData, int]],
    val_pairs: list[tuple[EstablishmentData, int]],
    b0: B0Params,
    scales: dict[str, float],
    max_steps: int | None = None,
) -> dict[str, Any]:
    t_start = time.monotonic()
    d = run_dir(kind, lr, seed)
    d.mkdir(parents=True, exist_ok=True)
    meta_p = d / "state.json"
    cfg = {
        "kind": kind,
        "lr": lr,
        "seed": seed,
        "batch": BATCH,
        "max_epochs": MAX_EPOCHS,
        "patience": PATIENCE,
        "scales": scales,
        "code": code_hashes(),
        "n_train": len(train_pairs),
        "n_val": len(val_pairs),
    }
    model = new_model(kind, b0, seed)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    if meta_p.exists():
        meta = json.loads(meta_p.read_text())
        if meta["config"]["code"] != cfg["code"]:
            raise ckpt.CheckpointRefused("code hashes changed since this run started (T-CKPT-03)")
        obj = ckpt.load_verified(d / "last.pt", meta["last_sha256"])
        model.load_state_dict(obj["model"])
        opt.load_state_dict(obj["optimizer"])
        ckpt.unpack_rng(obj["rng"])
        st = json.loads(obj["state_json"])
    else:
        meta = {"config": cfg, "log": []}
        st = {
            "epoch": 0,
            "batch_pos": 0,
            "best_val": None,
            "best_epoch": None,
            "bad": 0,
            "done": False,
            "steps": 0,
            "train_seconds": 0.0,
        }
    last_ck = time.monotonic()
    steps_here = 0

    def checkpoint() -> None:
        nonlocal last_ck
        meta["last_sha256"] = _save(d, "last.pt", model, opt, st, cfg)
        meta["config"] = cfg
        meta_p.write_text(json.dumps(meta, indent=1))
        last_ck = time.monotonic()

    while not st["done"]:
        perm = order(len(train_pairs), seed, st["epoch"])
        nb = (len(perm) + BATCH - 1) // BATCH
        while st["batch_pos"] < nb:
            if time.monotonic() - t_start > budget_s or (
                max_steps is not None and steps_here >= max_steps
            ):
                checkpoint()
                return {"status": "incomplete", **st}
            t0 = time.monotonic()
            sel = perm[st["batch_pos"] * BATCH : (st["batch_pos"] + 1) * BATCH]
            batch = make_batch([train_pairs[i] for i in sel], kind)
            opt.zero_grad()
            loss = total_loss(forward_losses(model, batch), scales)
            loss.backward()
            opt.step()
            st["batch_pos"] += 1
            st["steps"] += 1
            steps_here += 1
            st["train_seconds"] += time.monotonic() - t0
            if not torch.isfinite(loss):
                st["diverged"] = True
                checkpoint()
                return {"status": "diverged", **st}
            if time.monotonic() - last_ck > CKPT_EVERY_S:
                checkpoint()
        v = evaluate_loss(model, kind, val_pairs, scales)
        st["epoch"] += 1
        st["batch_pos"] = 0
        improved = st["best_val"] is None or v["total"] < st["best_val"]
        if improved:
            st["best_val"], st["best_epoch"], st["bad"] = v["total"], st["epoch"], 0
            meta["best_sha256"] = _save(d, "best.pt", model, opt, st, cfg)
        else:
            st["bad"] += 1
        meta["log"].append(
            {
                "epoch": st["epoch"],
                "val_total": v["total"],
                "val_means": v["means"],
                "improved": improved,
            }
        )
        if st["bad"] >= PATIENCE or st["epoch"] >= MAX_EPOCHS:
            st["done"] = True
        checkpoint()
    return {"status": "done", **st}
