#!/usr/bin/env python3
"""Final multi-seed Stage-2 head measurement for the winning head config."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np
import torch

from rs_jepa.config import RSJEPAConfig, load_config
from rs_jepa.heads import CriticalityReadout, Stage2Metrics
from rs_jepa.seed import set_global_seed
from rs_jepa.splits import CROSS_SITE_VAL, TEMPORAL_VAL, TRAIN
from rs_jepa.train import load_encoder_checkpoint
from rs_jepa.train_stage2 import (
    Stage2Examples,
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


def _winning_cfg(cfg: RSJEPAConfig) -> RSJEPAConfig:
    stage2 = replace(
        cfg.stage2,
        head_depth=4,
        max_epochs=20,
        head_hidden_dim=128,
    )
    return replace(cfg, stage2=stage2)


def _examples_for_checkpoint(
    checkpoint: Path,
    cfg: RSJEPAConfig,
    *,
    device: torch.device,
) -> tuple[torch.nn.Module, Stage2Examples, Stage2Examples, Stage2Examples]:
    loaded = load_encoder_checkpoint(checkpoint, device=device)
    encoder = freeze_encoder(loaded.encoder)
    if not _encoder_clean(encoder):
        raise AssertionError("L'encodeur chargé ne doit pas porter de gradient.")
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
    return encoder, train_examples, cross_examples, temporal_examples


def _metric_row(
    latent: str,
    seed: int,
    split: str,
    metric: Stage2Metrics,
) -> dict[str, float | int | str]:
    return {
        "latent": latent,
        "seed": seed,
        "split": split,
        "acc": metric.ordinal_accuracy,
        "mae": metric.mae_levels,
        "ranking_corr": metric.ranking_corr,
        "tension_corr": metric.tension_corr,
    }


def _run_latent(
    latent: str,
    checkpoint: Path,
    cfg: RSJEPAConfig,
    seeds: list[int],
    *,
    device: torch.device,
) -> list[dict[str, float | int | str]]:
    encoder, train_examples, cross_examples, temporal_examples = _examples_for_checkpoint(
        checkpoint,
        cfg,
        device=device,
    )
    rows: list[dict[str, float | int | str]] = []
    for seed in seeds:
        set_global_seed(seed, deterministic=cfg.stage1.deterministic)
        run_cfg = replace(cfg, seed=seed)
        heads = CriticalityReadout(run_cfg.stage1.latent_dim, run_cfg.stage2)
        train_stage2_heads(heads, train_examples, run_cfg, device=device)
        if not _encoder_clean(encoder):
            raise AssertionError("Stage-2 a créé un gradient sur l'encodeur gelé.")
        cross = evaluate_stage2(heads, cross_examples, run_cfg, CROSS_SITE_VAL, device=device)
        temporal = evaluate_stage2(
            heads,
            temporal_examples,
            run_cfg,
            TEMPORAL_VAL,
            device=device,
        )
        rows.append(_metric_row(latent, seed, "cross_site", cross))
        rows.append(_metric_row(latent, seed, "temporal", temporal))
    return rows


def _print_table(title: str, rows: list[dict[str, float | int | str]]) -> None:
    print(f"\n{title}")
    print("seed | split | acc | mae_levels | ranking_corr | tension_corr")
    print("---: | :---- | --: | ---------: | -----------: | -----------:")
    for row in rows:
        print(
            f"{int(row['seed'])} | {row['split']} | "
            f"{float(row['acc']):.3f} | {float(row['mae']):.3f} | "
            f"{float(row['ranking_corr']):.3f} | {float(row['tension_corr']):.3f}"
        )


def _mean_std(values: np.ndarray) -> tuple[float, float]:
    std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
    return float(values.mean()), std


def _summary(label: str, rows: list[dict[str, float | int | str]]) -> dict[str, float]:
    cross = [row for row in rows if row["split"] == "cross_site"]
    acc = np.asarray([float(row["acc"]) for row in cross])
    ranking = np.asarray([float(row["ranking_corr"]) for row in cross])
    acc_mean, acc_std = _mean_std(acc)
    ranking_mean, ranking_std = _mean_std(ranking)
    lagging = int(np.sum(acc < 0.80))
    print(
        f"{label}: acc={acc_mean:.3f} ± {acc_std:.3f} "
        f"(min={acc.min():.3f}, max={acc.max():.3f}); "
        f"ranking={ranking_mean:.3f} ± {ranking_std:.3f} "
        f"(min={ranking.min():.3f}, max={ranking.max():.3f}); "
        f"lagging_acc<0.80={lagging}/{len(acc)}"
    )
    return {
        "acc_mean": acc_mean,
        "acc_std": acc_std,
        "acc_min": float(acc.min()),
        "acc_max": float(acc.max()),
        "ranking_mean": ranking_mean,
        "ranking_std": ranking_std,
        "ranking_min": float(ranking.min()),
        "ranking_max": float(ranking.max()),
        "lagging": float(lagging),
        "n": float(len(acc)),
    }


def _print_summary(
    mature_rows: list[dict[str, float | int | str]],
    short_rows: list[dict[str, float | int | str]],
) -> None:
    print("\nCross-site summary, winning head config depth=4 epochs=20 hidden=128")
    mature = _summary("mature", mature_rows)
    short = _summary("short", short_rows)
    print(
        "\nHEADLINE PRODUCT NUMBER: "
        f"mature acc={mature['acc_mean']:.3f} ± {mature['acc_std']:.3f}; "
        f"ranking={mature['ranking_mean']:.3f} ± {mature['ranking_std']:.3f}"
    )
    if mature["acc_mean"] > short["acc_mean"] and mature["ranking_mean"] > short["ranking_mean"]:
        print("CONFIG-MATCHED COMPARISON: mature beats short on mean acc and ranking.")
    else:
        print("CONFIG-MATCHED COMPARISON: mature does not beat short on both mean metrics.")
    if mature["lagging"] > 1:
        print(
            "CAVEAT: lagging-seed problem persists for mature latent; head training "
            "is unstable enough to report error bars prominently."
        )
    else:
        print("CAVEAT: mature lagging-seed problem is limited under the winning head config.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/phaseA.yaml"))
    parser.add_argument("--seeds", default="0,1,2,3,4,5,6,7")
    parser.add_argument("--short", type=Path, default=Path("runs/phaseA/encoder_20x100.pt"))
    parser.add_argument("--mature", type=Path, default=Path("runs/phaseA/encoder_10k.pt"))
    parser.add_argument("--short-seeds", default=None)
    args = parser.parse_args()

    cfg = _winning_cfg(load_config(args.config))
    mature_seeds = _parse_seeds(args.seeds)
    short_seeds = _parse_seeds(args.short_seeds) if args.short_seeds else mature_seeds
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(
        "Final Stage-2 winning-head measurement; "
        f"mature_seeds={mature_seeds}; short_seeds={short_seeds}; device={device}"
    )
    print("encoder gradients asserted None after every head training run")

    mature_rows = _run_latent("mature", args.mature, cfg, mature_seeds, device=device)
    short_rows = _run_latent("short", args.short, cfg, short_seeds, device=device)
    _print_table("MATURE: runs/phaseA/encoder_10k.pt", mature_rows)
    _print_table("SHORT: runs/phaseA/encoder_20x100.pt", short_rows)
    _print_summary(mature_rows, short_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
