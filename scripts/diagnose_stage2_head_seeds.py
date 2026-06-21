#!/usr/bin/env python3
"""Multi-seed diagnostic for Stage-2 criticality heads on frozen encoders."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np
import torch

from rs_jepa.config import load_config
from rs_jepa.heads import CriticalityReadout, Stage2Metrics
from rs_jepa.seed import set_global_seed
from rs_jepa.splits import CROSS_SITE_VAL, TEMPORAL_VAL, TRAIN
from rs_jepa.train import load_encoder_checkpoint
from rs_jepa.train_stage2 import (
    build_stage2_sites,
    evaluate_stage2,
    extract_frozen_examples,
    freeze_encoder,
    train_stage2_heads,
)


def _parse_seeds(raw: str) -> list[int]:
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _encoder_clean(encoder: torch.nn.Module) -> bool:
    return all(param.grad is None for param in encoder.parameters())


def _metric_row(
    label: str,
    seed: int,
    split: str,
    metric: Stage2Metrics,
) -> dict[str, float | str | int]:
    return {
        "checkpoint": label,
        "seed": seed,
        "split": split,
        "acc": metric.ordinal_accuracy,
        "mae": metric.mae_levels,
        "ranking_corr": metric.ranking_corr,
        "tension_corr": metric.tension_corr,
    }


def _run_checkpoint(
    label: str,
    checkpoint: Path,
    cfg,
    seeds: list[int],
    *,
    device: torch.device,
) -> list[dict[str, float | str | int]]:
    loaded = load_encoder_checkpoint(checkpoint, device=device)
    encoder = freeze_encoder(loaded.encoder)
    if not _encoder_clean(encoder):
        raise AssertionError("L'encodeur chargé ne doit avoir aucun gradient initial.")

    _sites, train_sites, cross_site_sites = build_stage2_sites(cfg)
    train_examples = extract_frozen_examples(encoder, train_sites, cfg, TRAIN, device=device)
    cross_examples = extract_frozen_examples(
        encoder,
        cross_site_sites,
        cfg,
        CROSS_SITE_VAL,
        device=device,
    )
    temporal_examples = extract_frozen_examples(
        encoder,
        train_sites,
        cfg,
        TEMPORAL_VAL,
        device=device,
    )

    rows: list[dict[str, float | str | int]] = []
    for seed in seeds:
        set_global_seed(seed, deterministic=cfg.stage1.deterministic)
        run_cfg = replace(cfg, seed=seed)
        heads = CriticalityReadout(run_cfg.stage1.latent_dim, run_cfg.stage2)
        train_stage2_heads(heads, train_examples, run_cfg, device=device)
        if not _encoder_clean(encoder):
            raise AssertionError("Stage-2 a créé un gradient sur l'encodeur gelé.")
        cross = evaluate_stage2(heads, cross_examples, run_cfg, CROSS_SITE_VAL, device=device)
        temporal = evaluate_stage2(heads, temporal_examples, run_cfg, TEMPORAL_VAL, device=device)
        rows.append(_metric_row(label, seed, "cross_site", cross))
        rows.append(_metric_row(label, seed, "temporal", temporal))
    return rows


def _print_table(title: str, rows: list[dict[str, float | str | int]]) -> None:
    print(f"\n{title}")
    print("seed | split | acc | mae_levels | ranking_corr | tension_corr")
    print("---: | :---- | --: | ---------: | -----------: | -----------:")
    for row in rows:
        print(
            f"{int(row['seed'])} | {row['split']} | "
            f"{float(row['acc']):.3f} | {float(row['mae']):.3f} | "
            f"{float(row['ranking_corr']):.3f} | {float(row['tension_corr']):.3f}"
        )


def _cross_summary(label: str, rows: list[dict[str, float | str | int]]) -> dict[str, float]:
    cross = [row for row in rows if row["split"] == "cross_site"]
    acc = np.asarray([float(row["acc"]) for row in cross])
    rank = np.asarray([float(row["ranking_corr"]) for row in cross])
    return {
        f"{label}_acc_mean": float(acc.mean()),
        f"{label}_acc_min": float(acc.min()),
        f"{label}_acc_max": float(acc.max()),
        f"{label}_rank_mean": float(rank.mean()),
        f"{label}_rank_min": float(rank.min()),
        f"{label}_rank_max": float(rank.max()),
    }


def _print_summary(
    rows_a: list[dict[str, float | str | int]],
    rows_b: list[dict[str, float | str | int]],
) -> None:
    summary = {}
    summary.update(_cross_summary("A", rows_a))
    summary.update(_cross_summary("B", rows_b))
    print("\nCross-site summary")
    print(
        "A short: "
        f"acc mean={summary['A_acc_mean']:.3f} min={summary['A_acc_min']:.3f} "
        f"max={summary['A_acc_max']:.3f}; "
        f"ranking mean={summary['A_rank_mean']:.3f} min={summary['A_rank_min']:.3f} "
        f"max={summary['A_rank_max']:.3f}"
    )
    print(
        "B mature: "
        f"acc mean={summary['B_acc_mean']:.3f} min={summary['B_acc_min']:.3f} "
        f"max={summary['B_acc_max']:.3f}; "
        f"ranking mean={summary['B_rank_mean']:.3f} min={summary['B_rank_min']:.3f} "
        f"max={summary['B_rank_max']:.3f}"
    )
    overlap_acc = (
        summary["A_acc_min"] <= summary["B_acc_max"]
        and summary["B_acc_min"] <= summary["A_acc_max"]
    )
    overlap_rank = (
        summary["A_rank_min"] <= summary["B_rank_max"]
        and summary["B_rank_min"] <= summary["A_rank_max"]
    )
    if overlap_acc or overlap_rank:
        print(
            "VERDICT: no real difference; mature latent not worse, extra rank beyond "
            "~11 does not help heads at this depth/epochs"
        )
    elif (
        summary["A_acc_min"] > summary["B_acc_max"]
        and summary["A_rank_min"] > summary["B_rank_max"]
    ):
        print(
            "VERDICT: real: mature latent yields worse heads, investigate head "
            "depth/epochs vs latent rank, or target normalization"
        )
    else:
        print("VERDICT: mixed; distributions do not cleanly support one simple reading.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/phaseA.yaml"))
    parser.add_argument("--seeds", default="0,1,2,3,4")
    parser.add_argument("--short", type=Path, default=Path("runs/phaseA/encoder_20x100.pt"))
    parser.add_argument("--mature", type=Path, default=Path("runs/phaseA/encoder_10k.pt"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    seeds = _parse_seeds(args.seeds)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Stage-2 head seed diagnostic; seeds={seeds}; device={device}")
    print("encoder gradients asserted None after every head training run")

    rows_a = _run_checkpoint("A_short", args.short, cfg, seeds, device=device)
    rows_b = _run_checkpoint("B_mature", args.mature, cfg, seeds, device=device)
    _print_table("A: runs/phaseA/encoder_20x100.pt", rows_a)
    _print_table("B: runs/phaseA/encoder_10k.pt", rows_b)
    _print_summary(rows_a, rows_b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
