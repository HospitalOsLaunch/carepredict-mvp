#!/usr/bin/env python3
"""Capacity sweep for Stage-2 heads on the mature RS-JEPA latent."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np
import torch

from rs_jepa.config import RSJEPAConfig, Stage2Config, load_config
from rs_jepa.heads import CriticalityReadout, Stage2Metrics, ranking_correlation
from rs_jepa.probe import fit_linear_predict, r2_score
from rs_jepa.seed import set_global_seed
from rs_jepa.splits import CROSS_SITE_VAL, TRAIN
from rs_jepa.train import load_encoder_checkpoint
from rs_jepa.train_stage2 import (
    Stage2Examples,
    build_stage2_sites,
    evaluate_stage2,
    extract_frozen_examples,
    freeze_encoder,
    train_stage2_heads,
)

SHORT_BASELINE_ACC = 0.835
SHORT_BASELINE_RANKING = 0.699


def _parse_seeds(raw: str) -> list[int]:
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _encoder_clean(encoder: torch.nn.Module) -> bool:
    return all(param.grad is None for param in encoder.parameters())


def _stage2_cfg(base: Stage2Config, *, depth: int, epochs: int, hidden: int) -> Stage2Config:
    return replace(base, head_depth=depth, max_epochs=epochs, head_hidden_dim=hidden)


def _configs(base: Stage2Config) -> list[tuple[str, Stage2Config]]:
    return [
        ("depth=2_epochs=3_hidden=64", _stage2_cfg(base, depth=2, epochs=3, hidden=64)),
        ("depth=3_epochs=10_hidden=64", _stage2_cfg(base, depth=3, epochs=10, hidden=64)),
        ("depth=4_epochs=20_hidden=128", _stage2_cfg(base, depth=4, epochs=20, hidden=128)),
    ]


def _examples_for_checkpoint(
    checkpoint: Path,
    cfg: RSJEPAConfig,
    *,
    device: torch.device,
) -> tuple[torch.nn.Module, Stage2Examples, Stage2Examples]:
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
    return encoder, train_examples, cross_examples


def _row(
    latent: str,
    config_name: str,
    seed: int,
    metric: Stage2Metrics,
) -> dict[str, float | int | str]:
    return {
        "latent": latent,
        "head_config": config_name,
        "seed": seed,
        "acc": metric.ordinal_accuracy,
        "ranking_corr": metric.ranking_corr,
    }


def _run_sweep(
    cfg: RSJEPAConfig,
    encoder: torch.nn.Module,
    train: Stage2Examples,
    cross: Stage2Examples,
    seeds: list[int],
    *,
    device: torch.device,
) -> list[dict[str, float | int | str]]:
    rows = []
    for config_name, stage2_cfg in _configs(cfg.stage2):
        run_cfg = replace(cfg, stage2=stage2_cfg)
        for seed in seeds:
            set_global_seed(seed, deterministic=cfg.stage1.deterministic)
            seeded_cfg = replace(run_cfg, seed=seed)
            heads = CriticalityReadout(seeded_cfg.stage1.latent_dim, seeded_cfg.stage2)
            train_stage2_heads(heads, train, seeded_cfg, device=device)
            if not _encoder_clean(encoder):
                raise AssertionError("Stage-2 a créé un gradient sur l'encodeur gelé.")
            metric = evaluate_stage2(heads, cross, seeded_cfg, CROSS_SITE_VAL, device=device)
            rows.append(_row("mature", config_name, seed, metric))
    return rows


def _linear_ordinal_probe(
    latent_name: str,
    train: Stage2Examples,
    cross: Stage2Examples,
) -> dict[str, float | str]:
    pred = fit_linear_predict(
        train.latents.numpy(),
        train.levels.numpy().astype(float),
        cross.latents.numpy(),
    )
    pred_levels = np.rint(pred).clip(0, int(train.levels.max().item())).astype(int)
    y = cross.levels.numpy()
    return {
        "latent": latent_name,
        "ordinal_r2": float(r2_score(y.astype(float), pred)),
        "ordinal_acc": float(np.mean(pred_levels == y)),
        "ranking_corr": ranking_correlation(pred, y),
    }


def _print_rows(rows: list[dict[str, float | int | str]]) -> None:
    print("\nlatent | head_config | seed | cross_site acc | ranking_corr")
    print(":----- | :---------- | ---: | -------------: | -----------:")
    for row in rows:
        print(
            f"{row['latent']} | {row['head_config']} | {int(row['seed'])} | "
            f"{float(row['acc']):.3f} | {float(row['ranking_corr']):.3f}"
        )


def _print_linear(rows: list[dict[str, float | str]]) -> None:
    print("\nLinear ordinal probe")
    print("latent | ordinal_r2 | ordinal_acc | ranking_corr")
    print(":----- | ---------: | ----------: | -----------:")
    for row in rows:
        print(
            f"{row['latent']} | {float(row['ordinal_r2']):.3f} | "
            f"{float(row['ordinal_acc']):.3f} | {float(row['ranking_corr']):.3f}"
        )


def _print_summary(rows: list[dict[str, float | int | str]]) -> None:
    print("\nSummary vs short-latent baseline")
    print(f"short baseline: acc={SHORT_BASELINE_ACC:.3f} ranking_corr={SHORT_BASELINE_RANKING:.3f}")
    best_acc = -np.inf
    best_rank = -np.inf
    for config_name in {str(row["head_config"]) for row in rows}:
        cfg_rows = [row for row in rows if row["head_config"] == config_name]
        acc = np.asarray([float(row["acc"]) for row in cfg_rows])
        rank = np.asarray([float(row["ranking_corr"]) for row in cfg_rows])
        best_acc = max(best_acc, float(acc.max()))
        best_rank = max(best_rank, float(rank.max()))
        print(
            f"{config_name}: acc mean={acc.mean():.3f} min={acc.min():.3f} max={acc.max():.3f}; "
            f"ranking mean={rank.mean():.3f} min={rank.min():.3f} max={rank.max():.3f}"
        )
    if best_acc >= SHORT_BASELINE_ACC or best_rank >= SHORT_BASELINE_RANKING:
        print(
            "VERDICT: head under-capacity: mature latent is fine, shallow head could "
            "not extract the low-dim criticality subspace from the richer space"
        )
    else:
        print(
            "VERDICT: mature latent genuinely carries less linearly/shallowly accessible "
            "criticality; the JEPA objective at 10k steps traded criticality-readability "
            "for prediction-richness"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/phaseA.yaml"))
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--short", type=Path, default=Path("runs/phaseA/encoder_20x100.pt"))
    parser.add_argument("--mature", type=Path, default=Path("runs/phaseA/encoder_10k.pt"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    seeds = _parse_seeds(args.seeds)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Stage-2 mature-latent capacity sweep; seeds={seeds}; device={device}")
    print("encoder gradients asserted None after every head training run")

    _short_encoder, short_train, short_cross = _examples_for_checkpoint(
        args.short,
        cfg,
        device=device,
    )
    mature_encoder, mature_train, mature_cross = _examples_for_checkpoint(
        args.mature,
        cfg,
        device=device,
    )
    linear_rows = [
        _linear_ordinal_probe("short", short_train, short_cross),
        _linear_ordinal_probe("mature", mature_train, mature_cross),
    ]
    rows = _run_sweep(cfg, mature_encoder, mature_train, mature_cross, seeds, device=device)
    _print_rows(rows)
    _print_linear(linear_rows)
    _print_summary(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
