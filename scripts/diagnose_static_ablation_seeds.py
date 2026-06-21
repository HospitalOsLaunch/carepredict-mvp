#!/usr/bin/env python3
"""Diagnostic multi-seed de l'ablation static du probe RS-JEPA.

Ce script mesure seulement la stabilité du delta with_static - without_static
sur des latents entraînés. Il ne change ni la loss, ni l'encodeur, ni les
hyperparamètres persistés dans la configuration.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np
import torch

from rs_jepa.config import load_config
from rs_jepa.probe import ProbeResult
from rs_jepa.train import run_stage1_training


def _parse_seeds(raw: str) -> list[int]:
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _cfg_for_seed(args: argparse.Namespace, seed: int):
    cfg = load_config(args.config)
    split = replace(cfg.split, seed=seed)
    synthetic = replace(cfg.synthetic, seed=seed)
    training = replace(
        cfg.training,
        max_epochs=args.max_epochs,
        steps_per_epoch=args.steps_per_epoch,
        checkpoint_path="",
    )
    return replace(cfg, seed=seed, split=split, synthetic=synthetic, training=training)


def _snapshot_params(module: torch.nn.Module) -> list[torch.Tensor]:
    return [param.detach().cpu().clone() for param in module.parameters()]


def _assert_params_unchanged(before: list[torch.Tensor], module: torch.nn.Module) -> None:
    for old_param, new_param in zip(before, module.parameters(), strict=True):
        if not torch.equal(old_param, new_param.detach().cpu()):
            raise AssertionError("Le probe a modifié les paramètres de l'encodeur.")


def _row(seed: int, split: str, result: ProbeResult) -> dict[str, float | int | str]:
    rank = min(result.effective_rank_with_static, result.effective_rank_without_static)
    return {
        "seed": seed,
        "split": split,
        "rank": rank,
        "with_static": result.per_timestep_r2_with_static,
        "without_static": result.per_timestep_r2_without_static,
        "delta": result.per_timestep_static_delta,
        "interpretable": int(rank >= 8.0),
    }


def _print_row(row: dict[str, float | int | str]) -> None:
    print(
        "seed={seed} split={split} rank={rank:.2f} "
        "with={with_static:.3f} without={without_static:.3f} "
        "delta_pt={delta:.3f} interpretable={interpretable}".format(**row)
    )


def _summary(rows: list[dict[str, float | int | str]]) -> None:
    print(
        "\nseed | probe_rank | cross_delta_pt | temporal_delta_pt | "
        "cross with/without | temporal with/without"
    )
    print(
        "---: | ---------: | -------------: | ----------------: | "
        "-----------------: | --------------------:"
    )
    seeds = sorted({int(row["seed"]) for row in rows})
    cross_deltas = []
    for seed in seeds:
        cross = next(row for row in rows if row["seed"] == seed and row["split"] == "cross_site")
        temporal = next(row for row in rows if row["seed"] == seed and row["split"] == "temporal")
        if cross["interpretable"]:
            cross_deltas.append(float(cross["delta"]))
        print(
            f"{seed} | {float(cross['rank']):.2f} | {float(cross['delta']):+.3f} | "
            f"{float(temporal['delta']):+.3f} | "
            f"{float(cross['with_static']):.3f}/{float(cross['without_static']):.3f} | "
            f"{float(temporal['with_static']):.3f}/{float(temporal['without_static']):.3f}"
        )

    if not cross_deltas:
        print("\nVERDICT: aucun seed interprétable (rank < 8).")
        return
    mean_delta = float(np.mean(cross_deltas))
    min_delta = float(np.min(cross_deltas))
    max_delta = float(np.max(cross_deltas))
    sign_flips = min_delta <= 0.0 <= max_delta
    print(
        "\nCross-site delta_pt interprétable: "
        f"mean={mean_delta:+.3f} min={min_delta:+.3f} max={max_delta:+.3f}"
    )
    if sign_flips or abs(mean_delta) < 0.02:
        print("VERDICT: SEED NOISE: static conditioning is sound; residual anomaly is not real")
    elif max_delta < 0.0:
        print("VERDICT: REAL RESIDUAL: static fusion in encoder.py is the next inspection target")
    else:
        print("VERDICT: effet mixte; delta ne correspond pas à un résidu négatif stable.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/phaseA.yaml"))
    parser.add_argument("--seeds", default="0,1,2,3,4")
    parser.add_argument("--max-epochs", type=int, default=20)
    parser.add_argument("--steps-per-epoch", type=int, default=100)
    args = parser.parse_args()

    rows: list[dict[str, float | int | str]] = []
    print(
        f"recipe=max_epochs={args.max_epochs} steps_per_epoch={args.steps_per_epoch} "
        f"seeds={_parse_seeds(args.seeds)}"
    )
    for seed in _parse_seeds(args.seeds):
        print(f"\n=== seed {seed} ===")
        cfg = _cfg_for_seed(args, seed)
        artifacts = run_stage1_training(cfg, log=False)
        before_probe = _snapshot_params(artifacts.encoder)
        for split_name, result in artifacts.probes.items():
            row = _row(seed, split_name, result)
            rows.append(row)
            _print_row(row)
        _assert_params_unchanged(before_probe, artifacts.encoder)

    _summary(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
